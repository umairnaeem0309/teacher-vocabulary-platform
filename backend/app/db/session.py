"""Database session management (Phase 0: connectivity only).

The engine is created from environment configuration. ORM models and Alembic
migrations are introduced in Phase 2 (database foundation). Sync engine with
psycopg3 is the simplest maintainable choice; FastAPI runs sync endpoints on
a threadpool.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


def _build_url() -> str:
    """Normalize the configured URL to the psycopg3 driver."""
    url = settings.database_url
    if url.startswith("postgresql://"):
        # Plain libpq URL -> force the psycopg3 SQLAlchemy dialect.
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Return the process-wide engine, creating it on first use."""
    global _engine, _session_factory
    if _engine is None:
        _engine = create_engine(_build_url(), pool_pre_ping=True, future=True)
        _session_factory = sessionmaker(bind=_engine, autoflush=False, future=True)
    return _engine


def make_session() -> Session:
    """Return a plain session (tests, scripts). Caller manages commit/close."""
    get_engine()
    assert _session_factory is not None
    return _session_factory()


def get_session() -> Generator[Session, None, None]:
    """Yield a database session (FastAPI dependency)."""
    session = make_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
