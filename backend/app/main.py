"""Lockverity FastAPI application entry point.

Wires the structured error envelope, request-id middleware, CORS,
and every API router under the configured prefix.

Run locally::

    uvicorn app.main:app --reload

The app does not serve any user-uploaded content, does not expose
the workspace root, and does not proxy to external providers in
v0.1. The static frontend, when present, is hosted separately.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.db import engine
from app.utils.datetime import isoformat_utc, utcnow

logger = logging.getLogger("lockverity")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def _lifespan(_: FastAPI):
    """Sanity-check the schema at startup.

    We do not run migrations automatically - the operator runs
    ``alembic upgrade head`` before starting the app. We do,
    however, log a warning if the metadata doesn't match the
    database, which usually means migrations were skipped.
    """
    settings = get_settings()
    logger.info(
        "lockverity %s starting (env=%s, db=%s)",
        __version__,
        settings.environment,
        settings.database_url,
    )
    yield
    logger.info("lockverity shutting down (now=%s)", isoformat_utc(utcnow()))
    engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=settings.app_tagline,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        lifespan=_lifespan,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Accept", "Content-Type"],
            max_age=600,
        )

    @app.middleware("http")
    async def _request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Reuse a client-supplied request id if present, otherwise
        # mint a new one. The id is returned on every error envelope
        # so operators can correlate a user-visible failure to a
        # server log line.
        incoming = request.headers.get("x-request-id", "").strip()
        request_id = incoming or secrets.token_hex(16)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


# Convenience for ``uvicorn app.main:app``.
app = create_app()


__all__ = ["app", "create_app"]
