"""Adversarial publication validation and safe state-predicate acceptance."""

from copy import deepcopy
from typing import Any
from uuid import UUID

import pytest
from pydantic import JsonValue

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.registry import (
    ModelBinding,
    ModelProfileSpec,
    PermissionPolicySpec,
    ProviderSpec,
    RegistrySpec,
    RetryRegistrySpec,
    RouteCandidate,
    RoutePolicySpec,
    WorkerSpec,
)
from jarvis_contracts.workflow import Predicate, WorkflowSpec
from jarvis_contracts.workflow_api import WorkflowResolvedRevision, WorkflowResolvedSnapshot
from jarvis_orchestrator.workflows.predicates import evaluate_predicate, get_path
from jarvis_orchestrator.workflows.validation import (
    effective_policy,
    fanout_regions,
    normalize_workflow,
    validate_workflow,
)


def node(identifier: str, kind: str = "router", **values: Any) -> dict[str, Any]:
    return {"id": identifier, "type": kind, "label": identifier, "config": {}, **values}


def edge(source: str, target: str, **values: Any) -> dict[str, Any]:
    return {"id": f"{source}-{target}", "from": source, "to": target, "kind": "always", **values}


def workflow(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "key": "validation-fixture",
        "name": "Validation fixture",
        "entrypoint": nodes[0]["id"],
        "nodes": nodes,
        "edges": edges,
        "outputs": {"result_path": "$.final"},
    }


def codes(
    raw: WorkflowSpec | dict[str, Any], snapshot: WorkflowResolvedSnapshot | None = None
) -> set[str]:
    return {issue.code for issue in validate_workflow(raw, snapshot).issues}


def revision(number: int, spec: RegistrySpec, **values: Any) -> WorkflowResolvedRevision:
    envelope = {
        "revision_id": UUID(int=number),
        "configuration_id": UUID(int=number + 100),
        "key": f"registry-{number}",
        "revision": 1,
        "display_name": f"Registry {number}",
        "description": "",
        "enabled": True,
        "archived": False,
        "spec": spec,
        **values,
    }
    digest = sha256_digest(
        {
            "kind": spec.kind,
            "key": envelope["key"],
            "revision": envelope["revision"],
            "schema_version": "1.0",
            "spec": {
                "spec": spec.model_dump(mode="json"),
                **{
                    field: envelope[field]
                    for field in ("display_name", "description", "enabled", "archived")
                },
            },
        }
    )
    return WorkflowResolvedRevision.model_validate({**envelope, "content_hash": digest})


def snapshot(raw: dict[str, Any], *revisions: WorkflowResolvedRevision) -> WorkflowResolvedSnapshot:
    return WorkflowResolvedSnapshot(
        workflow_content_hash=normalize_workflow(WorkflowSpec.model_validate(raw)).content_hash,
        revisions=revisions,
    )


def defaults() -> dict[str, Any]:
    return {
        "timeout_seconds": 30,
        "retry_policy_ref": str(UUID(int=1)),
        "permission_policy_ref": str(UUID(int=2)),
        "worker_selector": {"revision_id": str(UUID(int=3)), "requires": ["code"]},
        "model_route_ref": str(UUID(int=4)),
    }


def registry() -> tuple[WorkflowResolvedRevision, ...]:
    return (
        revision(1, RetryRegistrySpec(rules=())),
        revision(
            2,
            PermissionPolicySpec(
                git="allow", shell="allow", allowed_capabilities=("code", "git", "tests")
            ),
        ),
        revision(3, WorkerSpec(capabilities=("code", "git", "tests"))),
        revision(
            4,
            RoutePolicySpec(
                candidates=(RouteCandidate(profile_revision_id=UUID(int=5)),),
                purposes=("organizer", "architect", "reviewer", "developer"),
            ),
        ),
        revision(
            5,
            ModelProfileSpec(
                provider_revision_id=UUID(int=6),
                model_identifier="fixture",
                purposes=("organizer", "architect", "reviewer", "developer"),
                context_limit=1000,
                output_limit=100,
            ),
        ),
        revision(6, ProviderSpec(provider_kind="demo")),
    )


