"""Idempotent canonical demo configuration through M3/M4 service APIs."""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis_api.registry.service import RegistryService
from jarvis_api.workflows.service import WorkflowService
from jarvis_contracts.registry import RegistryWrite
from jarvis_contracts.workflow import WorkflowSpec
from jarvis_contracts.workflow_api import (
    WorkflowCommand,
    WorkflowCreateRequest,
    WorkflowDocument,
    WorkflowDraftWrite,
)


async def bootstrap_demo(
    factory: async_sessionmaker[AsyncSession],
    owner: UUID,
    *,
    namespace: str = "demo-m6",
) -> WorkflowDocument:
    registry = RegistryService(factory)
    refs: dict[str, str] = {}
    purposes = ["organizer", "architect", "reviewer"]
    definitions: list[tuple[str, dict[str, Any]]] = [
        ("provider", {"kind": "provider_connection", "provider_kind": "demo"}),
        ("worker", {"kind": "worker", "capabilities": ["code", "git", "tests"]}),
        (
            "retry",
            {
                "kind": "retry_policy",
                "rules": [
                    {
                        "failure_class": value,
                        "max_retries": 2,
                        "initial_delay_ms": 0,
                        "max_delay_ms": 0,
                        "jitter": "none",
                        "exhaustion_action": "fail",
                    }
                    for value in [
                        "code.test_failure",
                        "code.review_failure",
                        "infrastructure.worker_transport",
                        "provider.transient",
                    ]
                ],
            },
        ),
        (
            "permission",
            {
                "kind": "permission_policy",
                "allowed_capabilities": ["code", "git", "tests"],
                "git": "allow",
                "shell": "allow",
            },
        ),
        (
            "profile",
            {
                "kind": "model_profile",
                "model_identifier": "DEMO-fixture-v1",
                "purposes": purposes,
                "capabilities": ["chat", "structured_json"],
                "structured_json": True,
                "context_limit": 16384,
                "output_limit": 2048,
            },
        ),
        ("route", {"kind": "route_policy", "purposes": purposes, "allow_unknown_health": True}),
    ]
    for key, definition in definitions:
        if key == "profile":
            definition["provider_revision_id"] = refs["provider"]
        if key == "route":
            definition["candidates"] = [{"profile_revision_id": refs["profile"]}]
        body = RegistryWrite.model_validate(
            {
                "key": f"{namespace}-{key}",
                "display_name": f"DEMO {key}",
                "spec": definition,
                "idempotency_key": f"{namespace}-bootstrap-{key}-v1",
            }
        )
        record = await registry.write(
            body.spec.kind, body, actor_id=owner, correlation_id="demo-bootstrap"
        )
        refs[key] = str(record.revision_id)
    workflows = WorkflowService(factory, registry)
    doc = await workflows.create(
        WorkflowCreateRequest(
            key=f"{namespace}-canonical",
            name="DEMO · deterministic development",
            idempotency_key=f"{namespace}-workflow-create-v1",
        ),
        owner,
        "demo-bootstrap",
    )
    doc = await workflows.save(
        doc.template.id,
        WorkflowDraftWrite(
            expected_version=doc.template.version,
            idempotency_key=f"{namespace}-workflow-save-v1",
            spec=canonical_workflow(refs).model_copy(update={"key": f"{namespace}-canonical"}),
        ),
        owner,
        "demo-bootstrap",
    )
    return await workflows.publish(
        doc.template.id,
        WorkflowCommand(
            expected_version=doc.template.version,
            idempotency_key=f"{namespace}-workflow-publish-v1",
        ),
        owner,
        "demo-bootstrap",
    )


def canonical_workflow(refs: dict[str, str]) -> WorkflowSpec:
    nodes: list[dict[str, Any]] = []
    for identifier, kind in [
        ("organizer", "organizer"),
        ("architect", "architect"),
        ("dispatch", "task_dispatch"),
        ("developer", "worker"),
        ("verify", "verify"),
        ("reviewer", "reviewer"),
        ("integrate", "integrate"),
        ("final_verify", "verify"),
        ("final_review", "reviewer"),
        ("decision", "approval"),
        ("publish", "github_publish"),
        ("finish", "finalize"),
        ("failed", "finalize"),
        ("rejected", "finalize"),
    ]:
        policy: dict[str, Any] = {}
        config: dict[str, Any] = {}
        if kind in {"organizer", "architect", "reviewer"}:
            policy["model_route_ref"] = refs["route"]
        if kind == "architect":
            config["max_tasks"] = 2
        if kind in {"worker", "verify"}:
            policy["worker_selector"] = {"revision_id": refs["worker"]}
        if kind in {"worker", "verify"}:
            policy["verification"] = {"source": "task", "required": True}
        if kind == "github_publish":
            policy["approval"] = {
                "required_grant_from": "decision",
                "action_type": "github.push_and_pr",
            }
        if identifier in {"failed", "rejected"}:
            config["outcome"] = "failed" if identifier == "failed" else "cancelled"
        nodes.append(
            {
                "id": identifier,
                "type": kind,
                "label": f"DEMO {identifier}",
                "config": config,
                "policy": policy,
            }
        )
    edges: list[dict[str, Any]] = []

    def edge(source: str, target: str, **kwargs: Any) -> None:
        edges.append(
            {"id": f"e{len(edges)}", "from": source, "to": target, "kind": "always", **kwargs}
        )

    def checked(source: str, target: str, retry_target: str, failure: str) -> None:
        edge(source, retry_target, kind="retry", retry_class=failure, priority=0)
        edge(
            source,
            target,
            kind="on_result",
            priority=1,
            when={"path": "$.outcome.status", "op": "eq", "value": "succeeded"},
        )
        edge(source, "failed", kind="on_result", fallback=True, priority=2)

    checked("organizer", "architect", "organizer", "provider.transient")
    edge("architect", "dispatch")
    edge(
        "dispatch",
        "developer",
        kind="iterate",
        iteration_key="tasks",
        max_iterations=2,
        progress_path="$.tasks.terminal_count",
        priority=0,
        when={"path": "$.tasks.current_task", "op": "neq", "value": None},
    )
    edge("dispatch", "final_verify", kind="on_result", fallback=True, priority=1)
    checked("developer", "verify", "developer", "infrastructure.worker_transport")
    checked("verify", "reviewer", "developer", "code.test_failure")
    checked("reviewer", "integrate", "developer", "code.review_failure")
    edge("integrate", "dispatch")
    edge(
        "decision",
        "publish",
        kind="on_result",
        priority=0,
        when={"path": "$.approval.decision", "op": "eq", "value": "approved"},
    )
    edge("decision", "rejected", kind="on_result", fallback=True, priority=1)
    edge("final_verify", "final_review")
    edge("final_review", "decision")
    edge("publish", "finish")
    return WorkflowSpec.model_validate(
        {
            "key": "demo-m6-canonical",
            "name": "DEMO deterministic development",
            "entrypoint": "organizer",
            "defaults": {
                "retry_policy_ref": refs["retry"],
                "permission_policy_ref": refs["permission"],
                "timeout_seconds": 30,
            },
            "nodes": nodes,
            "edges": edges,
            "outputs": {"result_path": "$.final.status"},
        }
    )
