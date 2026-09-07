"""Publication/compiler validation for the canonical workflow specification.

This module has no database, live registry, network or execution dependencies.
Publication supplies its transactionally resolved immutable registry snapshot.
"""

from __future__ import annotations

import json
import math
from collections import Counter, deque
from collections.abc import Iterable
from uuid import UUID

from pydantic import JsonValue, ValidationError

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.enums import FailureClass
from jarvis_contracts.registry import (
    ModelProfileSpec,
    PermissionPolicySpec,
    ProviderSpec,
    RetryRegistrySpec,
    RoutePolicySpec,
    WorkerSpec,
)
from jarvis_contracts.workflow import (
    COMPILER_VERSION,
    MAX_GRAPH_DEPTH,
    MAX_JSON_DEPTH,
    MAX_PREDICATE_COUNT,
    MAX_PREDICATE_DEPTH,
    MAX_WORKFLOW_BYTES,
    NodePolicy,
    Predicate,
    PredicateOperator,
    WorkflowEdge,
    WorkflowEdgeKind,
    WorkflowNode,
    WorkflowNodeType,
    WorkflowSpec,
    default_reducers,
)
from jarvis_contracts.workflow_api import (
    WorkflowIssue,
    WorkflowResolvedRevision,
    WorkflowResolvedSnapshot,
    WorkflowValidationReport,
)
from jarvis_contracts.workflow_nodes import NODE_DEFINITIONS
from jarvis_orchestrator.workflows.predicates import ALLOWED_PATHS

_BOUNDED = {WorkflowEdgeKind.RETRY, WorkflowEdgeKind.ITERATE}
_MODEL_NODES = {
    WorkflowNodeType.ORGANIZER,
    WorkflowNodeType.ARCHITECT,
    WorkflowNodeType.REVIEWER,
}
_WORKER_NODES = {WorkflowNodeType.WORKER, WorkflowNodeType.VERIFY}
_ACTION_TYPES = {
    WorkflowNodeType.WORKER: "worker.execute",
    WorkflowNodeType.INTEGRATE: "git.integrate",
    WorkflowNodeType.GITHUB_PUBLISH: "github.push_and_pr",
}


def effective_policy(spec: WorkflowSpec, node: WorkflowNode) -> NodePolicy:
    """Overlay explicitly supplied node policy values on workflow defaults."""
    values = spec.defaults.model_dump()
    if node.type not in _WORKER_NODES:
        values["worker_selector"] = None
    if node.type not in _MODEL_NODES | {WorkflowNodeType.WORKER}:
        values["model_route_ref"] = None
    if node.type not in _WORKER_NODES:
        values["verification"] = None
    if node.type not in _ACTION_TYPES:
        values["approval"] = None
    values.update(node.policy.model_dump(exclude_unset=True, exclude_none=True))
    return NodePolicy.model_validate(values)


def normalize_workflow(spec: WorkflowSpec) -> WorkflowSpec:
    """Materialize typed config and effective policy defaults before hashing.

    Inheritance must survive JSON persistence: Python's model_fields_set is
    transient and cannot become a hidden input to compilation identity.
    """
    return spec.model_copy(
        update={
            "nodes": tuple(
                node.model_copy(
                    update={
                        "config": NODE_DEFINITIONS[node.type]
                        .config_model.model_validate(node.config)
                        .model_dump(mode="json"),
                        "policy": effective_policy(spec, node),
                    }
                )
                for node in sorted(spec.nodes, key=lambda node: node.id)
            ),
            "edges": tuple(
                sorted(spec.edges, key=lambda edge: (edge.source, edge.priority, edge.id))
            ),
        }
    )


def _issue(
    code: str,
    message: str,
    *,
    node: str | None = None,
    edge: str | None = None,
    path: str | None = None,
) -> WorkflowIssue:
    return WorkflowIssue(code=code, message=message, node_id=node, edge_id=edge, path=path)


def _resource_issues(raw: dict[str, JsonValue]) -> list[WorkflowIssue]:
    pending: list[tuple[object, int]] = [(raw, 0)]
    count = 0
    while pending:
        value, depth = pending.pop()
        count += 1
        if depth > MAX_JSON_DEPTH or count > MAX_WORKFLOW_BYTES:
            return [
                _issue("resource.json_depth", "Workflow JSON nesting/complexity exceeds limits")
            ]
        if isinstance(value, dict):
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend((item, depth + 1) for item in value)
        elif isinstance(value, float) and not math.isfinite(value):
            return [_issue("resource.non_finite", "Workflow JSON must contain finite numbers")]
    try:
        size = len(json.dumps(raw, ensure_ascii=False, allow_nan=False).encode())
    except (TypeError, ValueError, RecursionError):
        return [_issue("schema.invalid_json", "Workflow must contain JSON data only")]
    if size > MAX_WORKFLOW_BYTES:
        return [_issue("resource.json_size", "Workflow JSON exceeds the 1 MiB limit")]
    return []


