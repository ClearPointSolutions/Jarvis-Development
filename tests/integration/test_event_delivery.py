from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_api.events.artifacts import LocalEventArtifactStore, artifact_path
from jarvis_api.events.normalizer import EventIntent, EventNormalizer, EventWriter
from jarvis_api.events.redaction import RecursiveRedactor
from jarvis_api.events.router import EventPrincipal, build_event_router
from jarvis_api.events.sse import (
    EventStream,
    PollingEventWakeups,
    PostgresEventWakeups,
    SseConnectionLimiter,
    parse_sse_data,
)
from jarvis_contracts.commands import RunCommandRequest
from jarvis_contracts.enums import (
    EventCategory,
    EventMode,
    EventSeverity,
    EventVisibility,
    RunCommandKind,
)
from jarvis_contracts.events import EventScope, EventSource, NewEvent, NormalizedEvent
from jarvis_contracts.ids import RunId
from jarvis_persistence.models import (
    ArtifactModel,
    EventModel,
    JobModel,
    ProjectModel,
    RunEventCounterModel,
    RunModel,
)
from jarvis_persistence.repositories import (
    CommandRepository,
    EventRepository,
    RunSequenceGapError,
    UnsupportedEventSchemaError,
)
from tests.integration.support import NOW, seed_run

pytestmark = pytest.mark.integration


def event(run_id: UUID, sequence: int, *, event_type: str = "run.started") -> NewEvent:
    return NewEvent(
        occurred_at=NOW,
        category=EventCategory.RUN,
        type=event_type,
        severity=EventSeverity.INFO,
        message=f"Event {sequence}",
        mode=EventMode.DEMO,
        visibility=EventVisibility.OWNER,
        scope=EventScope(run_id=RunId(run_id)),
        source=EventSource(
            kind="orchestrator",
            name="m2b-integration",
            instance_id=f"producer-{run_id}",
            source_sequence=sequence,
        ),
        correlation_id=str(run_id),
        data={"source_sequence": sequence},
    )


