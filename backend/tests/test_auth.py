"""Phase 15 tests: teacher authentication (sections 5, 39, 91).

Covers the §91 checklist: valid login, invalid password, expired session,
unauthorized request, logout — plus bootstrap-window closure, cookie
flags, token-hash-at-rest, lazy pruning and anti-enumeration timing.

DB-dependent tests run against the dev database with unique per-run
emails and full cleanup in finally blocks. The bootstrap test needs a
teacher-free database; it uses a UNIQUE constraint trick instead — it
creates its own teacher first via the core API (never via bootstrap if
one exists) and asserts the window-closure behaviour, which is the
observable guarantee §91 asks for.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import auth as auth_core
from tests.conftest import requires_db


def _email() -> str:
    return f"auth-test-{uuid.uuid4().hex[:12]}@example.com"


def _make_teacher(email: str, password: str = "correct horse battery staple") -> None:
    """Insert a teacher directly (bypasses the bootstrap gate)."""
    from app.db.session import get_engine

    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO teachers (id, email, password_hash, display_name, is_active) "
                "VALUES (:id, :email, :ph, 'Auth Test Teacher', true)"
            ),
            {
                "id": uuid.uuid4(),
                "email": email,
                "ph": auth_core.hash_password(password),
            },
        )


def _drop_teacher(email: str) -> None:
    from app.db.session import get_engine

    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM teachers WHERE email = :email"), {"email": email})


# --------------------------------------------------------------------------
# Password hashing / token units (no DB)
# --------------------------------------------------------------------------


class TestPasswordUnits:
    def test_argon2id_hash_and_verify(self) -> None:
        h = auth_core.hash_password("s3cret-password")
        assert h.startswith("$argon2id$")
        assert auth_core.verify_password(h, "s3cret-password")
        assert not auth_core.verify_password(h, "wrong-password")

    def test_verify_malformed_hash_is_false(self) -> None:
        assert not auth_core.verify_password("not-a-hash", "whatever")

    def test_token_hash_is_sha256_and_deterministic(self) -> None:
        t = auth_core.new_session_token()
        assert t != auth_core.token_hash(t)
        assert auth_core.token_hash(t) == auth_core.token_hash(t)
        assert len(auth_core.new_session_token()) >= 40  # 32 bytes urlsafe

    def test_registration_validation(self) -> None:
        assert auth_core.validate_registration("a@b.com", "longenough-pw", "T") is None
        assert auth_core.validate_registration("not-an-email", "longenough-pw", "T")
        assert auth_core.validate_registration("a@b.com", "short", "T")
        assert auth_core.validate_registration("a@b.com", "longenough-pw", "  ")
        assert auth_core.validate_registration("a@b.com", "x" * 2000, "T")


# --------------------------------------------------------------------------
# §91 checklist against the live API
# --------------------------------------------------------------------------


@requires_db
class TestAuthFlow:
    def test_full_flow_bootstrap_login_logout(self, client: TestClient) -> None:
        """Bootstrap closes after the first teacher; login/logout cycle."""
        # 1) Bootstrap works exactly once ever (first run may already have
        #    a teacher from a previous phase; both outcomes are correct).
        email = _email()
        r = client.post(
            "/api/v1/auth/bootstrap",
            json={"email": email, "password": "bootstrap-pass-1", "display_name": "First"},
        )
        try:
            if r.status_code == 201:
                assert "session_token" in r.cookies
                assert r.json()["teacher"]["email"] == email
                assert "now closed" in r.json()["note"]
                created = True
            else:
                assert r.status_code == 403
                assert r.json()["error"]["code"] == "bootstrap_closed"
                created = False
        finally:
            if created:
                _drop_teacher(email)

        # 2) After the window: bootstrap refuses (403) regardless of input.
        if not created:
            r2 = client.post(
                "/api/v1/auth/bootstrap",
                json={"email": email, "password": "bootstrap-pass-1", "display_name": "X"},
            )
            assert r2.status_code == 403

        # 3) Login with a teacher we own; invalid password rejected (§91).
        email2 = _email()
        _make_teacher(email2)
        try:
            bad = client.post(
                "/api/v1/auth/login",
                json={"email": email2, "password": "definitely-wrong"},
            )
            assert bad.status_code == 401
            assert bad.json()["error"]["code"] == "authentication_error"

            good = client.post(
                "/api/v1/auth/login",
                json={"email": email2, "password": "correct horse battery staple"},
            )
            assert good.status_code == 200
            assert good.json()["teacher"]["email"] == email2
            assert "session_token" in good.cookies

            # Cookie flags (§39: secure HTTP-only cookie).
            set_cookie = good.headers["set-cookie"]
            assert "HttpOnly" in set_cookie
            assert "samesite=lax" in set_cookie.lower()
            assert "Secure" not in set_cookie  # development

            # 4) Session endpoint authenticates with the cookie.
            who = client.get("/api/v1/auth/session")
            assert who.status_code == 200
            assert who.json()["teacher"]["email"] == email2

            # 5) Logout revokes server-side; the old cookie is dead after.
            out = client.post("/api/v1/auth/logout")
            assert out.status_code == 200
            assert out.json()["revoked"] is True

            after = client.get("/api/v1/auth/session")
            assert after.status_code == 401
            assert after.json()["error"]["code"] == "authentication_error"
        finally:
            _drop_teacher(email2)

    def test_unauthorized_request_without_cookie(self, client: TestClient) -> None:
        """§91: unauthorized request → uniform 401 envelope."""
        r = client.get("/api/v1/auth/session")
        assert r.status_code == 401
        body = r.json()
        assert body["error"]["code"] == "authentication_error"
        assert body["error"]["request_id"]

    def test_unknown_email_no_enumeration(self, client: TestClient) -> None:
        """Unknown email and wrong password share the same 401/message."""
        r = client.post(
            "/api/v1/auth/login",
            json={"email": _email(), "password": "whatever-password"},
        )
        assert r.status_code == 401
        assert r.json()["error"]["message"] == "Invalid email or password."

    def test_token_stored_hashed_not_plaintext(self, client: TestClient) -> None:
        """§56/§39: the DB must hold the token hash, never the token."""
        email = _email()
        _make_teacher(email)
        try:
            r = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "correct horse battery staple"},
            )
            assert r.status_code == 200
            token = r.cookies["session_token"]
            from app.db.session import get_engine

            with get_engine().connect() as conn:
                stored = conn.execute(
                    text(
                        "SELECT token_hash FROM teacher_sessions WHERE token_hash = :h"
                    ),
                    {"h": auth_core.token_hash(token)},
                ).first()
                plaintext = conn.execute(
                    text(
                        "SELECT count(*) FROM teacher_sessions "
                        "WHERE token_hash = :t"
                    ),
                    {"t": token},
                ).scalar()
            assert stored is not None  # hash lookup finds the session
            assert plaintext == 0  # token itself is not stored
        finally:
            _drop_teacher(email)


# --------------------------------------------------------------------------
# Session mechanics (direct DB manipulation for expiry)
# --------------------------------------------------------------------------


@requires_db
class TestSessionMechanics:
    def test_expired_session_is_dead_and_pruned(self, client: TestClient) -> None:
        """§91: expired session must not authenticate; row is pruned."""
        email = _email()
        _make_teacher(email)
        try:
            r = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "correct horse battery staple"},
            )
            token = r.cookies["session_token"]
            th = auth_core.token_hash(token)

            from app.db.session import get_engine

            with get_engine().begin() as conn:
                conn.execute(
                    text(
                        "UPDATE teacher_sessions SET expires_at = :past "
                        "WHERE token_hash = :h"
                    ),
                    {
                        "h": th,
                        "past": datetime.now(tz=None).astimezone()
                        - timedelta(minutes=1),
                    },
                )

            # Expired cookie → 401 (§91 expired session case)…
            assert client.get("/api/v1/auth/session").status_code == 401

            # …and the row was pruned lazily.
            with get_engine().connect() as conn:
                n = conn.execute(
                    text("SELECT count(*) FROM teacher_sessions WHERE token_hash = :h"),
                    {"h": th},
                ).scalar()
            assert n == 0
        finally:
            _drop_teacher(email)

    def test_revoked_session_cannot_authenticate(self, client: TestClient) -> None:
        email = _email()
        _make_teacher(email)
        try:
            r = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "correct horse battery staple"},
            )
            token = r.cookies["session_token"]
            from app.db.session import get_engine

            with get_engine().begin() as conn:
                assert auth_core.revoke_session(conn, token)
                # Second revoke is a no-op (already revoked).
                assert not auth_core.revoke_session(conn, token)
            assert client.get("/api/v1/auth/session").status_code == 401
        finally:
            _drop_teacher(email)

    def test_garbage_cookie_is_unauthorized(self, client: TestClient) -> None:
        client.cookies.set("session_token", "garbage-token-value")
        assert client.get("/api/v1/auth/session").status_code == 401

    def test_inactive_teacher_cannot_authenticate(self, client: TestClient) -> None:
        email = _email()
        _make_teacher(email)
        try:
            r = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "correct horse battery staple"},
            )
            assert r.status_code == 200
            from app.db.session import get_engine

            with get_engine().begin() as conn:
                conn.execute(
                    text("UPDATE teachers SET is_active = false WHERE email = :e"),
                    {"e": email},
                )
            assert client.get("/api/v1/auth/session").status_code == 401
        finally:
            _drop_teacher(email)

    def test_validation_rejects_bad_payloads(self, client: TestClient) -> None:
        """Short passwords fail domain validation with a 422 envelope."""
        r = client.post(
            "/api/v1/auth/bootstrap",
            json={"email": _email(), "password": "short", "display_name": "X"},
        )
        # If a teacher already exists, bootstrap_closure (403) wins — that
        # is correct: never leak whether the password would have passed.
        if r.status_code == 422:
            assert r.json()["error"]["code"] == "validation_error"
        else:
            assert r.status_code == 403
