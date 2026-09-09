"""A receipt survives the model/domain crash window without repeated inference."""

from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis_api.registry.service import RegistryService
from jarvis_contracts.registry import ProviderRequest, RegistryWrite
from jarvis_orchestrator.providers.configuration import ProviderRuntimeConfig
from jarvis_orchestrator.providers.ollama import OllamaAdapter
from jarvis_orchestrator.providers.runtime import RuntimeModel
from jarvis_orchestrator.runtime.effects import AmbiguousEffectError
from jarvis_persistence.models import EventModel, ModelResponseReceiptModel
from tests.integration.test_m5_runtime import acquire, prepare_run
from tests.unit.test_m3_providers import SCHEMA, config

pytestmark = pytest.mark.integration


async def test_response_receipt_reentry_and_private_immutable_storage(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await prepare_run(session_factory)
    owner, fence = await acquire(session_factory, run_id)
    provider, profile, provider_id, profile_id = config("ollama")
    registry = RegistryService(session_factory, allowed_endpoints=("http://mock.test",))
    provider_record = await registry.write(
        "provider_connection",
        RegistryWrite(
            key="receipt-" + uuid4().hex,
            display_name="Receipt provider",
            idempotency_key=str(uuid4()),
            spec=provider,
        ),
        actor_id=uuid4(),
        correlation_id=str(uuid4()),
    )
    provider_id = provider_record.revision_id
    profile = profile.model_copy(update={"provider_revision_id": provider_id})
    profile_record = await registry.write(
        "model_profile",
        RegistryWrite(
            key="receipt-" + uuid4().hex,
            display_name="Receipt profile",
            idempotency_key=str(uuid4()),
            spec=profile,
        ),
        actor_id=uuid4(),
        correlation_id=str(uuid4()),
    )
    profile_id = profile_record.revision_id
    configuration = ProviderRuntimeConfig(allowed_endpoints=("http://mock.test",))
    model = RuntimeModel(configuration, owner, fence, provider, profile, provider_id, profile_id)
    calls = 0

    def response(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "done": True,
                "model": "configured-model",
                "message": {"content": '{"answer":"saved"}'},
            },
        )

    model.adapter = OllamaAdapter(
        provider,
        profile,
        provider_id,
        profile_id,
        allowed_endpoints=frozenset(configuration.allowed_endpoints),
        transport=httpx.MockTransport(response),
    )
    request = ProviderRequest(
        purpose="utility",
        text="hello",
        output_tokens=20,
        correlation_id="receipt-test",
        run_id=run_id,
        structured_schema=SCHEMA,
    )
    call_id = uuid4()

    def crash(point: str) -> None:
        if point == "after_model_receipt_before_domain_result":
            raise RuntimeError("injected crash")

    owner.fault = crash
    with pytest.raises(RuntimeError, match="injected"):
        await model.invoke(call_id, request)
    # A fresh gateway with no mock transport must use the persisted receipt.
    replacement = RuntimeModel(
        configuration, owner, fence, provider, profile, provider_id, profile_id
    )
    assert await replacement.invoke(call_id, request) == {"answer": "saved"}
    assert calls == 1
    with pytest.raises(AmbiguousEffectError, match="identity"):
        await replacement.invoke(call_id, request.model_copy(update={"text": "changed"}))
    async with session_factory() as session:
        assert await session.get(ModelResponseReceiptModel, call_id) is not None
        assert (
            len(
                (
                    await session.scalars(
                        select(EventModel).where(
                            EventModel.run_id == run_id, EventModel.type == "model.call_completed"
                        )
                    )
                ).all()
            )
            == 1
        )
        for role in ("jarvis_v1_api", "jarvis_v1_readonly"):
            assert not await session.scalar(
                text(
                    "SELECT has_table_privilege(:role, 'control.model_response_receipts', 'SELECT')"
                ),
                {"role": role},
            )
    for statement in (
        "UPDATE control.model_response_receipts SET request_digest='changed' WHERE call_id=:id",
        "DELETE FROM control.model_response_receipts WHERE call_id=:id",
    ):
        with pytest.raises(DBAPIError, match="immutable"):
            async with session_factory.begin() as session:
                await session.execute(text(statement), {"id": call_id})


async def test_started_call_without_response_remains_ambiguous(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await prepare_run(session_factory)
    owner, fence = await acquire(session_factory, run_id)
    provider, profile, provider_id, profile_id = config("ollama")
    model = RuntimeModel(
        ProviderRuntimeConfig(allowed_endpoints=("http://mock.test",)),
        owner,
        fence,
        provider,
        profile,
        provider_id,
        profile_id,
    )
    call_id = uuid4()
    async with owner.fenced(fence) as (session, run):
        await owner.event(session, run, "model.call_started", {"call_id": str(call_id)})
    with pytest.raises(AmbiguousEffectError, match="reconciliation"):
        await model.invoke(
            call_id,
            ProviderRequest(
                purpose="utility",
                text="hello",
                output_tokens=20,
                correlation_id="ambiguous",
                run_id=run_id,
            ),
        )
