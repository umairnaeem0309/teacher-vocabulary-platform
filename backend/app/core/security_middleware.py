"""Security middleware (phase 23, sections 39/40/100).

Three independent defenses, layered inside the CORS / correlation /
access-log stack so blocked requests are still logged and correlated:

1. **SecurityHeadersMiddleware** — defensive response headers on every
   response (§39 XSS prevention belt-and-suspenders; the SPA/API split
   and React escaping remain the primary XSS defense — the API serves
   JSON only).
2. **OriginCheckMiddleware** — CSRF defense for the cookie-authenticated
   API (§39 "CSRF protection where applicable"). Browsers attach session
   cookies to cross-site requests regardless of CORS, so every
   state-changing request that arrives with an ``Origin`` header (i.e.
   was made by a browser) must present an explicitly allowed origin.
   Requests without ``Origin`` are non-browser clients (curl, server
   scripts, tests) which cannot be CSRFed — they pass.
3. **RateLimitMiddleware** — per-client-IP fixed-window limits (§39
   "rate limiting where appropriate"): tight on login/bootstrap (the
   password-guessing surface) and imports (expensive multipart parsing),
   generous on reads/writes. Over budget → 429 with ``Retry-After``.

The single-teacher deployment model (§39) makes client IP the right
limiting key; the limiter is in-process (see app.core.ratelimit).
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.context import adopt_request_id, new_request_id
from app.core.errors import error_envelope
from app.core.ratelimit import (
    LIMIT_LOGIN,
    LIMIT_READ,
    LIMIT_UPLOAD,
    LIMIT_WRITE,
    Decision,
    Limit,
    RateLimiter,
    limits_from_settings,
)

#: Methods that cannot change server state (§100 CSRF scope).
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: Methods that carry a request body and may mutate state.
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: Login/bootstrap: the password-guessing surface gets the tightest budget.
_AUTH_LIMIT_PATHS = frozenset({"/api/v1/auth/login", "/api/v1/auth/bootstrap"})

#: Multipart upload endpoints: expensive parsing gets its own budget.
_UPLOAD_PREFIX = "/api/v1/imports/"

#: Module-level limiter so tests can reset state between cases (the app
#: object is created once per process and shared by every TestClient).
rate_limiter = RateLimiter()


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Standard-envelope error response for middleware rejections.

    Middleware rejections short-circuit before the route runs, so the
    correlation ID may not have reached this task's context yet (task-
    copied contexts between BaseHTTPMiddleware layers). The id is shared
    via ``request.state`` (the scope dict crosses all layers): reuse it,
    or establish a fresh one. The rejection response carries the header
    itself — an early-returning inner middleware may not pass back
    through the correlation layer's post-processing on every Starlette
    version — so envelope and header always agree (§56 contract).
    """
    request_id = getattr(request.state, "request_id", "")
    if not request_id:
        request_id = new_request_id()
        request.state.request_id = request_id
    adopt_request_id(request_id)
    all_headers = {"X-Request-ID": request_id, **(headers or {})}
    return JSONResponse(
        status_code=status_code,
        content=error_envelope(code=code, message=message),
        headers=all_headers,
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Defensive response headers on every response (§39)."""

    def __init__(self, app: object) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "strict-origin-when-cross-origin",
        }

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        for name, value in self._headers.items():
            response.headers[name] = value
        return response


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """Reject cross-origin state-changing browser requests (CSRF, §39).

    A request is treated as browser-made iff it carries an ``Origin``
    header (browsers send it on every cross-site request and on
    same-origin mutating fetch/XHR). Browser-made requests must present
    one of ``settings.allowed_request_origin_list``; anything else gets
    403 before touching the route. Origin-less requests are non-browser
    clients that present credentials deliberately — they pass (and are
    still rate-limited and session-authenticated downstream).
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method in MUTATING_METHODS:
            settings = getattr(request.app.state, "settings", None)
            allowed = (
                settings.allowed_request_origin_list if settings is not None else []
            )
            if allowed:  # empty list disables the check (non-browser deployment)
                origin = request.headers.get("origin")
                if origin and origin not in allowed:
                    return _error_response(
                        request,
                        403,
                        "forbidden",
                        "Cross-origin request rejected.",
                    )
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-client-IP fixed-window rate limiting (§39)."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        classification = self._classify(request)
        if classification is None:
            return await call_next(request)
        route_class, limit = classification
        decision = rate_limiter.check(
            f"{route_class}:{self._client_key(request)}", limit
        )
        if not decision.allowed:
            return _error_response(
                request,
                429,
                "rate_limited",
                "Too many requests; slow down and try again soon.",
                headers={
                    "Retry-After": str(decision.retry_after),
                    "X-RateLimit-Limit": str(limit.max_requests),
                },
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit.max_requests)
        return response

    def _classify(self, request: Request) -> tuple[str, Limit] | None:
        """Map the request to a route class, or None when limiting is off."""
        settings = getattr(request.app.state, "settings", None)
        if settings is None or not settings.rate_limit_enabled:
            return None
        limits = limits_from_settings(settings)
        path = request.url.path
        candidate: tuple[str, Limit] | None
        if path in _AUTH_LIMIT_PATHS and request.method == "POST":
            candidate = (LIMIT_LOGIN, limits[LIMIT_LOGIN])
        elif path.startswith(_UPLOAD_PREFIX) and request.method == "POST":
            candidate = (LIMIT_UPLOAD, limits[LIMIT_UPLOAD])
        elif request.method in MUTATING_METHODS:
            candidate = (LIMIT_WRITE, limits[LIMIT_WRITE])
        elif request.method in SAFE_METHODS:
            candidate = (LIMIT_READ, limits[LIMIT_READ])
        else:
            candidate = None
        if candidate is not None and candidate[1].max_requests <= 0:
            # A non-positive budget means "class disabled", not "block all".
            return None
        return candidate
        if path in _AUTH_LIMIT_PATHS and request.method == "POST":
            return (LIMIT_LOGIN, limits[LIMIT_LOGIN])
        if path.startswith(_UPLOAD_PREFIX) and request.method == "POST":
            return (LIMIT_UPLOAD, limits[LIMIT_UPLOAD])
        if request.method in MUTATING_METHODS:
            return (LIMIT_WRITE, limits[LIMIT_WRITE])
        if request.method in SAFE_METHODS:
            return (LIMIT_READ, limits[LIMIT_READ])
        return None

    @staticmethod
    def _client_key(request: Request) -> str:
        return request.client.host if request.client else "unknown"


__all__ = [
    "Decision",
    "OriginCheckMiddleware",
    "RateLimitMiddleware",
    "SecurityHeadersMiddleware",
    "rate_limiter",
]
