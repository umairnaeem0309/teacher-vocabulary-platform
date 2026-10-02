"""Per-request correlation context (section 56).

The correlation ID is generated once per request by middleware, stored in a
context variable and attached to every log line. The API error envelope
echoes it back to clients so a user-reported problem can be matched to logs.
"""

from contextvars import ContextVar
from uuid import uuid4

NO_REQUEST_ID = ""

_request_id: ContextVar[str] = ContextVar("request_id", default=NO_REQUEST_ID)


def new_request_id() -> str:
    """Generate a fresh correlation ID and store it in the context."""
    value = uuid4().hex
    _request_id.set(value)
    return value


def adopt_request_id(value: str) -> str:
    """Adopt an externally-chosen correlation ID into the context.

    Phase 23: security-middleware rejections can short-circuit before any
    handler runs; the rejection path calls this so its error envelope
    still carries a correlation ID that matches the access log and the
    ``X-Request-ID`` response header.
    """
    _request_id.set(value)
    return value


def get_request_id() -> str:
    """Return the current correlation ID (empty string outside a request)."""
    return _request_id.get()
