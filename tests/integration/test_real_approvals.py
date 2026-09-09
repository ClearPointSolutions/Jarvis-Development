"""Production approval boundary, append-only authority and durable same-thread resume."""

from datetime import timedelta
from typing import Any

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis_contracts.approvals import ApprovalView
from jarvis_contracts.workflow import ApprovalPolicy, NodePolicy
from jarvis_orchestrator.runtime.approvals import (
    approval_handler,
    expire_approvals,
    validate_request_event,
)
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership
from jarvis_orchestrator.workflows.factories import NodeContext
from jarvis_orchestrator.workflows.state import WorkflowStateV1
from jarvis_persistence.checkpoints import postgres_saver
from jarvis_persistence.models import EventModel, JobModel, ProjectModel, RunModel
from tests.integration.test_m2_integrated_api import IntegratedApi, login
from tests.integration.test_m2_integrated_api import integrated_api as integrated_api
from tests.integration.test_m5_runtime import acquire, prepare_run
from tests.unit.test_m4_workflows_compiler import node, snapshot_for, spec_for

pytestmark = pytest.mark.integration


async def waiting(
    factory: async_sessionmaker[AsyncSession],
    api: IntegratedApi,
    database_url: str,
    *,
    expiry: int = 300,
) -> Any:
    spec = spec_for(
        (
            node(
                "approve",
                "approval",
                config={"action_type": "worker.execute", "expires_in_seconds": expiry},
            ),
            node(
                "work",
                "worker",
                policy=NodePolicy(
                    approval=ApprovalPolicy(
                        required_grant_from="approve", action_type="worker.execute"
                    )
                ),
            ),
        )
    )
    run_id = await prepare_run(factory)
    async with factory.begin() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None
        run.mode = "real"
        project = await session.scalar(
            select(ProjectModel).join(JobModel).join(RunModel).where(RunModel.id == run_id)
        )
        assert project is not None
        project.owner_user_id = api.owner_id
    owner, fence = await acquire(factory, run_id)
    context = NodeContext(spec.nodes[0], NodePolicy(), snapshot_for(spec), "approval-visit-1")

    def builder(
        active_owner: RunOwnership, active_fence: RunFence
    ) -> StateGraph[WorkflowStateV1, Any, Any, Any]:
        handler = approval_handler(active_owner, active_fence, spec, {"binding_digest": "a" * 64})

        async def request(state: WorkflowStateV1) -> WorkflowStateV1:
            return await handler(state, context, {})

        graph = StateGraph(WorkflowStateV1)
        graph.add_node("approve", request)
        graph.add_edge(START, "approve")
        graph.add_edge("approve", END)
        return graph

    config: RunnableConfig = {"configurable": {"thread_id": "production-approval-" + str(run_id)}}
    async with postgres_saver(database_url, setup=True) as saver:
        graph = builder(owner, fence).compile(checkpointer=saver)
        await graph.ainvoke({}, config)
        assert any(task.interrupts for task in (await graph.aget_state(config)).tasks)
    async with owner.fenced(fence) as (session, run):
        run.status = "approval_required"
        run.version += 1
        approval = ApprovalView.model_validate(next(iter(run.runtime_json["approvals"].values())))
        version = run.version
        await owner.release_in(session, fence)
    return run_id, approval, version, builder, config


@pytest.mark.parametrize("decision", ["approved", "rejected"])
async def test_real_decision_restart_same_thread_and_idempotency(
    integrated_api: IntegratedApi,
    session_factory: async_sessionmaker[AsyncSession],
    database_url: str,
    decision: str,
) -> None:
    api = integrated_api
    run_id, approval, version, builder, config = await waiting(session_factory, api, database_url)
    url = f"/api/v1/runs/{run_id}/approvals/{approval.id}/decisions"
    body = {
        "idempotency_key": "decision-1",
        "request_digest": approval.request_digest,
        "expected_run_version": version,
        "decision": decision,
    }
    assert (await api.client.post(url, json=body)).status_code == 401
    headers = {"x-csrf-token": (await login(api)).json()["csrf_token"]}
    assert (await api.client.post(url, json=body)).status_code == 403
    response = await api.client.post(url, headers=headers, json=body)
    assert response.status_code == 202, response.text
    assert (await api.client.post(url, headers=headers, json=body)).json() == response.json()
    assert (
        await api.client.post(
            url,
            headers=headers,
            json={**body, "decision": "rejected" if decision == "approved" else "approved"},
        )
    ).status_code == 409
    assert (
        await api.client.post(url, headers=headers, json={**body, "idempotency_key": "second"})
    ).status_code == 409
    owner, fence = await acquire(session_factory, run_id)
    async with postgres_saver(database_url) as saver:
        graph = builder(owner, fence).compile(checkpointer=saver)
        result = await graph.ainvoke(
            Command(resume={"kind": "approval", "id": str(approval.id)}), config
        )
        assert result["approval"]["decision"] == decision
        assert result["outcome"]["status"] == (
            "succeeded" if decision == "approved" else "cancelled"
        )
    async with session_factory() as session:
        events = (
            await session.scalars(select(EventModel).where(EventModel.run_id == run_id))
        ).all()
        assert sum(event.type == "approval.requested" for event in events) == 1
        assert sum(event.type == "approval.decided" for event in events) == 1
        assert sum(event.type == "approval.resumed" for event in events) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("node_id", "forged"),
        ("action_type", "github.push_and_pr"),
        ("expires_at", None),
        ("parameters", {"forged": True}),
    ],
)
async def test_request_projection_tampering_rejected(
    integrated_api: IntegratedApi,
    session_factory: async_sessionmaker[AsyncSession],
    database_url: str,
    field: str,
    value: Any,
) -> None:
    run_id, approval, version, _, _ = await waiting(session_factory, integrated_api, database_url)
    changed = approval.model_copy(update={field: value})
    async with session_factory.begin() as session:
        with pytest.raises(ValueError, match="append-only"):
            await validate_request_event(session, changed)
        run = await session.get(RunModel, run_id)
        assert run is not None
        run.runtime_json = {
            **run.runtime_json,
            "approvals": {str(approval.id): changed.model_dump(mode="json")},
        }
    headers = {"x-csrf-token": (await login(integrated_api)).json()["csrf_token"]}
    response = await integrated_api.client.post(
        f"/api/v1/runs/{run_id}/approvals/{approval.id}/decisions",
        headers=headers,
        json={
            "idempotency_key": "tampered",
            "expected_run_version": version,
            "request_digest": approval.request_digest,
            "decision": "approved",
        },
    )
    assert response.status_code == 409, response.text


async def test_expired_wait_is_durably_queued_for_denied_resume(
    integrated_api: IntegratedApi,
    session_factory: async_sessionmaker[AsyncSession],
    database_url: str,
) -> None:
    from jarvis_orchestrator.runtime.ownership import RunOwnership
    from jarvis_persistence.testing import FrozenClock

    run_id, approval, _, _, _ = await waiting(session_factory, integrated_api, database_url)
    owner = RunOwnership(
        session_factory,
        owner="expiry-test",
        clock=FrozenClock(approval.expires_at + timedelta(seconds=1)),
    )
    await expire_approvals(owner)
    async with session_factory() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None and run.status == "queued"
        assert run.runtime_json["approvals"][str(approval.id)]["decision"] == "expired"
