"""Small checkpoint-safe workflow channels and deterministic parallel reducers."""

from __future__ import annotations

from copy import deepcopy
from typing import Annotated, TypedDict

from pydantic import JsonValue

from jarvis_contracts.base import canonical_json


class WorkflowInvariantError(ValueError):
    """A declarative graph or injected handler violated its runtime contract."""


def merge_by_id(left: dict[str, JsonValue], right: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Idempotent, order-independent merge; conflicting delivery fails closed."""
    merged = deepcopy(left)
    for key, value in right.items():
        if key in merged and canonical_json({"value": merged[key]}) != canonical_json(
            {"value": value}
        ):
            raise WorkflowInvariantError(f"Conflicting completion for identity {key}")
        merged[key] = deepcopy(value)
    return dict(sorted(merged.items()))


def set_union(left: list[str], right: list[str]) -> list[str]:
    return sorted(set(left) | set(right))


def max_map(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    merged = dict(left)
    for key, value in right.items():
        if type(value) is not int or value < 0:
            raise WorkflowInvariantError("Counters must be nonnegative integers")
        merged[key] = max(merged.get(key, 0), value)
    return dict(sorted(merged.items()))


class BranchOutput(TypedDict, total=False):
    results: Annotated[dict[str, JsonValue], merge_by_id]
    child_results: Annotated[dict[str, JsonValue], merge_by_id]
    expected_children: Annotated[list[str], set_union]
    completed_children: Annotated[list[str], set_union]
    counters: Annotated[dict[str, int], max_map]


class WorkflowStateV1(BranchOutput, total=False):
    """Internal routing metadata is checkpointed; no hidden reasoning is stored."""

    node: dict[str, JsonValue]
    outcome: dict[str, JsonValue]
    tasks: dict[str, JsonValue]
    verification: dict[str, JsonValue]
    review: dict[str, JsonValue]
    approval: dict[str, JsonValue]
    final: dict[str, JsonValue]
    cancelled: bool
    child_identity: str
    _route: str
    _needs_verification: bool


def merged_state(state: WorkflowStateV1, update: WorkflowStateV1) -> WorkflowStateV1:
    merged = deepcopy(state)
    merged.update(deepcopy(update))
    merged["results"] = merge_by_id(state.get("results", {}), update.get("results", {}))
    merged["child_results"] = merge_by_id(
        state.get("child_results", {}), update.get("child_results", {})
    )
    merged["counters"] = max_map(state.get("counters", {}), update.get("counters", {}))
    merged["expected_children"] = set_union(
        state.get("expected_children", []), update.get("expected_children", [])
    )
    merged["completed_children"] = set_union(
        state.get("completed_children", []), update.get("completed_children", [])
    )
    return merged