def test_minimal_workflow_normalizes_and_hashes_identically() -> None:
    raw = workflow([node("finish", "finalize")], [])
    normalized = normalize_workflow(WorkflowSpec.model_validate(raw))
    assert normalized.nodes[0].config == {"outcome": "derive"}
    assert validate_workflow(raw).valid
    assert validate_workflow(raw).content_hash == normalized.content_hash
    assert validate_workflow(normalized, snapshot(raw)).valid
    assert normalize_workflow(normalized) == normalized


def test_effective_defaults_preserve_explicit_false_and_null_inherits() -> None:
    raw = workflow(
        [
            node(
                "finish",
                "finalize",
                policy={"accepts_runtime_instructions": False, "timeout_seconds": None},
            )
        ],
        [],
    )
    raw["defaults"] = {"timeout_seconds": 40, "accepts_runtime_instructions": True}
    spec = WorkflowSpec.model_validate(raw)
    policy = effective_policy(spec, spec.nodes[0])
    assert policy.timeout_seconds == 40
    assert policy.accepts_runtime_instructions is False


def test_policy_inheritance_is_materialized_before_hashing_and_survives_json() -> None:
    raw = workflow([node("finish", "finalize")], [])
    raw["defaults"] = {"timeout_seconds": 40, "accepts_runtime_instructions": True}
    spec = WorkflowSpec.model_validate(raw)
    normalized = normalize_workflow(spec)
    restored = WorkflowSpec.model_validate_json(normalized.model_dump_json())
    assert effective_policy(restored, restored.nodes[0]).accepts_runtime_instructions is True
    assert restored.content_hash == normalized.content_hash
    assert validate_workflow(spec).content_hash == validate_workflow(raw).content_hash
    assert validate_workflow(restored).content_hash == normalized.content_hash


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ({"spec_version": "1.0"}, "schema.unsupported_version"),
        ({"entrypoint": "unknown"}, "graph.entrypoint"),
        ({"entrypoint": []}, "graph.entrypoint"),
        ({"reducers": {"tasks": "merge_by_id"}}, "state.reducers"),
        ({"name": "x" * 161}, "schema.invalid"),
        ({"description": "x" * 2001}, "schema.invalid"),
        ({"secret_ref": "secret:test-reference"}, "schema.invalid"),
    ],
)
def test_raw_envelope_guards(mutation: dict[str, JsonValue], expected: str) -> None:
    raw = workflow([node("finish", "finalize")], [])
    raw.update(mutation)
    assert expected in codes(raw)


def test_duplicate_dangling_and_schema_issues_address_original_ids() -> None:
    raw = workflow(
        [node("start"), node("finish", "finalize"), node("start")],
        [edge("start", "finish"), edge("start", "finish"), edge("start", "missing")],
    )
    issues = validate_workflow(raw).issues
    assert any(
        issue.code == "graph.duplicate_node" and issue.node_id == "start" for issue in issues
    )
    assert any(
        issue.code == "graph.duplicate_edge" and issue.edge_id == "start-finish" for issue in issues
    )
    assert any(
        issue.code == "graph.dangling_edge" and issue.edge_id == "start-missing" for issue in issues
    )
    raw = workflow([node("finish", "finalize", node_version="2.0")], [])
    assert validate_workflow(raw).issues[0].node_id == "finish"


def test_type_specific_config_rejects_code_unknown_fields_and_limits() -> None:
    for config in ({"python": "print('never')"}, {"outcome": "success"}):
        raw = workflow([node("finish", "finalize", config=config)], [])
        issues = validate_workflow(raw).issues
        assert issues[0].code == "node.config" and issues[0].node_id == "finish"
    raw = workflow([node("plan", "architect", config={"max_tasks": 10001})], [])
    assert "node.config" in codes(raw)


def test_resources_reject_depth_size_count_and_nonfinite_without_crashing() -> None:
    raw = workflow([node("finish", "finalize")], [])
    nested: dict[str, Any] = {}
    cursor = nested
    for _ in range(25):
        cursor["nested"] = {}
        cursor = cursor["nested"]
    assert "resource.json_depth" in codes({**raw, "nested": nested})
    assert "resource.json_size" in codes({**raw, "name": "x" * 1_048_576})
    assert "resource.non_finite" in codes({**raw, "extra": float("nan")})
    many = [node(f"node-{number}", "finalize") for number in range(501)]
    assert "schema.invalid" in codes(workflow(many, []))


