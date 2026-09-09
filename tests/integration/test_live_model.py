"""Opt-in acceptance against an actually running local Ollama server.

CI has no model server, so these are skipped unless the operator points
`JARVIS_LIVE_OLLAMA_URL` at a reachable allowlisted endpoint and names an
installed tag in `JARVIS_LIVE_OLLAMA_MODEL`. Nothing here is a fixture: the
requests reach the real server and the recorded usage is the server's own.
"""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_api.registry.service import RegistryService
from jarvis_contracts.enums import FailureClass
from jarvis_contracts.registry import (
    ModelProfileSpec,
    ProviderRequest,
    ProviderSpec,
    RegistryWrite,
)
from jarvis_orchestrator.providers.budget import BudgetGateway
from jarvis_orchestrator.providers.configuration import ProviderRuntimeConfig
from jarvis_orchestrator.providers.runtime import RuntimeModel
from jarvis_orchestrator.runtime.nodes import ClassifiedNodeError
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership
from jarvis_orchestrator.runtime.planning import OrganizerOutput, TaskPlan, inline_schema
from jarvis_orchestrator.verification.model_reviewer import decision_schema
from jarvis_persistence.models import ModelCallModel, ModelResponseReceiptModel
from jarvis_persistence.repositories import LeaseRepository
from tests.integration.test_m5_runtime import prepare_run

pytestmark = pytest.mark.integration

LIVE_URL = os.environ.get("JARVIS_LIVE_OLLAMA_URL")
LIVE_MODEL = os.environ.get("JARVIS_LIVE_OLLAMA_MODEL")
LIVE_TIMEOUT = float(os.environ.get("JARVIS_LIVE_OLLAMA_TIMEOUT", "600"))

live = pytest.mark.skipif(
    not (LIVE_URL and LIVE_MODEL),
    reason="set JARVIS_LIVE_OLLAMA_URL and JARVIS_LIVE_OLLAMA_MODEL for live acceptance",
)


async def acquire_live(
    session_factory: async_sessionmaker[AsyncSession], run_id: UUID
) -> tuple[RunOwnership, RunFence]:
    """Hold the run lease for the whole live call.

    The shared 30-second test helper models a fast fixture. A real model can take
    far longer to warm, which the service survives by renewing the lease from its
    heartbeat; these tests have no heartbeat, so the lease is sized to the call.
    """

    ownership = RunOwnership(session_factory, owner=str(uuid7()))
    await ownership.register()
    async with session_factory.begin() as session:
        lease = await LeaseRepository().acquire(
            session,
            run_id=run_id,
            owner_instance_id=ownership.owner,
            ttl=timedelta(seconds=LIVE_TIMEOUT * 4),
        )
        assert lease is not None
        return ownership, RunFence(run_id, ownership.owner, lease.generation)


async def live_configuration(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    model_identifier: str | None = None,
) -> tuple[ProviderSpec, ModelProfileSpec, UUID, UUID]:
    """Register the live endpoint as ordinary immutable registry revisions."""

    assert LIVE_URL is not None and LIVE_MODEL is not None
    registry = RegistryService(session_factory, allowed_endpoints=(LIVE_URL,))
    provider = ProviderSpec(provider_kind="ollama", base_url=LIVE_URL)
    provider_record = await registry.write(
        "provider_connection",
        RegistryWrite(
            key="live-" + uuid4().hex,
            display_name="Live Ollama",
            idempotency_key=str(uuid4()),
            spec=provider,
        ),
        actor_id=uuid4(),
        correlation_id=str(uuid4()),
    )
    profile = ModelProfileSpec(
        provider_revision_id=provider_record.revision_id,
        model_identifier=model_identifier or LIVE_MODEL,
        purposes=("organizer", "architect", "reviewer", "utility"),
        context_limit=8192,
        output_limit=2048,
        structured_json=True,
    )
    profile_record = await registry.write(
        "model_profile",
        RegistryWrite(
            key="live-" + uuid4().hex,
            display_name="Live Ollama profile",
            idempotency_key=str(uuid4()),
            spec=profile,
        ),
        actor_id=uuid4(),
        correlation_id=str(uuid4()),
    )
    return provider, profile, provider_record.revision_id, profile_record.revision_id


