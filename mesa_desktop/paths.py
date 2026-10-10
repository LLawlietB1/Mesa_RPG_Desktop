"""Onde ficam o banco compartilhado e as preferências do programa."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
# Pasta do programa (ao lado do .exe quando empacotado) e pasta dos recursos (ícone).
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
RES_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
SETTINGS_DIR = Path(os.environ.get("APPDATA") or Path.home() / ".config") / "MesaDoMestreDesktop"
SETTINGS_FILE = SETTINGS_DIR / "config.json"
DB_NAME = "mesa.sqlite3"


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(data: dict) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def candidate_databases() -> list[Path]:
    """Bancos conhecidos, em ordem de preferência: o da versão web (pasta irmã) e o local deste programa."""
    web = APP_DIR.parent / "MesaDoMestre"
    return [web / "local" / "dados" / DB_NAME, web / "instance" / DB_NAME, APP_DIR / "dados" / DB_NAME]


def database_path() -> Path:
    """Escolha: variável MESA_DB > configuração salva > banco da versão web existente > dados/ deste programa."""
    env = os.environ.get("MESA_DB")
    if env:
        return Path(env).expanduser()
    saved = load_settings().get("database")
    if saved:
        return Path(saved)
    for candidate in candidate_databases():
        if candidate.exists():
            return candidate
    web_dir = APP_DIR.parent / "MesaDoMestre" / "local" / "dados"
    if web_dir.parent.exists():
        return web_dir / DB_NAME
    return (SETTINGS_DIR if FROZEN else APP_DIR / "dados") / DB_NAME
