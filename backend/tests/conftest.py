"""Shared pytest fixtures.

The database-dependent tests skip automatically (with a clear reason) when
PostgreSQL is not reachable, so the suite stays green on machines without the
database while still exercising everything else.
"""


import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.config import Settings
from app.main import app


def _db_available() -> tuple[bool, str]:
    """Check database reachability using the effective test settings."""
    s = Settings(app_env="test")
    url = s.database_url
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    try:
        eng = create_engine(url, pool_pre_ping=True)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        eng.dispose()
        return True, ""
    except Exception as exc:  # noqa: BLE001 - any failure means "not available"
        return False, str(getattr(exc, "orig", exc))


DB_AVAILABLE, DB_UNAVAILABLE_REASON = _db_available()

requires_db = pytest.mark.skipif(
    not DB_AVAILABLE,
    reason=f"PostgreSQL not reachable: {DB_UNAVAILABLE_REASON}",
)


@pytest.fixture(name="client")
def client_fixture() -> TestClient:
    """Test client bound to the app with settings suitable for tests.

    Rate limiting is disabled: the suite is one very chatty "client IP"
    and phase 23 budgets (120 writes / 60 s) would otherwise break
    unrelated endpoint tests. Security tests re-enable limiting
    explicitly via app.state.settings overrides (tests/test_security.py).
    """
    from app.core.settings import Settings

    app.state.settings = Settings(app_env="test", rate_limit_enabled=False)
    return TestClient(app)


@pytest.fixture(name="db_available")
def db_available_fixture() -> bool:
    """Expose database availability to tests."""
    return DB_AVAILABLE
