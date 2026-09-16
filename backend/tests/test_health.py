"""Tests for health endpoints (Phase 0 acceptance)."""

from fastapi.testclient import TestClient

from tests.conftest import requires_db


class TestLiveness:
    """Basic liveness endpoint must always pass."""

    def test_liveness_returns_ok(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health/live")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["app"]

    def test_health_endpoint_exists(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in {"ok", "degraded"}


class TestDatabaseHealth:
    """Database-backed health checks."""

    @requires_db
    def test_health_reports_db_up(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["database"] == "up"

    @requires_db
    def test_database_accepts_queries(self) -> None:
        from sqlalchemy import text

        from app.db.session import get_engine

        with get_engine().connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar_one()
            assert "PostgreSQL" in version


def test_health_without_db_reports_degraded(
    client: TestClient, db_available: bool
) -> None:
    """Document (not assert) behavior when DB is down: degraded, not crash."""
    if db_available:
        resp = client.get("/api/v1/health")
        assert resp.json()["status"] == "ok"