def _raw_references(raw: dict[str, JsonValue]) -> list[WorkflowIssue]:
    issues: list[WorkflowIssue] = []
    identifiers: dict[str, set[str]] = {}
    for collection, singular in (("nodes", "node"), ("edges", "edge")):
        members = raw.get(collection)
        seen: set[str] = set()
        identifiers[collection] = seen
        if not isinstance(members, list):
            continue
        for index, member in enumerate(members):
            if not isinstance(member, dict) or not isinstance(member.get("id"), str):
                continue
            member_id = str(member["id"])
            if member_id in seen:
                issues.append(
                    _issue(
                        f"graph.duplicate_{singular}",
                        f"Duplicate {singular} ID",
                        node=member_id if singular == "node" else None,
                        edge=member_id if singular == "edge" else None,
                        path=f"{collection}.{index}.id",
                    )
                )
            seen.add(member_id)
    entrypoint = raw.get("entrypoint")
    if not isinstance(entrypoint, str) or entrypoint not in identifiers["nodes"]:
        issues.append(
            _issue("graph.entrypoint", "Entrypoint must reference a node", path="entrypoint")
        )
    edges = raw.get("edges")
    if isinstance(edges, list):
        for index, member in enumerate(edges):
            if not isinstance(member, dict):
                continue
            for endpoint in ("from", "to"):
                value = member.get(endpoint)
                if not isinstance(value, str) or value not in identifiers["nodes"]:
                    issues.append(
                        _issue(
                            "graph.dangling_edge",
                            "Edge endpoint must reference a node",
                            edge=str(member.get("id", "")) or None,
                            path=f"edges.{index}.{endpoint}",
                        )
                    )
    return issues


def _schema_issues(exc: ValidationError, raw: dict[str, JsonValue]) -> list[WorkflowIssue]:
    issues = []
    for error in exc.errors(include_input=False, include_context=False, include_url=False):
        location = error["loc"]
        node_id = edge_id = None
        if len(location) > 1 and location[0] in {"nodes", "edges"}:
            items = raw.get(str(location[0]))
            index = location[1]
            if isinstance(items, list) and isinstance(index, int) and index < len(items):
                item = items[index]
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    if location[0] == "nodes":
                        node_id = str(item["id"])
                    else:
                        edge_id = str(item["id"])
        issues.append(
            _issue(
                "schema.invalid",
                f"Invalid workflow field ({error['type']})",
                node=node_id,
                edge=edge_id,
                path=".".join(map(str, location)) or "$",
            )
        )
    return issues


def _predicate_issues(predicate: Predicate, edge: WorkflowEdge) -> list[WorkflowIssue]:
    issues = []
    pending = [(predicate, 1)]
    count = 0
    while pending:
        current, depth = pending.pop()
        count += 1
        if depth > MAX_PREDICATE_DEPTH or count > MAX_PREDICATE_COUNT:
            issues.append(_issue("predicate.limit", "Predicate exceeds AST limits", edge=edge.id))
            break
        if current.path is not None and current.path not in ALLOWED_PATHS:
            issues.append(_issue("predicate.path", "Predicate path is not approved", edge=edge.id))
        if current.op is PredicateOperator.IN and (
            not isinstance(current.value, list) or len(current.value) > 64
        ):
            issues.append(
                _issue("predicate.value", "in requires at most 64 JSON values", edge=edge.id)
            )
        if current.op in {
            PredicateOperator.LT,
            PredicateOperator.LTE,
            PredicateOperator.GT,
            PredicateOperator.GTE,
        } and (not isinstance(current.value, (int, float)) or isinstance(current.value, bool)):
            issues.append(_issue("predicate.value", "Ordering requires a number", edge=edge.id))
        if current.args and current.value is not None:
            issues.append(
                _issue("predicate.value", "Logical predicates cannot contain values", edge=edge.id)
            )
        pending.extend((child, depth + 1) for child in current.args)
    return issues


def _reachable(start: str, adjacency: dict[str, list[str]], *, stop: str | None = None) -> set[str]:
    reached: set[str] = set()
    pending = [start]
    while pending:
        node = pending.pop()
        if node in reached or node == stop:
            continue
        reached.add(node)
        pending.extend(adjacency.get(node, ()))
    return reached


