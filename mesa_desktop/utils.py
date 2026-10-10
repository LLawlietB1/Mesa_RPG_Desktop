"""Funções auxiliares sem dependência de interface."""
from __future__ import annotations

from datetime import date, datetime, timezone

MAX_KV_LINES = 40


def parse_kv_lines(text: str | None) -> dict:
    """Converte linhas `chave: valor` em dict (campos personalizados). Ignora linhas vazias."""
    result: dict = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if ":" not in line:
            raise ValueError(f"Linha inválida (use «chave: valor»): {line[:40]}")
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if not key or len(key) > 60 or len(value) > 300:
            raise ValueError(f"Chave ou valor inválido: {line[:40]}")
        result[key] = value
    if len(result) > MAX_KV_LINES:
        raise ValueError(f"Máximo de {MAX_KV_LINES} campos personalizados.")
    return result


def format_kv_lines(data: dict | None) -> str:
    return "\n".join(f"{k}: {v}" for k, v in (data or {}).items())


def like_pattern(term: str) -> str:
    """Padrão LIKE seguro (escapa %, _ e a barra); use com escape='\\'."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def to_local(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone()


def fmt_datetime(value: datetime | None) -> str:
    local = to_local(value)
    return local.strftime("%d/%m/%Y %H:%M") if local else "—"


def fmt_date(value: date | datetime | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        value = to_local(value)
    return value.strftime("%d/%m/%Y")


def clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None