def test_reachability_terminal_and_unbounded_subcycle_cannot_hide_behind_retry() -> None:
    raw = workflow(
        [node("start"), node("left"), node("right"), node("finish", "finalize"), node("orphan")],
        [
            edge("start", "left"),
            edge("left", "right"),
            edge("right", "left"),
            edge("right", "finish", fallback=True, priority=2),
        ],
    )
    assert {"graph.unreachable", "graph.no_terminal", "graph.unbounded_cycle"} <= codes(raw)
    raw["edges"].append(
        edge("right", "start", kind="retry", retry_class="code.test_failure", priority=1)
    )
    assert "graph.unbounded_cycle" in codes(raw)
    assert "cycle.retry_bound" in codes(raw)


@pytest.mark.parametrize(
    ("edges", "expected"),
    [
        (
            [
                edge(
                    "start",
                    "finish",
                    kind="on_result",
                    when={"op": "eq", "path": "$.node.result", "value": True},
                )
            ],
            "routing.fallback",
        ),
        (
            [edge("start", "finish", kind="on_result"), edge("start", "fail", fallback=True)],
            "routing.condition",
        ),
        (
            [edge("start", "finish"), edge("start", "fail", fallback=True)],
            "routing.unconditional_overlap",
        ),
        (
            [
                edge("start", "finish", kind="on_failure"),
                edge("start", "fail", kind="on_failure"),
                edge("start", "end", fallback=True),
            ],
            "routing.priority",
        ),
        (
            [
                edge(
                    "start",
                    "finish",
                    kind="on_result",
                    fallback=True,
                    when={"op": "exists", "path": "$.node.result"},
                )
            ],
            "routing.fallback_condition",
        ),
    ],
)
def test_conditional_routes_have_deterministic_total_fallbacks(
    edges: list[dict[str, Any]], expected: str
) -> None:
    raw = workflow(
        [
            node("start"),
            node("finish", "finalize"),
            node("fail", "finalize"),
            node("end", "finalize"),
        ],
        edges,
    )
    assert expected in codes(raw)


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ({"op": "eq", "path": "$.environment.password", "value": "x"}, "predicate.path"),
        ({"op": "eval", "path": "$.node.result"}, "schema.invalid"),
        ({"op": "eq", "path": "__import__('os')", "value": "x"}, "schema.invalid"),
        (
            {"op": "in", "path": "$.node.result", "value": "unsafe substring membership"},
            "predicate.value",
        ),
        ({"op": "lt", "path": "$.node.result", "value": True}, "predicate.value"),
        ({"op": "not", "args": []}, "schema.invalid"),
    ],
)
def test_predicate_grammar_guards(condition: dict[str, Any], expected: str) -> None:
    raw = workflow(
        [node("start"), node("finish", "finalize")],
        [
            edge("start", "finish", kind="on_result", when=condition),
            edge("start", "finish", id="fallback", fallback=True),
        ],
    )
    assert expected in codes(raw)


def test_predicate_depth_is_bounded_independently_of_json_depth() -> None:
    condition: dict[str, Any] = {"op": "exists", "path": "$.node.result"}
    for _ in range(8):
        condition = {"op": "not", "args": [condition]}
    raw = workflow(
        [node("start"), node("finish", "finalize")],
        [
            edge("start", "finish", kind="on_result", when=condition),
            edge("start", "finish", id="fallback", fallback=True),
        ],
    )
    assert "predicate.limit" in codes(raw)


@pytest.mark.parametrize(
    ("condition", "state", "expected"),
    [
        ({"op": "eq", "path": "$.node.result", "value": True}, {"node": {"result": 1}}, False),
        ({"op": "neq", "path": "$.node.result", "value": False}, {}, False),
        ({"op": "exists", "path": "$.node.result"}, {"node": {"result": None}}, True),
        (
            {"op": "in", "path": "$.node.result", "value": [True, "ok"]},
            {"node": {"result": "ok"}},
            True,
        ),
        (
            {"op": "lt", "path": "$.tasks.terminal_count", "value": 2},
            {"tasks": {"terminal_count": 1}},
            True,
        ),
        (
            {"op": "lte", "path": "$.tasks.terminal_count", "value": 2},
            {"tasks": {"terminal_count": 2}},
            True,
        ),
        (
            {"op": "gt", "path": "$.tasks.terminal_count", "value": 2},
            {"tasks": {"terminal_count": 3}},
            True,
        ),
        (
            {"op": "gte", "path": "$.tasks.terminal_count", "value": 2},
            {"tasks": {"terminal_count": 2}},
            True,
        ),
        ({"op": "lt", "path": "$.node.result", "value": 2}, {"node": {"result": "1"}}, False),
    ],
)
def test_predicates_evaluate_json_types_and_missing_paths_safely(
    condition: dict[str, Any], state: dict[str, object], expected: bool
) -> None:
    assert evaluate_predicate(Predicate.model_validate(condition), state) is expected
    assert get_path(state, "$.environment") is None


