"""SQLite engine and session handling (SQLAlchemy 2.x, synchronous)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Naive UTC timestamp; every stored datetime is UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


class Database:
    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "dwhcr.db"
        self.engine: Engine = create_engine(
            f"sqlite:///{self.path.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        event.listen(self.engine, "connect", _sqlite_pragmas)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    def create_all(self) -> None:
        from app import models  # noqa: F401  (registers the tables)
        from app.migrations import upgrade_schema

        Base.metadata.create_all(self.engine)
        upgrade_schema(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()


def _sqlite_pragmas(dbapi_connection, _record) -> None:  # type: ignore[no-untyped-def]
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


_database: Database | None = None


def init_database(data_dir: Path) -> Database:
    global _database
    if _database is not None:
        _database.dispose()
    _database = Database(data_dir)
    _database.create_all()
    return _database


def get_database() -> Database:
    if _database is None:
        raise RuntimeError("Veritabanı başlatılmadı.")
    return _database


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    session = get_database().session_factory()
    try:
        yield session
    finally:
        session.close()
