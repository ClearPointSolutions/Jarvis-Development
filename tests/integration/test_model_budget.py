"""A paid call is only issued under a durable grant from the bound spend policy."""

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx
import httpx2
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis_api.registry.service import RegistryService
from jarvis_contracts.registry import (
    EgressPolicy,
    ModelProfileSpec,
    Pricing,
    ProviderRequest,
    ProviderSpec,
    RegistryWrite,
    RouteCandidate,
    RoutePolicySpec,
    SpendPolicy,
)
from jarvis_orchestrator.providers.budget import (
    BudgetDeniedError,
    BudgetGateway,
    estimate_input_tokens,
)
from jarvis_orchestrator.providers.configuration import ProviderRuntimeConfig
from jarvis_orchestrator.providers.openai import OpenAIAdapter
from jarvis_orchestrator.providers.runtime import RuntimeModel
from jarvis_persistence.models import EventModel, ModelBudgetGrantModel, ModelCallModel
from tests.integration.test_m5_runtime import acquire, prepare_run
from tests.unit.test_m3_providers import SCHEMA, native

pytestmark = pytest.mark.integration

KNOWN_PRICING = Pricing(
    status="known",
    input_per_million=Decimal("1000"),
    output_per_million=Decimal("2000"),
    source="fixture",
)


async def paid_configuration(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    pricing: Pricing = KNOWN_PRICING,
) -> tuple[ProviderSpec, ModelProfileSpec, UUID, UUID]:
    """Register a remote paid provider/profile pair as immutable revisions."""

    registry = RegistryService(session_factory, allowed_endpoints=("https://mock.test",))
    provider = ProviderSpec(
        provider_kind="openai",
        base_url="https://mock.test",
        locality="remote",
        egress=EgressPolicy(remote_allowed=True, paid=True),
    )
    provider_record = await registry.write(
        "provider_connection",
        RegistryWrite(
            key="budget-" + uuid4().hex,
            display_name="Paid provider",
            idempotency_key=str(uuid4()),
            spec=provider,
        ),
        actor_id=uuid4(),
        correlation_id=str(uuid4()),
    )
    profile = ModelProfileSpec(
        provider_revision_id=provider_record.revision_id,
        model_identifier="configured-model",
        purposes=("utility",),
        locality="remote",
        context_limit=10000,
        output_limit=200,
        structured_json=True,
        pricing=pricing,
    )
    profile_record = await registry.write(
        "model_profile",
        RegistryWrite(
            key="budget-" + uuid4().hex,
            display_name="Paid profile",
            idempotency_key=str(uuid4()),
            spec=profile,
        ),
        actor_id=uuid4(),
        correlation_id=str(uuid4()),
    )
    return provider, profile, provider_record.revision_id, profile_record.revision_id


def route(profile_revision_id: UUID, spend: SpendPolicy) -> RoutePolicySpec:
    return RoutePolicySpec(
        candidates=(RouteCandidate(profile_revision_id=profile_revision_id),),
        purposes=("utility",),
        allow_remote=True,
        spend=spend,
    )


async def bound_route(
    session_factory: async_sessionmaker[AsyncSession],
    profile_revision_id: UUID,
    spend: SpendPolicy,
) -> BudgetGateway:
    """Persist the spend policy as a real immutable revision and bind it."""

    registry = RegistryService(session_factory, allowed_endpoints=("https://mock.test",))
    record = await registry.write(
        "route_policy",
        RegistryWrite(
            key="budget-route-" + uuid4().hex,
            display_name="Budget route",
            idempotency_key=str(uuid4()),
            spec=route(profile_revision_id, spend),
        ),
        actor_id=uuid4(),
        correlation_id=str(uuid4()),
    )
    spec = record.spec
    assert isinstance(spec, RoutePolicySpec)
    return BudgetGateway(spec, record.revision_id)


