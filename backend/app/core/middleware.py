"""HTTP middleware (section 56).

- CorrelationIdMiddleware: one correlation ID per request, echoed in the
  ``X-Request-ID`` response header and attached to every log line.
- AccessLogMiddleware: one structured access-log line per request containing
  route, method, status code and duration in milliseconds.
"""

import re
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.context import adopt_request_id, new_request_id
from app.core.logging import get_logger

access_logger = get_logger("app.access")

#: A well-formed correlation ID: exactly 32 lowercase hex chars (the
#: format new_request_id() generates). Anything else is treated as absent
#: so clients cannot inject junk into logs (phase 23 hardening).
_REQUEST_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Assign a correlation ID to every request.

    An inbound ``X-Request-ID`` from another platform component is
    adopted when well-formed; otherwise a fresh one is generated.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        incoming = request.headers.get("X-Request-ID", "")
        if _REQUEST_ID_RE.fullmatch(incoming):
            request_id = adopt_request_id(incoming)
        else:
            request_id = new_request_id()
        # Share via request.state (backed by the scope dict, which crosses
        # middleware boundaries even where contextvars do not — phase 23:
        # security-middleware rejections must log and echo this same id).
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = getattr(
            request.state, "request_id", request_id
        )
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Log one line per request: route, status, duration."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            access_logger.error(
                "%s %s -> 500 (%.1f ms, unhandled exception)",
                request.method,
                request.url.path,
                duration_ms,
                extra={"route": request.url.path, "method": request.method, "status": 500},
            )
            raise
        duration_ms = (time.perf_counter() - start) * 1000
        access_logger.info(
            "%s %s -> %d (%.1f ms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            extra={
                "route": request.url.path,
                "method": request.method,
                "status": response.status_code,
                "duration_ms": round(duration_ms, 1),
            },
        )
        return response
