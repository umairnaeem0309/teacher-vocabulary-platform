"""Global exception handlers translating every failure into one envelope.

Coverage (section 55):
- ``AppError``: typed domain errors -> their own status/code.
- ``RequestValidationError``: FastAPI/Pydantic schema errors -> 422 with
  sanitized field errors (input values are stripped, never echoed).
- ``StarletteHTTPException``: framework HTTP errors (404/405/...) -> envelope.
- unhandled ``Exception``: logged with traceback internally, generic 500
  externally. No stack traces or internals in responses.
"""

from collections.abc import Mapping, Sequence

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError, error_envelope
from app.core.logging import get_logger

logger = get_logger("app.errors")

# Human-facing names for common framework HTTP codes.
_HTTP_CODE_NAMES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}


def _sanitize_validation_errors(
    errors: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Keep location/message/type; never echo received input values back."""
    return [
        {
            "loc": e.get("loc"),
            "msg": e.get("msg"),
            "type": e.get("type"),
        }
        for e in errors[:20]
    ]


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all handlers to the application."""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "app error: %s: %s",
            exc.code,
            exc.message,
            extra={"route": request.url.path, "method": request.method},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_envelope(code=exc.code, message=exc.message, details=exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.info(
            "schema validation failed: %d errors",
            len(exc.errors()),
            extra={"route": request.url.path, "method": request.method},
        )
        return JSONResponse(
            status_code=422,
            content=error_envelope(
                code="schema_validation_error",
                message="Request payload failed schema validation.",
                details={"errors": _sanitize_validation_errors(exc.errors())},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = _HTTP_CODE_NAMES.get(exc.status_code, f"http_{exc.status_code}")
        return JSONResponse(
            status_code=exc.status_code,
            content=error_envelope(code=code, message=str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def handle_unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled exception on %s %s",
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content=error_envelope(
                code="internal_error",
                message="An unexpected error occurred.",
            ),
        )
