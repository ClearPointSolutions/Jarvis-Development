"""Owner-scoped accounting that reconciles started/result receipts before totals."""

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select

from jarvis_api.auth.dependencies import CurrentPrincipal
from jarvis_api.errors import ApiProblemError
from jarvis_api.runtime import get_run, sessions
from jarvis_contracts.operations import CurrencyUsage, RunUsage
from jarvis_contracts.registry import AccountingRecord
from jarvis_persistence.models import ModelCallModel

router = APIRouter(prefix="/api/v1", tags=["operations"])


def aggregate(records: list[AccountingRecord]) -> RunUsage:
    latest: dict[str, AccountingRecord] = {}
    for record in records:
        prior = latest.get(record.correlation_id)
        if prior is not None and (prior.profile_revision_id, prior.provider_revision_id) != (
            record.profile_revision_id,
            record.provider_revision_id,
        ):
            raise ValueError("accounting correlation identity changed")
        if prior is None or (record.created_at, record.outcome != "unknown") > (
            prior.created_at,
            prior.outcome != "unknown",
        ):
            latest[record.correlation_id] = record
    values = list(latest.values())
    unknown = sum(
        row.usage.total_tokens is None or row.usage.provenance == "unknown" for row in values
    )
    tokens = sum(row.usage.total_tokens or 0 for row in values if row.usage.provenance != "unknown")
    currencies = []
    for currency in sorted({row.cost.currency for row in values}):
        costs = [row.cost for row in values if row.cost.currency == currency]
        missing = sum(
            cost.status == "unknown" or (cost.amount is None and cost.status != "not_applicable")
            for cost in costs
        )
        subtotal = sum(
            (
                cost.amount
                for cost in costs
                if cost.amount is not None and cost.status in {"exact", "estimated"}
            ),
            Decimal(0),
        )
        status = (
            "unknown"
            if missing
            else "not_applicable"
            if all(cost.status == "not_applicable" for cost in costs)
            else "estimated"
            if any(cost.status == "estimated" for cost in costs)
            else "exact"
        )
        currencies.append(
            CurrencyUsage(
                currency=currency,
                known_subtotal=subtotal,
                total=None if status in {"unknown", "not_applicable"} else subtotal,
                status=status,
                unknown_calls=missing,
            )
        )
    return RunUsage(
        calls=len(values),
        known_tokens=tokens,
        total_tokens=None if unknown else tokens,
        unknown_usage_calls=unknown,
        provenance="unknown"
        if unknown
        else "estimated"
        if any(row.usage.provenance == "estimated" for row in values)
        else "exact",
        currencies=tuple(currencies),
    )


@router.get("/runs/{run_id}/usage", response_model=RunUsage)
async def usage(request: Request, run_id: UUID, principal: CurrentPrincipal) -> RunUsage:
    await get_run(request, run_id, principal)
    async with sessions(request, principal)() as session:
        rows = (
            await session.scalars(
                select(ModelCallModel).where(ModelCallModel.run_id == run_id).limit(10001)
            )
        ).all()
        if len(rows) > 10000:
            raise ApiProblemError(
                409, "usage.limit", "This run requires a paginated accounting export"
            )
        return aggregate([AccountingRecord.model_validate(row.record_json) for row in rows])
