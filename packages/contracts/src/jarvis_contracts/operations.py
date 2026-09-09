"""Truthful read-only operational projections."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from jarvis_contracts.base import ContractModel


class CurrencyUsage(ContractModel):
    currency: str
    known_subtotal: Decimal
    total: Decimal | None
    status: Literal["exact", "estimated", "unknown", "not_applicable"]
    unknown_calls: int


class RunUsage(ContractModel):
    calls: int
    total_tokens: int | None
    known_tokens: int
    unknown_usage_calls: int
    provenance: Literal["exact", "estimated", "unknown"]
    currencies: tuple[CurrencyUsage, ...]
    worker_usage: Literal["unavailable"] = "unavailable"


class SystemHealth(ContractModel):
    observed_at: datetime
    database: Literal["healthy"] = "healthy"
    orchestrator: Literal["healthy", "stale", "unknown"]
    last_heartbeat_at: datetime | None
    heartbeat_stale_after_seconds: int
    accepting_instances: int
    run_counts: dict[str, int]
    expired_active_leases: int
