"""Health check endpoints.

Phase 0: verifies process liveness and database connectivity. The database
check is deliberately separate from the basic ping so the app can report
degraded state instead of crashing when PostgreSQL is unavailable.
"""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.db.session import get_engine

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Health status payload."""

    status: str
    app: str
    environment: str
    database: str | None = None
    detail: str | None = None


def _check_database() -> dict[str, Any]:
    """Attempt a trivial database round-trip."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"database": "up"}
    except SQLAlchemyError as exc:
        return {"database": "down", "detail": str(exc.__cause__ or exc)}


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Process liveness plus database connectivity."""
    result = _check_database()
    db_status = result.get("database", "unknown")
    overall = "ok" if db_status == "up" else "degraded"
    return HealthResponse(
        status=overall,
        app=settings.app_name,
        environment=settings.app_env,
        database=db_status,
        detail=result.get("detail"),
    )


@router.get("/health/live", response_model=HealthResponse)
def liveness() -> HealthResponse:
    """Process liveness only (no database dependency)."""
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        environment=settings.app_env,
    )