def _adjacency(edges: Iterable[WorkflowEdge]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for edge in edges:
        result.setdefault(edge.source, []).append(edge.target)
    return result


def fanout_regions(spec: WorkflowSpec) -> dict[str, dict[str, set[str]]]:
    """Return disjoint child regions for a workflow that passed validation."""
    adjacency = _adjacency(spec.edges)
    regions = {}
    for node in spec.nodes:
        if node.type is not WorkflowNodeType.FANOUT:
            continue
        children = node.config.get("children", [])
        assert isinstance(children, list)
        regions[node.id] = {
            str(child): _reachable(str(child), adjacency, stop=str(node.config["join_id"]))
            for child in children
        }
    return regions


def _acyclic_nodes(nodes: set[str], edges: Iterable[WorkflowEdge]) -> tuple[set[str], int]:
    adjacency = _adjacency(edges)
    indegree = Counter(target for targets in adjacency.values() for target in targets)
    pending = deque((node, 1) for node in nodes if indegree[node] == 0)
    visited: set[str] = set()
    depth = 0
    distances: dict[str, int] = {}
    while pending:
        node, level = pending.popleft()
        visited.add(node)
        depth = max(depth, level)
        for target in adjacency.get(node, ()):
            indegree[target] -= 1
            distances[target] = max(distances.get(target, 1), level + 1)
            if not indegree[target]:
                pending.append((target, distances[target]))
    return visited, depth


def _graph_issues(spec: WorkflowSpec) -> list[WorkflowIssue]:
    issues = []
    nodes = {node.id: node for node in spec.nodes}
    adjacency = _adjacency(spec.edges)
    reached = _reachable(spec.entrypoint, adjacency)
    reverse: dict[str, list[str]] = {}
    for edge in spec.edges:
        reverse.setdefault(edge.target, []).append(edge.source)
    terminal_reached: set[str] = set()
    for node in spec.nodes:
        if node.type is WorkflowNodeType.FINALIZE:
            terminal_reached.update(_reachable(node.id, reverse))
            if adjacency.get(node.id):
                issues.append(
                    _issue(
                        "graph.terminal_edges", "Finalize cannot have outgoing edges", node=node.id
                    )
                )
    for node in spec.nodes:
        if node.id not in reached:
            issues.append(_issue("graph.unreachable", "Node is unreachable", node=node.id))
        if node.id not in terminal_reached:
            issues.append(_issue("graph.no_terminal", "Node has no terminal path", node=node.id))
        outgoing = [edge for edge in spec.edges if edge.source == node.id]
        if node.type in {WorkflowNodeType.FANOUT, WorkflowNodeType.FINALIZE} or not outgoing:
            continue
        conditional = len(outgoing) > 1 or any(
            edge.kind is not WorkflowEdgeKind.ALWAYS for edge in outgoing
        )
        if conditional:
            fallbacks = [edge for edge in outgoing if edge.fallback]
            if len(fallbacks) != 1:
                issues.append(
                    _issue(
                        "routing.fallback",
                        "Conditional routes require exactly one fallback",
                        node=node.id,
                    )
                )
            priorities = [edge.priority for edge in outgoing if not edge.fallback]
            if len(set(priorities)) != len(priorities):
                issues.append(
                    _issue(
                        "routing.priority", "Conditional priorities must be distinct", node=node.id
                    )
                )
            for edge in outgoing:
                if edge.fallback and (
                    edge.when is not None or edge.kind in _BOUNDED or edge.retry_class is not None
                ):
                    issues.append(
                        _issue(
                            "routing.fallback_condition",
                            "Fallback cannot have a condition or bound",
                            edge=edge.id,
                        )
                    )
                elif not edge.fallback and edge.kind is WorkflowEdgeKind.ALWAYS:
                    issues.append(
                        _issue(
                            "routing.unconditional_overlap",
                            "An unconditional route must be the fallback",
                            edge=edge.id,
                        )
                    )
                elif (
                    not edge.fallback
                    and edge.kind is WorkflowEdgeKind.ON_RESULT
                    and edge.when is None
                ):
                    issues.append(
                        _issue(
                            "routing.condition", "Result route requires a predicate", edge=edge.id
                        )
                    )
    acyclic, depth = _acyclic_nodes(
        set(nodes), (edge for edge in spec.edges if edge.kind not in _BOUNDED)
    )
    for node_id in sorted(set(nodes) - acyclic):
        issues.append(
            _issue(
                "graph.unbounded_cycle", "Cycle has no bounded retry or iterator edge", node=node_id
            )
        )
    if depth > MAX_GRAPH_DEPTH:
        issues.append(_issue("resource.graph_depth", "Graph depth exceeds its limit"))
    iteration_keys: set[str] = set()
    for edge in spec.edges:
        if edge.when:
            issues.extend(_predicate_issues(edge.when, edge))
        if edge.kind is WorkflowEdgeKind.ITERATE:
            if (
                nodes[edge.source].type is not WorkflowNodeType.TASK_DISPATCH
                or edge.progress_path != "$.tasks.terminal_count"
            ):
                issues.append(
                    _issue(
                        "cycle.progress",
                        "Only task_dispatch can iterate strictly increasing task terminal_count",
                        edge=edge.id,
                    )
                )
            if edge.iteration_key in iteration_keys:
                issues.append(
                    _issue("cycle.iteration_key", "Iterator keys must be unique", edge=edge.id)
                )
            iteration_keys.add(edge.iteration_key or "")
            without_progress = _adjacency(
                item
                for item in spec.edges
                if nodes[item.source].type is not WorkflowNodeType.INTEGRATE
                and nodes[item.target].type is not WorkflowNodeType.INTEGRATE
            )
            if edge.source in _reachable(edge.target, without_progress):
                issues.append(
                    _issue(
                        "cycle.nonprogressing",
                        "Every task iteration cycle must integrate terminal task progress",
                        edge=edge.id,
                    )
                )
            for node in spec.nodes:
                if node.type is WorkflowNodeType.ARCHITECT and int(
                    str(node.config["max_tasks"])
                ) > (edge.max_iterations or 0):
                    issues.append(
                        _issue(
                            "cycle.task_bound",
                            "Architect task bound exceeds iterator bound",
                            node=node.id,
                            edge=edge.id,
                        )
                    )
        unused_iteration = edge.kind is not WorkflowEdgeKind.ITERATE and any(
            value is not None
            for value in (edge.iteration_key, edge.progress_path, edge.max_iterations)
        )
        unused_failure_class = (
            edge.kind not in {WorkflowEdgeKind.RETRY, WorkflowEdgeKind.ON_FAILURE}
            and edge.retry_class is not None
        )
        if unused_iteration or unused_failure_class:
            issues.append(
                _issue(
                    "routing.unused_bound",
                    "Bounds belong only to their declared edge kind",
                    edge=edge.id,
                )
            )
    return issues


def _fanout_issues(spec: WorkflowSpec) -> list[WorkflowIssue]:
    issues: list[WorkflowIssue] = []
    nodes = {node.id: node for node in spec.nodes}
    regions = fanout_regions(spec)
    adjacency = _adjacency(spec.edges)
    all_owned: set[str] = set()
    claimed_joins: set[str] = set()
    for fanout_id, children in regions.items():
        fanout = nodes[fanout_id]
        join_id = str(fanout.config["join_id"])
        declared = fanout.config["children"]
        assert isinstance(declared, list)
        if (
            not declared
            or len(declared) != len(set(map(str, declared)))
            or len(declared) > int(str(fanout.config["max_fanout"]))
        ):
            issues.append(
                _issue(
                    "fanout.children",
                    "Fanout needs unique children within its configured bound",
                    node=fanout_id,
                )
            )
        join = nodes.get(join_id)
        if (
            join is None
            or join.type is not WorkflowNodeType.JOIN
            or join.config["fanout_id"] != fanout_id
            or join_id in claimed_joins
        ):
            issues.append(
                _issue("fanout.join", "Fanout needs its own matching join", node=fanout_id)
            )
        claimed_joins.add(join_id)
        outgoing = [edge for edge in spec.edges if edge.source == fanout_id]
        if Counter(edge.target for edge in outgoing) != Counter(map(str, declared)) or any(
            edge.kind is not WorkflowEdgeKind.ALWAYS or edge.fallback for edge in outgoing
        ):
            issues.append(
                _issue(
                    "fanout.edges",
                    "Fanout edges must match all configured child entries",
                    node=fanout_id,
                )
            )
        owned: set[str] = set()
        for child, region in children.items():
            if child not in nodes or child == join_id:
                issues.append(
                    _issue(
                        "fanout.child", "Child must reference a distinct entry node", node=fanout_id
                    )
                )
                continue
            if owned & region or all_owned & region:
                issues.append(
                    _issue(
                        "fanout.overlap", "Parallel child regions cannot overlap", node=fanout_id
                    )
                )
            owned.update(region)
            branch_edges = [
                edge for edge in spec.edges if edge.source in region and edge.target in region
            ]
            acyclic, _ = _acyclic_nodes(region, branch_edges)
            if acyclic != region:
                issues.append(
                    _issue(
                        "fanout.cycle", "Parallel branches cannot contain cycles", node=fanout_id
                    )
                )
            for node_id in region:
                node = nodes[node_id]
                if node.type in {WorkflowNodeType.FANOUT, WorkflowNodeType.JOIN}:
                    issues.append(
                        _issue("fanout.nested", "Nested fanout/join is unsupported", node=node_id)
                    )
                if set(NODE_DEFINITIONS[node.type].outputs) - set(default_reducers()):
                    issues.append(
                        _issue(
                            "fanout.scalar_write",
                            "Parallel node writes an unreduced state channel",
                            node=node_id,
                        )
                    )
                policy = effective_policy(spec, node)
                if (
                    node.type is WorkflowNodeType.WORKER
                    and policy.verification
                    and policy.verification.required
                ):
                    issues.append(
                        _issue(
                            "fanout.verification",
                            "Parallel workers cannot require branch-local scalar verification",
                            node=node_id,
                        )
                    )
                if not adjacency.get(node_id) or any(
                    target not in region and target != join_id
                    for target in adjacency.get(node_id, ())
                ):
                    issues.append(
                        _issue(
                            "fanout.escape",
                            "Every branch route must reach its matching join",
                            node=node_id,
                        )
                    )
                for edge in spec.edges:
                    if (
                        edge.target == node_id
                        and edge.source not in region
                        and not (edge.source == fanout_id and node_id == child)
                    ):
                        issues.append(
                            _issue(
                                "fanout.external_entry",
                                "Parallel branches cannot have external incoming edges",
                                node=node_id,
                                edge=edge.id,
                            )
                        )
            if fanout_id in _reachable(join_id, adjacency):
                issues.append(
                    _issue(
                        "fanout.reentry",
                        "Fanout activations cannot overlap through a cycle",
                        node=fanout_id,
                    )
                )
        for edge in spec.edges:
            if edge.target == join_id and edge.source not in owned:
                issues.append(
                    _issue(
                        "fanout.join_entry",
                        "Join can receive only its own branch completions",
                        edge=edge.id,
                    )
                )
        all_owned.update(owned)
    for node in spec.nodes:
        if node.type is WorkflowNodeType.JOIN and node.id not in claimed_joins:
            issues.append(
                _issue("fanout.orphan_join", "Join must have a matching fanout", node=node.id)
            )
    return issues


def _revision_dependencies(revision: WorkflowResolvedRevision) -> list[tuple[UUID, str]]:
    spec = revision.spec
    if isinstance(spec, RoutePolicySpec):
        return [(candidate.profile_revision_id, "model_profile") for candidate in spec.candidates]
    if isinstance(spec, ModelProfileSpec):
        return [(spec.provider_revision_id, "provider_connection")]
    if isinstance(spec, WorkerSpec):
        return [
            (revision_id, "model_profile")
            for revision_id in spec.model_binding.allowed_profile_revision_ids
        ]
    if isinstance(spec, ProviderSpec) and spec.retry_policy_revision_id:
        return [(spec.retry_policy_revision_id, "retry_policy")]
    return []


def _snapshot_issues(spec: WorkflowSpec, snapshot: WorkflowResolvedSnapshot) -> list[WorkflowIssue]:
    issues: list[WorkflowIssue] = []
    if snapshot.compiler_version != COMPILER_VERSION:
        issues.append(
            _issue("snapshot.compiler_version", "Snapshot compiler version is unsupported")
        )
    if snapshot.workflow_content_hash != spec.content_hash:
        issues.append(
            _issue("snapshot.workflow_hash", "Snapshot does not match normalized workflow hash")
        )
    revisions = {revision.revision_id: revision for revision in snapshot.revisions}
    if len(revisions) != len(snapshot.revisions):
        issues.append(_issue("snapshot.duplicate_revision", "Snapshot revision IDs must be unique"))
    for revision in snapshot.revisions:
        digest = sha256_digest(
            {
                "kind": revision.spec.kind,
                "key": revision.key,
                "revision": revision.revision,
                "schema_version": "1.0",
                "spec": {
                    "spec": revision.spec.model_dump(mode="json"),
                    "display_name": revision.display_name,
                    "description": revision.description,
                    "enabled": revision.enabled,
                    "archived": revision.archived,
                },
            }
        )
        if revision.content_hash != digest:
            issues.append(
                _issue("snapshot.revision_hash", "Snapshot configuration content hash is invalid")
            )
        if not revision.enabled or revision.archived:
            issues.append(
                _issue("reference.inactive", "Snapshot contains an inactive configuration revision")
            )
        for revision_id, kind in _revision_dependencies(revision):
            dependency = revisions.get(revision_id)
            if dependency is None or dependency.spec.kind != kind:
                issues.append(
                    _issue(
                        "reference.dependency",
                        "Snapshot dependency is missing or has an incompatible type",
                    )
                )
        if isinstance(revision.spec, RoutePolicySpec):
            for candidate in revision.spec.candidates:
                profile = revisions.get(candidate.profile_revision_id)
                if (
                    profile
                    and isinstance(profile.spec, ModelProfileSpec)
                    and (
                        set(revision.spec.required_capabilities)
                        - (
                            set(profile.spec.capabilities)
                            | {
                                capability
                                for capability in ("structured_json", "tool_calls", "streaming")
                                if getattr(profile.spec, capability)
                            }
                        )
                        or not set(revision.spec.purposes) <= set(profile.spec.purposes)
                    )
                ):
                    issues.append(
                        _issue(
                            "reference.model_capabilities",
                            "Route candidate has incompatible capabilities or purposes",
                        )
                    )
        if isinstance(revision.spec, ModelProfileSpec):
            provider = revisions.get(revision.spec.provider_revision_id)
            if provider and isinstance(provider.spec, ProviderSpec):
                allowed_parameters = {
                    "openai": {"temperature", "top_p", "reasoning_effort"},
                    "ollama": {"temperature", "top_p", "seed", "keep_alive"},
                    "demo": {"temperature", "top_p", "reasoning_effort", "seed", "keep_alive"},
                }
                if (
                    revision.spec.locality != provider.spec.locality
                    or set(revision.spec.parameters)
                    - allowed_parameters[provider.spec.provider_kind]
                ):
                    issues.append(
                        _issue(
                            "reference.provider_compatibility",
                            "Profile is incompatible with provider locality or parameters",
                        )
                    )
    return issues


def _policy_issues(
    spec: WorkflowSpec, snapshot: WorkflowResolvedSnapshot | None
) -> list[WorkflowIssue]:
    issues: list[WorkflowIssue] = []
    revisions = (
        {revision.revision_id: revision for revision in snapshot.revisions} if snapshot else {}
    )
    nodes = {node.id: node for node in spec.nodes}
    for node in spec.nodes:
        policy = effective_policy(spec, node)
        definition = NODE_DEFINITIONS[node.type]
        if node.policy.worker_selector is not None and node.type not in _WORKER_NODES:
            issues.append(
                _issue(
                    "policy.inapplicable",
                    "This node type cannot select a worker",
                    node=node.id,
                    path="policy.worker_selector",
                )
            )
        if node.policy.model_route_ref is not None and node.type not in _MODEL_NODES | {
            WorkflowNodeType.WORKER
        }:
            issues.append(
                _issue(
                    "policy.inapplicable",
                    "This node type cannot select a model route",
                    node=node.id,
                    path="policy.model_route_ref",
                )
            )
        required: list[str] = []
        if definition.external:
            required.extend(("timeout_seconds", "retry_policy_ref", "permission_policy_ref"))
        if node.type in _MODEL_NODES:
            required.append("model_route_ref")
        if node.type in _WORKER_NODES:
            required.append("worker_selector")
        for field in required:
            if getattr(policy, field) is None:
                issues.append(
                    _issue(
                        "policy.required",
                        f"Node requires an effective {field}",
                        node=node.id,
                        path=f"policy.{field}",
                    )
                )
        if node.type is WorkflowNodeType.VERIFY and (
            policy.verification is None or not policy.verification.required
        ):
            issues.append(
                _issue(
                    "policy.verification",
                    "Verify requires enabled task verification policy",
                    node=node.id,
                )
            )
        action = _ACTION_TYPES.get(node.type)
        permission = (
            revisions.get(policy.permission_policy_ref) if policy.permission_policy_ref else None
        )
        approval_required = node.type is WorkflowNodeType.GITHUB_PUBLISH
        if permission and isinstance(permission.spec, PermissionPolicySpec):
            permission_spec = permission.spec
            approval_required |= bool(
                action and action in permission_spec.approval_required_actions
            )
            required_caps = set(definition.capabilities) | set(
                policy.worker_selector.requires if policy.worker_selector else ()
            )
            if required_caps & set(permission_spec.denied_capabilities) or required_caps - set(
                permission_spec.allowed_capabilities
            ):
                issues.append(
                    _issue(
                        "policy.capability_denied",
                        "Permission policy does not allow required node capabilities",
                        node=node.id,
                    )
                )
            operation_decisions = []
            if node.type in {
                WorkflowNodeType.WORKER,
                WorkflowNodeType.INTEGRATE,
                WorkflowNodeType.GITHUB_PUBLISH,
            }:
                operation_decisions.append(permission_spec.git)
            if node.type in _WORKER_NODES:
                operation_decisions.append(permission_spec.shell)
            if operation_decisions:
                if "deny" in operation_decisions:
                    issues.append(
                        _issue(
                            "policy.action_denied",
                            "Permission policy denies a required shell or Git operation",
                            node=node.id,
                        )
                    )
                approval_required |= "require_approval" in operation_decisions
        approval = policy.approval
        if approval_required and (approval is None or not approval.required_grant_from):
            issues.append(
                _issue(
                    "policy.approval",
                    "Protected action requires a named approval grant",
                    node=node.id,
                )
            )
        if approval is not None:
            grant = nodes.get(approval.required_grant_from or "")
            if (
                not action
                or approval.action_type != action
                or grant is None
                or grant.type is not WorkflowNodeType.APPROVAL
                or grant.config["action_type"] != action
            ):
                issues.append(
                    _issue(
                        "policy.approval",
                        "Approval policy must name a matching typed granting node",
                        node=node.id,
                    )
                )
        refs: list[tuple[UUID | None, str, str]] = [
            (
                policy.worker_selector.revision_id if policy.worker_selector else None,
                "worker",
                "worker_selector",
            ),
            (policy.model_route_ref, "route_policy", "model_route_ref"),
            (policy.retry_policy_ref, "retry_policy", "retry_policy_ref"),
            (policy.permission_policy_ref, "permission_policy", "permission_policy_ref"),
        ]
        if snapshot:
            for revision_id, kind, field in refs:
                if revision_id is None:
                    continue
                revision = revisions.get(revision_id)
                if revision is None or revision.spec.kind != kind:
                    issues.append(
                        _issue(
                            "reference.invalid",
                            f"{field} revision is missing or has an incompatible type",
                            node=node.id,
                            path=f"policy.{field}",
                        )
                    )
                elif not revision.enabled or revision.archived:
                    issues.append(
                        _issue(
                            "reference.inactive",
                            f"{field} revision is inactive",
                            node=node.id,
                            path=f"policy.{field}",
                        )
                    )
            worker = (
                revisions.get(policy.worker_selector.revision_id)
                if policy.worker_selector
                else None
            )
            route = revisions.get(policy.model_route_ref) if policy.model_route_ref else None
            purpose = "developer" if node.type is WorkflowNodeType.WORKER else node.type.value
            if (
                route
                and isinstance(route.spec, RoutePolicySpec)
                and purpose not in route.spec.purposes
            ):
                issues.append(
                    _issue(
                        "reference.route_purpose",
                        "Model route does not support this node's purpose",
                        node=node.id,
                    )
                )
            if worker and isinstance(worker.spec, WorkerSpec):
                requires = set(definition.capabilities) | set(
                    policy.worker_selector.requires if policy.worker_selector else ()
                )
                if requires - set(worker.spec.capabilities):
                    issues.append(
                        _issue(
                            "reference.worker_capabilities",
                            "Selected worker lacks required capabilities",
                            node=node.id,
                        )
                    )
                if policy.max_concurrency and policy.max_concurrency > worker.spec.max_concurrency:
                    issues.append(
                        _issue(
                            "reference.worker_concurrency",
                            "Node concurrency exceeds selected worker capacity",
                            node=node.id,
                        )
                    )
                if (
                    node.type is WorkflowNodeType.WORKER
                    and worker.spec.model_binding.mode == "control_plane"
                    and policy.model_route_ref is None
                ):
                    issues.append(
                        _issue(
                            "policy.required",
                            "Control-plane worker requires a model route",
                            node=node.id,
                        )
                    )
                if (
                    node.type is WorkflowNodeType.WORKER
                    and worker.spec.model_binding.mode == "none"
                    and worker.spec.adapter_kind != "demo"
                ):
                    issues.append(
                        _issue(
                            "reference.worker_model",
                            "Non-demo worker requires an explicit model binding",
                            node=node.id,
                        )
                    )
                route = revisions.get(policy.model_route_ref) if policy.model_route_ref else None
                allowed = worker.spec.model_binding.allowed_profile_revision_ids
                if (
                    node.type is WorkflowNodeType.WORKER
                    and allowed
                    and route
                    and isinstance(route.spec, RoutePolicySpec)
                    and any(
                        candidate.profile_revision_id not in allowed
                        for candidate in route.spec.candidates
                    )
                ):
                    issues.append(
                        _issue(
                            "reference.worker_model",
                            "Model route exceeds worker's declared model binding",
                            node=node.id,
                        )
                    )
    for edge in spec.edges:
        if edge.kind is not WorkflowEdgeKind.RETRY:
            continue
        if edge.retry_class in {
            FailureClass.CONFIGURATION_INVALID,
            FailureClass.SECURITY_POLICY_DENIED,
            FailureClass.APPROVAL_REJECTED,
            FailureClass.USER_CANCELLED,
        }:
            issues.append(
                _issue("cycle.nonretryable", "This failure class cannot be retried", edge=edge.id)
            )
        policy = effective_policy(spec, nodes[edge.source])
        revision = revisions.get(policy.retry_policy_ref) if policy.retry_policy_ref else None
        if policy.retry_policy_ref is None:
            issues.append(
                _issue(
                    "cycle.retry_bound", "Retry requires an immutable retry policy", edge=edge.id
                )
            )
        elif snapshot and revision and isinstance(revision.spec, RetryRegistrySpec):
            rule = next(
                (rule for rule in revision.spec.rules if rule.failure_class == edge.retry_class),
                None,
            )
            if rule is None or rule.max_retries < 1:
                issues.append(
                    _issue(
                        "cycle.retry_bound",
                        "Retry requires a positive class-specific finite budget",
                        edge=edge.id,
                    )
                )
                continue
            fallback = next(
                (item for item in spec.edges if item.source == edge.source and item.fallback), None
            )
            target = nodes.get(fallback.target) if fallback else None
            if (
                target is None
                or (
                    rule.exhaustion_action == "approval"
                    and target.type is not WorkflowNodeType.APPROVAL
                )
                or (
                    rule.exhaustion_action in {"fail", "block"}
                    and (
                        target.type is not WorkflowNodeType.FINALIZE
                        or target.config["outcome"]
                        != {"fail": "failed", "block": "blocked"}[rule.exhaustion_action]
                    )
                )
            ):
                issues.append(
                    _issue(
                        "cycle.retry_exhaustion",
                        "Retry fallback must match the policy's terminal exhaustion action",
                        edge=edge.id,
                    )
                )
    return issues


def _protected_paths(spec: WorkflowSpec) -> list[WorkflowIssue]:
    issues: list[WorkflowIssue] = []
    adjacency = _adjacency(spec.edges)
    nodes = {node.id: node for node in spec.nodes}
    # Finite abstract interpretation retains every path's evidence, including
    # new worker attempts that invalidate earlier verification/review evidence.
    pending = [(spec.entrypoint, False, False, False)]
    seen: set[tuple[str, bool, bool, bool]] = set()
    while pending:
        node_id, verified, reviewed, verification_required = pending.pop()
        identity = (node_id, verified, reviewed, verification_required)
        if identity in seen:
            continue
        seen.add(identity)
        node = nodes[node_id]
        policy = effective_policy(spec, node)
        if node.type is WorkflowNodeType.WORKER:
            verified = reviewed = False
            verification_required = policy.verification is not None and policy.verification.required
        elif node.type is WorkflowNodeType.VERIFY:
            verified = True
        elif node.type is WorkflowNodeType.REVIEWER:
            if not verified:
                issues.append(
                    _issue(
                        "security.verification_bypass",
                        "Review path bypasses required verification",
                        node=node_id,
                    )
                )
            reviewed = True
        elif node.type is WorkflowNodeType.GITHUB_PUBLISH:
            if not verified:
                issues.append(
                    _issue(
                        "security.verification_bypass",
                        "Publication path bypasses current verification",
                        node=node_id,
                    )
                )
            if not reviewed:
                issues.append(
                    _issue(
                        "security.review_bypass",
                        "Publication path bypasses current independent review",
                        node=node_id,
                    )
                )
        elif (
            node.type is WorkflowNodeType.FINALIZE
            and node.config["outcome"] == "derive"
            and verification_required
            and not verified
        ):
            issues.append(
                _issue(
                    "security.verification_bypass",
                    "Success path bypasses required verification",
                    node=node_id,
                )
            )
        pending.extend(
            (target, verified, reviewed, verification_required)
            for target in adjacency.get(node_id, ())
        )
    for node in spec.nodes:
        approval = effective_policy(spec, node).approval
        if approval and approval.required_grant_from:
            granting_node = approval.required_grant_from
            if node.id in _reachable(spec.entrypoint, adjacency, stop=granting_node):
                issues.append(
                    _issue(
                        "security.approval_bypass",
                        "Protected action has a path that bypasses its named approval",
                        node=node.id,
                    )
                )
            after_grant = set().union(
                *(
                    _reachable(target, adjacency, stop=granting_node)
                    for target in adjacency.get(granting_node, ())
                )
            )
            for candidate in after_grant:
                if (
                    candidate != node.id
                    and nodes[candidate].type is WorkflowNodeType.WORKER
                    and node.id in _reachable(candidate, adjacency, stop=granting_node)
                ):
                    issues.append(
                        _issue(
                            "security.stale_approval",
                            "A new worker invalidates the grant before this protected action",
                            node=node.id,
                        )
                    )
    return issues


def validate_workflow(
    raw: WorkflowSpec | dict[str, JsonValue],
    snapshot: WorkflowResolvedSnapshot | None = None,
) -> WorkflowValidationReport:
    """Return stable, canvas-addressable issues without exposing rejected input."""
    payload = raw.model_dump(mode="json", by_alias=True) if isinstance(raw, WorkflowSpec) else raw
    if isinstance(raw, WorkflowSpec):
        # Preserve inheritance while revalidating potentially model_copy-created
        # inputs. Normalization later makes effective values explicit and durable.
        payload["nodes"] = [
            {
                **node.model_dump(mode="json"),
                "policy": node.policy.model_dump(mode="json", exclude_unset=True),
            }
            for node in raw.nodes
        ]
    issues = _resource_issues(payload)
    if issues:
        return WorkflowValidationReport(valid=False, issues=tuple(issues))
    issues.extend(_raw_references(payload))
    try:
        spec = WorkflowSpec.model_validate(payload)
    except ValidationError as exc:
        issues.extend(_schema_issues(exc, payload))
        return WorkflowValidationReport(valid=False, issues=tuple(issues))
    if spec.spec_version != "1.1":
        issues.append(_issue("schema.unsupported_version", "Compiler requires workflow spec 1.1"))
    if spec.reducers != default_reducers():
        issues.append(
            _issue("state.reducers", "Workflow reducers must match the versioned state contract")
        )
    for node in spec.nodes:
        try:
            NODE_DEFINITIONS[node.type].config_model.model_validate(node.config)
        except ValidationError as exc:
            for error in exc.errors(include_input=False, include_context=False, include_url=False):
                issues.append(
                    _issue(
                        "node.config",
                        f"Invalid node configuration ({error['type']})",
                        node=node.id,
                        path="config." + ".".join(map(str, error["loc"])),
                    )
                )
    if any(issue.code == "node.config" for issue in issues):
        return WorkflowValidationReport(valid=False, issues=tuple(issues))
    spec = normalize_workflow(spec)
    issues.extend(_graph_issues(spec))
    issues.extend(_fanout_issues(spec))
    issues.extend(_policy_issues(spec, snapshot))
    issues.extend(_protected_paths(spec))
    if snapshot is not None:
        issues.extend(_snapshot_issues(spec, snapshot))
    unique = tuple(dict.fromkeys(issues))
    return WorkflowValidationReport(
        valid=not unique,
        issues=unique,
        content_hash=spec.content_hash,
        snapshot_hash=snapshot.snapshot_hash if snapshot else None,
    )
