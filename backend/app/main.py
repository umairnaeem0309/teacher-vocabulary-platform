"""FastAPI application factory.

Phase 1 scope: architecture foundation — correlation middleware, access
logging, uniform error handling, CORS and the domain-router layout
(section 54). Domain endpoints are honest 501 stubs until their phase
implements them; `/api/v1/health` is real.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.exception_handlers import register_exception_handlers
from app.api.v1.routers import routers as domain_routers
from app.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.middleware import AccessLogMiddleware, CorrelationIdMiddleware

logger = get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Validate configuration at startup; log the boot line."""
    configure_logging()
    logger.info(
        "starting %s (env=%s, log_format=%s)",
        settings.app_name,
        settings.app_env,
        settings.log_format,
    )
    yield
    logger.info("shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    # Middleware (outermost first).
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    # Uniform error envelope for every failure mode (section 55).
    register_exception_handlers(app)

    # Domain routers (section 54) — one per domain, no giant router.
    for router in domain_routers:
        app.include_router(router, prefix="/api/v1")

    return app


app = create_app()
