"""Shared helper for not-yet-implemented domain endpoints.

Each domain keeps its own router module from Phase 1 so the API surface is
organized and documentable from the start (section 54). Endpoints whose
functionality arrives in a later phase return a consistent 501 envelope —
an honest signal to clients and tests, never a silent fake.

The ``phase`` argument records which phase will implement the endpoint,
keeping ``plan.md`` and the API self-documenting.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.errors import error_envelope


def not_implemented(router: APIRouter, path: str, phase: int, **kwargs: object) -> None:
    """Register a placeholder route returning 501 with the standard envelope."""

    phase_fixed = phase
    options: dict[str, object] = {"methods": ["GET"], **kwargs}

    @router.api_route(path, **options)  # type: ignore[arg-type]
    async def _stub() -> JSONResponse:
        return JSONResponse(
            status_code=501,
            content=error_envelope(
                code="not_implemented",
                message=f"This endpoint is not implemented yet; "
                f"planned for phase {phase_fixed}.",
                details={"phase": phase_fixed},
            ),
        )


def register_stubs(
    router: APIRouter, routes: list[tuple[str, int]], **kwargs: object
) -> None:
    """Register several placeholder routes on one router."""
    for path, phase in routes:
        not_implemented(router, path, phase, **kwargs)
