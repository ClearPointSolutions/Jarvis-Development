from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_contracts.commands import RunCommandReceipt, RunCommandRequest
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
    ConfigurationModel,
    ConfigurationRevisionModel,
    EffectModel,
    EventGlobalCounterModel,
    EventModel,
    IdempotencyRecordModel,
    OrchestratorInstanceModel,
    ProjectModel,
    RunCommandModel,
    TaskModel,
)
from jarvis_persistence.repositories import (
    CommandRepository,
    EffectRepository,
    EventRepository,
    IdempotencyConflictError,
    IdempotencyRepository,
    LeaseRepository,
    OptimisticConcurrencyConflictError,
)
from jarvis_persistence.testing import FrozenClock, SequenceIdGenerator
from tests.integration.support import NOW, seed_run

pytestmark = pytest.mark.integration


def new_event(run_id: RunId, sequence: int, *, key: str | None = None) -> NewEvent:
    return NewEvent(
        occurred_at=NOW,
        category=EventCategory.RUN,
        type="run.started",
        severity=EventSeverity.INFO,
        message=f"Run started source sequence {sequence}",
        mode=EventMode.DEMO,
        visibility=EventVisibility.OWNER,
        scope=EventScope(run_id=run_id),
        source=EventSource(
            kind="orchestrator",
            name="integration-test",
            instance_id="test-instance",
            source_sequence=sequence,
        ),
        correlation_id=str(run_id),
        idempotency_key=key,
        data={"sequence": sequence},
    )


