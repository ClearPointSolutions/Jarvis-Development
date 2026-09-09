"""Durable fail-closed budget authorization for paid provider inference.

A paid call is only issued after the run's immutable route spend policy grants
it inside the same fenced transaction that records the call intent. The grant is
private, immutable and keyed by the call identity, so recovery replays the
original decision instead of re-authorizing a second billed inference.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis_api.routing.policies import calculate_cost, evaluate_spend
from jarvis_contracts.base import canonical_json, sha256_digest
from jarvis_contracts.enums import FailureClass
from jarvis_contracts.registry import (
    ModelProfileSpec,
    ProviderRequest,
    RoutePolicySpec,
    RouteRequirements,
    Usage,
)
from jarvis_orchestrator.runtime.nodes import ClassifiedNodeError
from jarvis_persistence.models import ModelBudgetGrantModel, ModelCallModel

if TYPE_CHECKING:  # pragma: no cover - typing only
    from jarvis_orchestrator.workflows.factories import NodeContext

BUDGET_ESTIMATE_BYTES_PER_TOKEN = 3
"""Conservative deterministic bound used only for pre-call ceilings.

Provider tokenizers are not reproducible here. English UTF-8 text averages about
four bytes per token, so dividing by three over-estimates the request rather than
admitting a call that a real tokenizer would price above the configured ceiling.
"""


class BudgetDeniedError(ClassifiedNodeError):
    """A paid call the immutable spend policy refuses to authorize."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        super().__init__(FailureClass.SECURITY_POLICY_DENIED)
        self.reasons = reasons


def estimate_input_tokens(request: ProviderRequest) -> int:
    """Return a deterministic conservative input-token bound for one request."""

    size = len(request.text.encode("utf-8"))
    if request.structured_schema is not None:
        size += len(canonical_json(request.structured_schema))
    for tool in request.tools:
        size += len(canonical_json(tool))
    return max(1, -(-size // BUDGET_ESTIMATE_BYTES_PER_TOKEN))


class BudgetGateway:
    """Evaluate the run's bound spend policy before any billed inference."""

    def __init__(self, route: RoutePolicySpec | None, route_revision_id: UUID | None) -> None:
        self.route, self.route_revision_id = route, route_revision_id

    def policy_digest(self) -> str:
        if self.route is None or self.route_revision_id is None:
            return sha256_digest({"spend": None})
        return sha256_digest(
            {
                "spend": self.route.spend.model_dump(mode="json"),
                "route_revision_id": str(self.route_revision_id),
            }
        )

    async def run_spend(self, session: AsyncSession, run_id: UUID) -> Decimal | None:
        """Return durable spend for the run, or None when it cannot be determined.

        Every completed call contributes a `:result` accounting row. A `:started`
        row without its `:result` peer is an inference that may have been billed
        before a crash, so the run total is unknowable and the caller fails closed.
        """

        rows = (
            await session.scalars(select(ModelCallModel).where(ModelCallModel.run_id == run_id))
        ).all()
        started: set[str] = set()
        completed: set[str] = set()
        total = Decimal(0)
        for row in rows:
            _, _, stage = row.idempotency_key.rpartition(":")
            record = row.record_json
            if stage == "started":
                started.add(row.correlation_id)
                continue
            if stage != "result":
                continue
            completed.add(row.correlation_id)
            if record.get("demo") is True:
                continue
            cost = record.get("cost") or {}
            if cost.get("status") == "not_applicable":
                continue
            amount = cost.get("amount")
            if cost.get("status") not in {"exact", "estimated"} or amount is None:
                # A real call whose cost is unknown makes the run total unsafe.
                return None
            total += Decimal(str(amount))
        if started - completed:
            return None
        return total

    async def authorize(
        self,
        session: AsyncSession,
        run_id: UUID,
        call_id: UUID,
        request: ProviderRequest,
        profile: ModelProfileSpec,
        profile_revision_id: UUID,
        provider_revision_id: UUID,
        request_digest: str,
        *,
        paid: bool,
    ) -> ModelBudgetGrantModel | None:
        """Grant or refuse one paid call; free providers need no grant."""

        if not paid:
            return None
        digest = self.policy_digest()
        grant = await session.get(ModelBudgetGrantModel, call_id)
        if grant is not None:
            if (
                grant.run_id != run_id
                or grant.request_digest != request_digest
                or grant.policy_digest != digest
            ):
                raise BudgetDeniedError(("Recorded budget grant does not match this call",))
            if grant.decision != "allow":
                # Already durable: replay the original refusal without rewriting it.
                raise BudgetDeniedError(tuple(str(item) for item in grant.reasons_json))
            return grant
        reasons: tuple[str, ...]
        decision: str
        estimate = None
        spent = await self.run_spend(session, run_id)
        if self.route is None or self.route_revision_id is None:
            decision, reasons = "deny", ("Paid use requires an immutable bound route policy",)
        elif profile.pricing.status != "known":
            decision, reasons = "deny", ("Paid provider pricing is not known",)
        elif spent is None and self.route.spend.max_run_cost is not None:
            # Only a policy that actually caps the run needs the running total;
            # an indeterminate total can never be shown to fit that cap.
            decision, reasons = "deny", ("Durable run spend cannot be determined",)
        else:
            requirements = RouteRequirements(
                purpose=request.purpose,
                input_tokens=estimate_input_tokens(request),
                output_tokens=request.output_tokens,
                data_classification=request.data_classification,
                run_spend=spent,
            )
            estimate = calculate_cost(
                Usage(
                    input_tokens=requirements.input_tokens,
                    output_tokens=requirements.output_tokens,
                    provenance="estimated",
                ),
                profile.pricing,
            ).amount
            decision, reasons = evaluate_spend(
                self.route.spend, requirements, profile.pricing, paid=True
            )
        # `require_approval` is not an authorization: the durable approval node
        # protects the effect, and this gateway alone never releases the spend.
        granted = ModelBudgetGrantModel(
            call_id=call_id,
            run_id=run_id,
            route_revision_id=self.route_revision_id,
            profile_revision_id=profile_revision_id,
            provider_revision_id=provider_revision_id,
            request_digest=request_digest,
            policy_digest=digest,
            decision=decision,
            reasons_json=list(reasons),
            estimated_cost=estimate,
            run_spend_before=spent,
        )
        session.add(granted)
        await session.flush()
        return granted


def bound_budget(context: NodeContext) -> BudgetGateway:
    """Bind the gateway to the node's immutable route policy revision.

    A node without a declared model route has no spend authority at all, so the
    returned gateway refuses every paid provider rather than assuming defaults.
    """

    reference = context.policy.model_route_ref
    if reference is None:
        return BudgetGateway(None, None)
    route = next(
        (row.spec for row in context.snapshot.revisions if row.revision_id == reference),
        None,
    )
    if not isinstance(route, RoutePolicySpec):
        return BudgetGateway(None, None)
    return BudgetGateway(route, reference)
