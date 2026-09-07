"""Wire event delivery to the actual durable authentication boundary."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis_api.auth.dependencies import current_principal
from jarvis_api.auth.repository import AuthRepository
from jarvis_api.auth.service import AuthPrincipal, AuthService
from jarvis_api.config import Settings
from jarvis_api.errors import ApiProblemError
from jarvis_api.events.router import EventPrincipal, build_event_router
from jarvis_api.events.sse import EventStream, PostgresEventWakeups, SseConnectionLimiter
from jarvis_contracts.events import EventScope
from jarvis_persistence.models import JobModel, ProjectModel
from jarvis_persistence.repositories import EventRepository


def install_event_delivery(
    app: FastAPI,
    config: Settings,
    factory: async_sessionmaker[AsyncSession],
    service: AuthService,
) -> None:
    repository = EventRepository()
    auth_repository = AuthRepository()

    async def authorize_run(session: AsyncSession, principal: EventPrincipal, run_id: UUID) -> bool:
        return (
            await auth_repository.owned_run(session, user_id=principal.user_id, run_id=run_id)
            is not None
        )

    async def authorize_scope(
        session: AsyncSession, principal: EventPrincipal, scope: EventScope
    ) -> bool:
        if scope.run_id is not None:
            return await authorize_run(session, principal, scope.run_id)
        project_id = scope.project_id
        if scope.job_id is not None:
            project_id = await session.scalar(
                select(JobModel.project_id).where(JobModel.id == scope.job_id)
            )
            if project_id is None:
                return False
        if project_id is not None:
            return (
                await session.scalar(
                    select(ProjectModel.id).where(
                        ProjectModel.id == project_id,
                        ProjectModel.owner_user_id == principal.user_id,
                    )
                )
                is not None
            )
        return scope.thread_id is None

    async def authorize_stream(principal: EventPrincipal) -> bool:
        identity = cast(AuthPrincipal, principal)
        return (
            await service.authenticate(
                session_token=identity.session_token,
                correlation_id="stream-revalidation",
                read_only=True,
            )
            is not None
        )

    async def stream_guard(request: Request) -> None:
        origin = request.headers.get("origin")
        # Same-origin EventSource may omit Origin; browser Fetch Metadata must never
        # claim a cross-origin request. Host is checked independently by middleware.
        if (
            origin is not None and origin != config.public_origin.rstrip("/")
        ) or request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
            raise ApiProblemError(
                403, "request.origin_rejected", "The request origin is not allowed"
            )

    stream = EventStream(
        session_factory=factory,
        repository=repository,
        wakeups=PostgresEventWakeups(config.database_url),
        page_size=config.event_replay_page_size,
        poll_seconds=config.sse_poll_seconds,
        keepalive_seconds=config.sse_keepalive_seconds,
    )
    app.include_router(
        build_event_router(
            session_factory=factory,
            repository=repository,
            stream=stream,
            limiter=SseConnectionLimiter(config.sse_max_connections),
            principal_dependency=current_principal,
            stream_guard_dependency=stream_guard,
            authorize_run=authorize_run,
            default_page_size=config.event_replay_page_size,
            authorize_stream=authorize_stream,
            authorize_event_scope=authorize_scope,
            artifact_root=config.artifact_root,
        )
    )
