"""Teacher authentication endpoints (Phase 15, sections 5/39/91).

POST /auth/bootstrap  — create the first teacher; window closes forever
                        once one exists (no public registration).
POST /auth/login      — email + password → HTTP-only session cookie.
GET  /auth/session    — who am I (200 with teacher, 401 without).
POST /auth/logout     — revoke the server-side session, clear the cookie.

The cookie carries only the opaque random token; the DB stores its
SHA-256 hash. Cookie flags: HttpOnly, SameSite=Lax, Secure when the app
runs in production/staging, and a Max-Age matching SESSION_TTL.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text

from app.core import auth
from app.core.errors import AuthenticationError, error_envelope
from app.db.session import get_engine

router = APIRouter(prefix="/auth", tags=["auth"])

_LOGIN_SQL = """
SELECT id, email, display_name, password_hash, is_active
FROM teachers WHERE email = :email
"""


class CredentialsIn(BaseModel):
    """Login / bootstrap payload."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)
    display_name: str | None = Field(default=None, max_length=200)


def _get_token(request: Request) -> str:
    return request.cookies.get(auth.COOKIE_NAME, "")


def _cookie_kwargs(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    secure = settings.app_env in ("production", "staging")
    return {
        "key": auth.COOKIE_NAME,
        "httponly": True,
        "samesite": "lax",
        "secure": secure,
        "max_age": int(auth.SESSION_TTL.total_seconds()),
        "path": "/",
    }


def _require_teacher(request: Request) -> dict[str, Any]:
    """Dependency: resolve the session cookie or raise 401 (section 40).

    Uses a committing connection: resolve_session's lazy prune of expired
    sessions must survive (a rolled-back prune would leave dead rows).
    """
    token = _get_token(request)
    with get_engine().begin() as conn:
        session = auth.resolve_session(conn, token)
    if session is None:
        raise AuthenticationError("Authentication is required.")
    return session


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_envelope(code=code, message=message),
    )


def _teacher_payload(teacher: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(teacher["id"] if "id" in teacher else teacher["teacher_id"]),
        "email": teacher["email"],
        "display_name": teacher["display_name"],
    }


@router.post("/bootstrap")
def bootstrap_teacher(body: CredentialsIn, request: Request) -> JSONResponse:
    """Create the first teacher account; closed forever afterwards (§91)."""
    err = auth.validate_registration(
        body.email, body.password, body.display_name or ""
    )
    if err:
        return _error(422, "validation_error", err)
    with get_engine().begin() as conn:
        if auth.count_teachers(conn) > 0:
            return _error(
                403,
                "bootstrap_closed",
                "Bootstrap is closed: a teacher account already exists.",
            )
        try:
            teacher = auth.create_teacher(
                conn, body.email, body.password, body.display_name or ""
            )
        except ValueError:
            return _error(409, "conflict", "That email is already registered.")
        token = auth.new_session_token()
        auth.create_session(conn, teacher["teacher_id"], token)
    response = JSONResponse(
        status_code=201,
        content={
            "teacher": _teacher_payload(teacher),
            "note": "Bootstrap window is now closed.",
        },
    )
    response.set_cookie(value=token, **_cookie_kwargs(request))
    return response


@router.post("/login")
def login(body: CredentialsIn, request: Request) -> JSONResponse:
    """Email + password → HTTP-only session cookie (section 5).

    Unknown email and wrong password return the same message (no user
    enumeration); a decoy hash is verified for unknown emails so both
    paths burn comparable Argon2 time.
    """
    email = body.email.strip().lower()
    with get_engine().begin() as conn:
        teacher = conn.execute(
            text(_LOGIN_SQL), {"email": email}
        ).mappings().first()
        if teacher is None or not teacher["is_active"]:
            auth.verify_password(
                auth.hash_password("decoy-password-for-timing"), body.password
            )
            return _error(401, "authentication_error", "Invalid email or password.")
        if not auth.verify_password(teacher["password_hash"], body.password):
            return _error(401, "authentication_error", "Invalid email or password.")
        token = auth.new_session_token()
        session = auth.create_session(conn, teacher["id"], token)
    response = JSONResponse(
        content={
            "teacher": _teacher_payload(dict(teacher)),
            "session": {"expires_at": session["expires_at"].isoformat()},
        }
    )
    response.set_cookie(value=token, **_cookie_kwargs(request))
    return response


@router.get("/session")
def current_session(
    session: Annotated[dict[str, Any], Depends(_require_teacher)],
) -> dict[str, Any]:
    """Return the authenticated teacher for the session cookie."""
    return {
        "teacher": {
            "id": str(session["teacher_id"]),
            "email": session["email"],
            "display_name": session["display_name"],
        },
        "expires_at": session["expires_at"].isoformat(),
    }


@router.post("/logout")
def logout(request: Request) -> JSONResponse:
    """Revoke the server-side session and clear the cookie."""
    token = _get_token(request)
    revoked = False
    if token:
        with get_engine().begin() as conn:
            revoked = auth.revoke_session(conn, token)
    response = JSONResponse(content={"revoked": revoked})
    response.delete_cookie(
        key=auth.COOKIE_NAME, path="/", httponly=True, samesite="lax"
    )
    return response
