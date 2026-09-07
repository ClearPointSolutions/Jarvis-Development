"""Bounded, data-only predicates over the workflow's observable state."""

from collections.abc import Mapping
from typing import cast

from pydantic import JsonValue

from jarvis_contracts.workflow import Predicate, PredicateOperator

ALLOWED_PATHS = frozenset(
    {
        "$.outcome.status",
        "$.outcome.failure_class",
        "$.node.result",
        "$.node.status",
        "$.node.failure_class",
        "$.tasks.terminal_count",
        "$.tasks.total_count",
        "$.tasks.current_task",
        "$.verification.passed",
        "$.review.passed",
        "$.approval.decision",
        "$.approval.action_type",
        "$.approval.granted_by",
        "$.final.status",
        "$.cancelled",
    }
)
_MISSING = object()


def _lookup(state: Mapping[str, object], path: str) -> object:
    if path not in ALLOWED_PATHS:
        return _MISSING
    value: object = state
    for part in path[2:].split("."):
        if not isinstance(value, Mapping) or part not in value:
            return _MISSING
        value = value[part]
    return value


def get_path(state: Mapping[str, object], path: str) -> JsonValue | None:
    """Read an approved path; inaccessible/missing fields produce no value."""
    value = _lookup(state, path)
    return None if value is _MISSING else cast(JsonValue, value)


def _equal(left: object, right: object) -> bool:
    # JSON booleans are not numbers, despite Python's bool subclassing int.
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return left == right


def evaluate_predicate(predicate: Predicate, state: Mapping[str, object]) -> bool:
    """Evaluate an already validated AST without executing user-authored code."""
    op = predicate.op
    if op is PredicateOperator.AND:
        return all(evaluate_predicate(arg, state) for arg in predicate.args)
    if op is PredicateOperator.OR:
        return any(evaluate_predicate(arg, state) for arg in predicate.args)
    if op is PredicateOperator.NOT:
        return not evaluate_predicate(predicate.args[0], state)
    actual = _lookup(state, predicate.path or "")
    if op is PredicateOperator.EXISTS:
        return actual is not _MISSING
    if actual is _MISSING:
        return False
    expected = predicate.value
    if op is PredicateOperator.EQ:
        return _equal(actual, expected)
    if op is PredicateOperator.NEQ:
        return not _equal(actual, expected)
    if op is PredicateOperator.IN:
        return isinstance(expected, list) and any(_equal(actual, item) for item in expected)
    if (
        not isinstance(actual, (int, float))
        or isinstance(actual, bool)
        or not isinstance(expected, (int, float))
        or isinstance(expected, bool)
    ):
        return False
    if op is PredicateOperator.LT:
        return actual < expected
    if op is PredicateOperator.LTE:
        return actual <= expected
    if op is PredicateOperator.GT:
        return actual > expected
    return actual >= expected
