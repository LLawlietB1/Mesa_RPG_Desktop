"""Backup e restauração POR USUÁRIO, no mesmo formato .zip do app web (um backup feito aqui restaura lá e
vice-versa). A restauração substitui só os dados do usuário, numa única transação (tudo ou nada), gerando ids
novos e remapeando as chaves estrangeiras."""
from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from mesa_desktop.models import Base, Campaign, FileAsset, Player, User, utcnow
from mesa_desktop.services.errors import AppError
from mesa_desktop.services.images import SAFE_NAME, process_image

APP_ID = "mesa-do-mestre"
FORMAT_VERSION = 2
MANIFEST, DATA, FILES_PREFIX = "manifest.json", "data.json", "files/"
MAX_ROWS = 100_000
MAX_UNCOMPRESSED = 40 * 1024 * 1024


class BackupError(AppError):
    """Falha esperada de backup/restauração, com mensagem legível."""


def _t(name):
    return Base.metadata.tables[name]


def _specs(uid):
    camps = select(_t("campaigns").c.id).where(_t("campaigns").c.owner_id == uid)

    def by_campaign(t):
        return _t(t).c.campaign_id.in_(camps)

    npcs = select(_t("npcs").c.id).where(by_campaign("npcs"))
    quests = select(_t("quests").c.id).where(by_campaign("quests"))
    sessions = select(_t("game_sessions").c.id).where(by_campaign("game_sessions"))
    items = select(_t("items").c.id).where(by_campaign("items"))
    return [
        ("campaigns", _t("campaigns").c.owner_id == uid),
        ("players", _t("players").c.owner_id == uid),
        ("campaign_players", by_campaign("campaign_players")),
        ("characters", by_campaign("characters")),
        ("experience_history", by_campaign("experience_history")),
        ("notes", by_campaign("notes")),
        ("npcs", by_campaign("npcs")),
        ("character_npc_relationships", _t("character_npc_relationships").c.npc_id.in_(npcs)),
        ("quests", by_campaign("quests")),
        ("quest_objectives", _t("quest_objectives").c.quest_id.in_(quests)),
        ("quest_status_history", _t("quest_status_history").c.quest_id.in_(quests)),
        ("quest_characters", _t("quest_characters").c.quest_id.in_(quests)),
        ("game_sessions", by_campaign("game_sessions")),
        ("session_participants", _t("session_participants").c.session_id.in_(sessions)),
        ("session_npcs", _t("session_npcs").c.session_id.in_(sessions)),
        ("session_quests", _t("session_quests").c.session_id.in_(sessions)),
        ("session_events", by_campaign("session_events")),
        ("items", by_campaign("items")),
        ("character_items", _t("character_items").c.item_id.in_(items)),
    ]


TABLE_ORDER = [name for name, _ in _specs(0)]
IMAGE_COLUMNS = {("campaigns", "cover_image"), ("characters", "portrait"), ("npcs", "image")}
OWNER_COLUMN = "owner_id"


def _ser(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def create_backup(s: Session, user: User) -> tuple[str, bytes]:
    uid = user.id
    tables = {}
    for name, where in _specs(uid):
        t = _t(name)
        cols = [c for c in t.columns if c.name != OWNER_COLUMN]
        rows = s.execute(select(*cols).where(where)).mappings().all()
        tables[name] = [{k: _ser(v) for k, v in row.items()} for row in rows]
    assets = s.query(FileAsset).filter_by(owner_id=uid).all()
    manifest = {"app": APP_ID, "format": FORMAT_VERSION, "created_at": utcnow().isoformat(timespec="seconds") + "Z",
                "user": user.email}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST, json.dumps(manifest, indent=2))
        zf.writestr(DATA, json.dumps({"tables": tables, "assets": [
            {"id": a.id, "content_type": a.content_type} for a in assets]}, ensure_ascii=False))
        for a in assets:
            zf.writestr(FILES_PREFIX + a.id, bytes(a.data or b""))
    return f"mesa-do-mestre-{utcnow().strftime('%Y%m%d-%H%M%S')}.zip", buf.getvalue()