async def live_model(
    session_factory: async_sessionmaker[AsyncSession],
    owner: object,
    fence: object,
    *,
    model_identifier: str | None = None,
) -> RuntimeModel:
    assert LIVE_URL is not None
    provider, profile, provider_id, profile_id = await live_configuration(
        session_factory, model_identifier=model_identifier
    )
    return RuntimeModel(
        ProviderRuntimeConfig(allowed_endpoints=(LIVE_URL,), probe_seconds=60),
        owner,  # type: ignore[arg-type]
        fence,  # type: ignore[arg-type]
        provider,
        profile,
        provider_id,
        profile_id,
        BudgetGateway(None, None),
    )


async def recorded_outcomes(
    session_factory: async_sessionmaker[AsyncSession], run_id: UUID
) -> list[str]:
    """Return the durable outcome of every completed model call for the run."""

    async with session_factory() as session:
        return [
            str(row.record_json["outcome"])
            for row in (
                await session.scalars(select(ModelCallModel).where(ModelCallModel.run_id == run_id))
            ).all()
            if row.idempotency_key.endswith(":result")
        ]


@live
async def test_live_connection_validation_reports_a_checked_network() -> None:
    from jarvis_orchestrator.providers.ollama import OllamaAdapter

    assert LIVE_URL is not None and LIVE_MODEL is not None
    provider = ProviderSpec(provider_kind="ollama", base_url=LIVE_URL)
    provider_revision_id = uuid4()
    profile = ModelProfileSpec(
        provider_revision_id=provider_revision_id,
        model_identifier=LIVE_MODEL,
        purposes=("utility",),
        context_limit=8192,
        output_limit=2048,
        structured_json=True,
    )
    adapter = OllamaAdapter(
        provider,
        profile,
        provider_revision_id,
        uuid4(),
        allowed_endpoints=frozenset({LIVE_URL}),
    )
    async with asyncio.timeout(LIVE_TIMEOUT):
        status = await adapter.validate_connection()
    assert status.valid, status.issues
    # A real probe reaches the server; it is not a configuration-only check.
    assert status.network_checked
    assert status.demo is False


