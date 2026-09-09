"""Real composition refuses configurations that cannot survive a real provider."""

from uuid import uuid4

import pytest
from tests.unit.test_m4_workflows_compiler import node, snapshot_for, spec_for

from jarvis_contracts.enums import FailureClass
from jarvis_contracts.failures import RetryRule
from jarvis_contracts.registry import RetryRegistrySpec
from jarvis_contracts.workflow import NodePolicy
from jarvis_contracts.workflow_api import WorkflowResolvedRevision
from jarvis_orchestrator.runtime.composition import (
    REQUIRED_MODEL_RETRY_CLASSES,
    require_provider_retry_rules,
)
from jarvis_orchestrator.runtime.errors import RuntimeDependencyError
from jarvis_orchestrator.workflows.factories import NodeContext


def context_for(policy: NodePolicy, revisions: tuple[WorkflowResolvedRevision, ...]) -> NodeContext:
    spec = spec_for((node("plan"),), ())
    snapshot = snapshot_for(spec).model_copy(update={"revisions": revisions})
    return NodeContext(spec.nodes[0], policy, snapshot, "preflight")


def retry_revision(rules: tuple[RetryRule, ...]) -> WorkflowResolvedRevision:
    """Build the resolved revision shape the runtime reads from the snapshot."""

    return WorkflowResolvedRevision(
        revision_id=uuid4(),
        configuration_id=uuid4(),
        key="retry",
        revision=1,
        display_name="Retry policy",
        spec=RetryRegistrySpec(rules=rules),
        content_hash="0" * 64,
    )


def rule(failure: FailureClass, retries: int = 2) -> RetryRule:
    return RetryRule(
        failure_class=failure,
        max_retries=retries,
        initial_delay_ms=0,
        max_delay_ms=0,
        exhaustion_action="fail",
    )


def test_model_node_without_a_retry_policy_is_refused() -> None:
    with pytest.raises(RuntimeDependencyError, match="no immutable retry policy"):
        require_provider_retry_rules(context_for(NodePolicy(), ()))


def test_missing_provider_retry_rules_are_named_before_the_run_starts() -> None:
    revision = retry_revision((rule(REQUIRED_MODEL_RETRY_CLASSES[0]),))
    policy = NodePolicy(retry_policy_ref=revision.revision_id)
    with pytest.raises(RuntimeDependencyError) as refusal:
        require_provider_retry_rules(context_for(policy, (revision,)))
    message = str(refusal.value)
    # The first class is covered; every other required class must be reported.
    assert REQUIRED_MODEL_RETRY_CLASSES[0].value not in message
    for failure in REQUIRED_MODEL_RETRY_CLASSES[1:]:
        assert failure.value in message


def test_a_zero_retry_rule_does_not_count_as_coverage() -> None:
    revision = retry_revision(tuple(rule(item, 0) for item in REQUIRED_MODEL_RETRY_CLASSES))
    policy = NodePolicy(retry_policy_ref=revision.revision_id)
    with pytest.raises(RuntimeDependencyError, match="real providers require"):
        require_provider_retry_rules(context_for(policy, (revision,)))


def test_complete_provider_retry_coverage_is_accepted() -> None:
    revision = retry_revision(tuple(rule(item) for item in REQUIRED_MODEL_RETRY_CLASSES))
    policy = NodePolicy(retry_policy_ref=revision.revision_id)
    require_provider_retry_rules(context_for(policy, (revision,)))