async def test_commit_order_projection_boundary_and_replay_are_atomic(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_run(session_factory)
    repository = EventRepository()
    first_appended = asyncio.Event()
    allow_first_commit = asyncio.Event()

    async def first_writer() -> NormalizedEvent:
        async with session_factory.begin() as session:
            written = await repository.append(session, event(seeded.run_id, 1))
            first_appended.set()
            await allow_first_commit.wait()
            return written

    async def second_writer() -> NormalizedEvent:
        async with session_factory.begin() as session:
            return await repository.append(session, event(seeded.run_id, 2))

    first_task = asyncio.create_task(first_writer())
    await first_appended.wait()

    async with session_factory() as session:
        before = await repository.run_projection_snapshot(session, run_id=seeded.run_id)
    assert before is not None
    assert before.last_run_sequence == 0

    second_task = asyncio.create_task(second_writer())
    await asyncio.sleep(0.05)
    assert not second_task.done(), "higher event position committed past the locked lower cursor"
    allow_first_commit.set()
    first, second = await asyncio.gather(first_task, second_task)

    assert second.global_position == first.global_position + 1
    assert (first.run_sequence, second.run_sequence) == (1, 2)
    async with session_factory() as session:
        after = await repository.run_projection_snapshot(session, run_id=seeded.run_id)
        page = await repository.page(
            session,
            run_id=seeded.run_id,
            after=before.read_cursor,
            limit=20,
        )
    assert after is not None
    assert after.last_event_position == second.global_position
    assert after.last_run_sequence == 2
    assert [item.event_id for item in page.items] == [first.event_id, second.event_id]


async def test_event_dedup_pagination_and_unknown_minor_type(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_run(session_factory)
    repository = EventRepository()
    unknown = event(seeded.run_id, 1, event_type="future.safe_event")
    async with session_factory.begin() as session:
        first = await repository.append(session, unknown)
        duplicate = await repository.append(session, unknown)
        second = await repository.append(session, event(seeded.run_id, 2))
    assert duplicate.event_id == first.event_id
    assert duplicate.run_sequence == 1

    async with session_factory() as session:
        first_page = await repository.page(session, run_id=seeded.run_id, after=0, limit=1)
        assert first_page.next_after == first.global_position
        second_page = await repository.page(
            session,
            run_id=seeded.run_id,
            after=first_page.next_after,
            limit=1,
        )
    assert first_page.items[0].type == "future.safe_event"
    assert second_page.items[0].event_id == second.event_id
    assert second_page.next_after is None


async def test_unsupported_major_and_physical_run_gap_are_explicit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded_major = await seed_run(session_factory)
    repository = EventRepository()
    async with session_factory.begin() as session:
        stored = await repository.append(session, event(seeded_major.run_id, 1))
        row = await session.scalar(
            select(RunModel).where(RunModel.id == seeded_major.run_id).with_for_update()
        )
        assert row is not None
        # The test cannot mutate an event row; instead it validates conversion of a
        # hypothetical retained row using the immutable ORM instance before commit.
        event_row = await session.get(EventModel, stored.global_position)
        assert event_row is not None
        event_row.schema_version = "2.0"
        with pytest.raises(UnsupportedEventSchemaError):
            repository._to_contract(event_row)
        await session.rollback()

    seeded_gap = await seed_run(session_factory)
    async with session_factory.begin() as session:
        session.add(RunEventCounterModel(run_id=seeded_gap.run_id, last_sequence=1))
    async with session_factory.begin() as session:
        await repository.append(session, event(seeded_gap.run_id, 1))
    async with session_factory() as session:
        with pytest.raises(RunSequenceGapError, match="expected 1, received 2"):
            await repository.page(session, run_id=seeded_gap.run_id, after=0, limit=20)


async def test_redacted_oversized_data_creates_immutable_artifact(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    seeded = await seed_run(session_factory)
    secret = "synthetic-m2b-canary-value"
    root = tmp_path / "artifacts"
    normalizer = EventNormalizer(
        redactor=RecursiveRedactor((secret,)),
        artifact_sink=LocalEventArtifactStore(root),
        inline_bytes=1_024,
        max_bytes=65_536,
    )
    repository = EventRepository()
    writer = EventWriter(normalizer=normalizer, repository=repository)
    async with session_factory.begin() as session:
        result = await writer.append(
            session,
            EventIntent(
                occurred_at=NOW,
                category=EventCategory.COMMAND,
                type="command.output_summary",
                severity=EventSeverity.INFO,
                message=f"Output excluded {secret}",
                mode=EventMode.DEMO,
                visibility=EventVisibility.OWNER,
                scope=EventScope(run_id=RunId(seeded.run_id)),
                source=EventSource(kind="worker_adapter", name="test-worker"),
                correlation_id=str(seeded.run_id),
                data={
                    "stdout": f"token={secret}\n" + ("safe-output\n" * 500),
                    "scratchpad": "hidden reasoning fixture",
                },
            ),
        )

    persisted = result.event
    assert result.extracted
    assert len(persisted.model_dump_json().encode()) < 65_536
    assert secret not in persisted.model_dump_json()
    async with session_factory() as session:
        artifact = await session.get(ArtifactModel, persisted.artifact_refs[0].artifact_id)
    assert artifact is not None
    content = artifact_path(root, artifact.storage_key).read_text(encoding="utf-8")
    assert secret not in content
    assert "hidden reasoning fixture" not in content
    assert "[REDACTED:" in content


async def test_notify_arrives_only_after_event_commit(
    session_factory: async_sessionmaker[AsyncSession], database_url: str
) -> None:
    seeded = await seed_run(session_factory)
    repository = EventRepository()
    wakeups = PostgresEventWakeups(database_url)

    async with wakeups.subscribe() as subscription, session_factory() as session:
        async with session.begin():
            written = await repository.append(session, event(seeded.run_id, 1))
            assert not await subscription.wait(0.05)
        assert await subscription.wait(1.5)

    async with session_factory() as session:
        page = await repository.page(session, run_id=seeded.run_id, after=0, limit=20)
    assert page.items[-1].global_position == written.global_position


async def test_mixed_command_and_event_writers_finish_without_deadlock(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_run(session_factory)
    event_repository = EventRepository()
    command_repository = CommandRepository()

    async def append(index: int) -> None:
        async with session_factory.begin() as session:
            await event_repository.append(session, event(seeded.run_id, index))

    async def command(index: int) -> None:
        request = RunCommandRequest(
            run_id=RunId(seeded.run_id),
            kind=RunCommandKind.INSTRUCTION,
            idempotency_key=f"m2b-command-{index}",
            payload={"instruction": f"test {index}"},
        )
        async with session_factory.begin() as session:
            await command_repository.enqueue(session, request)

    work = [append(index) for index in range(1, 9)] + [command(index) for index in range(1, 9)]
    await asyncio.wait_for(asyncio.gather(*work), timeout=10)


@dataclass(frozen=True)
class Principal:
    user_id: UUID


class OneFrameStream(EventStream):
    def __init__(self) -> None:
        self.cursor: int | None = None

    async def iter_frames(
        self,
        *,
        run_id: UUID,
        after: int,
        is_disconnected: Callable[[], Awaitable[bool]] | None = None,
    ) -> AsyncIterator[str]:
        del run_id, is_disconnected
        self.cursor = after
        yield f'data: {{"cursor":{after}}}\n\n'


async def test_router_authorizes_objects_and_last_event_id_wins(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_run(session_factory)
    repository = EventRepository()
    async with session_factory.begin() as session:
        await repository.append(session, event(seeded.run_id, 1))

    principal = Principal(user_id=seeded.user_id)
    guard_calls = 0

    async def current_principal() -> EventPrincipal:
        return principal

    async def stream_guard(request: Request) -> None:
        nonlocal guard_calls
        guard_calls += 1
        if request.headers.get("origin") != "http://testserver":
            raise HTTPException(status_code=403, detail="invalid origin")

    async def authorize(session: AsyncSession, candidate: EventPrincipal, run_id: UUID) -> bool:
        owner = await session.scalar(
            select(ProjectModel.owner_user_id)
            .join(JobModel, JobModel.project_id == ProjectModel.id)
            .join(RunModel, RunModel.job_id == JobModel.id)
            .where(RunModel.id == run_id)
        )
        return owner == candidate.user_id

    async def authorize_stream(candidate: EventPrincipal) -> bool:
        return candidate.user_id == principal.user_id

    one_frame = OneFrameStream()
    app = FastAPI()
    app.include_router(
        build_event_router(
            session_factory=session_factory,
            repository=repository,
            stream=one_frame,
            limiter=SseConnectionLimiter(2),
            principal_dependency=current_principal,
            stream_guard_dependency=stream_guard,
            authorize_run=authorize,
            default_page_size=20,
            authorize_stream=authorize_stream,
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        page_response = await client.get(f"/api/v1/runs/{seeded.run_id}/events")
        snapshot_response = await client.get(f"/api/v1/runs/{seeded.run_id}/event-snapshot")
        inaccessible = await client.get(f"/api/v1/runs/{uuid7()}/events")
        rejected_stream = await client.get(
            f"/api/v1/runs/{seeded.run_id}/events/stream?after=1",
            headers={"Origin": "http://invalid.example"},
        )
        stream_response = await client.get(
            f"/api/v1/runs/{seeded.run_id}/events/stream?after=1",
            headers={"Last-Event-ID": "17", "Origin": "http://testserver"},
        )

    assert page_response.status_code == 200, page_response.text
    assert snapshot_response.status_code == 200
    assert (
        snapshot_response.json()["read_cursor"] >= snapshot_response.json()["last_event_position"]
    )
    assert inaccessible.status_code == 404
    assert rejected_stream.status_code == 403
    assert stream_response.status_code == 200
    assert stream_response.headers["x-accel-buffering"] == "no"
    assert one_frame.cursor == 17
    assert guard_calls == 2
    operation_ids = {
        operation["operationId"]
        for path in app.openapi()["paths"].values()
        for operation in path.values()
    }
    assert {
        "list_run_events",
        "get_run_event_snapshot",
        "stream_run_events",
    }.issubset(operation_ids)


async def test_concurrent_distinct_run_writers_and_rollback_do_not_leave_gaps(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = [await seed_run(session_factory) for _ in range(3)]
    repository = EventRepository()

    async def write(index: int) -> NormalizedEvent:
        async with session_factory.begin() as session:
            return await repository.append(session, event(seeded[index % 3].run_id, index + 1))

    async with session_factory() as session:
        discarded = await repository.append(session, event(seeded[0].run_id, 999))
        await session.rollback()
    written = await asyncio.wait_for(asyncio.gather(*(write(i) for i in range(18))), 15)
    positions = sorted(item.global_position for item in written)
    assert positions == list(range(discarded.global_position, discarded.global_position + 18))
    for run in seeded:
        assert sorted(
            item.run_sequence
            for item in written
            if item.scope.run_id == run.run_id and item.run_sequence is not None
        ) == list(range(1, 7))


async def test_database_stream_reconnect_replays_events_without_notifications(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_run(session_factory)
    repository = EventRepository()
    stream = EventStream(
        session_factory=session_factory,
        repository=repository,
        wakeups=PollingEventWakeups(),
        page_size=1,
        poll_seconds=0.01,
        keepalive_seconds=30,
    )
    async with session_factory.begin() as session:
        first = await repository.append(session, event(seeded.run_id, 1))
    frames = stream.iter_frames(run_id=seeded.run_id, after=0)
    assert parse_sse_data(await anext(frames))["event_id"] == str(first.event_id)
    await cast(AsyncGenerator[str, None], frames).aclose()
    async with session_factory.begin() as session:
        second = await repository.append(session, event(seeded.run_id, 2))
        third = await repository.append(session, event(seeded.run_id, 3))
        duplicate = await repository.append(session, event(seeded.run_id, 3))
    assert duplicate.event_id == third.event_id
    resumed = stream.iter_frames(run_id=seeded.run_id, after=first.global_position)
    assert parse_sse_data(await anext(resumed))["event_id"] == str(second.event_id)
    assert parse_sse_data(await anext(resumed))["event_id"] == str(third.event_id)
    next_frame = asyncio.ensure_future(anext(resumed))
    async with session_factory.begin() as session:
        fourth = await repository.append(session, event(seeded.run_id, 4))
    assert parse_sse_data(await asyncio.wait_for(next_frame, 2))["event_id"] == str(fourth.event_id)
    await cast(AsyncGenerator[str, None], resumed).aclose()


async def test_cross_project_scope_is_rejected_before_event_commit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    one, two = await seed_run(session_factory), await seed_run(session_factory)
    repository = EventRepository()
    invalid = event(one.run_id, 1).model_copy(
        update={"scope": EventScope(run_id=RunId(one.run_id), job_id=two.job_id)}
    )
    async with session_factory.begin() as session:
        with pytest.raises(ValueError, match="job"):
            await repository.append(session, invalid)


async def test_artifact_role_write_is_append_only_and_download_checks_visibility(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    seeded = await seed_run(session_factory)
    root = tmp_path / "artifacts"
    writer = EventWriter(
        repository=EventRepository(),
        normalizer=EventNormalizer(
            redactor=RecursiveRedactor(),
            artifact_sink=LocalEventArtifactStore(root),
            inline_bytes=1024,
            max_bytes=65536,
        ),
    )
    results = []
    for visibility in (EventVisibility.OWNER, EventVisibility.INTERNAL):
        async with session_factory.begin() as session:
            await session.execute(text("SET LOCAL ROLE jarvis_v1_api"))
            written = await writer.append(
                session,
                EventIntent(
                    occurred_at=NOW,
                    type="command.output_summary",
                    severity=EventSeverity.INFO,
                    mode=EventMode.DEMO,
                    visibility=visibility,
                    scope=EventScope(run_id=RunId(seeded.run_id)),
                    source=EventSource(kind="api", name="artifact-test"),
                    correlation_id="artifact-test",
                    data={"stdout": visibility.value * 1024},
                ),
            )
            results.append(written.event.artifact_refs[0].artifact_id)
    for statement in (
        "UPDATE control.artifacts SET kind = 'changed' WHERE id = :id",
        "DELETE FROM control.artifacts WHERE id = :id",
        "UPDATE event_store.events SET message = 'changed' WHERE run_id = :id",
        "DELETE FROM event_store.events WHERE run_id = :id",
    ):
        async with session_factory() as session:
            await session.execute(text("SET LOCAL ROLE jarvis_v1_api"))
            with pytest.raises(DBAPIError):
                await session.execute(
                    text(statement), {"id": seeded.run_id if "events" in statement else results[0]}
                )
            await session.rollback()
    # The immutable trigger also protects privileged accidental updates.
    async with session_factory() as session:
        with pytest.raises(DBAPIError):
            await session.execute(
                text("UPDATE control.artifacts SET kind='changed' WHERE id=:id"), {"id": results[0]}
            )
        await session.rollback()
    principal = Principal(seeded.user_id)
    allowed = True

    async def current() -> EventPrincipal:
        return principal

    async def guard() -> None:
        pass

    async def authorize(session: AsyncSession, candidate: EventPrincipal, run: UUID) -> bool:
        return allowed and run == seeded.run_id and candidate.user_id == seeded.user_id

    async def live(candidate: EventPrincipal) -> bool:
        return True

    app = FastAPI()
    app.include_router(
        build_event_router(
            session_factory=session_factory,
            repository=EventRepository(),
            stream=OneFrameStream(),
            limiter=SseConnectionLimiter(1),
            principal_dependency=current,
            stream_guard_dependency=guard,
            authorize_run=authorize,
            default_page_size=20,
            authorize_stream=live,
            artifact_root=root,
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(f"/api/v1/artifacts/{results[0]}")
        assert response.status_code == 200
        assert response.headers["content-disposition"].startswith("attachment;")
        assert response.headers["content-type"] == "application/octet-stream"
        assert (await client.get(f"/api/v1/artifacts/{results[1]}")).status_code == 404
        allowed = False
        assert (await client.get(f"/api/v1/artifacts/{results[0]}")).status_code == 404


async def test_stream_stops_after_session_revocation_and_releases_connection(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_run(session_factory)
    principal = Principal(seeded.user_id)
    checks = 0

    class TwoFrames(OneFrameStream):
        async def iter_frames(
            self,
            *,
            run_id: UUID,
            after: int,
            is_disconnected: Callable[[], Awaitable[bool]] | None = None,
        ) -> AsyncIterator[str]:
            yield 'data: {"sequence":1}\n\n'
            yield 'data: {"sequence":2}\n\n'

    async def current() -> EventPrincipal:
        return principal

    async def guard() -> None:
        pass

    async def authorize(session: AsyncSession, candidate: EventPrincipal, run_id: UUID) -> bool:
        return run_id == seeded.run_id

    async def live(candidate: EventPrincipal) -> bool:
        nonlocal checks
        checks += 1
        return checks == 1

    limiter = SseConnectionLimiter(1)
    app = FastAPI()
    app.include_router(
        build_event_router(
            session_factory=session_factory,
            repository=EventRepository(),
            stream=TwoFrames(),
            limiter=limiter,
            principal_dependency=current,
            stream_guard_dependency=guard,
            authorize_run=authorize,
            default_page_size=20,
            authorize_stream=live,
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(f"/api/v1/runs/{seeded.run_id}/events/stream")
    assert response.status_code == 200
    assert response.text == 'data: {"sequence":1}\n\n'
    assert checks == 2
    assert await limiter.claim(str(principal.user_id))
    await limiter.release(str(principal.user_id))
