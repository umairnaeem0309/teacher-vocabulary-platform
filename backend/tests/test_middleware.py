"""Tests for correlation middleware and access logging (section 56)."""

import logging

from fastapi.testclient import TestClient


class TestCorrelationId:
    """Every response carries X-Request-ID; each request gets its own."""

    def test_request_id_header_present(self, client: TestClient) -> None:
        resp = client.get("/api/v1/health/live")
        assert resp.headers.get("X-Request-ID")
        assert len(resp.headers["X-Request-ID"]) == 32

    def test_request_ids_differ_between_requests(self, client: TestClient) -> None:
        id1 = client.get("/api/v1/health/live").headers["X-Request-ID"]
        id2 = client.get("/api/v1/health/live").headers["X-Request-ID"]
        assert id1 != id2


class TestErrorEnvelopeCorrelation:
    """Error envelopes echo the request's correlation ID."""

    def test_404_envelope_has_request_id(self, client: TestClient) -> None:
        resp = client.get("/api/v1/nope")
        request_id = resp.headers["X-Request-ID"]
        body = resp.json()
        assert body["error"]["request_id"] == request_id


class TestSensitiveKeyMasking:
    """Secrets passed through logging extras never reach output (section 56)."""

    def test_masking_via_extra(self, caplog: logging.LogRecord) -> None:
        from app.core.logging import JsonFormatter

        logger = logging.getLogger("test.mask")
        formatter = JsonFormatter()
        logger.propagate = True

        with caplog.at_level(logging.INFO, logger="test.mask"):
            logger.info(
                "attempt",
                extra={"password": "hunter2", "token": "abc", "user": "teacher"},
            )

        record = caplog.records[-1]
        rendered = formatter.format(record)
        # Rendered JSON never contains the secret values.
        assert "hunter2" not in rendered
        assert '"abc"' not in rendered
        # Non-sensitive fields survive.
        assert "teacher" in rendered

    def test_nested_masking(self) -> None:
        from app.core.logging import _mask_sensitive

        masked = _mask_sensitive(
            {"body": {"password": "x", "nested": [{"api_key": "y"}], "ok": 1}}
        )
        assert masked["body"]["password"] == "***"
        assert masked["body"]["nested"][0]["api_key"] == "***"
        assert masked["body"]["ok"] == 1
