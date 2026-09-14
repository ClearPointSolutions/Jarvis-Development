"""An escaped worker/provider boundary keeps its retry class through the service.

Regression for the M12A/B known gap: a ``WorkerBoundaryError`` that escapes the
worker adapter used to lose its declared ``failure_class`` in ``nodes.py`` and
hard-block with ``orchestration.runtime_error`` even when it declared a
retryable class. It must now drive class-specific retry policy, while a
non-retryable class (configuration/security) still blocks and native text never
reaches the operator-visible failure record.
"""

from __future__ import annotations

import pytest
from langchain_core.runnables import RunnableConfig
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis_contracts.enums import FailureClass
from jarvis_contracts.failures import RetryRule
from jarvis_contracts.registry import RetryRegistrySpec
from jarvis_orchestrator.runtime.nodes import RuntimeBlockedError
from jarvis_orchestrator.runtime.service import OrchestratorService
from jarvis_orchestrator.workers.safety import WorkerBoundaryError
from jarvis_orchestrator.workflows.factories import NodeContext
from jarvis_orchestrator.workflows.state import WorkflowStateV1
from jarvis_persistence.models import EventModel, FailureModel, RetryCounterModel, RunModel
from tests.integration.test_m5_effects import DeterministicAdapter
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


class RaiseBoundaryOnce(DeterministicAdapter):
    """Raise a boundary error on the first dispatch, then succeed."""

    def __init__(self, code: str, failure_class: FailureClass) -> None:
        super().__init__()
        self._code = code
        self._failure_class = failure_class

    async def dispatch(
        self,
        identity: str,
        state: WorkflowStateV1,
        context: NodeContext,
        config: RunnableConfig,
    ) -> None:
        self.dispatches += 1
        if self.dispatches == 1:
            raise WorkerBoundaryError(self._code, self._failure_class)
        self.results[identity] = {
            "outcome": {"status": "completed"},
            "results": {context.execution_id: {"status": "succeeded"}},
        }


def _timeout_retry_spec() -> tuple[object, object]:
    defaults, revisions = external_defaults()
    retry = resolved_revision(
        RetryRegistrySpec(
            rules=(
                RetryRule(
                    failure_class=FailureClass.INFRASTRUCTURE_TIMEOUT,
                    max_retries=1,
                    exhaustion_action="fail",
                ),
            )
        )
    )
    defaults = defaults.model_copy(update={"retry_policy_ref": retry.revision_id})
    revisions = (*(rev for rev in revisions if rev.spec.kind != "retry_policy"), retry)
    spec = spec_for(
        (
            node("work", "worker"),
            node("done", "finalize"),
            node("failed", "finalize", config={"outcome": "failed"}),
        ),
        (
            edge(
                "work",
                "work",
                kind="retry",
                retry_class=FailureClass.INFRASTRUCTURE_TIMEOUT.value,
                priority=0,
            ),
            edge(
                "work",
                "done",
                kind="on_result",
                priority=1,
                when={"path": "$.outcome.status", "op": "eq", "value": "completed"},
            ),
            edge("work", "failed", kind="on_result", fallback=True, priority=2),
        ),
        defaults=defaults,
    )
    return spec, snapshot_for(spec, *revisions)


async def test_escaped_timeout_boundary_is_retried_not_blocked(
    database_url: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    spec, snapshot = _timeout_retry_spec()
    run_id = await prepare_run(session_factory, spec, snapshot)  # type: ignore[arg-type]
    owner, fence = await acquire(session_factory, run_id)
    adapter = RaiseBoundaryOnce("invocation_deadline", FailureClass.INFRASTRUCTURE_TIMEOUT)

    await OrchestratorService(database_url, owner, adapters={"work": adapter})._execute(fence)

    async with session_factory() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None and run.status == "completed"
        assert adapter.dispatches == 2
        failures = (
            await session.scalars(select(FailureModel).where(FailureModel.run_id == run_id))
        ).all()
        assert [row.failure_class for row in failures] == ["infrastructure.timeout"]
        assert failures[0].retryable is True
        # Only the enum crossed the boundary; the failure record the operator
        # sees carries a server-owned summary, never the boundary's own text.
        assert failures[0].summary == "Node execution failed"
        events = (
            await session.scalars(select(EventModel.type).where(EventModel.run_id == run_id))
        ).all()
        assert events.count("failure.classified") == 1
        counters = (
            await session.scalars(
                select(RetryCounterModel).where(RetryCounterModel.run_id == run_id)
            )
        ).all()
        assert [(row.failure_class, row.consumed) for row in counters] == [
            ("infrastructure.timeout", 1)
        ]


async def test_escaped_configuration_boundary_still_hard_blocks(
    database_url: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    spec, snapshot = _timeout_retry_spec()
    run_id = await prepare_run(session_factory, spec, snapshot)  # type: ignore[arg-type]
    owner, fence = await acquire(session_factory, run_id)
    adapter = RaiseBoundaryOnce("wrapper_unconfigured", FailureClass.CONFIGURATION_INVALID)

    with pytest.raises(RuntimeBlockedError):
        await OrchestratorService(database_url, owner, adapters={"work": adapter})._execute(fence)

    async with session_factory() as session:
        failures = (
            await session.scalars(select(FailureModel).where(FailureModel.run_id == run_id))
        ).all()
        assert [row.failure_class for row in failures] == ["configuration.invalid"]
        assert failures[0].retryable is False
    assert adapter.dispatches == 1