async def test_event_allocation_is_ordered_concurrently_and_deduplicated(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_run(session_factory)
    repository = EventRepository()

    async def append(sequence: int) -> NormalizedEvent:
        async with session_factory.begin() as session:
            return await repository.append(session, new_event(RunId(seeded.run_id), sequence))

    events = await asyncio.gather(append(1), append(2))
    assert {event.run_sequence for event in events} == {1, 2}
    assert abs(events[0].global_position - events[1].global_position) == 1

    duplicate_source = await append(1)
    assert duplicate_source.event_id == events[0].event_id

    idem_event = new_event(RunId(seeded.run_id), 3, key="event/run-start-003")
    async with session_factory.begin() as session:
        first = await repository.append(session, idem_event)
        second = await repository.append(
            session,
            idem_event.model_copy(
                update={"source": idem_event.source.model_copy(update={"source_sequence": 4})}
            ),
        )
    assert first.event_id == second.event_id
    assert first.run_sequence == 3


async def test_event_rows_and_immutable_configuration_rows_reject_mutation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_run(session_factory)
    repository = EventRepository(SequenceIdGenerator(start=500))
    async with session_factory.begin() as session:
        event = await repository.append(session, new_event(RunId(seeded.run_id), 20))

    async with session_factory() as session:
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(
                text("UPDATE event_store.events SET message = 'changed' WHERE event_id = :id"),
                {"id": event.event_id},
            )
        await session.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            await session.execute(
                text("DELETE FROM event_store.events WHERE event_id = :id"),
                {"id": event.event_id},
            )
        await session.rollback()

    configuration_id = uuid7()
    revision_id = uuid7()
    async with session_factory.begin() as session:
        session.add(
            ConfigurationModel(
                id=configuration_id,
                kind="worker",
                key=f"worker-{configuration_id}",
                display_name="Worker",
            )
        )
        await session.flush()
        session.add(
            ConfigurationRevisionModel(
                id=revision_id,
                configuration_id=configuration_id,
                revision=1,
                schema_version="1.0",
                spec_json={},
                content_hash="b" * 64,
            )
        )
    async with session_factory() as session:
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(
                text(
                    "UPDATE control.configuration_revisions SET content_hash = :hash WHERE id = :id"
                ),
                {"hash": "c" * 64, "id": revision_id},
            )
        await session.rollback()
        with pytest.raises(DBAPIError, match="immutable"):
            await session.execute(
                text(
                    "UPDATE control.run_config_snapshots SET snapshot_hash = :hash WHERE id = :id"
                ),
                {"hash": "c" * 64, "id": seeded.snapshot_id},
            )
        await session.rollback()
        with pytest.raises(DBAPIError, match="published workflow"):
            await session.execute(
                text(
                    "UPDATE control.workflow_versions SET compiler_version = 'changed' "
                    "WHERE id = :id"
                ),
                {"id": seeded.workflow_version_id},
            )
        await session.rollback()


async def test_command_sequence_and_idempotency_are_transactional_under_race(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_run(session_factory)
    repository = CommandRepository()

    async def enqueue(key: str, kind: RunCommandKind = RunCommandKind.PAUSE) -> RunCommandReceipt:
        request = RunCommandRequest(
            run_id=RunId(seeded.run_id),
            kind=kind,
            idempotency_key=key,
        )
        async with session_factory.begin() as session:
            return await repository.enqueue(session, request)

    receipts = await asyncio.gather(enqueue("command/race-001"), enqueue("command/race-002"))
    assert sorted(receipt.sequence for receipt in receipts) == [1, 2]
    duplicate = await enqueue("command/race-001")
    assert duplicate.duplicate
    assert duplicate.command_id in {receipt.command_id for receipt in receipts}

    with pytest.raises(IdempotencyConflictError):
        await enqueue("command/race-001", RunCommandKind.CANCEL)

    stale = RunCommandRequest(
        run_id=RunId(seeded.run_id),
        kind=RunCommandKind.RETRY,
        idempotency_key="command/stale-version",
        expected_run_version=99,
    )
    with pytest.raises(OptimisticConcurrencyConflictError):
        async with session_factory.begin() as session:
            await repository.enqueue(session, stale)


async def test_idempotency_effect_and_lease_primitives_do_not_duplicate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_run(session_factory)
    idempotency = IdempotencyRepository()
    async with session_factory.begin() as session:
        first, created = await idempotency.begin(
            session,
            scope="test",
            key="request/idempotency-001",
            request_digest="d" * 64,
        )
        repeated, repeated_created = await idempotency.begin(
            session,
            scope="test",
            key="request/idempotency-001",
            request_digest="d" * 64,
        )
        with pytest.raises(IdempotencyConflictError):
            await idempotency.begin(
                session,
                scope="test",
                key="request/idempotency-001",
                request_digest="x" * 64,
            )
    assert created and not repeated_created
    assert first.id == repeated.id

    effects = EffectRepository()
    async with session_factory.begin() as session:
        effect, effect_created = await effects.prepare(
            session,
            run_id=seeded.run_id,
            kind="test.effect",
            idempotency_key="effect/prepare-001",
            request_digest="e" * 64,
            request={"safe": True},
            fence_generation=1,
        )
        same, same_created = await effects.prepare(
            session,
            run_id=seeded.run_id,
            kind="test.effect",
            idempotency_key="effect/prepare-001",
            request_digest="e" * 64,
            request={"safe": True},
            fence_generation=1,
        )
        with pytest.raises(IdempotencyConflictError):
            await effects.prepare(
                session,
                run_id=seeded.run_id,
                kind="test.effect",
                idempotency_key="effect/prepare-001",
                request_digest="x" * 64,
                request={"safe": False},
                fence_generation=1,
            )
    assert effect_created and not same_created
    assert effect.id == same.id

    clock = FrozenClock(NOW)
    leases = LeaseRepository(clock)
    async with session_factory.begin() as session:
        session.add_all(
            [
                OrchestratorInstanceModel(
                    id="orch-a", started_at=NOW, heartbeat_at=NOW, version="test"
                ),
                OrchestratorInstanceModel(
                    id="orch-b", started_at=NOW, heartbeat_at=NOW, version="test"
                ),
            ]
        )
    async with session_factory.begin() as session:
        lease_a = await leases.acquire(
            session,
            run_id=seeded.run_id,
            owner_instance_id="orch-a",
            ttl=timedelta(seconds=30),
        )
    async with session_factory.begin() as session:
        denied = await leases.acquire(
            session,
            run_id=seeded.run_id,
            owner_instance_id="orch-b",
            ttl=timedelta(seconds=30),
        )
    assert lease_a is not None and denied is None
    clock.advance(timedelta(seconds=31))
    async with session_factory.begin() as session:
        lease_b = await leases.acquire(
            session,
            run_id=seeded.run_id,
            owner_instance_id="orch-b",
            ttl=timedelta(seconds=30),
        )
    assert lease_b is not None
    assert lease_b.generation == lease_a.generation + 1


async def test_database_constraints_and_logical_roles(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_run(session_factory)
    async with session_factory() as session:
        session.add(
            TaskModel(
                id=uuid7(),
                run_id=seeded.run_id,
                key="duplicate-key",
                title="First",
                status="pending",
                acceptance_criteria_json=[],
                verification_json={},
            )
        )
        session.add(
            TaskModel(
                id=uuid7(),
                run_id=seeded.run_id,
                key="duplicate-key",
                title="Second",
                status="pending",
                acceptance_criteria_json=[],
                verification_json={},
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        roles = (
            await session.execute(
                text(
                    "SELECT rolname, rolcanlogin FROM pg_roles "
                    "WHERE rolname IN ('jarvis_v1_api', 'jarvis_v1_migrator', "
                    "'jarvis_v1_orchestrator', 'jarvis_v1_readonly') ORDER BY rolname"
                )
            )
        ).all()
        assert [tuple(row) for row in roles] == [
            ("jarvis_v1_api", False),
            ("jarvis_v1_migrator", False),
            ("jarvis_v1_orchestrator", False),
            ("jarvis_v1_readonly", False),
        ]
        assert await session.scalar(
            text("SELECT has_table_privilege('jarvis_v1_readonly','control.runs','SELECT')")
        )
        assert not await session.scalar(
            text("SELECT has_table_privilege('jarvis_v1_readonly','control.runs','INSERT')")
        )
        assert not await session.scalar(
            text("SELECT has_table_privilege('jarvis_v1_api','event_store.events','UPDATE')")
        )
        assert await session.scalar(
            text(
                "SELECT has_table_privilege("
                "'jarvis_v1_orchestrator','langgraph.checkpoints','SELECT,INSERT,UPDATE,DELETE')"
            )
        )

        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "UPDATE control.workflow_templates SET current_published_version_id = :missing"
                ),
                {"missing": uuid7()},
            )
            await session.commit()
        await session.rollback()

        counts = {
            "events": await session.scalar(select(func.count()).select_from(EventModel)),
            "commands": await session.scalar(select(func.count()).select_from(RunCommandModel)),
            "effects": await session.scalar(select(func.count()).select_from(EffectModel)),
            "idempotency": await session.scalar(
                select(func.count()).select_from(IdempotencyRecordModel)
            ),
            "projects": await session.scalar(select(func.count()).select_from(ProjectModel)),
            "counter": await session.scalar(
                select(EventGlobalCounterModel.last_position).where(EventGlobalCounterModel.id == 1)
            ),
        }
        assert all(value is not None for value in counts.values())
