from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from media_automata.config import get_settings
from media_automata.db.models import Base


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    connect_args = (
        {"check_same_thread": False, "timeout": 60}
        if settings.database_url.startswith("sqlite")
        else {}
    )
    engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
    if settings.database_url.startswith("sqlite"):
        _configure_sqlite(engine)
    return engine


def _configure_sqlite(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=60000")
        cursor.close()


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _apply_lightweight_migrations(engine)


def _apply_lightweight_migrations(engine: Engine) -> None:
    inspector = inspect(engine)
    if "jobs" not in inspector.get_table_names() or "platform_tasks" not in inspector.get_table_names():
        return
    with engine.begin() as connection:
        job_columns = {column["name"] for column in inspector.get_columns("jobs")}
        if "scheduled_for" not in job_columns:
            connection.execute(text("ALTER TABLE jobs ADD COLUMN scheduled_for DATETIME"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_scheduled_for ON jobs (scheduled_for)"))

        task_columns = {column["name"] for column in inspector.get_columns("platform_tasks")}
        if "scheduled_for" not in task_columns:
            connection.execute(text("ALTER TABLE platform_tasks ADD COLUMN scheduled_for DATETIME"))
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_platform_tasks_scheduled_for ON platform_tasks (scheduled_for)")
            )


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
