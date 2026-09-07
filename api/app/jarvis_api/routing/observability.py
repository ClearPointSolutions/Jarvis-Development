"""Durable M3 circuit transitions and append-only accounting, without a scheduler."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis_api.events.normalizer import EventIntent, EventNormalizer, EventWriter
from jarvis_api.events.redaction import RecursiveRedactor
from jarvis_api.routing.policies import calculate_cost
from jarvis_contracts.base import sha256_digest
from jarvis_contracts.enums import EventMode, EventSeverity, EventVisibility
from jarvis_contracts.events import EventScope, EventSource
from jarvis_contracts.registry import (
    REGISTRY_SPEC_ADAPTER,
    AccountingRecord,
    CircuitPolicy,
    HealthStatus,
    ModelProfileSpec,
    ProviderSpec,
    RoutePolicySpec,
)
from jarvis_persistence.models import (
    ConfigurationRevisionModel,
    EventGlobalCounterModel,
    ModelCallModel,
    ProviderHealthModel,
)
from jarvis_persistence.repositories import EventRepository, IdempotencyConflictError
from jarvis_persistence.testing import Clock, SystemClock


def event_writer() -> EventWriter:
    return EventWriter(
        repository=EventRepository(),
        normalizer=EventNormalizer(
            redactor=RecursiveRedactor(),
            artifact_sink=None,
            inline_bytes=32_768,
            max_bytes=65_536,
        ),
    )


async def lock_events(session: AsyncSession) -> None:
    await session.scalar(
        select(EventGlobalCounterModel)
        .where(
            EventGlobalCounterModel.id == 1,
        )
        .with_for_update()
    )


class HealthService:
    """Revision-scoped circuit state with a fenced single half-open probe lease."""

    def __init__(self, factory: async_sessionmaker[AsyncSession], clock: Clock | None = None):
        self.factory = factory
        self.clock = clock or SystemClock()
        self.writer = event_writer()

    async def _row(self, session: AsyncSession, revision_id: UUID) -> ProviderHealthModel:
        revision = await session.get(ConfigurationRevisionModel, revision_id)
        if revision is None:
            raise ValueError("provider health revision is missing")
        spec = REGISTRY_SPEC_ADAPTER.validate_python(revision.spec_json.get("spec"))
        if not isinstance(spec, ProviderSpec):
            raise ValueError("provider health requires a provider revision")
        row = await session.get(ProviderHealthModel, revision_id, with_for_update=True)
        if row is None:
            row = ProviderHealthModel(
                revision_id=revision_id,
                status="unknown",
                circuit_state="closed",
                failure_count=0,
                version=0,
            )
            session.add(row)
            await session.flush()
        return row

    async def _event(self, session: AsyncSession, row: ProviderHealthModel) -> None:
        revision = await session.get(ConfigurationRevisionModel, row.revision_id)
        demo = bool(revision and revision.spec_json.get("spec", {}).get("provider_kind") == "demo")
        await self.writer.append(
            session,
            EventIntent(
                occurred_at=self.clock.now(),
                type="model.health_changed",
                severity=EventSeverity.INFO,
                mode=EventMode.DEMO if demo else EventMode.REAL,
                visibility=EventVisibility.OWNER,
                source=EventSource(
                    kind="provider_adapter", name="provider_health", instance_id="m3"
                ),
                correlation_id=str(row.revision_id),
                data={
                    "provider_revision_id": str(row.revision_id),
                    "status": row.status,
                    "circuit_state": row.circuit_state,
                    "failure_count": row.failure_count,
                    "version": row.version,
                },
            ),
        )

    async def acquire_probe(self, revision_id: UUID, policy: CircuitPolicy) -> int | None:
        async with self.factory() as session, session.begin():
            await lock_events(session)
            row = await self._row(session, revision_id)
            now = self.clock.now()
            if row.circuit_state == "closed":
                return row.version
            if row.circuit_state == "open" and row.next_probe_at and row.next_probe_at > now:
                return None
            if (
                row.circuit_state == "half_open"
                and row.probe_lease_until
                and row.probe_lease_until > now
            ):
                return None
            row.circuit_state = "half_open"
            row.probe_lease_until = now + timedelta(seconds=policy.cooldown_seconds)
            row.version += 1
            await self._event(session, row)
            return row.version

    async def observe(
        self,
        revision_id: UUID,
        policy: CircuitPolicy,
        *,
        success: bool,
        status: HealthStatus | None = None,
        probe_version: int | None = None,
    ) -> bool:
        async with self.factory() as session, session.begin():
            await lock_events(session)
            row = await self._row(session, revision_id)
            now = self.clock.now()
            if probe_version is not None and row.version != probe_version:
                return False
            if row.circuit_state == "open":
                return False
            if row.circuit_state == "half_open" and (
                probe_version is None
                or row.probe_lease_until is None
                or row.probe_lease_until <= now
            ):
                return False
            previous = (row.status, row.circuit_state)
            if success:
                row.status = status or "healthy"
                row.circuit_state = "closed"
                row.failure_count = 0
                row.window_started_at = now
                row.next_probe_at = None
                row.probe_lease_until = None
            else:
                if (
                    row.window_started_at is None
                    or (now - row.window_started_at).total_seconds() > policy.failure_window_seconds
                ):
                    row.failure_count = 0
                    row.window_started_at = now
                row.failure_count += 1
                row.status = status or "degraded"
                if (
                    row.failure_count >= policy.failure_threshold
                    or row.circuit_state == "half_open"
                ):
                    row.circuit_state = "open"
                    row.status = status or "unavailable"
                    row.next_probe_at = now + timedelta(seconds=policy.cooldown_seconds)
                    row.probe_lease_until = None
            row.observed_at = now
            row.version += 1
            if previous != (row.status, row.circuit_state):
                await self._event(session, row)
            return True


class AccountingService:
    def __init__(self, factory: async_sessionmaker[AsyncSession]):
        self.factory = factory
        self.writer = event_writer()

    async def record(self, record: AccountingRecord, *, idempotency_key: str) -> AccountingRecord:
        # Accounting never stores prompts, credentials or native exceptions.
        if (
            not 8 <= len(idempotency_key) <= 200
            or RecursiveRedactor().redact_text(idempotency_key)[1]
        ):
            raise ValueError("accounting idempotency key is invalid")
        payload = record.model_dump(mode="json")
        if RecursiveRedactor().redact(payload).value != payload:
            raise ValueError("accounting contains sensitive content")
        async with self.factory() as session, session.begin():
            await lock_events(session)
            prior = await session.scalar(
                select(ModelCallModel).where(
                    ModelCallModel.correlation_id == record.correlation_id,
                    ModelCallModel.idempotency_key == idempotency_key,
                )
            )
            if prior is not None:
                if sha256_digest(prior.record_json) != sha256_digest(payload):
                    raise IdempotencyConflictError("accounting idempotency conflict")
                return AccountingRecord.model_validate(prior.record_json)
            profile_revision = await session.get(
                ConfigurationRevisionModel, record.profile_revision_id
            )
            provider_revision = await session.get(
                ConfigurationRevisionModel, record.provider_revision_id
            )
            if profile_revision is None or provider_revision is None:
                raise ValueError("accounting references missing revisions")
            profile = REGISTRY_SPEC_ADAPTER.validate_python(profile_revision.spec_json.get("spec"))
            provider = REGISTRY_SPEC_ADAPTER.validate_python(
                provider_revision.spec_json.get("spec")
            )
            if (
                not isinstance(profile, ModelProfileSpec)
                or not isinstance(provider, ProviderSpec)
                or profile.provider_revision_id != record.provider_revision_id
                or record.pricing != profile.pricing
                or record.cost != calculate_cost(record.usage, record.pricing)
                or record.demo != (provider.provider_kind == "demo")
            ):
                raise ValueError("accounting snapshot or cost does not match configuration")
            if record.route_revision_id:
                route_revision = await session.get(
                    ConfigurationRevisionModel, record.route_revision_id
                )
                if route_revision is None:
                    raise ValueError("accounting route revision is missing")
                route = REGISTRY_SPEC_ADAPTER.validate_python(route_revision.spec_json.get("spec"))
                if not isinstance(route, RoutePolicySpec) or record.profile_revision_id not in {
                    c.profile_revision_id for c in route.candidates
                }:
                    raise ValueError("accounting profile is not declared by route")
            session.add(
                ModelCallModel(
                    id=record.id,
                    profile_revision_id=record.profile_revision_id,
                    provider_revision_id=record.provider_revision_id,
                    route_revision_id=record.route_revision_id,
                    run_id=record.run_id,
                    correlation_id=record.correlation_id,
                    idempotency_key=idempotency_key,
                    record_json=payload,
                    created_at=record.created_at,
                )
            )
            await session.flush()
            await self.writer.append(
                session,
                EventIntent(
                    occurred_at=record.created_at,
                    type="model.usage_recorded",
                    severity=EventSeverity.INFO,
                    mode=EventMode.DEMO if record.demo else EventMode.REAL,
                    visibility=EventVisibility.OWNER,
                    source=EventSource(
                        kind="provider_adapter", name="accounting", instance_id="m3"
                    ),
                    correlation_id=record.correlation_id,
                    scope=EventScope(
                        run_id=record.run_id,
                        project_id=record.project_id,
                        task_id=record.task_id,
                        workflow_node_id=record.node_id,
                    ),
                    data={
                        "model_call_id": str(record.id),
                        "profile_revision_id": str(record.profile_revision_id),
                        "usage": record.usage.model_dump(mode="json"),
                        "cost": record.cost.model_dump(mode="json"),
                        "outcome": record.outcome,
                    },
                ),
            )
        return record
