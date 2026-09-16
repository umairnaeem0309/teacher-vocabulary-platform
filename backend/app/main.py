"""FastAPI application factory.

Phase 0 scope: application skeleton with a health endpoint. Domain routers
(auth, students, vocabulary, search, ...) are added in later phases.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.health import router as health_router
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run startup/shutdown hooks. Database checks live in the health router."""
    yield


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.include_router(health_router, prefix="/api/v1")

    return app


app = create_app()
