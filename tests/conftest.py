import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mesa_desktop import db  # noqa: E402
from mesa_desktop.services import auth  # noqa: E402

PASSWORD = "senha-forte-1"


@pytest.fixture()
def database(tmp_path):
    db.open_database(tmp_path / "teste.sqlite3")
    yield tmp_path / "teste.sqlite3"
    db.close_database()


@pytest.fixture()
def s(database):
    with db.session() as session:
        yield session


@pytest.fixture()
def admin(s):
    return auth.register_user(s, "Dono", "dono@example.com", PASSWORD, "palavra dono")


@pytest.fixture()
def master(s, admin):
    return auth.register_user(s, "Mestre", "mestre@example.com", PASSWORD, "palavra mestre")


def png_bytes(size=(40, 30), color=(200, 30, 30)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture()
def png_file(tmp_path):
    p = tmp_path / "img.png"
    p.write_bytes(png_bytes())
    return str(p)
