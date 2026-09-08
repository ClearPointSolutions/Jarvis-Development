from __future__ import annotations

import asyncio

import pytest
from langchain_core.runnables import RunnableConfig
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis_contracts.enums import FailureClass, RunCommandKind
from jarvis_contracts.failures import RetryRule
from jarvis_contracts.registry import (
    ModelProfileSpec,
    ProviderSpec,
    RetryRegistrySpec,
    RouteCandidate,
    RoutePolicySpec,
)
from jarvis_orchestrator.runtime.service import OrchestratorService
from jarvis_orchestrator.workflows.factories import NodeContext
from jarvis_orchestrator.workflows.state import WorkflowStateV1
from jarvis_persistence.models import EventModel, RetryCounterModel, RunModel
from tests.integration.test_m5_control import enqueue
from tests.integration.test_m5_effects import DeterministicAdapter, InjectedCrash
from tests.integration.test_m5_runtime import acquire, prepare_run
from tests.unit.test_m4_workflows_compiler import (
    edge,
    external_defaults,
    node,
    resolved_revision,
    snapshot_for,
    spec_for,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "failure",
    [
        FailureClass.CODE_TEST_FAILURE,
        FailureClass.INFRASTRUCTURE_WORKER_TRANSPORT,
        FailureClass.PROVIDER_RATE_LIMITED,
        FailureClass.PROVIDER_TRANSIENT,
        FailureClass.CODE_REVIEW_FAILURE,
        FailureClass.CODE_GIT_CONFLICT,
    ],
)
@pytest.mark.parametrize("exhausted", [False, True])
async def test_fail001_005_007_class_specific_budget_and_durable_backoff(
    database_url: str,
    session_factory: async_sessionmaker[AsyncSession],
    failure: FailureClass,
    exhausted: bool,
) -> None:
    profiles_seen: list[object] = []

    class FailingOnce(DeterministicAdapter):
        async def dispatch(
            self,
            identity: str,
            state: WorkflowStateV1,
            context: NodeContext,
            config: RunnableConfig,
        ) -> None:
            await super().dispatch(identity, state, context, config)
            profiles_seen.append(config["configurable"].get("runtime_model_profile_revision_id"))
            if self.dispatches == 1 or exhausted:
                self.results[identity] = {
                    "outcome": {"status": "failed", "failure_class": failure.value}
                }

    defaults, revisions = external_defaults()
    retry = resolved_revision(
        RetryRegistrySpec(
            rules=(
                RetryRule(
                    failure_class=failure,
                    max_retries=1,
                    initial_delay_ms=(
                        5000
                        if failure is FailureClass.CODE_TEST_FAILURE and not exhausted
                        else 1000
                    ),
                    exhaustion_action="block",
                    allow_failover=failure.value.startswith("provider."),
                ),
            )
        )
    )
    defaults = defaults.model_copy(update={"retry_policy_ref": retry.revision_id})
    revisions = (*(rev for rev in revisions if rev.spec.kind != "retry_policy"), retry)
    if failure.value.startswith("provider."):
        provider = resolved_revision(ProviderSpec(provider_kind="demo"))
        profiles = tuple(
            resolved_revision(
                ModelProfileSpec(
                    provider_revision_id=provider.revision_id,
                    model_identifier=f"fake-{number}",
                    purposes=("developer",),
                    capabilities=("chat",),
                    context_limit=4096,
                    output_limit=512,
                )
            )
            for number in range(2)
        )
        route = resolved_revision(
            RoutePolicySpec(
                candidates=tuple(
                    RouteCandidate(profile_revision_id=profile.revision_id, priority=number)
                    for number, profile in enumerate(profiles)
                ),
                purposes=("developer",),
                allow_unknown_health=True,
                failover_classes=(failure,),
            )
        )
        defaults = defaults.model_copy(
            update={"model_route_ref": route.revision_id, "timeout_seconds": 30}
        )
        revisions = (*revisions, provider, *profiles, route)
    spec = spec_for(
        (
            node("work", "worker"),
            node("finish", "finalize", config={"outcome": "blocked"}),
            node("done", "finalize"),
        ),
        (
            edge("work", "work", kind="retry", retry_class=failure.value, priority=0),
            edge(
                "work",
                "done",
                kind="on_result",
                priority=1,
                when={"path": "$.outcome.status", "op": "eq", "value": "completed"},
            ),
            edge("work", "finish", kind="on_result", fallback=True, priority=2),
        ),
        defaults=defaults,
    )
    run_id = await prepare_run(session_factory, spec, snapshot_for(spec, *revisions))
    owner, fence = await acquire(session_factory, run_id)
    adapter = FailingOnce()
    if failure is FailureClass.CODE_TEST_FAILURE and not exhausted:

        def crash(point: str) -> None:
            if point == "during_retry_scheduling":
                raise InjectedCrash()

        owner.fault = crash
        with pytest.raises(InjectedCrash):
            await OrchestratorService(database_url, owner, adapters={"work": adapter})._execute(
                fence
            )
        await owner.release(fence)
        owner, fence = await acquire(session_factory, run_id)
    await OrchestratorService(database_url, owner, adapters={"work": adapter})._execute(fence)
    async with session_factory() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None and run.status == "queued"
        assert run.runtime_json["wait"]["kind"] == "backoff"
        deadline = run.claimable_at
        thread = run.langgraph_thread_id
    if failure is FailureClass.CODE_TEST_FAILURE and not exhausted:
        await enqueue(session_factory, run_id, RunCommandKind.PAUSE)
        paused_owner, paused_fence = await acquire(session_factory, run_id)
        await OrchestratorService(database_url, paused_owner, adapters={"work": adapter})._execute(
            paused_fence
        )
        async with session_factory() as session:
            paused = await session.get(RunModel, run_id)
            assert paused is not None and paused.status == "paused"
            assert paused.langgraph_thread_id == thread
            assert paused.runtime_json["retry_at"] == deadline.isoformat()
        assert adapter.dispatches == 1
        await enqueue(session_factory, run_id, RunCommandKind.RESUME)
        async with session_factory() as session:
            resumed = await session.get(RunModel, run_id)
            assert resumed is not None and resumed.status == "queued"
            assert resumed.claimable_at >= deadline
    await asyncio.sleep(max(0, (deadline - owner.clock.now()).total_seconds()))
    replacement, new_fence = await acquire(session_factory, run_id)
    await OrchestratorService(database_url, replacement, adapters={"work": adapter})._execute(
        new_fence
    )
    async with session_factory() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None and run.status == ("blocked" if exhausted else "completed")
        counters = (
            await session.scalars(
                select(RetryCounterModel).where(RetryCounterModel.run_id == run_id)
            )
        ).all()
        assert [(counter.failure_class, counter.consumed) for counter in counters] == [
            (failure.value, 1)
        ]
        events = (
            await session.scalars(select(EventModel.type).where(EventModel.run_id == run_id))
        ).all()
        assert events.count("failure.classified") == (2 if exhausted else 1)
        assert events.count("retry.budget_consumed") == 1
        assert events.count("retry.budget_exhausted") == (1 if exhausted else 0)
    assert adapter.dispatches == 2
    if failure.value.startswith("provider."):
        assert profiles_seen == [str(profile.revision_id) for profile in profiles]