async def free_configuration(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[ProviderSpec, ModelProfileSpec, UUID, UUID]:
    """Register a local unpaid provider/profile pair as immutable revisions."""

    registry = RegistryService(session_factory, allowed_endpoints=("http://mock.test",))
    provider = ProviderSpec(provider_kind="ollama", base_url="http://mock.test")
    provider_record = await registry.write(
        "provider_connection",
        RegistryWrite(
            key="free-" + uuid4().hex,
            display_name="Free provider",
            idempotency_key=str(uuid4()),
            spec=provider,
        ),
        actor_id=uuid4(),
        correlation_id=str(uuid4()),
    )
    profile = ModelProfileSpec(
        provider_revision_id=provider_record.revision_id,
        model_identifier="configured-model",
        purposes=("utility",),
        context_limit=10000,
        output_limit=200,
        structured_json=True,
    )
    profile_record = await registry.write(
        "model_profile",
        RegistryWrite(
            key="free-" + uuid4().hex,
            display_name="Free profile",
            idempotency_key=str(uuid4()),
            spec=profile,
        ),
        actor_id=uuid4(),
        correlation_id=str(uuid4()),
    )
    return provider, profile, provider_record.revision_id, profile_record.revision_id


def paid_model(
    owner: Any,
    fence: Any,
    provider: ProviderSpec,
    profile: ModelProfileSpec,
    provider_id: UUID,
    profile_id: UUID,
    gateway: BudgetGateway,
    handler: Any,
) -> RuntimeModel:
    model = RuntimeModel(
        ProviderRuntimeConfig(allowed_endpoints=("https://mock.test",)),
        owner,
        fence,
        provider,
        profile,
        provider_id,
        profile_id,
        gateway,
    )
    model.adapter = OpenAIAdapter(
        provider,
        profile,
        provider_id,
        profile_id,
        allowed_endpoints=frozenset({"https://mock.test"}),
        transport=httpx2.MockTransport(handler),
        secret_ref="secret:fixture",
        secret_resolver=lambda _: "synthetic-credential-value",
    )
    return model


def request_for(run_id: UUID, body: str = "hello") -> ProviderRequest:
    return ProviderRequest(
        purpose="utility",
        text=body,
        output_tokens=20,
        correlation_id="budget-test",
        run_id=run_id,
        structured_schema=SCHEMA,
    )


def unreachable(_: httpx2.Request) -> httpx2.Response:  # pragma: no cover - must not run
    raise AssertionError("an unauthorized paid call reached the provider")


def test_input_estimate_is_conservative_and_deterministic() -> None:
    request = request_for(uuid4(), "x" * 300)
    first = estimate_input_tokens(request)
    assert first == estimate_input_tokens(request)
    # The schema is priced too, and the bound exceeds a 4-bytes-per-token guess.
    assert first > len(request.text) // 4


async def test_allowed_paid_call_records_an_immutable_private_grant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await prepare_run(session_factory)
    owner, fence = await acquire(session_factory, run_id)
    provider, profile, provider_id, profile_id = await paid_configuration(session_factory)
    calls = 0

    def respond(_: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(200, json=native('{"answer":"paid"}'))

    model = paid_model(
        owner,
        fence,
        provider,
        profile,
        provider_id,
        profile_id,
        await bound_route(session_factory, profile_id, SpendPolicy(allow_paid=True)),
        respond,
    )
    call_id = uuid4()
    assert await model.invoke(call_id, request_for(run_id)) == {"answer": "paid"}
    assert calls == 1
    async with session_factory() as session:
        grant = await session.get(ModelBudgetGrantModel, call_id)
        assert grant is not None
        assert grant.decision == "allow"
        assert grant.run_spend_before == Decimal(0)
        assert grant.estimated_cost is not None and grant.estimated_cost > 0
        types = set(
            (
                await session.scalars(select(EventModel.type).where(EventModel.run_id == run_id))
            ).all()
        )
        assert {"model.budget_authorized", "model.call_started", "model.call_completed"} <= types
        assert not await session.scalar(
            text(
                "SELECT has_table_privilege('jarvis_v1_api','control.model_budget_grants','SELECT')"
            )
        )
    for statement in (
        "UPDATE control.model_budget_grants SET decision='allow' WHERE call_id=:id",
        "DELETE FROM control.model_budget_grants WHERE call_id=:id",
    ):
        with pytest.raises(DBAPIError, match="immutable"):
            async with session_factory.begin() as session:
                await session.execute(text(statement), {"id": call_id})


async def test_paid_call_is_denied_without_a_bound_route_policy(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await prepare_run(session_factory)
    owner, fence = await acquire(session_factory, run_id)
    provider, profile, provider_id, profile_id = await paid_configuration(session_factory)
    model = paid_model(
        owner,
        fence,
        provider,
        profile,
        provider_id,
        profile_id,
        BudgetGateway(None, None),
        unreachable,
    )
    call_id = uuid4()
    with pytest.raises(BudgetDeniedError) as denial:
        await model.invoke(call_id, request_for(run_id))
    assert "immutable bound route policy" in denial.value.reasons[0]
    async with session_factory() as session:
        grant = await session.get(ModelBudgetGrantModel, call_id)
        # The refusal is committed, not lost with the aborted call.
        assert grant is not None and grant.decision == "deny"
        types = (
            await session.scalars(select(EventModel.type).where(EventModel.run_id == run_id))
        ).all()
        assert "model.budget_denied" in types
        assert "model.call_started" not in types


async def test_disallowed_paid_use_and_exhausted_run_budget_fail_closed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await prepare_run(session_factory)
    owner, fence = await acquire(session_factory, run_id)
    provider, profile, provider_id, profile_id = await paid_configuration(session_factory)

    # allow_paid defaults to False: a configured paid provider stays unusable.
    disabled = paid_model(
        owner,
        fence,
        provider,
        profile,
        provider_id,
        profile_id,
        await bound_route(session_factory, profile_id, SpendPolicy()),
        unreachable,
    )
    with pytest.raises(BudgetDeniedError) as denial:
        await disabled.invoke(uuid4(), request_for(run_id))
    assert "Paid provider use is disabled" in denial.value.reasons

    # A ceiling the estimate cannot satisfy is refused before any network call.
    exhausted = paid_model(
        owner,
        fence,
        provider,
        profile,
        provider_id,
        profile_id,
        await bound_route(
            session_factory,
            profile_id,
            SpendPolicy(allow_paid=True, max_run_cost=Decimal("0.000001")),
        ),
        unreachable,
    )
    with pytest.raises(BudgetDeniedError) as exceeded:
        await exhausted.invoke(uuid4(), request_for(run_id))
    assert "Per-run cost ceiling cannot be satisfied" in exceeded.value.reasons


async def test_unknown_pricing_denies_paid_use(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await prepare_run(session_factory)
    owner, fence = await acquire(session_factory, run_id)
    provider, profile, provider_id, profile_id = await paid_configuration(
        session_factory, pricing=Pricing(status="unknown")
    )
    model = paid_model(
        owner,
        fence,
        provider,
        profile,
        provider_id,
        profile_id,
        await bound_route(session_factory, profile_id, SpendPolicy(allow_paid=True)),
        unreachable,
    )
    with pytest.raises(BudgetDeniedError) as denial:
        await model.invoke(uuid4(), request_for(run_id))
    assert "pricing is not known" in denial.value.reasons[0]


async def test_ambiguous_prior_spend_denies_further_paid_calls(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A billed call that never produced a result makes the run total unsafe."""

    run_id = await prepare_run(session_factory)
    owner, fence = await acquire(session_factory, run_id)
    provider, profile, provider_id, profile_id = await paid_configuration(session_factory)
    gateway = await bound_route(
        session_factory,
        profile_id,
        SpendPolicy(allow_paid=True, max_run_cost=Decimal("1000")),
    )

    def die(_: httpx2.Request) -> httpx2.Response:
        # Adapters classify ordinary provider errors into a recorded result; only
        # a hard death leaves a started call with no outcome at all.
        raise KeyboardInterrupt("process killed mid-inference")

    interrupted = paid_model(owner, fence, provider, profile, provider_id, profile_id, gateway, die)
    with pytest.raises(KeyboardInterrupt):
        await interrupted.invoke(uuid4(), request_for(run_id))
    async with session_factory() as session:
        keys = (
            await session.scalars(
                select(ModelCallModel.idempotency_key).where(ModelCallModel.run_id == run_id)
            )
        ).all()
    assert [key for key in keys if key.endswith(":started")]
    assert not [key for key in keys if key.endswith(":result")]

    blocked = paid_model(
        owner, fence, provider, profile, provider_id, profile_id, gateway, unreachable
    )
    with pytest.raises(BudgetDeniedError) as denial:
        await blocked.invoke(uuid4(), request_for(run_id))
    assert "Durable run spend cannot be determined" in denial.value.reasons


async def test_restart_replays_the_original_decision_without_a_second_charge(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await prepare_run(session_factory)
    owner, fence = await acquire(session_factory, run_id)
    provider, profile, provider_id, profile_id = await paid_configuration(session_factory)
    calls = 0

    def respond(_: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(200, json=native('{"answer":"once"}'))

    model = paid_model(
        owner,
        fence,
        provider,
        profile,
        provider_id,
        profile_id,
        await bound_route(session_factory, profile_id, SpendPolicy(allow_paid=True)),
        respond,
    )
    call_id = uuid4()

    def crash(point: str) -> None:
        if point == "after_model_receipt_before_domain_result":
            raise RuntimeError("injected restart")

    original = owner.fault
    owner.fault = crash
    with pytest.raises(RuntimeError, match="injected restart"):
        await model.invoke(call_id, request_for(run_id))
    owner.fault = original

    # Restart: a fresh gateway and adapter must reuse the receipt, not re-bill.
    restarted = paid_model(
        owner,
        fence,
        provider,
        profile,
        provider_id,
        profile_id,
        await bound_route(session_factory, profile_id, SpendPolicy(allow_paid=True)),
        respond,
    )
    assert await restarted.invoke(call_id, request_for(run_id)) == {"answer": "once"}
    assert calls == 1
    async with session_factory() as session:
        grants = (
            await session.scalars(
                select(ModelBudgetGrantModel).where(ModelBudgetGrantModel.run_id == run_id)
            )
        ).all()
        assert len(grants) == 1


async def test_a_recorded_denial_is_replayed_for_the_same_call(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await prepare_run(session_factory)
    owner, fence = await acquire(session_factory, run_id)
    provider, profile, provider_id, profile_id = await paid_configuration(session_factory)

    def build(gateway: BudgetGateway) -> RuntimeModel:
        return paid_model(
            owner,
            fence,
            provider,
            profile,
            provider_id,
            profile_id,
            gateway,
            unreachable,
        )

    bound = await bound_route(session_factory, profile_id, SpendPolicy())
    call_id = uuid4()
    with pytest.raises(BudgetDeniedError):
        await build(bound).invoke(call_id, request_for(run_id))
    # Restart against the same bound revision replays the durable refusal.
    with pytest.raises(BudgetDeniedError) as replay:
        await build(bound).invoke(call_id, request_for(run_id))
    assert "Paid provider use is disabled" in replay.value.reasons
    # A later permissive revision cannot retroactively release the recorded call.
    widened = await bound_route(session_factory, profile_id, SpendPolicy(allow_paid=True))
    with pytest.raises(BudgetDeniedError) as tampered:
        await build(widened).invoke(call_id, request_for(run_id))
    assert "does not match" in tampered.value.reasons[0]
    async with session_factory() as session:
        grants = (
            await session.scalars(
                select(ModelBudgetGrantModel).where(ModelBudgetGrantModel.call_id == call_id)
            )
        ).all()
        assert len(grants) == 1


async def test_free_local_providers_need_no_grant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from jarvis_orchestrator.providers.ollama import OllamaAdapter

    run_id = await prepare_run(session_factory)
    owner, fence = await acquire(session_factory, run_id)
    provider, profile, provider_id, profile_id = await free_configuration(session_factory)
    model = RuntimeModel(
        ProviderRuntimeConfig(allowed_endpoints=("http://mock.test",)),
        owner,
        fence,
        provider,
        profile,
        provider_id,
        profile_id,
        BudgetGateway(None, None),
    )
    model.adapter = OllamaAdapter(
        provider,
        profile,
        provider_id,
        profile_id,
        allowed_endpoints=frozenset({"http://mock.test"}),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "done": True,
                    "model": "configured-model",
                    "message": {"content": '{"answer":"free"}'},
                },
            )
        ),
    )
    assert await model.invoke(uuid4(), request_for(run_id)) == {"answer": "free"}
    async with session_factory() as session:
        assert not (
            await session.scalars(
                select(ModelBudgetGrantModel).where(ModelBudgetGrantModel.run_id == run_id)
            )
        ).all()


async def test_an_indeterminate_total_only_blocks_a_policy_that_caps_the_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Without a run ceiling the running total constrains nothing, so it is not required."""

    run_id = await prepare_run(session_factory)
    owner, fence = await acquire(session_factory, run_id)
    provider, profile, provider_id, profile_id = await paid_configuration(session_factory)
    uncapped = await bound_route(session_factory, profile_id, SpendPolicy(allow_paid=True))

    def die(_: httpx2.Request) -> httpx2.Response:
        raise KeyboardInterrupt("process killed mid-inference")

    interrupted = paid_model(
        owner, fence, provider, profile, provider_id, profile_id, uncapped, die
    )
    with pytest.raises(KeyboardInterrupt):
        await interrupted.invoke(uuid4(), request_for(run_id))
    async with session_factory() as session:
        # The total really is unknown; the policy simply does not depend on it.
        assert await uncapped.run_spend(session, run_id) is None

    def respond(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=native('{"answer":"uncapped"}'))

    allowed = paid_model(
        owner, fence, provider, profile, provider_id, profile_id, uncapped, respond
    )
    assert await allowed.invoke(uuid4(), request_for(run_id)) == {"answer": "uncapped"}
