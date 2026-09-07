"""FastAPI application factory for Jarvis Mission Control."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from jarvis_api.auth.authorization import ObjectAuthorizer
from jarvis_api.auth.crypto import load_server_key
from jarvis_api.auth.routes import router as auth_router
from jarvis_api.auth.service import AuthService
from jarvis_api.config import Settings, get_settings
from jarvis_api.errors import install_error_handlers
from jarvis_api.security import install_security_middleware
from jarvis_contracts.api import LivenessResponse
from jarvis_persistence.database import (
    create_async_database_engine,
    create_async_session_factory,
)
from jarvis_persistence.testing import Clock


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    clock: Clock | None = None,
    server_key: bytes | None = None,
) -> FastAPI:
    config = settings or get_settings()
    owned_engine: AsyncEngine | None = None
    if session_factory is None:
        owned_engine = create_async_database_engine(config.database_url)
        session_factory = create_async_session_factory(owned_engine)
    resolved_server_key = (
        server_key
        if server_key is not None
        else load_server_key(
            config.csrf_hmac_key_file,
            production=config.env == "production",
        )
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        if owned_engine is not None:
            await owned_engine.dispose()

    app = FastAPI(
        title="Jarvis V1 API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = config
    app.state.session_factory = session_factory
    app.state.auth_service = AuthService(
        session_factory,
        config,
        server_key=resolved_server_key,
        clock=clock,
    )
    app.state.object_authorizer = ObjectAuthorizer(session_factory)
    install_error_handlers(app)
    install_security_middleware(app, config)
    app.include_router(auth_router)

    @app.get(
        "/health",
        response_model=LivenessResponse,
        operation_id="get_liveness",
        tags=["system"],
    )
    async def health() -> LivenessResponse:
        return LivenessResponse()

    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run("jarvis_api.main:app", host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    run()
