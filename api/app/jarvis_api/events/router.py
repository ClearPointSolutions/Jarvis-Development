"""Composable authorized event replay and SSE routes."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis_api.events.artifacts import artifact_path
from jarvis_api.events.sse import EventStream, SseConnectionLimiter, resolve_event_cursor
from jarvis_contracts.api import EventPage, RunEventSnapshotResponse
from jarvis_persistence.models import ArtifactModel, EventModel
from jarvis_persistence.repositories import (
    EventCursorExpiredError,
    EventRepository,
    RunSequenceGapError,
    UnsupportedEventSchemaError,
)


class EventPrincipal(Protocol):
    @property
    def user_id(self) -> UUID: ...


PrincipalDependency = Callable[..., Awaitable[EventPrincipal]]
StreamGuardDependency = Callable[..., Awaitable[None]]
RunAuthorizer = Callable[[AsyncSession, EventPrincipal, UUID], Awaitable[bool]]


def build_event_router(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    repository: EventRepository,
    stream: EventStream,
    limiter: SseConnectionLimiter,
    principal_dependency: PrincipalDependency,
    stream_guard_dependency: StreamGuardDependency,
    authorize_run: RunAuthorizer,
    default_page_size: int,
    authorize_stream: Callable[[EventPrincipal], Awaitable[bool]],
    artifact_root: Path | None = None,
) -> APIRouter:
    """Build routes without coupling event delivery to an auth implementation."""

    router = APIRouter(prefix="/api/v1", tags=["events"])
    principal_marker = Depends(principal_dependency)
    stream_guard_marker = Depends(stream_guard_dependency)

    @router.get(
        "/runs/{run_id}/events",
        response_model=EventPage,
        operation_id="list_run_events",
    )
    async def list_events(
        run_id: UUID,
        principal: EventPrincipal = principal_marker,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=default_page_size, ge=1, le=1_000),
    ) -> EventPage:
        async with session_factory() as session:
            if not await authorize_run(session, principal, run_id):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
            try:
                return await repository.page(session, run_id=run_id, after=after, limit=limit)
            except EventCursorExpiredError as error:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "event.cursor_expired",
                        "earliest_position": error.earliest,
                        "latest_position": error.latest,
                    },
                ) from error
            except UnsupportedEventSchemaError as error:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "event.unsupported_schema",
                        "global_position": error.global_position,
                    },
                ) from error
            except RunSequenceGapError as error:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "event.run_sequence_gap",
                        "global_position": error.global_position,
                        "expected": error.expected,
                        "actual": error.actual,
                    },
                ) from error

    @router.get(
        "/runs/{run_id}/event-snapshot",
        response_model=RunEventSnapshotResponse,
        operation_id="get_run_event_snapshot",
    )
    async def get_event_snapshot(
        run_id: UUID,
        principal: EventPrincipal = principal_marker,
    ) -> RunEventSnapshotResponse:
        async with session_factory() as session:
            if not await authorize_run(session, principal, run_id):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
            snapshot = await repository.run_projection_snapshot(session, run_id=run_id)
        if snapshot is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
        return RunEventSnapshotResponse(
            run_id=snapshot.run_id,
            status=snapshot.status,
            last_event_position=snapshot.last_event_position,
            last_run_sequence=snapshot.last_run_sequence,
            last_event_at=snapshot.last_event_at,
            read_cursor=snapshot.read_cursor,
        )

    @router.get(
        "/runs/{run_id}/events/stream",
        operation_id="stream_run_events",
    )
    async def stream_events(
        request: Request,
        run_id: UUID,
        principal: EventPrincipal = principal_marker,
        _stream_guard: None = stream_guard_marker,
        after: int = Query(default=0, ge=0),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        del _stream_guard
        try:
            cursor = resolve_event_cursor(after=after, last_event_id=last_event_id)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "event.invalid_cursor"},
            ) from error

        async with session_factory() as session:
            if not await authorize_run(session, principal, run_id):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")

        principal_key = str(principal.user_id)
        if not await limiter.claim(principal_key):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"code": "event.stream_limit"},
            )

        async def frames() -> AsyncIterator[str]:
            try:
                async for frame in stream.iter_frames(
                    run_id=run_id,
                    after=cursor,
                    is_disconnected=request.is_disconnected,
                ):
                    if not await authorize_stream(principal):
                        return
                    async with session_factory() as session:
                        if not await authorize_run(session, principal, run_id):
                            return
                    yield frame
            finally:
                await limiter.release(principal_key)

        return StreamingResponse(
            frames(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/artifacts/{artifact_id}", operation_id="get_event_artifact")
    async def get_artifact(
        artifact_id: UUID, principal: EventPrincipal = principal_marker
    ) -> FileResponse:
        if artifact_root is None:
            raise HTTPException(status_code=404, detail="not found")
        async with session_factory() as session:
            artifact = await session.get(ArtifactModel, artifact_id)
            # Only artifacts referenced by a visible persisted event are downloadable.
            visible = await session.scalar(
                select(EventModel.global_position)
                .where(
                    EventModel.artifact_refs_json.contains([{"artifact_id": str(artifact_id)}]),
                    EventModel.visibility.in_(("owner", "operator")),
                )
                .limit(1)
            )
            if artifact is None or visible is None:
                raise HTTPException(status_code=404, detail="not found")
            if artifact.run_id is not None and not await authorize_run(
                session, principal, artifact.run_id
            ):
                raise HTTPException(status_code=404, detail="not found")
            try:
                path = artifact_path(artifact_root, artifact.storage_key)
            except ValueError:
                raise HTTPException(status_code=404, detail="not found") from None
            if not path.is_file():
                raise HTTPException(status_code=404, detail="not found")
        return FileResponse(
            path,
            media_type="application/octet-stream",
            filename=f"{artifact_id}.json",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    return router
