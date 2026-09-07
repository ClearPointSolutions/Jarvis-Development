"""Transactional M1 repositories for ordering and idempotency invariants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from jarvis_contracts.api import EventPage
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
    ArtifactModel,
    EffectModel,
    EventGlobalCounterModel,
    EventModel,
    IdempotencyRecordModel,
    JobModel,
    NodeExecutionModel,
    ProjectModel,
    RunCommandModel,
    RunEventCounterModel,
    RunLeaseModel,
    RunModel,
    TaskAttemptModel,
    TaskModel,
)
from jarvis_persistence.testing import Clock, IdGenerator, SystemClock


class PersistenceInvariantError(RuntimeError):
    """The database does not satisfy a required M1 invariant."""


class IdempotencyConflictError(ValueError):
    """An idempotency key was reused for a different canonical request."""


class OptimisticConcurrencyConflictError(ValueError):
    """A command targeted a stale mutable run version."""


class UnsupportedEventSchemaError(ValueError):
    """A stored event cannot be represented by this API's contract major."""

    def __init__(self, *, global_position: int, schema_version: str) -> None:
        self.global_position = global_position
        self.schema_version = schema_version
        super().__init__(
            f"event at position {global_position} uses unsupported schema {schema_version}"
        )


class EventCursorExpiredError(ValueError):
    """A replay cursor is outside the retained committed global event range."""

    def __init__(self, *, requested: int, earliest: int, latest: int) -> None:
        self.requested = requested
        self.earliest = earliest
        self.latest = latest
        super().__init__(f"event cursor {requested} is outside retained range {earliest}..{latest}")


class RunSequenceGapError(ValueError):
    """A run's durable event sequence contains a missing position."""

    def __init__(self, *, expected: int, actual: int, global_position: int) -> None:
        self.expected = expected
        self.actual = actual
        self.global_position = global_position
        super().__init__(
            f"run event sequence gap at position {global_position}: "
            f"expected {expected}, received {actual}"
        )


@dataclass(frozen=True)
class RunProjectionSnapshot:
    """Run projection and commit-safe event cursor from one database statement."""

    run_id: UUID
    status: str
    last_event_position: int
    last_run_sequence: int
    last_event_at: datetime | None
    read_cursor: int