def _read_package(source) -> tuple[dict, dict[str, bytes]]:
    try:
        zf = zipfile.ZipFile(source)
    except zipfile.BadZipFile:
        raise BackupError("O arquivo escolhido não é um .zip válido.") from None
    with zf:
        total = 0
        for info in zf.infolist():
            total += info.file_size
            n = info.filename
            if info.is_dir():
                continue
            ok = n in (MANIFEST, DATA) or (n.startswith(FILES_PREFIX) and SAFE_NAME.match(n[len(FILES_PREFIX):]))
            if not ok:
                raise BackupError(f"O arquivo contém uma entrada não permitida: {n[:60]}")
        if total > MAX_UNCOMPRESSED:
            raise BackupError("O backup excede o tamanho máximo permitido.")
        names = set(zf.namelist())
        if MANIFEST not in names or DATA not in names:
            raise BackupError("Arquivo inválido: não é um backup do Mesa do Mestre.")
        try:
            manifest = json.loads(zf.read(MANIFEST))
            data = json.loads(zf.read(DATA))
        except (ValueError, UnicodeDecodeError):
            raise BackupError("Conteúdo do backup ilegível.") from None
        if manifest.get("app") != APP_ID or manifest.get("format") != FORMAT_VERSION:
            raise BackupError("Este arquivo não é um backup compatível desta versão do Mesa do Mestre.")
        files = {}
        for a in data.get("assets", []):
            aid = a.get("id", "")
            if not SAFE_NAME.match(aid) or FILES_PREFIX + aid not in names:
                raise BackupError("Backup referencia uma imagem ausente ou inválida.")
            files[aid] = zf.read(FILES_PREFIX + aid)
    tables = data.get("tables")
    if not isinstance(tables, dict) or set(tables) - set(TABLE_ORDER):
        raise BackupError("Estrutura de dados do backup desconhecida.")
    if sum(len(v) for v in tables.values() if isinstance(v, list)) > MAX_ROWS:
        raise BackupError("O backup tem registros demais.")
    for name, rows in tables.items():
        valid = {c.name for c in _t(name).columns} - {OWNER_COLUMN}
        if not isinstance(rows, list) or any(not isinstance(r, dict) or set(r) - valid for r in rows):
            raise BackupError(f"Dados inválidos na tabela «{name}».")
    return data, files


def _coerce(column, value):
    if value is None:
        return None
    try:
        if isinstance(column.type, DateTime):
            return datetime.fromisoformat(value.rstrip("Z"))
        if isinstance(column.type, Date):
            return date.fromisoformat(value)
        if isinstance(column.type, Boolean):
            return bool(value)
    except (ValueError, AttributeError):
        raise BackupError(f"Valor inválido na coluna «{column.name}».") from None
    return value


def restore_backup(s: Session, user: User, source) -> dict:
    """Substitui os dados DO USUÁRIO pelos do backup. Qualquer falha desfaz tudo."""
    data, files = _read_package(source)
    uid = user.id
    try:
        asset_map: dict[str, str] = {}
        processed_files: dict[str, tuple[bytes, str]] = {}
        for old_id, raw in files.items():
            try:
                processed_files[old_id] = process_image(raw)
            except AppError:
                raise BackupError("O backup contém uma imagem inválida.") from None
            asset_map[old_id] = uuid.uuid4().hex
        for model in (Campaign, Player, FileAsset):
            s.execute(delete(model).where(model.owner_id == uid))
        for old_id, (processed, ctype) in processed_files.items():
            s.add(FileAsset(id=asset_map[old_id], owner_id=uid, content_type=ctype, size=len(processed), data=processed))
        s.flush()
        id_maps: dict[str, dict] = {}
        for name in TABLE_ORDER:
            t = _t(name)
            id_maps[name] = {}
            for row in data["tables"].get(name, []):
                values = {}
                for col in t.columns:
                    if col.name == OWNER_COLUMN:
                        values[col.name] = uid
                        continue
                    if col.name == "id" and col.primary_key and not col.foreign_keys:
                        continue
                    if col.name not in row:
                        continue
                    value = row[col.name]
                    if (name, col.name) in IMAGE_COLUMNS:
                        if value is not None and value not in asset_map:
                            raise BackupError("Backup referencia uma imagem ausente.")
                        value = asset_map.get(value)
                    elif col.foreign_keys and value is not None:
                        target = next(iter(col.foreign_keys)).column.table.name
                        if value not in id_maps.get(target, {}) and str(value) not in id_maps.get(target, {}):
                            raise BackupError(f"Backup inconsistente: referência inexistente em «{name}.{col.name}».")
                        value = id_maps[target].get(value, id_maps[target].get(str(value)))
                    else:
                        value = _coerce(col, value)
                    values[col.name] = value
                result = s.execute(t.insert().values(**values))
                if "id" in t.columns and row.get("id") is not None:
                    id_maps[name][row["id"]] = result.inserted_primary_key[0]
        s.commit()
    except BackupError:
        s.rollback()
        raise
    except SQLAlchemyError:
        s.rollback()
        raise BackupError("O backup contém dados inconsistentes com esta versão do sistema. Nada foi alterado.") from None
    return {"rows": sum(len(v) for v in data["tables"].values()), "images": len(files)}
