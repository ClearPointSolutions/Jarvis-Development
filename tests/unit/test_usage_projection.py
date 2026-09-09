"""Unknown accounting is never zero and receipt stages are not extra calls."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from jarvis_api.usage import aggregate
from jarvis_contracts.registry import AccountingRecord, Cost, Pricing, Usage


def call() -> AccountingRecord:
    return AccountingRecord(
        id=uuid4(),
        profile_revision_id=uuid4(),
        provider_revision_id=uuid4(),
        correlation_id=str(uuid4()),
        latency_ms=0,
        usage=Usage(),
        pricing=Pricing(),
        cost=Cost(),
        outcome="unknown",
        created_at=datetime(2026, 9, 9, tzinfo=UTC),
    )


def test_started_receipt_reconciles_to_one_exact_call_in_any_order() -> None:
    started = call()
    complete = started.model_copy(
        update={
            "id": uuid4(),
            "outcome": "completed",
            "usage": Usage(input_tokens=10, output_tokens=5, total_tokens=15, provenance="exact"),
            "cost": Cost(amount=Decimal("0.01"), status="exact"),
        }
    )
    for rows in ([started, complete], [complete, started], [started, complete, complete]):
        result = aggregate(rows)
        assert result.calls == 1 and result.total_tokens == 15
        assert result.provenance == "exact"
        assert result.currencies[0].total == Decimal("0.01")


def test_ambiguous_call_preserves_unknown_total_and_known_subtotal() -> None:
    unknown = call()
    known = call().model_copy(
        update={
            "usage": Usage(total_tokens=15, provenance="estimated"),
            "cost": Cost(amount=Decimal("1.25"), status="estimated"),
            "outcome": "completed",
        }
    )
    result = aggregate([unknown, known])
    assert result.calls == 2 and result.total_tokens is None
    assert result.known_tokens == 15 and result.unknown_usage_calls == 1
    assert result.currencies[0].total is None
    assert result.currencies[0].known_subtotal == Decimal("1.25")


def test_currencies_remain_separate_and_free_is_not_unknown_zero() -> None:
    free = call().model_copy(update={"cost": Cost(status="not_applicable")})
    euro = call().model_copy(
        update={"cost": Cost(amount=Decimal("2"), currency="EUR", status="exact")}
    )
    result = aggregate([free, euro])
    costs = {value.currency: value for value in result.currencies}
    assert costs["USD"].total is None and costs["USD"].status == "not_applicable"
    assert costs["EUR"].total == Decimal("2")


def test_changed_profile_cannot_hide_under_a_completed_correlation() -> None:
    original = call()
    changed = original.model_copy(
        update={
            "profile_revision_id": uuid4(),
            "created_at": original.created_at + timedelta(seconds=1),
        }
    )
    with pytest.raises(ValueError, match="identity"):
        aggregate([original, changed])


def test_empty_run_has_no_invented_model_cost() -> None:
    result = aggregate([])
    assert result.calls == 0 and result.total_tokens == 0 and not result.currencies
    assert result.worker_usage == "unavailable"
