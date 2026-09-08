"""Non-privileged demo decision. Never usable as a production authorization."""

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt
from pydantic import JsonValue

from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership
from jarvis_orchestrator.workflows.factories import NodeContext, NodeHandler
from jarvis_orchestrator.workflows.state import WorkflowStateV1


def demo_decision(ownership: RunOwnership, fence: RunFence) -> NodeHandler:
    async def decide(
        state: WorkflowStateV1,
        context: NodeContext,
        config: RunnableConfig,
    ) -> WorkflowStateV1:
        async with ownership.fenced(fence) as (session, run):
            if run.mode != "demo":
                raise ValueError("Demo decision cannot authorize a real run")
            decision = run.runtime_json.get("demo_decision")
            if decision is None:
                decision = {
                    "id": context.execution_id,
                    "node_id": context.node.id,
                    "decision": "pending",
                }
                run.runtime_json = {**run.runtime_json, "demo_decision": decision}
                await ownership.event(
                    session,
                    run,
                    "approval.requested",
                    {
                        "workflow_node_id": context.node.id,
                        "decision_id": context.execution_id,
                        "summary": "DEMO publication decision; no external side effect",
                    },
                )
            wait: dict[str, JsonValue] = {"kind": "demo_decision", "id": context.execution_id}
            run.runtime_json = {**run.runtime_json, "wait": wait}
        value = interrupt(wait)
        if not isinstance(value, dict) or value.get("id") != context.execution_id:
            raise ValueError("Demo decision does not match the checkpoint interrupt")
        async with ownership.fenced(fence) as (session, run):
            decision = run.runtime_json["demo_decision"]
            run.runtime_json = {**run.runtime_json, "wait": None}
            if run.desired_state == "cancelled":
                return {"outcome": {"status": "cancelled"}}
            if decision["decision"] not in {"approved", "rejected"}:
                raise ValueError("No durable demo decision")
            await ownership.event(
                session,
                run,
                "approval.resumed",
                {
                    "workflow_node_id": context.node.id,
                    "decision": decision["decision"],
                },
            )
            return {
                "approval": {
                    "decision": decision["decision"],
                    "action_type": context.node.config["action_type"],
                    "granted_by": context.node.id,
                },
                "outcome": {
                    "status": "succeeded" if decision["decision"] == "approved" else "cancelled"
                },
            }

    return decide
