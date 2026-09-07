from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.commands import RunCommandRequest
from jarvis_contracts.configuration import ConfigurationRevision, RunConfigurationSnapshot
from jarvis_contracts.enums import (
    ConfigurationKind,
    EventCategory,
    EventMode,
    EventSeverity,
    EventVisibility,
    FailureClass,
    RunCommandKind,
)
from jarvis_contracts.events import EventScope, EventSource, NewEvent, NormalizedEvent
from jarvis_contracts.failures import FailureEvidence, classify_failure
from jarvis_contracts.generate import output_path, schema_bytes
from jarvis_contracts.ids import (
    ConfigurationId,
    ConfigurationRevisionId,
    EventId,
    ProjectId,
    RunId,
    RunSnapshotId,
    WorkflowVersionId,
    new_id,
)
from jarvis_contracts.workflow import (
    Predicate,
    PredicateOperator,
    WorkflowEdge,
    WorkflowEdgeKind,
    WorkflowNode,
    WorkflowNodeType,
    WorkflowOutputs,
    WorkflowSpec,
)

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def make_workflow() -> WorkflowSpec:
    return WorkflowSpec(
        key="test_workflow",
        name="Test workflow",
        entrypoint="start",
        nodes=(
            WorkflowNode(id="start", type=WorkflowNodeType.ORGANIZER, label="Start", config={}),
            WorkflowNode(id="finish", type=WorkflowNodeType.FINALIZE, label="Finish", config={}),
        ),
        edges=(
            WorkflowEdge(
                id="edge_1",
                **{"from": "start", "to": "finish"},
                kind=WorkflowEdgeKind.ALWAYS,
            ),
        ),
        outputs=WorkflowOutputs(result_path="$.final"),
    )


def make_event(**overrides: object) -> NormalizedEvent:
    values: dict[str, object] = {
        "event_id": new_id(EventId),
        "global_position": 1,
        "run_sequence": None,
        "occurred_at": NOW,
        "recorded_at": NOW,
        "category": EventCategory.SYSTEM,
        "type": "system.health_changed",
        "severity": EventSeverity.INFO,
        "message": "System is healthy",
        "mode": EventMode.DEMO,
        "visibility": EventVisibility.OWNER,
        "scope": EventScope(),
        "source": EventSource(kind="orchestrator", name="unit-test"),
        "correlation_id": "unit-test-correlation",
        "data": {"healthy": True},
        "artifact_refs": (),
    }
    values.update(overrides)
    return NormalizedEvent.model_validate(values)


def test_domain_ids_are_uuid7() -> None:
    identifier = new_id(ProjectId)
    assert identifier.version == 7


def test_workflow_spec_is_structurally_valid_and_hash_is_stable() -> None:
    workflow = make_workflow()
    reparsed = WorkflowSpec.model_validate_json(workflow.model_dump_json(by_alias=True))

    assert workflow.content_hash == reparsed.content_hash
    assert reparsed.edges[0].source == "start"


def test_workflow_rejects_dangling_edges_and_unbounded_iterators() -> None:
    with pytest.raises(ValidationError, match="unknown nodes"):
        WorkflowSpec(
            key="invalid",
            name="Invalid",
            entrypoint="start",
            nodes=(
                WorkflowNode(id="start", type=WorkflowNodeType.ORGANIZER, label="Start", config={}),
            ),
            edges=(
                WorkflowEdge(
                    id="edge",
                    **{"from": "start", "to": "missing"},
                    kind=WorkflowEdgeKind.ALWAYS,
                ),
            ),
            outputs=WorkflowOutputs(result_path="$.final"),
        )
    with pytest.raises(ValidationError, match="iterate edges require"):
        WorkflowEdge(
            id="loop",
            **{"from": "start", "to": "start"},
            kind=WorkflowEdgeKind.ITERATE,
        )


def test_predicate_contract_allows_only_declarative_shapes() -> None:
    leaf = Predicate(op=PredicateOperator.EQ, path="$.task.status", value="ready")
    logical = Predicate(op=PredicateOperator.NOT, args=(leaf,))
    assert logical.args == (leaf,)

    with pytest.raises(ValidationError, match="requires a path"):
        Predicate(op=PredicateOperator.EQ, value="ready")


