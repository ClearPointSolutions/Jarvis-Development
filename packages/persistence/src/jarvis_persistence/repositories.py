"""Transactional M1 repositories for ordering and idempotency invariants."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from jarvis_contracts.commands import RunCommandReceipt, RunCommandRequest
from jarvis_contracts.enums import CommandStatus, EffectStatus
from jarvis_contracts.events import (
    ArtifactReference,
    EventScope,
    EventSource,
    EventTrace,
    NewEvent,
    NormalizedEvent,
)
from jarvis_contracts.ids import CommandId, EventId, RunId
from jarvis_persistence.models import (
    EffectModel,
    EventGlobalCounterModel,
    EventModel,
    IdempotencyRecordModel,
    RunCommandModel,
    RunEventCounterModel,
    RunLeaseModel,
    RunModel,
)
from jarvis_persistence.testing import Clock, IdGenerator, SystemClock


class PersistenceInvariantError(RuntimeError):
    """The database does not satisfy a required M1 invariant."""


class IdempotencyConflictError(ValueError):
    """An idempotency key was reused for a different canonical request."""


class OptimisticConcurrencyConflictError(ValueError):
    """A command targeted a stale mutable run version."""


class Uuid7Generator:
    def next(self) -> UUID:
        return uuid7()


class EventRepository:
    """Append events under the normative global-then-run lock ordering."""

    def __init__(self, id_generator: IdGenerator | None = None) -> None:
        self._ids = id_generator or Uuid7Generator()

    async def append(self, session: AsyncSession, event: NewEvent) -> NormalizedEvent:
        global_counter = await session.scalar(
            select(EventGlobalCounterModel).where(EventGlobalCounterModel.id == 1).with_for_update()
        )
        if global_counter is None:
            raise PersistenceInvariantError("event global counter is not initialized")

        idempotency_scope_key = self._idempotency_scope_key(event)
        source_dedupe_key = self._source_dedupe_key(event)
        duplicate = await self._find_duplicate(
            session,
            idempotency_scope_key=idempotency_scope_key,
            source_dedupe_key=source_dedupe_key,
        )
        if duplicate is not None:
            return self._to_contract(duplicate)

        run_sequence: int | None = None
        if event.scope.run_id is not None:
            await session.execute(
                insert(RunEventCounterModel)
                .values(run_id=event.scope.run_id, last_sequence=0)
                .on_conflict_do_nothing(index_elements=[RunEventCounterModel.run_id])
            )
            run_counter = await session.scalar(
                select(RunEventCounterModel)
                .where(RunEventCounterModel.run_id == event.scope.run_id)
                .with_for_update()
            )
            if run_counter is None:
                raise PersistenceInvariantError("run event counter could not be initialized")
            run_counter.last_sequence += 1
            run_sequence = run_counter.last_sequence

        global_counter.last_position += 1
        row = EventModel(
            event_id=self._ids.next(),
            schema_version=event.schema_version,
            global_position=global_counter.last_position,
            run_sequence=run_sequence,
            occurred_at=event.occurred_at,
            category=event.category.value,
            type=event.type,
            severity=event.severity.value,
            message=event.message,
            mode=event.mode.value,
            visibility=event.visibility.value,
            project_id=event.scope.project_id,
            thread_id=event.scope.thread_id,
            job_id=event.scope.job_id,
            run_id=event.scope.run_id,
            task_id=event.scope.task_id,
            task_attempt_id=event.scope.task_attempt_id,
            workflow_node_id=event.scope.workflow_node_id,
            node_execution_id=event.scope.node_execution_id,
            source_kind=event.source.kind,
            source_name=event.source.name,
            source_instance_id=event.source.instance_id,
            source_host_id=event.source.host_id,
            source_sequence=event.source.source_sequence,
            source_dedupe_key=source_dedupe_key,
            correlation_id=event.correlation_id,
            causation_event_id=event.causation_event_id,
            idempotency_key=event.idempotency_key,
            idempotency_scope_key=idempotency_scope_key,
            trace_json=event.trace.model_dump(mode="json") if event.trace else None,
            data_json=event.data,
            artifact_refs_json=[item.model_dump(mode="json") for item in event.artifact_refs],
        )
        session.add(row)
        await session.flush()
        await session.refresh(row, attribute_names=["recorded_at"])
        return self._to_contract(row)

    async def _find_duplicate(
        self,
        session: AsyncSession,
        *,
        idempotency_scope_key: str | None,
        source_dedupe_key: str | None,
    ) -> EventModel | None:
        predicates = []
        if idempotency_scope_key is not None:
            predicates.append(EventModel.idempotency_scope_key == idempotency_scope_key)
        if source_dedupe_key is not None:
            predicates.append(EventModel.source_dedupe_key == source_dedupe_key)
        if not predicates:
            return None
        result: EventModel | None = await session.scalar(select(EventModel).where(or_(*predicates)))
        return result

    @staticmethod
    def _idempotency_scope_key(event: NewEvent) -> str | None:
        if event.idempotency_key is None:
            return None
        scope = event.scope.run_id or event.scope.job_id or event.scope.project_id or "system"
        return f"{scope}:{event.idempotency_key}"

    @staticmethod
    def _source_dedupe_key(event: NewEvent) -> str | None:
        if event.source.source_sequence is None:
            return None
        source = event.source
        return ":".join(
            [
                source.kind,
                source.name,
                source.instance_id or "-",
                source.host_id or "-",
                str(source.source_sequence),
            ]
        )

    @staticmethod
    def _to_contract(row: EventModel) -> NormalizedEvent:
        trace = EventTrace.model_validate(row.trace_json) if row.trace_json else None
        return NormalizedEvent(
            schema_version="1.0",
            event_id=EventId(row.event_id),
            global_position=row.global_position,
            run_sequence=row.run_sequence,
            occurred_at=row.occurred_at,
            recorded_at=row.recorded_at,
            category=row.category,
            type=row.type,
            severity=row.severity,
            message=row.message,
            mode=row.mode,
            visibility=row.visibility,
            scope=EventScope(
                project_id=row.project_id,
                thread_id=row.thread_id,
                job_id=row.job_id,
                run_id=row.run_id,
                task_id=row.task_id,
                task_attempt_id=row.task_attempt_id,
                workflow_node_id=row.workflow_node_id,
                node_execution_id=row.node_execution_id,
            ),
            source=EventSource(
                kind=row.source_kind,
                name=row.source_name,
                instance_id=row.source_instance_id,
                host_id=row.source_host_id,
                source_sequence=row.source_sequence,
            ),
            correlation_id=row.correlation_id,
            causation_event_id=row.causation_event_id,
            idempotency_key=row.idempotency_key,
            trace=trace,
            data=row.data_json,
            artifact_refs=tuple(
                ArtifactReference.model_validate(item) for item in row.artifact_refs_json
            ),
        )


class CommandRepository:
    async def enqueue(self, session: AsyncSession, request: RunCommandRequest) -> RunCommandReceipt:
        run = await session.scalar(
            select(RunModel).where(RunModel.id == request.run_id).with_for_update()
        )
        if run is None:
            raise LookupError(f"run {request.run_id} does not exist")
        existing = await session.scalar(
            select(RunCommandModel).where(
                RunCommandModel.run_id == request.run_id,
                RunCommandModel.idempotency_key == request.idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_digest != request.request_digest:
                raise IdempotencyConflictError(
                    "command idempotency key was reused with new content"
                )
            return self._receipt(existing, duplicate=True)
        if request.expected_run_version is not None and request.expected_run_version != run.version:
            raise OptimisticConcurrencyConflictError("run version changed before command enqueue")

        run.next_command_sequence += 1
        row = RunCommandModel(
            id=uuid7(),
            run_id=request.run_id,
            sequence=run.next_command_sequence,
            kind=request.kind.value,
            status=CommandStatus.PENDING.value,
            idempotency_key=request.idempotency_key,
            request_digest=request.request_digest,
            payload_json=request.payload,
            expected_run_version=request.expected_run_version,
        )
        session.add(row)
        await session.flush()
        return self._receipt(row, duplicate=False)

    @staticmethod
    def _receipt(row: RunCommandModel, *, duplicate: bool) -> RunCommandReceipt:
        return RunCommandReceipt(
            command_id=CommandId(row.id),
            run_id=RunId(row.run_id),
            sequence=row.sequence,
            status=row.status,
            request_digest=row.request_digest,
            duplicate=duplicate,
        )


class IdempotencyRepository:
    async def begin(
        self,
        session: AsyncSession,
        *,
        scope: str,
        key: str,
        request_digest: str,
    ) -> tuple[IdempotencyRecordModel, bool]:
        record_id = uuid7()
        inserted = await session.scalar(
            insert(IdempotencyRecordModel)
            .values(
                id=record_id,
                scope=scope,
                key=key,
                request_digest=request_digest,
                state="started",
            )
            .on_conflict_do_nothing(
                index_elements=[IdempotencyRecordModel.scope, IdempotencyRecordModel.key]
            )
            .returning(IdempotencyRecordModel.id)
        )
        if inserted is not None:
            row = await session.get(IdempotencyRecordModel, inserted)
            if row is None:
                raise PersistenceInvariantError("inserted idempotency row disappeared")
            return row, True
        row = await session.scalar(
            select(IdempotencyRecordModel).where(
                IdempotencyRecordModel.scope == scope,
                IdempotencyRecordModel.key == key,
            )
        )
        if row is None:
            raise PersistenceInvariantError("conflicting idempotency row disappeared")
        if row.request_digest != request_digest:
            raise IdempotencyConflictError(
                "idempotency key was reused with a different request digest"
            )
        return row, False


class EffectRepository:
    async def prepare(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
        kind: str,
        idempotency_key: str,
        request_digest: str,
        request: dict[str, JsonValue],
        fence_generation: int,
        task_attempt_id: UUID | None = None,
        node_execution_id: UUID | None = None,
    ) -> tuple[EffectModel, bool]:
        await self._lock_run(session, run_id)
        existing = await session.scalar(
            select(EffectModel).where(
                EffectModel.run_id == run_id,
                EffectModel.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_digest != request_digest:
                raise IdempotencyConflictError("effect key was reused with a different request")
            return existing, False
        row = EffectModel(
            id=uuid7(),
            run_id=run_id,
            task_attempt_id=task_attempt_id,
            node_execution_id=node_execution_id,
            kind=kind,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            request_json=request,
            status=EffectStatus.PREPARED.value,
            fence_generation=fence_generation,
        )
        session.add(row)
        await session.flush()
        return row, True

    @staticmethod
    async def _lock_run(session: AsyncSession, run_id: UUID) -> RunModel:
        run = await session.scalar(select(RunModel).where(RunModel.id == run_id).with_for_update())
        if run is None:
            raise LookupError(f"run {run_id} does not exist")
        return run


class LeaseRepository:
    def __init__(self, clock: Clock | None = None) -> None:
        self._clock = clock or SystemClock()

    async def acquire(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
        owner_instance_id: str,
        ttl: timedelta,
    ) -> RunLeaseModel | None:
        if ttl <= timedelta(0):
            raise ValueError("lease TTL must be positive")
        run = await session.scalar(select(RunModel).where(RunModel.id == run_id).with_for_update())
        if run is None:
            raise LookupError(f"run {run_id} does not exist")

        now = self._clock.now()
        active = await session.scalar(
            select(RunLeaseModel)
            .where(RunLeaseModel.run_id == run_id, RunLeaseModel.released_at.is_(None))
            .with_for_update()
        )
        if active is not None and active.expires_at > now:
            if active.owner_instance_id != owner_instance_id:
                return None
            active.expires_at = now + ttl
            await session.flush()
            return active
        if active is not None:
            active.released_at = now
            await session.flush()

        generation_query = select(func.max(RunLeaseModel.generation)).where(
            RunLeaseModel.run_id == run_id
        )
        generation = (await session.scalar(generation_query) or 0) + 1
        lease = RunLeaseModel(
            id=uuid7(),
            run_id=run_id,
            owner_instance_id=owner_instance_id,
            generation=generation,
            acquired_at=now,
            expires_at=now + ttl,
        )
        session.add(lease)
        await session.flush()
        return lease
