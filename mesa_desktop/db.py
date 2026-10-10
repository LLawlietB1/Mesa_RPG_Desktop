"""Conexão com o banco SQLite compartilhado e verificação/criação do esquema.

O esquema é dono do app web (Alembic). Quando o arquivo ainda não existe, o desktop cria as tabelas e grava o
carimbo `alembic_version` com a revisão atual — assim `flask db upgrade` no app web não tenta recriar nada."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from mesa_desktop.models import Base

# Revisão do Alembic (app web) que este programa conhece. Atualize junto com o app web.
SCHEMA_REVISION = "b7c1d2e3f4a5"


class SchemaError(Exception):
    """Banco incompatível com este programa (versão diferente)."""


_engine: Engine | None = None
_factory: sessionmaker | None = None
_path: Path | None = None


def _pragmas(dbapi_connection, _record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")     # igual ao app web: as FKs e os ON DELETE CASCADE valem
        cur.execute("PRAGMA busy_timeout=15000")  # o app web pode estar escrevendo ao mesmo tempo
        cur.close()


def open_database(path: Path | str) -> Engine:
    """Abre (e cria, se preciso) o banco. Levanta SchemaError se a versão do esquema não bate."""
    global _engine, _factory, _path
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existed = path.exists() and path.stat().st_size > 0
    engine = create_engine(f"sqlite:///{path.as_posix()}", future=True)
    event.listen(engine, "connect", _pragmas)
    tables = set(inspect(engine).get_table_names())
    if not existed or not tables:
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
            conn.execute(text("DELETE FROM alembic_version"))
            conn.execute(text("INSERT INTO alembic_version (version_num) VALUES (:v)"), {"v": SCHEMA_REVISION})
    else:
        _check_schema(engine, tables)
    _engine, _path = engine, path
    _factory = sessionmaker(engine, expire_on_commit=False, future=True)
    return engine


def _check_schema(engine: Engine, tables: set[str]) -> None:
    if "alembic_version" not in tables or "users" not in tables:
        raise SchemaError("O arquivo escolhido não é um banco do Mesa do Mestre.")
    with engine.connect() as conn:
        rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    if rev != SCHEMA_REVISION:
        raise SchemaError(
            f"O banco está na versão de esquema «{rev}», mas este programa espera «{SCHEMA_REVISION}».\n"
            "Abra a versão web uma vez (local\\iniciar.bat) para atualizá-lo, ou atualize este programa.")


def database_path() -> Path:
    assert _path is not None, "banco não aberto"
    return _path


def close_database() -> None:
    global _engine, _factory, _path
    if _engine is not None:
        _engine.dispose()
    _engine = _factory = _path = None


@contextmanager
def session():
    """Sessão curta: lê/escreve e fecha. O commit é explícito em quem chama (ou use `commit()`)."""
    assert _factory is not None, "banco não aberto"
    s: Session = _factory()
    try:
        yield s
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
