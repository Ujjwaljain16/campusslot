from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Create the engine lazily so tests and Alembic can configure the environment first."""
    global _engine, _session_factory
    if _engine is None:
        url = get_settings().database_url
        options: dict = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **options)
        _session_factory = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one database session per request."""
    get_engine()
    assert _session_factory is not None
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()
