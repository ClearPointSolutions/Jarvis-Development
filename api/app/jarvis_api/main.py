"""FastAPI application factory for Jarvis Mission Control."""

from __future__ import annotations

import sys
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
from jarvis_api.event_delivery import install_event_delivery
from jarvis_api.registry.routes import router as registry_router
from jarvis_api.registry.service import RegistryService
from jarvis_api.routing.routes import router as routing_router
from jarvis_api.security import install_security_middleware
from jarvis_api.workflows.routes import router as workflow_router
from jarvis_api.workflows.service import WorkflowService
from jarvis_contracts.api import ApiErrorResponse, LivenessResponse
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
        responses={
            code: {"model": ApiErrorResponse}
            for code in (400, 401, 403, 404, 409, 413, 415, 422, 429, 500, 503)
        },
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
    app.state.registry_service = RegistryService(
        session_factory,
        allowed_endpoints=config.provider_allowed_endpoints,
        instance_id=config.api_instance_id,
    )
    app.state.workflow_service = WorkflowService(session_factory, app.state.registry_service)
    install_error_handlers(app)
    install_security_middleware(app, config)
    app.include_router(auth_router)
    app.include_router(registry_router)
    app.include_router(routing_router)
    app.include_router(workflow_router)
    install_event_delivery(app, config, session_factory, app.state.auth_service)

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
    # Uvicorn 0.52 supplies its own loop factory, overriding asyncio's policy.
    # Psycopg requires SelectorEventLoop on Windows for real server connections.
    uvicorn.run(
        "jarvis_api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        loop="asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto",
    )


if __name__ == "__main__":
    run()