def test_nested_boolean_predicate() -> None:
    condition = Predicate.model_validate(
        {
            "op": "and",
            "args": [
                {"op": "eq", "path": "$.cancelled", "value": False},
                {
                    "op": "or",
                    "args": [
                        {"op": "exists", "path": "$.node.result"},
                        {
                            "op": "not",
                            "args": [{"op": "eq", "path": "$.outcome.status", "value": "failed"}],
                        },
                    ],
                },
            ],
        }
    )
    assert evaluate_predicate(condition, {"cancelled": False, "outcome": {"status": "succeeded"}})


def test_policy_presence_and_typed_immutable_snapshot_dependencies() -> None:
    raw = workflow(
        [node("organize", "organizer"), node("finish", "finalize")], [edge("organize", "finish")]
    )
    assert "policy.required" in codes(raw)
    raw["defaults"] = defaults()
    revisions = registry()
    assert validate_workflow(raw, snapshot(raw, *revisions)).valid
    assert "reference.invalid" in codes(raw, snapshot(raw))
    assert "reference.dependency" in codes(raw, snapshot(raw, *revisions[:-1]))
    corrupt = revisions[0].model_copy(update={"content_hash": "a" * 64})
    assert "snapshot.revision_hash" in codes(raw, snapshot(raw, corrupt, *revisions[1:]))
    assert "snapshot.duplicate_revision" in codes(raw, snapshot(raw, *revisions, revisions[0]))
    inactive = revision(3, WorkerSpec(capabilities=("code", "git", "tests")), archived=True)
    assert "reference.inactive" in codes(
        raw, snapshot(raw, revisions[0], revisions[1], inactive, *revisions[3:])
    )
    assert "snapshot.workflow_hash" in codes(
        raw, snapshot(raw, *revisions).model_copy(update={"workflow_content_hash": "b" * 64})
    )


def test_worker_capabilities_and_model_binding_are_validated() -> None:
    raw = workflow([node("work", "worker"), node("finish", "finalize")], [edge("work", "finish")])
    raw["defaults"] = defaults()
    revisions = registry()
    wrong = revision(3, WorkerSpec(capabilities=("code",)))
    assert "reference.worker_capabilities" in codes(
        raw, snapshot(raw, *revisions[:2], wrong, *revisions[3:])
    )
    denied = revision(2, PermissionPolicySpec(denied_capabilities=("git",)))
    assert "policy.capability_denied" in codes(
        raw, snapshot(raw, revisions[0], denied, *revisions[2:])
    )


def parallel() -> dict[str, Any]:
    return workflow(
        [
            node("fanout", "fanout", config={"children": ["left", "right"], "join_id": "join"}),
            node("left"),
            node("right"),
            node("join", "join"),
            node("finish", "finalize"),
        ],
        [
            edge("fanout", "left"),
            edge("fanout", "right"),
            edge("left", "join"),
            edge("right", "join"),
            edge("join", "finish"),
        ],
    )


def test_explicit_fanout_regions_are_disjoint_and_complete() -> None:
    raw = parallel()
    assert validate_workflow(raw).valid
    spec = normalize_workflow(WorkflowSpec.model_validate(raw))
    assert fanout_regions(spec) == {"fanout": {"left": {"left"}, "right": {"right"}}}


def test_fanout_rejects_children_join_escape_overlap_and_scalar_writes() -> None:
    raw = parallel()
    raw["nodes"][0]["config"]["children"] = ["left", "left"]
    assert {"fanout.children", "fanout.edges"} <= codes(raw)
    raw = parallel()
    raw["nodes"][3]["config"] = {"fanout_id": "unknown"}
    assert "fanout.join" in codes(raw)
    raw = parallel()
    raw["edges"][2] = edge("left", "finish")
    assert "fanout.escape" in codes(raw)
    raw = parallel()
    raw["edges"][2] = edge("left", "right")
    assert "fanout.overlap" in codes(raw)
    raw = parallel()
    raw["nodes"][1] = node("left", "verify", policy={"verification": {"required": True}})
    raw["defaults"] = defaults()
    assert "fanout.scalar_write" in codes(raw)


