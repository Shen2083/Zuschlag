from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from zuschlag_api.api.routes import audit, health, rfqs, sap
from zuschlag_api.core.config import Settings, get_settings
from zuschlag_api.core.logging import configure_logging
from zuschlag_api.core.security import SecurityHeadersMiddleware
from zuschlag_api.db.session import get_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await get_engine().dispose()

    if settings.embedding_provider == "sentence_transformers":
        # Fail at startup, not on the first IDoc, if the model runtime is missing.
        from zuschlag_api.embeddings import embedder_from_settings

        embedder_from_settings(settings)

    docs = not settings.is_production
    app = FastAPI(
        title="Zuschlag.ai API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )

    # Order matters: the last added middleware runs first.
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,  # exact origins only, validated in Settings
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Tenant-ID",
            "X-Actor-ID",
            "X-Request-ID",
        ],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

    app.include_router(health.router)
    app.include_router(rfqs.router)
    app.include_router(audit.router)
    app.include_router(sap.router)
    return app


app = create_app()
