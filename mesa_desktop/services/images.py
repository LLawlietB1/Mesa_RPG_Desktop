"""Imagens: validadas, recodificadas em WEBP (sem EXIF, até 800 px) e guardadas NO BANCO (tabela file_assets),
exatamente como o app web — a mesma imagem aparece nos dois programas."""
from __future__ import annotations

import io
import re
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from mesa_desktop.models import FileAsset, User
from mesa_desktop.services.errors import AppError

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_FORMATS = {"PNG", "JPEG", "GIF", "WEBP"}
SAFE_NAME = re.compile(r"^[0-9a-f]{32}$")
MAX_DIMENSION = 800
MAX_IMAGE_BYTES = 3 * 1024 * 1024
QUOTA_BYTES = 3 * 1024 * 1024
NOT_ENABLED = ("O envio de imagens ainda não foi liberado para a sua conta. "
               "Peça a liberação em «Minha conta» (um administrador aprova em «Administração»).")


def process_image(data: bytes) -> tuple[bytes, str]:
    """Confere que é uma imagem de verdade e a recodifica em WEBP."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = 25_000_000          # protege contra «bombas de descompressão»
    try:
        probe = Image.open(io.BytesIO(data))
        if probe.format not in ALLOWED_FORMATS:
            raise AppError("O conteúdo do arquivo não corresponde a uma imagem válida.")
        probe.verify()
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        img.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
        img = img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")
        out = io.BytesIO()
        img.save(out, "WEBP", quality=82, method=4)
    except AppError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise AppError("O conteúdo do arquivo não corresponde a uma imagem válida.") from None
    return out.getvalue(), "image/webp"


def read_file_image(path: str) -> bytes:
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise AppError("Formato não permitido. Use PNG, JPG, GIF ou WEBP.")
    try:
        with open(path, "rb") as fh:
            raw = fh.read(MAX_IMAGE_BYTES + 1)
    except OSError:
        raise AppError("Não foi possível ler o arquivo escolhido.") from None
    if not raw:
        raise AppError("O arquivo está vazio.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise AppError(f"Imagem muito grande (máximo {MAX_IMAGE_BYTES // (1024 * 1024)} MB).")
    return raw


def used_bytes(s: Session, owner_id: int) -> int:
    return s.query(func.coalesce(func.sum(FileAsset.size), 0)).filter(FileAsset.owner_id == owner_id).scalar() or 0


def save_image_from_file(s: Session, user: User, path: str) -> str:
    """Valida, recodifica e adiciona a imagem à sessão (o commit é de quem chama). Devolve o id."""
    if not user.can_upload_images:
        raise AppError(NOT_ENABLED)
    data, ctype = process_image(read_file_image(path))
    if used_bytes(s, user.id) + len(data) > QUOTA_BYTES:
        raise AppError(f"Limite de armazenamento de imagens atingido ({QUOTA_BYTES // (1024 * 1024)} MB). "
                       "Remova imagens antigas.")
    asset = FileAsset(id=uuid.uuid4().hex, owner_id=user.id, content_type=ctype, size=len(data), data=data)
    s.add(asset)
    return asset.id


def delete_image(s: Session, owner_id: int, asset_id: str | None) -> None:
    """Remove a imagem do usuário (sem commit)."""
    if asset_id and SAFE_NAME.match(asset_id):
        s.query(FileAsset).filter(FileAsset.id == asset_id, FileAsset.owner_id == owner_id).delete()


def image_bytes(s: Session, owner_id: int, asset_id: str | None) -> bytes | None:
    if not asset_id or not SAFE_NAME.match(asset_id):
        return None
    asset = s.query(FileAsset).filter(FileAsset.id == asset_id, FileAsset.owner_id == owner_id).first()
    return bytes(asset.data) if asset and asset.data else None