def test_event_contract_requires_paired_run_order_and_enforces_size() -> None:
    run_id = new_id(RunId)
    event = make_event(scope=EventScope(run_id=run_id), run_sequence=1)
    assert event.scope.run_id == run_id

    with pytest.raises(ValidationError, match="present together"):
        make_event(scope=EventScope(run_id=run_id))
    with pytest.raises(ValidationError, match="64 KiB"):
        make_event(data={"oversized": "x" * 66_000})
    with pytest.raises(ValidationError, match="64 KiB"):
        NewEvent(
            occurred_at=NOW,
            category=EventCategory.SYSTEM,
            type="system.large_event",
            severity=EventSeverity.INFO,
            message="Oversized before persistence",
            mode=EventMode.DEMO,
            visibility=EventVisibility.OWNER,
            source=EventSource(kind="orchestrator", name="unit-test"),
            correlation_id="large-event",
            data={"oversized": "x" * 66_000},
        )


def test_failure_precedence_and_budget_semantics_are_deterministic() -> None:
    classified = classify_failure(
        FailureEvidence(
            security_policy_denied=True,
            verifier_failed=True,
            worker_transport_failed=True,
            code="denied",
        )
    )
    assert classified.failure_class is FailureClass.SECURITY_POLICY_DENIED
    assert not classified.retryable
    assert not classified.consumes_semantic_attempt

    transport = classify_failure(FailureEvidence(worker_transport_failed=True))
    assert transport.failure_class is FailureClass.INFRASTRUCTURE_WORKER_TRANSPORT
    assert not transport.consumes_semantic_attempt

    tests = classify_failure(FailureEvidence(verifier_failed=True))
    assert tests.failure_class is FailureClass.CODE_TEST_FAILURE
    assert tests.consumes_semantic_attempt


def test_command_digest_is_stable_and_excludes_idempotency_key() -> None:
    run_id = new_id(RunId)
    first = RunCommandRequest(
        run_id=run_id,
        kind=RunCommandKind.PAUSE,
        idempotency_key="client/request-001",
        payload={"reason": "operator"},
    )
    duplicate = first.model_copy(update={"idempotency_key": "client/request-002"})
    changed = first.model_copy(update={"payload": {"reason": "different"}})

    assert first.request_digest == duplicate.request_digest
    assert first.request_digest != changed.request_digest
    assert RunCommandKind.RETRY.value == "retry"


def test_immutable_revision_and_snapshot_verify_canonical_hashes() -> None:
    revision_payload = {
        "kind": ConfigurationKind.WORKER.value,
        "key": "worker_one",
        "revision": 1,
        "schema_version": "1.0",
        "spec": {"adapter": "demo"},
    }
    revision = ConfigurationRevision(
        id=new_id(ConfigurationRevisionId),
        configuration_id=new_id(ConfigurationId),
        kind=ConfigurationKind.WORKER,
        key="worker_one",
        revision=1,
        spec={"adapter": "demo"},
        content_hash=sha256_digest(revision_payload),
        created_at=NOW,
    )
    with pytest.raises(ValidationError, match="frozen"):
        revision.revision = 2  # type: ignore[misc]

    workflow_version_id = new_id(WorkflowVersionId)
    snapshot_payload = {
        "schema_version": "1.0",
        "workflow_version_id": str(workflow_version_id),
        "workflow_content_hash": "a" * 64,
        "resolved_revisions": [],
        "effective_spec": {"mode": "demo"},
    }
    snapshot = RunConfigurationSnapshot(
        id=new_id(RunSnapshotId),
        workflow_version_id=workflow_version_id,
        workflow_content_hash="a" * 64,
        resolved_revisions=(),
        effective_spec={"mode": "demo"},
        snapshot_hash=sha256_digest(snapshot_payload),
        created_at=NOW,
    )
    assert snapshot.snapshot_hash == sha256_digest(snapshot.hash_payload())


def test_generated_json_schema_is_current_and_contains_major_contracts() -> None:
    assert output_path().read_bytes() == schema_bytes()
    schema_text = schema_bytes().decode()
    assert '"NormalizedEvent"' in schema_text
    assert '"WorkflowSpec"' in schema_text
