"""FastAPI application factory.

Phase 1 scope: architecture foundation — correlation middleware, access
logging, uniform error handling, CORS and the domain-router layout
(section 54). Domain endpoints are honest 501 stubs until their phase
implements them; `/api/v1/health` is real.
"""

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.exception_handlers import register_exception_handlers
from app.api.v1.routers import routers as domain_routers
from app.config import settings
from app.core.logging import configure_logging, get_logger
from app.core.middleware import AccessLogMiddleware, CorrelationIdMiddleware
from app.core.security_middleware import (
    OriginCheckMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)

logger = get_logger("app")


def _warm_embeddings() -> None:
    """Load the BGE-M3 model once, off the request path (see ``lifespan``)."""
    try:
        from pipeline.enrich.embeddings import EmbeddingModel

        EmbeddingModel.shared().encode(["warmup"])
        logger.info("embedding model warmed and ready")
    except Exception:  # warm-up must never break startup
        logger.warning("embedding warm-up failed; will load lazily", exc_info=True)


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
    # Warm the embedding model off the request path. Otherwise the first
    # semantic search pays the full ~20 s BGE-M3 load inline and every
    # request queued behind it waits too. A daemon thread keeps startup
    # instant and non-fatal: on failure the model still loads lazily.
    if settings.embedding_warmup:
        threading.Thread(
            target=_warm_embeddings, name="embedding-warmup", daemon=True
        ).start()
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
    # Phase 23 hardening, inside CORS so blocked requests are still
    # correlated and access-logged. Order (innermost last): headers are
    # applied to every response; the origin check rejects cross-origin
    # state-changing browser requests before rate counting burns budget.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(OriginCheckMiddleware)

    # Uniform error envelope for every failure mode (section 55).
    register_exception_handlers(app)

    # Expose settings to request handlers (auth cookie flags, etc.).
    app.state.settings = settings

    # Domain routers (section 54) — one per domain, no giant router.
    for router in domain_routers:
        app.include_router(router, prefix="/api/v1")

    return app


app = create_app()
