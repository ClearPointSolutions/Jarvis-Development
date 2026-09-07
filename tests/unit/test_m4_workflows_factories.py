from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from langchain_core.runnables import RunnableConfig
from pydantic import JsonValue
from tests.unit.test_m4_workflows_compiler import node, snapshot_for, spec_for

from jarvis_contracts.workflow import ApprovalPolicy, NodePolicy, VerificationPolicy
from jarvis_orchestrator.workflows import NodeContext, WorkflowInvariantError, WorkflowStateV1
from jarvis_orchestrator.workflows.factories import NODE_FACTORIES


async def factory_result(
    kind: str,
    state: WorkflowStateV1,
    update: WorkflowStateV1,
    *,
    policy: NodePolicy | None = None,
    config: dict[str, Any] | None = None,
) -> WorkflowStateV1:
    spec = spec_for((node("test", kind, config=config or {}),))
    context = NodeContext(spec.nodes[0], policy or NodePolicy(), snapshot_for(spec), "")

    async def handler(
        state: WorkflowStateV1, context: NodeContext, config: RunnableConfig
    ) -> WorkflowStateV1:
        return deepcopy(update)

    factory = NODE_FACTORIES[context.node.type]
    return await factory(context, handler)(state, {})


@pytest.mark.parametrize(
    "grant",
    [
        {},
        {"decision": "rejected", "action_type": "worker.execute", "granted_by": "approve"},
        {"decision": "approved", "action_type": "git.integrate", "granted_by": "approve"},
        {"decision": "approved", "action_type": "worker.execute", "granted_by": "other"},
    ],
)
async def test_protected_effect_requires_exact_typed_approved_grant(grant: dict[str, Any]) -> None:
    policy = NodePolicy(
        approval=ApprovalPolicy(required_grant_from="approve", action_type="worker.execute")
    )
    with pytest.raises(WorkflowInvariantError, match="matching approved grant"):
        await factory_result("worker", {"approval": grant}, {}, policy=policy)


async def test_worker_consumes_grant_and_invalidates_older_verification_and_review() -> None:
    policy = NodePolicy(
        verification=VerificationPolicy(),
        approval=ApprovalPolicy(required_grant_from="approve", action_type="worker.execute"),
    )
    output = await factory_result(
        "worker",
        {
            "approval": {
                "decision": "approved",
                "action_type": "worker.execute",
                "granted_by": "approve",
            },
            "verification": {"passed": True},
            "review": {"passed": True},
        },
        {},
        policy=policy,
    )
    assert output["approval"] == output["verification"] == output["review"] == {}
    assert output["_needs_verification"]


@pytest.mark.parametrize(
    "kind, state, error",
    [
        ("reviewer", {}, "verification"),
        ("github_publish", {"verification": {"passed": False}}, "verification"),
        ("github_publish", {"verification": {"passed": True}}, "review"),
        ("finalize", {"_needs_verification": True}, "bypass"),
    ],
)
async def test_failure_cannot_advance_to_protected_success(
    kind: str, state: WorkflowStateV1, error: str
) -> None:
    with pytest.raises(WorkflowInvariantError, match=error):
        await factory_result(kind, state, {})


@pytest.mark.parametrize("passed", [True, False])
async def test_verifier_records_actual_verification_state(passed: bool) -> None:
    output = await factory_result("verify", {}, {"verification": {"passed": passed}})
    assert output["_needs_verification"] is not passed


@pytest.mark.parametrize(
    "state, status",
    [
        ({"_needs_verification": True, "cancelled": True}, "cancelled"),
        (
            {"_needs_verification": True, "outcome": {"failure_class": "code.test_failure"}},
            "failed",
        ),
        ({"outcome": {"status": "succeeded"}}, "completed"),
        ({"outcome": {"status": "blocked"}}, "blocked"),
    ],
)
async def test_finalizer_preserves_classified_failure_and_cancellation(
    state: WorkflowStateV1, status: str
) -> None:
    assert (await factory_result("finalize", state, {}))["final"] == {"status": status}


async def test_finalizer_rejects_unclassified_outcome() -> None:
    with pytest.raises(WorkflowInvariantError, match="unknown classified"):
        await factory_result("finalize", {"outcome": {"status": "invented"}}, {})


@pytest.mark.parametrize(
    "tasks",
    [
        {"total_count": 3},
        {"total_count": 1, "items": {"a": {}, "b": {}, "c": {}}},
        {"total_count": 1, "items": {"a": {}, "b": {}}},
        {"items": []},
    ],
)
async def test_architect_cannot_underreport_or_exceed_task_bound(tasks: dict[str, Any]) -> None:
    with pytest.raises(WorkflowInvariantError, match="Architect"):
        await factory_result("architect", {}, {"tasks": tasks}, config={"max_tasks": 2})


async def test_architect_validates_matching_bounded_plan() -> None:
    result = await factory_result(
        "architect",
        {},
        {"tasks": {"total_count": 2, "items": {"a": {}, "b": {}}}},
        config={"max_tasks": 2},
    )
    assert result["tasks"]["total_count"] == 2


async def test_dispatch_orders_ready_tasks_and_requires_successful_dependencies() -> None:
    items: dict[str, JsonValue] = {
        "z-last": {"dependencies": ["done"]},
        "a-first": {"dependencies": ["done"]},
        "blocked": {"dependencies": ["failed"]},
        "done": {"status": "completed"},
        "failed": {"status": "failed"},
    }
    output = await factory_result("task_dispatch", {"tasks": {"items": items}}, {})
    assert output["tasks"]["current_task"] == "a-first"
    assert output["tasks"]["terminal_count"] == 2
    assert output["tasks"]["total_count"] == 5


@pytest.mark.parametrize("items", [{"bad": "scalar"}, {"bad": {"dependencies": ["missing"]}}])
async def test_dispatch_rejects_malformed_tasks(items: dict[str, Any]) -> None:
    with pytest.raises(WorkflowInvariantError, match="Task"):
        await factory_result("task_dispatch", {"tasks": {"items": items}}, {})


async def test_handler_cannot_forge_result_identity_or_parallel_scalar_state() -> None:
    with pytest.raises(WorkflowInvariantError, match="execution identity"):
        await factory_result("worker", {}, {"results": {"another-node": "forged"}})
    with pytest.raises(WorkflowInvariantError, match="only write reduced"):
        await factory_result(
            "worker", {"child_identity": "fan:1:child"}, {"outcome": {"status": "failed"}}
        )


async def test_join_cannot_accept_missing_child_completion() -> None:
    with pytest.raises(WorkflowInvariantError, match="incomplete child"):
        await factory_result(
            "join",
            {"counters": {"visit:main:fan": 1}, "expected_children": ["fan:1:left"]},
            {},
            config={"fanout_id": "fan"},
        )
