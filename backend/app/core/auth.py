"""Teacher authentication core (Phase 15, section 91 / section 5).

- Argon2id password hashing (section 5 mandates Argon2id; argon2-cffi
  defaults are memory=64MiB, time_cost=3, parallelism=4 — OWASP-aligned).
- Sessions are fully server-side: the cookie carries only a random opaque
  token (32 bytes, secrets.token_urlsafe); the DB stores its SHA-256 hash
  (never the token — section 56 logging rule; a DB dump must not yield
  usable session credentials).
- Bootstrap: with zero teachers in the database, one teacher may be
  created via POST /auth/bootstrap. The window closes forever once a
  teacher exists (registration stays closed afterwards, section 91).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import text
from sqlalchemy.engine import Connection

# Argon2id parameters: verify implicitly recomputes with the stored params,
# so parameter changes invalidate old hashes gracefully on next login.
_hasher = PasswordHasher()

SESSION_TTL = timedelta(hours=24)
COOKIE_NAME = "session_token"
# Minimum viable password policy (section 39: input validation). Deliberately
# modest — length beats composition rules per current NIST guidance.
MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    """Hash a password with Argon2id."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Constant-time-ish password verification (argon2 raises on mismatch)."""
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:  # noqa: BLE001 - malformed hash must not 500
        return False


def validate_registration(email: str, password: str, display_name: str) -> str | None:
    """Return an error message for invalid registration input, else None."""
    email = (email or "").strip().lower()
    if "@" not in email or len(email) > 320 or email.startswith("@") or email.endswith("@"):
        return "A valid email address is required."
    if display_name is None or not display_name.strip() or len(display_name) > 200:
        return "A display name (1-200 characters) is required."
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > 1024:
        return "Password must be at most 1024 characters."
    return None


def new_session_token() -> str:
    """A fresh opaque session token (never stored in plaintext)."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    """SHA-256 of the session token — what the database stores."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    """Compare two hash strings without leaking timing information."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def create_session(conn: Connection, teacher_id: Any, token: str) -> dict[str, Any]:
    """Insert a server-side session for the given token."""
    row = conn.execute(
        text(
            "INSERT INTO teacher_sessions (id, teacher_id, token_hash, expires_at) "
            "VALUES (:id, :teacher_id, :token_hash, now() + :ttl) "
            "RETURNING id, created_at, expires_at"
        ),
        {
            "id": uuid.uuid4(),
            "teacher_id": teacher_id,
            "token_hash": token_hash(token),
            "ttl": SESSION_TTL,
        },
    ).mappings().one()
    return dict(row)


def resolve_session(
    conn: Connection, token: str
) -> dict[str, Any] | None:
    """Resolve a session token to its live teacher, or None.

    A session is live when: token hash matches, not revoked, not expired,
    and the teacher is active. Expired-but-unrevoked sessions are pruned
    lazily on access (section 91: expired session must not authenticate).
    """
    if not token:
        return None
    row = conn.execute(
        text(
            """
            SELECT t.id AS teacher_id, t.email, t.display_name, t.is_active,
                   s.id AS session_id, s.expires_at, s.revoked_at
            FROM teacher_sessions s
            JOIN teachers t ON t.id = s.teacher_id
            WHERE s.token_hash = :token_hash
            """
        ),
        {"token_hash": token_hash(token)},
    ).mappings().first()
    if row is None:
        return None
    if row["revoked_at"] is not None:
        return None
    if row["expires_at"] is not None and row["expires_at"] <= datetime.now(
        row["expires_at"].tzinfo
    ):
        # Lazy prune of this expired session.
        conn.execute(
            text("DELETE FROM teacher_sessions WHERE id = :sid"),
            {"sid": row["session_id"]},
        )
        return None
    if not row["is_active"]:
        return None
    return dict(row)


def revoke_session(conn: Connection, token: str) -> bool:
    """Revoke a session by token; True if a live session was revoked."""
    result = conn.execute(
        text(
            "UPDATE teacher_sessions SET revoked_at = now() "
            "WHERE token_hash = :token_hash AND revoked_at IS NULL"
        ),
        {"token_hash": token_hash(token)},
    )
    return bool(result.rowcount)


def count_teachers(conn: Connection) -> int:
    """Number of teacher accounts (bootstrap gate)."""
    return int(conn.execute(text("SELECT count(*) FROM teachers")).scalar() or 0)


def create_teacher(
    conn: Connection, email: str, password: str, display_name: str
) -> dict[str, Any]:
    """Create a teacher account (bootstrap only; registration stays closed)."""
    email = email.strip().lower()
    display_name = display_name.strip()
    if count_teachers(conn) > 0:
        raise PermissionError("bootstrap_closed")
    existing = conn.execute(
        text("SELECT id FROM teachers WHERE email = :email"), {"email": email}
    ).first()
    if existing is not None:
        raise ValueError("email_taken")
    tid = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO teachers (id, email, password_hash, display_name, is_active) "
            "VALUES (:id, :email, :password_hash, :display_name, true)"
        ),
        {
            "id": tid,
            "email": email,
            "password_hash": hash_password(password),
            "display_name": display_name,
        },
    )
    return {"teacher_id": tid, "email": email, "display_name": display_name}
