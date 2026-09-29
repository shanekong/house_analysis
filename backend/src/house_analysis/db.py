from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import BACKEND_DIR, database_url


def create_database_engine(url: Optional[str] = None) -> Engine:
    resolved_url = url or database_url()
    connect_args = {"check_same_thread": False} if resolved_url.startswith("sqlite") else {}
    engine = create_engine(resolved_url, connect_args=connect_args, future=True)

    if resolved_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def upgrade_database(url: Optional[str] = None) -> None:
    resolved_url = url or database_url()
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", resolved_url.replace("%", "%%"))
    command.upgrade(config, "head")

