"""Durable real approvals: event-backed requests and same-thread interrupts."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid5

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis_contracts.approvals import ApprovalView
from jarvis_contracts.base import sha256_digest
from jarvis_contracts.workflow import WorkflowSpec
from jarvis_orchestrator.runtime.effects import EffectAdapter, EffectObservation
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership, lock_events
from jarvis_orchestrator.workflows.factories import NodeContext, NodeHandler
from jarvis_orchestrator.workflows.state import WorkflowStateV1
from jarvis_persistence.models import EventModel, IntegrationHeadModel, RunModel


async def expire_approvals(owner: RunOwnership) -> None:
    async with owner.sessions.begin() as session:
        await lock_events(session)
        waiting = (
            await session.scalars(
                select(RunModel)
                .where(
                    RunModel.mode == "real",
                    RunModel.status == "approval_required",
                )
                .order_by(RunModel.id)
                .limit(100)
                .with_for_update()
            )
        ).all()
        for run in waiting:
            wait = run.runtime_json.get("wait", {})
            if not isinstance(wait, dict) or wait.get("kind") != "approval":
                continue
            entries = dict(run.runtime_json.get("approvals", {}))
            value = entries.get(str(wait.get("id")))
            if value is None:
                continue
            try:
                approval = ApprovalView.model_validate(value)
                await validate_request_event(session, approval)
            except ValueError:
                # A corrupt projection must neither grant authority nor prevent
                # unrelated healthy waits from expiring on this service tick.
                run.status = "blocked"
                run.version += 1
                run.result_summary = "Approval projection requires reconciliation"
                await owner.event(session, run, "run.blocked", {"reason": "approval.invalid"})
                continue
            if (
                approval.decision == "pending"
                and approval.expires_at is not None
                and approval.expires_at <= owner.clock.now()
            ):
                await validate_request_event(session, approval)
                entries[str(approval.id)] = approval.model_copy(
                    update={
                        "decision": "expired",
                        "decided_at": owner.clock.now(),
                    }
                ).model_dump(mode="json")
                run.runtime_json = {**run.runtime_json, "approvals": entries}
                run.status, run.claimable_at = "queued", owner.clock.now()
                run.version += 1
                await owner.event(
                    session,
                    run,
                    "approval.expired",
                    {
                        "approval_id": str(approval.id),
                        "request_digest": approval.request_digest,
                    },
                )


async def parameters(
    session: AsyncSession,
    run: RunModel,
    action: str,
    target: str,
    state: WorkflowStateV1,
    target_configuration: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    heads = (
        await session.scalars(
            select(IntegrationHeadModel)
            .where(
                IntegrationHeadModel.run_id == run.id,
            )
            .order_by(IntegrationHeadModel.repository_id)
        )
    ).all()
    return {
        "run_id": str(run.id),
        "workflow_version_id": str(run.workflow_version_id),
        "config_snapshot_id": str(run.config_snapshot_id),
        "action_type": action,
        "target_node_id": target,
        "target_configuration": target_configuration,
        "current_task": state.get("tasks", {}).get("current_task"),
        "verification": state.get("verification", {}),
        "review": state.get("review", {}),
        "integration_heads": [
            {
                "repository_id": str(head.repository_id),
                "head_sha": head.head_sha,
                "branch": head.branch,
                "snapshot_artifact_id": str(head.snapshot_artifact_id),
            }
            for head in heads
        ],
    }


async def validate_request_event(session: AsyncSession, approval: ApprovalView) -> None:
    event = await session.scalar(
        select(EventModel).where(
            EventModel.run_id == approval.run_id,
            EventModel.type == "approval.requested",
            EventModel.data_json["approval_id"].astext == str(approval.id),
        )
    )
    if (
        event is None
        or event.data_json.get("request_digest") != approval.request_digest
        or sha256_digest(approval.parameters) != approval.request_digest
        or event.data_json.get("parameters") != approval.parameters
        or event.data_json.get("workflow_node_id") != approval.node_id
        or event.data_json.get("action_type") != approval.action_type
        or event.data_json.get("created_at") != approval.created_at.isoformat()
        or event.data_json.get("expires_at")
        != (approval.expires_at.isoformat() if approval.expires_at else None)
    ):
        raise ValueError("approval request differs from append-only authority")


def approval_handler(
    owner: RunOwnership,
    fence: RunFence,
    spec: WorkflowSpec,
    target_configuration: dict[str, JsonValue],
) -> NodeHandler:
    async def decide(
        state: WorkflowStateV1, context: NodeContext, config: RunnableConfig
    ) -> WorkflowStateV1:
        from jarvis_orchestrator.workflows.validation import effective_policy

        targets = []
        for node in spec.nodes:
            policy = effective_policy(spec, node).approval
            if policy is not None and policy.required_grant_from == context.node.id:
                targets.append(node)
        if len(targets) != 1:
            raise ValueError("approval must authorize exactly one protected workflow node")
        identifier = uuid5(fence.run_id, "approval:" + context.execution_id)
        action = str(context.node.config["action_type"])
        async with owner.fenced(fence) as (session, run):
            if run.mode != "real":
                raise ValueError("production approval refuses demo runs")
            current_parameters = await parameters(
                session, run, action, targets[0].id, state, target_configuration
            )
            approvals = dict(run.runtime_json.get("approvals", {}))
            if str(identifier) not in approvals:
                expiry = context.node.config.get("expires_in_seconds")
                approval = ApprovalView(
                    id=identifier,
                    run_id=run.id,
                    node_id=context.node.id,
                    action_type=action,
                    parameters=current_parameters,
                    request_digest=sha256_digest(current_parameters),
                    created_at=owner.clock.now(),
                    expires_at=owner.clock.now() + timedelta(seconds=int(str(expiry)))
                    if expiry
                    else None,
                )
                approvals[str(identifier)] = approval.model_dump(mode="json")
                await owner.event(
                    session,
                    run,
                    "approval.requested",
                    {
                        "approval_id": str(identifier),
                        "workflow_node_id": context.node.id,
                        "request_digest": approval.request_digest,
                        "action_type": action,
                        "parameters": current_parameters,
                        "created_at": approval.created_at.isoformat(),
                        "expires_at": approval.expires_at.isoformat()
                        if approval.expires_at
                        else None,
                    },
                )
            approval = ApprovalView.model_validate(approvals[str(identifier)])
            await validate_request_event(session, approval)
            if approval.request_digest != sha256_digest(current_parameters):
                raise ValueError("protected parameters changed while awaiting approval")
            wait: dict[str, JsonValue] = {"kind": "approval", "id": str(identifier)}
            run.runtime_json = {**run.runtime_json, "approvals": approvals, "wait": wait}
        value = interrupt(wait)
        if not isinstance(value, dict) or value != wait:
            raise ValueError("approval resume does not match the durable interrupt")
        async with owner.fenced(fence) as (session, run):
            approval = ApprovalView.model_validate(run.runtime_json["approvals"][str(identifier)])
            await validate_request_event(session, approval)
            decision = approval.decision
            if run.desired_state == "cancelled":
                decision = "cancelled"
            elif approval.expires_at is not None and approval.expires_at <= owner.clock.now():
                decision = "expired"
            if decision == "pending":
                raise ValueError("approval has no durable decision")
            run.runtime_json = {**run.runtime_json, "wait": None}
            await owner.event(
                session,
                run,
                "approval.resumed",
                {
                    "approval_id": str(identifier),
                    "decision": decision,
                    "request_digest": approval.request_digest,
                },
            )
            return {
                "approval": {
                    "id": str(identifier),
                    "decision": decision,
                    "action_type": action,
                    "granted_by": context.node.id,
                    "request_digest": approval.request_digest,
                },
                "outcome": {"status": "succeeded" if decision == "approved" else "cancelled"},
            }

    return decide


class ProtectedEffect:
    def __init__(
        self,
        adapter: EffectAdapter,
        owner: RunOwnership,
        fence: RunFence,
        target_configuration: dict[str, JsonValue],
    ) -> None:
        self.adapter, self.owner, self.fence = adapter, owner, fence
        self.target_configuration = target_configuration
        self.idempotent = adapter.idempotent

    async def inspect(self, identity: str) -> EffectObservation:
        return await self.adapter.inspect(identity)

    async def cancel(self, identity: str) -> None:
        await self.adapter.cancel(identity)

    async def dispatch(
        self, identity: str, state: WorkflowStateV1, context: NodeContext, config: RunnableConfig
    ) -> None:
        policy = context.policy.approval
        if policy is not None and policy.required_grant_from:
            if policy.action_type is None:
                raise ValueError("protected effect requires a typed approval action")
            async with self.owner.fenced(self.fence) as (session, run):
                channel = state.get("approval", {})
                stored = run.runtime_json.get("approvals", {}).get(str(channel.get("id")))
                if stored is None:
                    raise ValueError("protected effect has no production approval")
                approval = ApprovalView.model_validate(stored)
                await validate_request_event(session, approval)
                current = await parameters(
                    session,
                    run,
                    policy.action_type,
                    context.node.id,
                    state,
                    self.target_configuration,
                )
                if (
                    run.desired_state == "cancelled"
                    or approval.decision != "approved"
                    or approval.node_id != policy.required_grant_from
                    or approval.action_type != policy.action_type
                    or approval.request_digest != sha256_digest(current)
                    or (
                        approval.expires_at is not None
                        and approval.expires_at <= self.owner.clock.now()
                    )
                ):
                    raise ValueError("approval grant is stale, rejected, expired or changed")
                decision = await session.scalar(
                    select(EventModel.event_id).where(
                        EventModel.run_id == run.id,
                        EventModel.type == "approval.decided",
                        EventModel.data_json["approval_id"].astext == str(approval.id),
                        EventModel.data_json["decision"].astext == "approved",
                        EventModel.data_json["request_digest"].astext == approval.request_digest,
                    )
                )
                if decision is None:
                    raise ValueError("approval decision lacks append-only authorization")
        await self.adapter.dispatch(identity, state, context, config)
