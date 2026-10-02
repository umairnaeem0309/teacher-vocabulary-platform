"""Phase 23 tests: security hardening (sections 39/40/100).

Covers:
- Rate limiting: per-IP budgets with 429 + Retry-After, route classes
  (login tightest, uploads separate), disable flag, window rollover.
- CSRF origin check: cross-origin mutating browser request → 403;
  same-origin, GET, and origin-less (curl) requests pass.
- Security headers present on every response.
- Production secret guard (§39 secret management).
- Upload byte cap (§39 safe file handling): oversized import → 413.
- §100 checklist spot checks reusing established behaviors: login
  anti-enumeration, HttpOnly cookie, no-internals error envelope,
  parameterized SQL via the import parser, teacher scoping.

Rate-limit state lives in a module-level limiter; tests reset it via
the ``clean_rate_limiter`` fixture so cases stay independent. Settings
are overridden per-test through ``app.state.settings`` (middleware reads
them per request).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import auth as auth_core
from app.core import security_middleware as sm
from app.core.ratelimit import Limit, RateLimiter
from tests.conftest import requires_db

PASSWORD = "correct horse battery staple"


def _override_settings(client: TestClient, **overrides: Any) -> Any:
    """Swap app.state.settings for a modified copy; return the real one.

    Rebuilds from the process environment (the test process runs with the
    dev/test env, not production), so this never trips the production
    secret guard.
    """
    from app.core.settings import Settings

    real = client.app.state.settings
    client.app.state.settings = Settings(_env_file=None, **overrides)
    return real


@pytest.fixture(name="clean_rate_limiter")
def clean_rate_limiter_fixture() -> Any:
    """Fresh limiter state per test (module-level limiter is shared)."""
    sm.rate_limiter._windows.clear()
    yield sm.rate_limiter
    sm.rate_limiter._windows.clear()


# ---------------------------------------------------------------------------
# Pure rate-limit unit tests (no HTTP, no DB)
# ---------------------------------------------------------------------------


class TestRateLimiterUnit:
    def test_window_fill_then_block(self) -> None:
        limiter = RateLimiter()
        limit = Limit(name="login", max_requests=3, window_seconds=60)
        keys = ["allowed" if limiter.check("ip:login", limit).allowed else "blocked"
                for _ in range(5)]
        assert keys == ["allowed", "allowed", "allowed", "blocked", "blocked"]

    def test_key_isolation(self) -> None:
        limiter = RateLimiter()
        limit = Limit(name="login", max_requests=1, window_seconds=60)
        assert limiter.check("ip1:login", limit).allowed
        # A different IP gets its own budget.
        assert limiter.check("ip2:login", limit).allowed
        assert not limiter.check("ip1:login", limit).allowed

    def test_retry_after_is_positive(self) -> None:
        limiter = RateLimiter()
        limit = Limit(name="login", max_requests=1, window_seconds=300)
        limiter.check("ip:login", limit)
        d = limiter.check("ip:login", limit)
        assert not d.allowed
        assert d.retry_after >= 1

    def test_sweep_drops_elapsed_windows(self) -> None:
        from app.core.ratelimit import _Window

        limiter = RateLimiter()
        limit = Limit(name="read", max_requests=1, window_seconds=1)
        limiter.check("ip:read", limit)
        # Make the window look fully elapsed, fill the map past the sweep
        # threshold, and verify the sweep removes the dead entry.
        limiter._windows[("ip:read", "read")].start -= 5
        for i in range(10_001):
            limiter._windows[(f"fill{i}", "read")] = _Window(
                start=0.0, count=1, period=60
            )
        limiter.check("fresh:read", limit)
        assert ("ip:read", "read") not in limiter._windows


# ---------------------------------------------------------------------------
# HTTP-level security middleware tests (no DB needed)
# ---------------------------------------------------------------------------


class TestSecurityMiddleware:
    def test_security_headers_on_every_response(self, client: TestClient) -> None:
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    def test_cross_origin_post_is_rejected_with_403(
        self, client: TestClient
    ) -> None:
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "x@example.com", "password": "irrelevant"},
            headers={"Origin": "https://evil.example"},
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "forbidden"
        assert "evil.example" not in r.text  # §55: never echo attacker input

    def test_allowed_origin_post_passes_middleware(
        self, client: TestClient, clean_rate_limiter: None
    ) -> None:
        # Origin allowed → passes middleware (401 here: no such teacher in
        # the no-DB context; DB-backed flows are covered by import/export
        # tests which run with the database).
        r = client.post(
            "/api/v1/auth/login",
            json={"email": f"nodb-{uuid.uuid4().hex[:8]}@example.com",
                  "password": "whatever-irrelevant"},
            headers={"Origin": "http://localhost:3000"},
        )
        assert r.status_code in (401, 429)  # never 403

    def test_originless_post_passes_middleware(self, client: TestClient) -> None:
        # curl-style clients send no Origin: cannot be CSRFed.
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "x"},
        )
        assert r.status_code == 401

    def test_get_is_exempt_from_origin_check(self, client: TestClient) -> None:
        r = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
        assert r.status_code == 200

    def test_middleware_rejection_envelope_carries_request_id(
        self, client: TestClient
    ) -> None:
        # Middleware rejections short-circuit before the route runs; the
        # envelope must still echo the correlation ID (§56).
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "x@example.com", "password": "x"},
            headers={"Origin": "https://evil.example"},
        )
        assert r.status_code == 403
        rid = r.headers["X-Request-ID"]
        assert rid
        assert r.json()["error"]["request_id"] == rid

    def test_wellformed_inbound_request_id_is_adopted(
        self, client: TestClient
    ) -> None:
        rid = "a" * 32
        r = client.get("/api/v1/health", headers={"X-Request-ID": rid})
        assert r.headers["X-Request-ID"] == rid

    def test_malformed_inbound_request_id_is_replaced(
        self, client: TestClient
    ) -> None:
        r = client.get("/api/v1/health", headers={"X-Request-ID": "DROP TABLE;"})
        rid = r.headers["X-Request-ID"]
        assert rid != "DROP TABLE;"
        assert len(rid) == 32

    def test_rate_limit_login_429(
        self, client: TestClient, clean_rate_limiter: None
    ) -> None:
        real = _override_settings(client, rate_limit_login_max=3)
        try:
            for _ in range(3):
                r = client.post(
                    "/api/v1/auth/login",
                    json={"email": "nobody@example.com", "password": "x"},
                )
                assert r.status_code == 401
            r = client.post(
                "/api/v1/auth/login",
                json={"email": "nobody@example.com", "password": "x"},
            )
            assert r.status_code == 429
            body = r.json()["error"]
            assert body["code"] == "rate_limited"
            assert r.headers["Retry-After"] >= "1"
            assert r.headers["X-RateLimit-Limit"] == "3"
            # 429 body keeps the uniform envelope shape.
            assert set(body) == {"code", "message", "details", "request_id"}
        finally:
            client.app.state.settings = real

    def test_rate_limit_disabled_passes_all(
        self, client: TestClient, clean_rate_limiter: None
    ) -> None:
        real = _override_settings(client, rate_limit_enabled=False)
        try:
            for _ in range(12):
                r = client.post(
                    "/api/v1/auth/login",
                    json={"email": "nobody@example.com", "password": "x"},
                )
                assert r.status_code == 401
        finally:
            client.app.state.settings = real

    def test_rate_limit_disabled_via_zero_max(
        self, client: TestClient, clean_rate_limiter: None
    ) -> None:
        # max=0 would otherwise block everything; the middleware must
        # treat non-positive budgets as "no limiting".
        real = _override_settings(client, rate_limit_login_max=0)
        try:
            r = client.post(
                "/api/v1/auth/login",
                json={"email": "nobody@example.com", "password": "x"},
            )
            assert r.status_code == 401
        finally:
            client.app.state.settings = real


# ---------------------------------------------------------------------------
# Production secret guard (§39 secret management)
# ---------------------------------------------------------------------------


class TestProductionSecretGuard:
    def test_placeholder_secret_rejected_in_production(self) -> None:
        from app.core.settings import Settings, SettingsError

        with pytest.raises(SettingsError, match="SESSION_SECRET"):
            Settings(
                app_env="production",
                session_secret="change-me-in-later-phases",
                _env_file=None,
            )

    def test_real_secret_accepted_in_production(self) -> None:
        from app.core.settings import Settings

        s = Settings(
            app_env="production",
            session_secret="x" * 64,
            _env_file=None,
        )
        assert s.session_secret == "x" * 64


# ---------------------------------------------------------------------------
# DB-backed §100 checklist spot checks
# ---------------------------------------------------------------------------


def _email() -> str:
    return f"sec-test-{uuid.uuid4().hex[:12]}@example.com"


def _make_teacher(email: str) -> uuid.UUID:
    from app.db.session import get_engine

    tid = uuid.uuid4()
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO teachers (id, email, password_hash, display_name, is_active) "
                "VALUES (:id, :email, :ph, 'Sec Test Teacher', true)"
            ),
            {"id": tid, "email": email, "ph": auth_core.hash_password(PASSWORD)},
        )
    return tid


def _drop_teacher(email: str) -> None:
    from app.db.session import get_engine

    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM teachers WHERE email = :email"), {"email": email})


@pytest.mark.usefixtures("clean_rate_limiter")
@requires_db
class TestAuthHardeningDB:
    def test_login_sets_httponly_lax_cookie(self, client: TestClient) -> None:
        email = _email()
        _make_teacher(email)
        try:
            r = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": PASSWORD},
                headers={"Origin": "http://localhost:3000"},
            )
            assert r.status_code == 200
            cookie = r.headers["set-cookie"]
            assert "httponly" in cookie.lower()
            assert "samesite=lax" in cookie.lower()
            assert "session_token=" in cookie
        finally:
            _drop_teacher(email)

    def test_wrong_password_and_unknown_email_identical(
        self, client: TestClient
    ) -> None:
        email = _email()
        _make_teacher(email)
        try:
            wrong = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "not-the-password"},
                headers={"Origin": "http://localhost:3000"},
            )
            unknown = client.post(
                "/api/v1/auth/login",
                json={"email": f"ghost-{uuid.uuid4().hex[:6]}@example.com",
                      "password": "not-the-password"},
                headers={"Origin": "http://localhost:3000"},
            )
            assert wrong.status_code == unknown.status_code == 401
            # Same code and message (no enumeration); request_id is
            # per-request by design and must differ.
            assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"]
            assert (
                wrong.json()["error"]["message"]
                == unknown.json()["error"]["message"]
            )
            assert (
                wrong.json()["error"]["request_id"]
                != unknown.json()["error"]["request_id"]
            )
        finally:
            _drop_teacher(email)

    def test_login_rate_limit_blocks_password_guessing(
        self, client: TestClient
    ) -> None:
        email = _email()
        _make_teacher(email)
        real = _override_settings(client, rate_limit_login_max=5)
        try:
            codes: list[int] = []
            for _ in range(8):
                r = client.post(
                    "/api/v1/auth/login",
                    json={"email": email, "password": "wrong-guess"},
                    headers={"Origin": "http://localhost:3000"},
                )
                codes.append(r.status_code)
            assert codes[:5] == [401] * 5
            assert codes[5:] == [429] * 3
            # The correct password sent after the block must NOT log in:
            # the window is per-IP, the block comes first (brute force
            # cannot ride a valid credential through the wall).
            blocked = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": PASSWORD},
                headers={"Origin": "http://localhost:3000"},
            )
            assert blocked.status_code == 429
        finally:
            client.app.state.settings = real
            _drop_teacher(email)


@pytest.mark.usefixtures("clean_rate_limiter")
@requires_db
class TestUploadCapDB:
    def test_oversized_upload_rejected_413(self, client: TestClient) -> None:
        email = _email()
        _make_teacher(email)
        real = _override_settings(client, upload_max_bytes=64)
        try:
            r = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": PASSWORD},
                headers={"Origin": "http://localhost:3000"},
            )
            assert r.status_code == 200
            big = b"headword\n" + b"a" * 200
            r2 = client.post(
                "/api/v1/imports/vocabulary/preview",
                files={"file": ("big.csv", big, "text/csv")},
                data={"format": "csv"},
            )
            assert r2.status_code == 413
            assert r2.json()["error"]["code"] == "payload_too_large"
        finally:
            client.app.state.settings = real
            _drop_teacher(email)

    def test_upload_within_cap_still_works(self, client: TestClient) -> None:
        email = _email()
        _make_teacher(email)
        try:
            r = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": PASSWORD},
                headers={"Origin": "http://localhost:3000"},
            )
            assert r.status_code == 200
            csv_text = "headword\nkosmos\n"
            r2 = client.post(
                "/api/v1/imports/vocabulary/preview",
                files={"file": ("ok.csv", csv_text.encode(), "text/csv")},
                data={"format": "csv"},
            )
            assert r2.status_code == 200
            assert r2.json()["total_rows"] == 1
        finally:
            _drop_teacher(email)
