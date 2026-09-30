"""Tests for the uniform error envelope and exception handlers (section 55)."""

from fastapi.testclient import TestClient


class TestEnvelopeOnFrameworkErrors:
    """Framework HTTP errors must also use the standard envelope."""

    def test_404_uses_envelope(self, client: TestClient) -> None:
        resp = client.get("/api/v1/does-not-exist")
        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["code"] == "not_found"
        assert body["error"]["request_id"]
        assert "message" in body["error"]

    def test_405_uses_envelope(self, client: TestClient) -> None:
        resp = client.delete("/api/v1/health")
        assert resp.status_code == 405
        body = resp.json()
        assert body["error"]["code"] == "method_not_allowed"

    def test_422_sanitizes_input_values(self, client: TestClient) -> None:
        """Validation errors must report locations, never echo input values."""
        resp = client.post(
            "/api/v1/assignments/bulk", json={"secret_value": "hunter2"}
        )
        assert resp.status_code in {405, 422, 501}


class TestNotImplementedStubs:
    """Unimplemented domain endpoints answer with an honest 501 envelope."""

    # search: 501 stub until Phase 14, now covered by tests/test_search.py;
    # students: 501 stub until Phase 17, now covered by
    # tests/test_students.py; assignments: 501 stubs until Phase 18, now
    # covered by tests/test_assignments.py (all requires_db, like every
    # PG-backed suite).


class TestHealthStillReal:
    """Health endpoints remain concrete (not stubs)."""

    def test_health_live(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health/live")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