def test_fanout_rejects_cycles_reentry_external_entry_and_orphan_join() -> None:
    raw = parallel()
    raw["edges"].append(edge("left", "left", kind="retry", retry_class="code.test_failure"))
    assert "fanout.cycle" in codes(raw)
    raw = parallel()
    raw["edges"].append(edge("join", "fanout", kind="retry", retry_class="code.test_failure"))
    assert "fanout.reentry" in codes(raw)
    raw = parallel()
    raw["edges"].append(edge("right", "left"))
    assert "fanout.external_entry" in codes(raw)
    raw = workflow([node("join", "join"), node("finish", "finalize")], [edge("join", "finish")])
    assert "fanout.orphan_join" in codes(raw)


def test_iterator_requires_dispatch_monotonic_path_integrator_and_task_bound() -> None:
    raw = workflow(
        [
            node("plan", "architect", config={"max_tasks": 20}),
            node("dispatch", "task_dispatch"),
            node("work"),
            node("finish", "finalize"),
        ],
        [
            edge("plan", "dispatch"),
            edge(
                "dispatch",
                "work",
                kind="iterate",
                iteration_key="tasks",
                progress_path="$.tasks.terminal_count",
                max_iterations=10,
            ),
            edge("work", "dispatch"),
            edge("dispatch", "finish", fallback=True),
        ],
    )
    raw["defaults"] = defaults()
    assert {"cycle.task_bound", "cycle.nonprogressing"} <= codes(raw)
    raw["edges"][1]["progress_path"] = "$.tasks.total_count"
    assert "cycle.progress" in codes(raw)


def protected() -> dict[str, Any]:
    raw = workflow(
        [
            node("work", "worker", policy={"verification": {"required": True}}),
            node("verify", "verify", policy={"verification": {"required": True}}),
            node("review", "reviewer"),
            node("approve", "approval"),
            node(
                "publish",
                "github_publish",
                policy={
                    "approval": {
                        "action_type": "github.push_and_pr",
                        "required_grant_from": "approve",
                    }
                },
            ),
            node("finish", "finalize"),
        ],
        [
            edge("work", "verify"),
            edge("verify", "review"),
            edge("review", "approve"),
            edge("approve", "publish"),
            edge("publish", "finish"),
        ],
    )
    raw["defaults"] = defaults()
    return raw


def test_protected_paths_require_current_verification_review_and_named_approval() -> None:
    raw = protected()
    assert validate_workflow(raw, snapshot(raw, *registry())).valid
    bypass = deepcopy(raw)
    bypass["edges"][0] = edge("work", "publish")
    assert {
        "security.verification_bypass",
        "security.review_bypass",
        "security.approval_bypass",
    } <= codes(bypass)
    bypass = deepcopy(raw)
    bypass["nodes"].append(node("new-work", "worker", policy={"verification": {"required": True}}))
    bypass["edges"][3] = edge("approve", "new-work")
    bypass["edges"].append(edge("new-work", "publish"))
    assert {"security.verification_bypass", "security.review_bypass"} <= codes(bypass)
    wrong = deepcopy(raw)
    wrong["nodes"][3]["config"] = {"action_type": "worker.execute"}
    assert "policy.approval" in codes(wrong)


def test_required_worker_verification_cannot_bypass_final_success() -> None:
    raw = workflow(
        [
            node("work", "worker", policy={"verification": {"required": True}}),
            node("finish", "finalize"),
        ],
        [edge("work", "finish")],
    )
    raw["defaults"] = defaults()
    assert "security.verification_bypass" in codes(raw)
    raw["nodes"][1]["config"] = {"outcome": "failed"}
    assert validate_workflow(raw).valid


