"""M3 durable circuit fencing and append-only accounting on real PostgreSQL."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jarvis_api.registry.service import RegistryService
from jarvis_api.routing.observability import AccountingService, HealthService
from jarvis_api.routing.policies import calculate_cost
from jarvis_contracts.registry import (
    AccountingRecord,
    CircuitPolicy,
    Cost,
    ModelProfileSpec,
    Pricing,
    ProviderSpec,
    RegistryRecord,
    RegistryWrite,
    Usage,
)
from jarvis_persistence.models import EventModel, ModelCallModel, ProviderHealthModel
from jarvis_persistence.repositories import IdempotencyConflictError
from jarvis_persistence.testing import FrozenClock

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def configured(
    database_url: str,
) -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], RegistryRecord, RegistryRecord]]:
    engine = create_async_engine(
        database_url,
        connect_args={"options": "-c role=jarvis_v1_orchestrator"},
        hide_parameters=True,
    )
    registry_engine = create_async_engine(
        database_url, connect_args={"options": "-c role=jarvis_v1_api"}, hide_parameters=True
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    registry = RegistryService(async_sessionmaker(registry_engine, expire_on_commit=False))
    actor = UUID("10000000-0000-0000-0000-000000000003")

    async def create(spec: ProviderSpec | ModelProfileSpec) -> RegistryRecord:
        return await registry.write(
            spec.kind,
            RegistryWrite(
                key="fixture-" + uuid4().hex,
                display_name="DEMO fixture",
                idempotency_key=str(uuid4()),
                spec=spec,
            ),
            actor_id=actor,
            correlation_id=str(uuid4()),
        )

    try:
        provider = await create(ProviderSpec(provider_kind="demo"))
        model = await create(
            ModelProfileSpec(
                provider_revision_id=provider.revision_id,
                model_identifier="demo-fixture",
                purposes=("utility",),
                context_limit=4096,
                output_limit=100,
                pricing=Pricing(
                    status="known", input_per_million=Decimal(2), output_per_million=Decimal(4)
                ),
            )
        )
        yield factory, provider, model
    finally:
        await engine.dispose()
        await registry_engine.dispose()


async def test_circuit_restart_threshold_concurrency_fencing(
    configured: tuple[async_sessionmaker[AsyncSession], RegistryRecord, RegistryRecord],
) -> None:
    factory, provider, _ = configured
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    policy = CircuitPolicy(failure_threshold=2, cooldown_seconds=10)
    service = HealthService(factory, clock)
    assert await service.observe(provider.revision_id, policy, success=False)
    assert await service.observe(provider.revision_id, policy, success=False)
    restarted = HealthService(factory, clock)
    assert await restarted.acquire_probe(provider.revision_id, policy) is None
    # A stale in-flight success cannot bypass an already-open cooldown.
    assert not await restarted.observe(provider.revision_id, policy, success=True)
    clock.advance(timedelta(seconds=11))
    probes = await asyncio.gather(
        *(restarted.acquire_probe(provider.revision_id, policy) for _ in range(5))
    )
    winners = [value for value in probes if value is not None]
    assert len(winners) == 1
    version = winners[0]
    assert not await restarted.observe(
        provider.revision_id, policy, success=True, probe_version=version - 1
    )
    assert not await restarted.observe(provider.revision_id, policy, success=True)
    assert await restarted.observe(
        provider.revision_id, policy, success=True, probe_version=version
    )
    async with factory() as session:
        row = await session.get(ProviderHealthModel, provider.revision_id)
        assert (
            row
            and row.circuit_state == "closed"
            and row.status == "healthy"
            and row.failure_count == 0
        )
        events = list(
            await session.scalars(
                select(EventModel).where(
                    EventModel.correlation_id == str(provider.revision_id),
                    EventModel.type == "model.health_changed",
                )
            )
        )
        assert len(events) >= 4
        assert all(event.mode == "demo" for event in events)


async def test_probe_expiry_and_failure_window(
    configured: tuple[async_sessionmaker[AsyncSession], RegistryRecord, RegistryRecord],
) -> None:
    factory, provider, _ = configured
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    policy = CircuitPolicy(failure_threshold=2, cooldown_seconds=5, failure_window_seconds=10)
    service = HealthService(factory, clock)
    await service.observe(provider.revision_id, policy, success=False)
    clock.advance(timedelta(seconds=11))
    await service.observe(provider.revision_id, policy, success=False)
    async with factory() as session:
        row = await session.get(ProviderHealthModel, provider.revision_id)
        assert row and row.failure_count == 1 and row.circuit_state == "closed"
    await service.observe(provider.revision_id, policy, success=False)
    clock.advance(timedelta(seconds=6))
    first = await service.acquire_probe(provider.revision_id, policy)
    assert first is not None
    clock.advance(timedelta(seconds=6))
    assert not await service.observe(
        provider.revision_id, policy, success=True, probe_version=first
    )
    second = await service.acquire_probe(provider.revision_id, policy)
    assert second is not None and second > first
    assert await service.observe(provider.revision_id, policy, success=False, probe_version=second)
    assert await service.acquire_probe(provider.revision_id, policy) is None


def accounting(provider: RegistryRecord, model: RegistryRecord) -> AccountingRecord:
    assert isinstance(model.spec, ModelProfileSpec)
    usage = Usage(input_tokens=100, output_tokens=20, total_tokens=120, provenance="exact")
    return AccountingRecord(
        id=uuid4(),
        provider_revision_id=provider.revision_id,
        profile_revision_id=model.revision_id,
        correlation_id=str(uuid4()),
        request_id="DEMO-fixture",
        latency_ms=12,
        usage=usage,
        pricing=model.spec.pricing,
        cost=calculate_cost(usage, model.spec.pricing),
        outcome="completed",
        created_at=datetime.now(UTC),
        demo=True,
    )


async def test_accounting_dedup_conflict_immutable_and_price_snapshot(
    configured: tuple[async_sessionmaker[AsyncSession], RegistryRecord, RegistryRecord],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    factory, provider, model = configured
    service = AccountingService(factory)
    record = accounting(provider, model)
    key = str(uuid4())
    values = await asyncio.gather(*(service.record(record, idempotency_key=key) for _ in range(4)))
    assert values == [record] * 4
    assert record.cost.amount == Decimal("0.00028")
    async with factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ModelCallModel)
                .where(ModelCallModel.correlation_id == record.correlation_id)
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventModel)
                .where(
                    EventModel.correlation_id == record.correlation_id,
                    EventModel.type == "model.usage_recorded",
                )
            )
            == 1
        )
    with pytest.raises(IdempotencyConflictError):
        await service.record(record.model_copy(update={"latency_ms": 14}), idempotency_key=key)
    # Even the database owner cannot mutate append-only accounting.
    for statement in (
        "UPDATE control.model_calls SET correlation_id='changed' WHERE id=:id",
        "DELETE FROM control.model_calls WHERE id=:id",
    ):
        async with session_factory() as session, session.begin():
            with pytest.raises(DBAPIError):
                await session.execute(text(statement), {"id": record.id})
    assert await AccountingService(factory).record(record, idempotency_key=key) == record


async def test_accounting_secret_and_false_cost_rejected(
    configured: tuple[async_sessionmaker[AsyncSession], RegistryRecord, RegistryRecord],
) -> None:
    factory, provider, model = configured
    service = AccountingService(factory)
    record = accounting(provider, model)
    for changed in (
        record.model_copy(update={"request_id": "token=synthetic-accounting-canary"}),
        record.model_copy(update={"cost": Cost(amount=Decimal(0), status="exact")}),
        record.model_copy(update={"provider_revision_id": model.revision_id}),
        record.model_copy(update={"pricing": Pricing()}),
    ):
        with pytest.raises(ValueError):
            await service.record(changed, idempotency_key=str(uuid4()))
    with pytest.raises(ValueError):
        await service.record(record, idempotency_key="token=synthetic-accounting-canary")
    async with factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ModelCallModel)
                .where(ModelCallModel.correlation_id == record.correlation_id)
            )
            == 0
        )
        assert not list(
            await session.scalars(
                select(EventModel).where(EventModel.correlation_id == record.correlation_id)
            )
        )
