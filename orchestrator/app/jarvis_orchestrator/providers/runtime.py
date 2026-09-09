"""Fenced model calls against immutable provider/profile revisions."""

from __future__ import annotations

from uuid import UUID, uuid5

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis_api.routing.observability import AccountingService
from jarvis_api.routing.policies import calculate_cost
from jarvis_contracts.base import canonical_json, sha256_digest
from jarvis_contracts.registry import (
    AccountingRecord,
    ModelProfileSpec,
    ProviderRequest,
    ProviderResult,
    ProviderSpec,
)
from jarvis_orchestrator.providers.configuration import ProviderRuntimeConfig
from jarvis_orchestrator.runtime.effects import AmbiguousEffectError
from jarvis_orchestrator.runtime.nodes import ClassifiedNodeError
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership
from jarvis_persistence.models import EventModel, ModelResponseReceiptModel


class RuntimeModel:
    """An ambiguous billed call is recorded and never silently issued again.

    No database transaction is held across network I/O. The ordinary service
    heartbeat remains free to renew its run lease while a cold model loads.
    """

    def __init__(
        self,
        configuration: ProviderRuntimeConfig,
        owner: RunOwnership,
        fence: RunFence,
        provider: ProviderSpec,
        profile: ModelProfileSpec,
        provider_id: UUID,
        profile_id: UUID,
    ) -> None:
        self.owner, self.fence = owner, fence
        self.profile, self.provider = profile, provider
        self.adapter = configuration.adapter(provider, profile, provider_id, profile_id)

    async def invoke(self, call_id: UUID, request: ProviderRequest) -> dict[str, JsonValue]:
        if request.run_id != self.fence.run_id:
            raise ValueError("model call run identity mismatch")
        self.adapter.check_request(request)
        # Paid ceilings need a durable grant before a call; reject until the
        # configured policy is evaluated by the composition's protected gateway.
        if self.provider.egress.paid:
            raise ValueError("paid model calls require a configured budget gateway")
        request_digest = sha256_digest(
            {
                "request": request.model_dump(mode="json"),
                "provider_revision_id": str(self.adapter.provider_revision_id),
                "profile_revision_id": str(self.adapter.profile_revision_id),
            }
        )
        async with self.owner.fenced(self.fence) as (session, run):
            receipt = await session.get(ModelResponseReceiptModel, call_id)
            if receipt is not None:
                if (
                    receipt.run_id != run.id
                    or receipt.request_digest != request_digest
                    or sha256_digest(receipt.response_json) != receipt.response_digest
                ):
                    raise AmbiguousEffectError("model receipt identity mismatch")
                return self._structured(ProviderResult.model_validate(receipt.response_json))
            previous = await session.scalar(
                select(EventModel.event_id).where(
                    EventModel.run_id == run.id,
                    EventModel.type == "model.call_started",
                    EventModel.data_json["call_id"].astext == str(call_id),
                )
            )
            if previous is not None:
                raise AmbiguousEffectError("model call requires receipt reconciliation")
            await self.owner.event(
                session,
                run,
                "model.call_started",
                {
                    "call_id": str(call_id),
                    "profile_revision_id": str(self.adapter.profile_revision_id),
                    "provider_revision_id": str(self.adapter.provider_revision_id),
                    "model_identifier": self.profile.model_identifier,
                },
            )
            # An append-only unknown attempt survives death during inference.
            await self._account(session, call_id, request, None)
        result = await self.adapter.invoke(request)
        payload = result.model_dump(mode="json")
        if len(canonical_json(payload)) > 2_097_152:
            raise AmbiguousEffectError("model response exceeds receipt limit")
        async with self.owner.fenced(self.fence) as (session, run):
            session.add(
                ModelResponseReceiptModel(
                    call_id=call_id,
                    run_id=run.id,
                    request_digest=request_digest,
                    response_digest=sha256_digest(payload),
                    response_json=payload,
                )
            )
            await self._account(session, call_id, request, result)
            await self.owner.event(
                session,
                run,
                "model.call_failed" if result.failure else "model.call_completed",
                {
                    "call_id": str(call_id),
                    "profile_revision_id": str(result.profile_revision_id),
                    "provider_revision_id": str(result.provider_revision_id),
                    "model_identifier": result.model_identifier,
                    "usage": result.usage.model_dump(mode="json"),
                    "latency_ms": result.latency_ms,
                    "failure": result.failure.model_dump(mode="json") if result.failure else None,
                },
            )
        self.owner.fault("after_model_receipt_before_domain_result")
        return self._structured(result)

    @staticmethod
    def _structured(result: ProviderResult) -> dict[str, JsonValue]:
        if result.failure:
            raise ClassifiedNodeError(result.failure.failure_class)
        if result.structured is None:
            raise ValueError("structured model result is required")
        return result.structured

    async def _account(
        self,
        session: AsyncSession,
        call_id: UUID,
        request: ProviderRequest,
        result: ProviderResult | None,
    ) -> None:
        from jarvis_contracts.registry import Usage

        usage = result.usage if result is not None else Usage()
        stage = "result" if result is not None else "started"
        await AccountingService(self.owner.sessions).record_in_session(
            session,
            AccountingRecord(
                id=uuid5(call_id, stage),
                profile_revision_id=self.adapter.profile_revision_id,
                provider_revision_id=self.adapter.provider_revision_id,
                correlation_id=str(call_id),
                run_id=self.fence.run_id,
                task_id=request.task_id,
                node_id=request.node_id,
                request_id=result.request_id if result else None,
                latency_ms=result.latency_ms if result else 0,
                usage=usage,
                pricing=self.profile.pricing,
                cost=calculate_cost(usage, self.profile.pricing),
                outcome="unknown"
                if result is None
                else "failed"
                if result.failure
                else "completed",
                created_at=self.owner.clock.now(),
            ),
            idempotency_key=f"{call_id}:{stage}",
        )