def test_retry_requires_positive_class_budget_and_matching_exhaustion() -> None:
    raw = workflow(
        [node("start"), node("finish", "finalize", config={"outcome": "blocked"})],
        [
            edge("start", "start", kind="retry", retry_class="code.test_failure"),
            edge("start", "finish", fallback=True),
        ],
    )
    raw["defaults"] = {"retry_policy_ref": str(UUID(int=1))}
    empty = revision(1, RetryRegistrySpec(rules=()))
    assert "cycle.retry_bound" in codes(raw, snapshot(raw, empty))
    retry = revision(
        1,
        RetryRegistrySpec.model_validate(
            {
                "rules": [
                    {
                        "failure_class": "code.test_failure",
                        "max_retries": 2,
                        "exhaustion_action": "block",
                    }
                ]
            }
        ),
    )
    assert validate_workflow(raw, snapshot(raw, retry)).valid
    raw["nodes"][1]["config"] = {"outcome": "failed"}
    assert "cycle.retry_exhaustion" in codes(raw, snapshot(raw, retry))


def test_route_purposes_are_subset_checked_and_require_node_purpose() -> None:
    raw = workflow(
        [node("organize", "organizer"), node("finish", "finalize")], [edge("organize", "finish")]
    )
    raw["defaults"] = defaults()
    revisions = registry()
    route = revision(
        4,
        RoutePolicySpec(
            candidates=(RouteCandidate(profile_revision_id=UUID(int=5)),),
            purposes=("utility", "organizer"),
        ),
    )
    assert "reference.model_capabilities" in codes(
        raw, snapshot(raw, *revisions[:3], route, *revisions[4:])
    )
    route = revision(
        4,
        RoutePolicySpec(
            candidates=(RouteCandidate(profile_revision_id=UUID(int=5)),), purposes=("developer",)
        ),
    )
    assert "reference.route_purpose" in codes(
        raw, snapshot(raw, *revisions[:3], route, *revisions[4:])
    )


def test_model_and_worker_policies_cannot_be_attached_to_router() -> None:
    raw = workflow(
        [
            node("route", policy={"worker_selector": {"revision_id": str(UUID(int=3))}}),
            node("finish", "finalize"),
        ],
        [edge("route", "finish")],
    )
    assert "policy.inapplicable" in codes(raw)
    raw["nodes"][0]["policy"] = {"model_route_ref": str(UUID(int=4))}
    assert "policy.inapplicable" in codes(raw)
    raw["nodes"][0].pop("policy")
    raw["defaults"] = defaults()
    normalized = normalize_workflow(WorkflowSpec.model_validate(raw))
    assert validate_workflow(normalized).valid
    assert all(
        item.policy.worker_selector is None and item.policy.model_route_ref is None
        for item in normalized.nodes
    )


@pytest.mark.parametrize(
    "permission",
    [
        PermissionPolicySpec(shell="allow", git="allow"),
        PermissionPolicySpec(
            allowed_capabilities=("code", "git", "tests"), git="deny", shell="allow"
        ),
        PermissionPolicySpec(
            allowed_capabilities=("code", "git", "tests"), git="allow", shell="deny"
        ),
    ],
)
def test_worker_permission_cannot_bypass_capability_or_operation_denial(
    permission: PermissionPolicySpec,
) -> None:
    raw = workflow([node("work", "worker"), node("finish", "finalize")], [edge("work", "finish")])
    raw["defaults"] = defaults()
    revisions = registry()
    altered = revision(2, permission)
    assert codes(raw, snapshot(raw, revisions[0], altered, *revisions[2:])) & {
        "policy.capability_denied",
        "policy.action_denied",
    }


def test_demo_model_exception_and_deterministic_verifier_on_modeled_worker() -> None:
    raw = workflow([node("work", "worker"), node("finish", "finalize")], [edge("work", "finish")])
    raw["defaults"] = defaults()
    raw["defaults"].pop("model_route_ref")
    revisions = registry()
    # DEMO explicitly supports deterministic non-model execution.
    assert validate_workflow(raw, snapshot(raw, *revisions)).valid
    worker = revision(
        3,
        WorkerSpec(
            capabilities=("code", "git", "tests"), model_binding=ModelBinding(mode="control_plane")
        ),
    )
    assert "policy.required" in codes(raw, snapshot(raw, *revisions[:2], worker, *revisions[3:]))
    raw["nodes"][0] = node("work", "verify", policy={"verification": {"required": True}})
    assert validate_workflow(raw, snapshot(raw, *revisions[:2], worker, *revisions[3:])).valid