SUPPORTED_EVENT_SCHEMA_MAJOR: Final = "1"


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

        await self.validate_scope(session, event.scope, event.artifact_refs)
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

        if event.scope.run_id is not None:
            run = await session.scalar(
                select(RunModel).where(RunModel.id == event.scope.run_id).with_for_update()
            )
            if run is None:
                raise PersistenceInvariantError("run event references a missing run")
            run.last_event_position = row.global_position
            run.last_run_sequence = run_sequence or 0
            run.last_event_at = row.recorded_at
            await session.flush()
        return self._to_contract(row)

    @staticmethod
    async def validate_scope(
        session: AsyncSession, scope: EventScope, references: tuple[ArtifactReference, ...]
    ) -> None:
        """Reject cross-resource references before any browser-visible fact is stored."""
        run = await session.get(RunModel, scope.run_id) if scope.run_id else None
        if scope.run_id and run is None:
            raise ValueError("event scope references a missing run")
        job_id = run.job_id if run else scope.job_id
        job = await session.get(JobModel, job_id) if job_id else None
        if job_id and job is None:
            raise ValueError("event scope references a missing job")
        if scope.job_id and (job is None or scope.job_id != job.id):
            raise ValueError("event job does not belong to its run")
        if scope.project_id:
            if job and job.project_id != scope.project_id:
                raise ValueError("event project does not belong to its job")
            if await session.get(ProjectModel, scope.project_id) is None:
                raise ValueError("event scope references a missing project")
        if scope.thread_id and (job is None or job.thread_id != scope.thread_id):
            raise ValueError("event thread does not belong to its job")
        task = await session.get(TaskModel, scope.task_id) if scope.task_id else None
        if scope.task_id and (task is None or task.run_id != scope.run_id):
            raise ValueError("event task does not belong to its run")
        if scope.task_attempt_id:
            attempt = await session.get(TaskAttemptModel, scope.task_attempt_id)
            attempt_task = await session.get(TaskModel, attempt.task_id) if attempt else None
            if (
                attempt_task is None
                or attempt_task.run_id != scope.run_id
                or (scope.task_id is not None and attempt_task.id != scope.task_id)
            ):
                raise ValueError("event attempt does not belong to its task/run")
        if scope.node_execution_id:
            node = await session.get(NodeExecutionModel, scope.node_execution_id)
            if (
                node is None
                or node.run_id != scope.run_id
                or (scope.task_id is not None and node.task_id != scope.task_id)
                or (
                    scope.task_attempt_id is not None
                    and node.task_attempt_id != scope.task_attempt_id
                )
                or (
                    scope.workflow_node_id is not None
                    and node.workflow_node_id != scope.workflow_node_id
                )
            ):
                raise ValueError("event node execution does not belong to its scope")
        for reference in references:
            artifact = await session.get(ArtifactModel, reference.artifact_id)
            if artifact is None or artifact.run_id != scope.run_id:
                raise ValueError("event artifact does not belong to its run")
            if artifact.kind == "event_payload":
                namespace = "system"
                for label, identifier in (
                    ("run", scope.run_id),
                    ("job", scope.job_id),
                    ("project", scope.project_id),
                ):
                    if identifier is not None:
                        namespace = f"{label}-{identifier}"
                        break
                if not artifact.storage_key.startswith(f"events/{namespace}/"):
                    raise ValueError("event artifact does not belong to its project/job scope")

    async def page(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
        after: int,
        limit: int,
    ) -> EventPage:
        """Read an owner-visible run page at one committed high-water boundary."""

        if not 0 <= after <= 9_223_372_036_854_775_807:
            raise ValueError("event cursor must fit a nonnegative PostgreSQL bigint")
        if limit < 1 or limit > 1_000:
            raise ValueError("event page limit must be between 1 and 1000")

        counter = await session.scalar(
            select(EventGlobalCounterModel.last_position).where(EventGlobalCounterModel.id == 1)
        )
        if counter is None:
            raise PersistenceInvariantError("event global counter is not initialized")

        earliest = await session.scalar(select(func.min(EventModel.global_position)))
        if after > counter:
            raise EventCursorExpiredError(requested=after, earliest=earliest or 0, latest=counter)
        if after > 0 and earliest is not None and after < earliest - 1:
            raise EventCursorExpiredError(requested=after, earliest=earliest, latest=counter)

        rows = list(
            (
                await session.scalars(
                    select(EventModel)
                    .where(
                        EventModel.run_id == run_id,
                        EventModel.global_position > after,
                        EventModel.global_position <= counter,
                        EventModel.visibility.in_(("owner", "operator")),
                    )
                    .order_by(EventModel.global_position)
                    .limit(limit + 1)
                )
            ).all()
        )
        has_more = len(rows) > limit
        visible_rows = rows[:limit]
        if visible_rows:
            prior_sequence = await session.scalar(
                select(func.max(EventModel.run_sequence)).where(
                    EventModel.run_id == run_id,
                    EventModel.global_position <= after,
                )
            )
            durable_rows = (
                await session.execute(
                    select(EventModel.run_sequence, EventModel.global_position)
                    .where(
                        EventModel.run_id == run_id,
                        EventModel.global_position > after,
                        EventModel.global_position <= visible_rows[-1].global_position,
                    )
                    .order_by(EventModel.global_position)
                )
            ).all()
            expected = (prior_sequence or 0) + 1
            for actual, global_position in durable_rows:
                if actual != expected:
                    raise RunSequenceGapError(
                        expected=expected,
                        actual=actual,
                        global_position=global_position,
                    )
                expected += 1
        items = tuple(self._to_contract(row) for row in visible_rows)
        return EventPage(
            items=items,
            after=after,
            high_watermark=counter,
            next_after=items[-1].global_position if has_more else None,
        )

    async def run_projection_snapshot(
        self, session: AsyncSession, *, run_id: UUID
    ) -> RunProjectionSnapshot | None:
        """Read projection fields and the event cursor from the same MVCC statement."""

        row = (
            await session.execute(
                select(
                    RunModel.id,
                    RunModel.status,
                    RunModel.last_event_position,
                    RunModel.last_run_sequence,
                    RunModel.last_event_at,
                    EventGlobalCounterModel.last_position.label("read_cursor"),
                )
                .select_from(RunModel)
                .join(EventGlobalCounterModel, EventGlobalCounterModel.id == 1)
                .where(RunModel.id == run_id)
            )
        ).one_or_none()
        if row is None:
            return None
        return RunProjectionSnapshot(
            run_id=row.id,
            status=row.status,
            last_event_position=row.last_event_position,
            last_run_sequence=row.last_run_sequence,
            last_event_at=row.last_event_at,
            read_cursor=row.read_cursor,
        )

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
        schema_major = row.schema_version.partition(".")[0]
        if schema_major != SUPPORTED_EVENT_SCHEMA_MAJOR:
            raise UnsupportedEventSchemaError(
                global_position=row.global_position,
                schema_version=row.schema_version,
            )
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
        # A command and its normalized audit event share a transaction. Acquire
        # the event allocation lock before the aggregate row to avoid inversion.
        await session.scalar(
            select(EventGlobalCounterModel).where(EventGlobalCounterModel.id == 1).with_for_update()
        )
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
