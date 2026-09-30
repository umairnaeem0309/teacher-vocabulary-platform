"""Application error hierarchy and API error envelope (section 55).

Goals: structured, consistent, actionable, safe.

- Domain code raises typed exceptions (``AppError`` subclasses) with
  machine-readable codes; the API layer translates them into a uniform JSON
  envelope: ``{"error": {"code", "message", "details", "request_id"}}``.
- ``details`` is safe by construction: only what the domain explicitly put
  there. Stack traces, credentials and filesystem paths never leave the
  process; they go to logs (with the correlation ID) instead.
"""

from http import HTTPStatus
from typing import Any

from app.core.context import get_request_id


class AppError(Exception):
    """Base class for all expected application errors."""

    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or self.message)
        # Carry the instance message into the error envelope: without
        # this, every envelope showed the class-level default and the
        # specific, user-actionable text was lost (found in Phase 22).
        self.message = message or self.message
        self.details = details or {}


class ValidationError(AppError):
    """Client input failed domain validation (distinct from schema 422)."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "validation_error"
    message = "The provided data is not valid."


class NotFoundError(AppError):
    """The requested resource does not exist."""

    status_code = HTTPStatus.NOT_FOUND
    code = "not_found"
    message = "The requested resource was not found."


class ConflictError(AppError):
    """The request conflicts with existing state (e.g. duplicates)."""

    status_code = HTTPStatus.CONFLICT
    code = "conflict"
    message = "The request conflicts with the current state."


class AuthenticationError(AppError):
    """Missing or invalid credentials."""

    status_code = HTTPStatus.UNAUTHORIZED
    code = "authentication_error"
    message = "Authentication is required."


class AuthorizationError(AppError):
    """Authenticated but not allowed to touch this resource."""

    status_code = HTTPStatus.FORBIDDEN
    code = "authorization_error"
    message = "You do not have access to this resource."


def error_envelope(
    *,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the uniform error payload returned by every error handler."""
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": get_request_id() or "-",
        }
    }