def test_worker_model_route_respects_declared_binding() -> None:
    raw = workflow([node("work", "worker"), node("finish", "finalize")], [edge("work", "finish")])
    raw["defaults"] = defaults()
    revisions = registry()
    bound_profile = revision(7, revisions[4].spec)
    worker = revision(
        3,
        WorkerSpec(
            capabilities=("code", "git", "tests"),
            model_binding=ModelBinding(
                mode="worker_managed", allowed_profile_revision_ids=(bound_profile.revision_id,)
            ),
        ),
    )
    assert "reference.worker_model" in codes(
        raw, snapshot(raw, *revisions[:2], worker, *revisions[3:], bound_profile)
    )


def test_single_worker_execute_grant_does_not_require_second_verifier_grant() -> None:
    raw = workflow(
        [
            node("approve", "approval", config={"action_type": "worker.execute"}),
            node(
                "work",
                "worker",
                policy={
                    "approval": {"action_type": "worker.execute", "required_grant_from": "approve"},
                    "verification": {"required": True},
                },
            ),
            node("verify", "verify", policy={"verification": {"required": True}}),
            node("finish", "finalize"),
        ],
        [edge("approve", "work"), edge("work", "verify"), edge("verify", "finish")],
    )
    raw["defaults"] = defaults()
    revisions = registry()
    permission = revision(
        2,
        PermissionPolicySpec(
            allowed_capabilities=("code", "git", "tests"),
            shell="allow",
            git="allow",
            approval_required_actions=("worker.execute",),
        ),
    )
    assert validate_workflow(raw, snapshot(raw, revisions[0], permission, *revisions[2:])).valid


def test_approval_before_new_work_cannot_authorize_later_publication() -> None:
    raw = protected()
    raw["entrypoint"] = "approve"
    raw["edges"] = [
        edge("approve", "work"),
        edge("work", "verify"),
        edge("verify", "review"),
        edge("review", "publish"),
        edge("publish", "finish"),
    ]
    assert "security.stale_approval" in codes(raw)


@pytest.mark.parametrize(
    "failure_class",
    ["configuration.invalid", "security.policy_denied", "approval.rejected", "user.cancelled"],
)
def test_forbidden_retry_classes_cannot_be_enabled_by_injected_policy(failure_class: str) -> None:
    raw = workflow(
        [node("start"), node("finish", "finalize", config={"outcome": "blocked"})],
        [
            edge("start", "start", kind="retry", retry_class=failure_class),
            edge("start", "finish", fallback=True),
        ],
    )
    raw["defaults"] = {"retry_policy_ref": str(UUID(int=1))}
    retry = revision(
        1,
        RetryRegistrySpec.model_validate(
            {
                "rules": [
                    {"failure_class": failure_class, "max_retries": 2, "exhaustion_action": "block"}
                ]
            }
        ),
    )
    assert "cycle.nonretryable" in codes(raw, snapshot(raw, retry))


def test_unsupported_snapshot_compiler_is_explicitly_rejected() -> None:
    raw = workflow([node("finish", "finalize")], [])
    invalid = snapshot(raw).model_copy(update={"compiler_version": "2.0.0"})
    assert "snapshot.compiler_version" in codes(raw, invalid)


@pytest.mark.parametrize(
    "kind, fields",
    [
        ("retry", {"retry_class": "code.test_failure", "iteration_key": "ignored"}),
        ("retry", {"retry_class": "code.test_failure", "max_iterations": 3}),
        (
            "iterate",
            {
                "retry_class": "code.test_failure",
                "iteration_key": "tasks",
                "progress_path": "$.tasks.terminal_count",
                "max_iterations": 3,
            },
        ),
        (
            "on_failure",
            {"retry_class": "code.test_failure", "progress_path": "$.tasks.terminal_count"},
        ),
    ],
)
def test_edge_kinds_reject_fields_belonging_to_other_semantics(
    kind: str, fields: dict[str, Any]
) -> None:
    raw = workflow(
        [node("start", "task_dispatch"), node("finish", "finalize")],
        [edge("start", "finish", kind=kind, **fields)],
    )
    assert "routing.unused_bound" in codes(raw)


def test_fallback_cannot_hide_a_failure_class_condition() -> None:
    raw = workflow(
        [node("start"), node("finish", "finalize")],
        [
            edge(
                "start", "finish", kind="on_failure", retry_class="code.test_failure", fallback=True
            )
        ],
    )
    assert "routing.fallback_condition" in codes(raw)