@live
async def test_live_organizer_and_architect_satisfy_the_real_planning_contracts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The live model must satisfy the same schemas the planning node uses."""

    run_id = await prepare_run(session_factory)
    owner, fence = await acquire_live(session_factory, run_id)
    model = await live_model(session_factory, owner, fence)
    objective = (
        "Add a function `add(a, b)` returning the sum in calculator.py, "
        "with a pytest test in test_calculator.py."
    )

    async with asyncio.timeout(LIVE_TIMEOUT):
        summary = await model.invoke(
            uuid4(),
            ProviderRequest(
                purpose="organizer",
                text=(
                    "Summarize the user's objective and constraints for the Architect. "
                    "Return only schema-valid JSON. /no_think\n" + objective
                ),
                output_tokens=1024,
                structured_schema=inline_schema(OrganizerOutput),
                correlation_id="live-organizer",
                run_id=run_id,
            ),
        )
    assert OrganizerOutput.model_validate(summary).summary

    async with asyncio.timeout(LIVE_TIMEOUT):
        plan = await model.invoke(
            uuid4(),
            ProviderRequest(
                purpose="architect",
                text=(
                    "Design at most 2 ordered tasks. Every task needs concrete acceptance "
                    "criteria and deterministic verification argv at the repository root, "
                    'for example ["python","-m","pytest"]. Never invent an absolute '
                    "path. Return only schema-valid JSON. /no_think\n" + objective
                ),
                output_tokens=2048,
                structured_schema=inline_schema(TaskPlan),
                correlation_id="live-architect",
                run_id=run_id,
            ),
        )
    parsed = TaskPlan.model_validate(plan)
    assert parsed.architecture and parsed.tasks
    assert all(task.verification for task in parsed.tasks)

    # Live usage and receipts are recorded exactly like any other real call.
    async with session_factory() as session:
        receipts = (
            await session.scalars(
                select(ModelResponseReceiptModel).where(ModelResponseReceiptModel.run_id == run_id)
            )
        ).all()
        assert len(receipts) == 2
        results = [
            row.record_json
            for row in (
                await session.scalars(select(ModelCallModel).where(ModelCallModel.run_id == run_id))
            ).all()
            if row.idempotency_key.endswith(":result")
        ]
        assert len(results) == 2
        for record in results:
            assert record["outcome"] == "completed"
            # Ollama reports real token counts rather than an estimate.
            assert record["usage"]["provenance"] == "exact"
            assert record["usage"]["input_tokens"] > 0
            # A local profile carries no configured pricing, so no amount is
            # invented; the provider is unpaid and needs no budget grant.
            assert record["cost"]["status"] in {"unknown", "not_applicable"}
            assert record["cost"]["amount"] is None


@live
async def test_live_reviewer_decision_is_valid_or_classified(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The reviewer schema is the strictest contract a configured model must meet.

    Small tags cannot reliably emit it. Either outcome is acceptable to the
    system, but never a crash and never a silently accepted malformed review:
    a shortfall must surface as a classified provider contract failure.
    """

    run_id = await prepare_run(session_factory)
    owner, fence = await acquire_live(session_factory, run_id)
    model = await live_model(session_factory, owner, fence)
    request = ProviderRequest(
        purpose="reviewer",
        text=(
            "Act as an independent code reviewer. PASS requires an empty findings "
            "list. Return only schema-valid JSON. /no_think\n"
            "Task: add(a, b) must return a + b. Source: def add(a, b): return a + b"
        ),
        output_tokens=2048,
        structured_schema=decision_schema(),
        correlation_id="live-reviewer",
        run_id=run_id,
    )
    try:
        async with asyncio.timeout(LIVE_TIMEOUT):
            decision = await model.invoke(uuid4(), request)
    except ClassifiedNodeError as classified:
        assert classified.failure is FailureClass.PROVIDER_CONTRACT_FAILURE
        assert await recorded_outcomes(session_factory, run_id) == ["failed"]
        return
    assert decision.get("verdict") in {"PASS", "FAIL"}
    assert decision.get("summary")
    assert await recorded_outcomes(session_factory, run_id) == ["completed"]


@live
async def test_live_missing_model_is_classified_not_crashed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An uninstalled tag is a classified provider failure, not an exception."""

    run_id = await prepare_run(session_factory)
    owner, fence = await acquire_live(session_factory, run_id)
    model = await live_model(
        session_factory, owner, fence, model_identifier="jarvis-absent-model:v0"
    )
    with pytest.raises(ClassifiedNodeError) as failure:
        async with asyncio.timeout(LIVE_TIMEOUT):
            await model.invoke(
                uuid4(),
                ProviderRequest(
                    purpose="utility",
                    text="unreachable",
                    output_tokens=64,
                    structured_schema={
                        "type": "object",
                        "properties": {"answer": {"type": "string"}},
                        "required": ["answer"],
                        "additionalProperties": False,
                    },
                    correlation_id="live-missing-model",
                    run_id=run_id,
                ),
            )
    assert failure.value.failure is not FailureClass.UNKNOWN
    async with session_factory() as session:
        failed = [
            row.record_json
            for row in (
                await session.scalars(select(ModelCallModel).where(ModelCallModel.run_id == run_id))
            ).all()
            if row.idempotency_key.endswith(":result")
        ]
        assert failed and failed[0]["outcome"] == "failed"
