"""Deterministic fixtures implementing the production-normalized boundary."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from uuid import UUID

from jarvis_contracts.enums import FailureClass
from jarvis_contracts.registry import (
    ModelProfileSpec,
    ProviderFailure,
    ProviderRequest,
    ProviderResult,
    ProviderSpec,
    ProviderToolCall,
    Usage,
    ValidationReport,
    WorkerSpec,
)

from .base import BaseAdapter, BoundaryError


@dataclass(frozen=True)
class DemoScenario:
    text: str = "DEMO response"
    chunks: tuple[str, ...] = ()
    tool_calls: tuple[ProviderToolCall, ...] = ()
    latency_seconds: float = 0
    usage: Usage = field(default_factory=Usage)
    failures: tuple[ProviderFailure, ...] = ()
    available: bool = True

    def __post_init__(self) -> None:
        if not 0 <= self.latency_seconds <= 30 or len(self.failures) > 100:
            raise ValueError("DEMO scenario bounds exceeded")


class DemoAdapter(BaseAdapter):
    def __init__(
        self,
        provider: ProviderSpec,
        profile: ModelProfileSpec,
        provider_revision_id: UUID,
        profile_revision_id: UUID,
        *,
        scenario: DemoScenario | None = None,
    ) -> None:
        super().__init__(provider, profile, provider_revision_id, profile_revision_id)
        if provider.provider_kind != "demo":
            raise ValueError("DEMO adapter cannot construct network providers")
        self.scenario = scenario or DemoScenario()
        self.attempts = 0

    async def list_models(self) -> tuple[str, ...]:
        return (self.profile.model_identifier,) if self.scenario.available else ()

    async def validate_connection(self) -> ValidationReport:
        try:
            self.check_profile()
        except BoundaryError as exc:
            return ValidationReport(
                valid=False, health="misconfigured", issues=(exc.code,), demo=True
            )
        return ValidationReport(
            valid=self.scenario.available,
            health="healthy" if self.scenario.available else "unavailable",
            demo=True,
            issues=() if self.scenario.available else ("DEMO unavailable",),
        )

    async def _invoke(self, request: ProviderRequest, *, streaming: bool) -> ProviderResult:
        started = time.monotonic()
        try:
            self.check_request(request)
            if streaming and not self.profile.streaming:
                raise BoundaryError("streaming_unsupported", FailureClass.CONFIGURATION_INVALID)
            self.attempts += 1
            async with asyncio.timeout(self.provider.timeouts.run_seconds):
                await asyncio.sleep(self.scenario.latency_seconds)
            if not self.scenario.available:
                raise BoundaryError(
                    "demo_unavailable", FailureClass.INFRASTRUCTURE_SERVICE_UNAVAILABLE
                )
            if self.attempts <= len(self.scenario.failures):
                return self.result(
                    failure=self.scenario.failures[self.attempts - 1], started=started
                )
            return self.result(
                text="".join(self.scenario.chunks)
                if streaming and self.scenario.chunks
                else self.scenario.text,
                started=started,
                request=request,
                tool_calls=self.scenario.tool_calls,
                usage=self.scenario.usage,
                request_id=f"DEMO-{self.attempts}",
            )
        except (Exception, asyncio.CancelledError) as exc:
            return self.result(failure=self.normalize_error(exc), started=started)


class DemoWorker:
    """Validation-only local worker; no scheduler, shell or remote execution."""

    def __init__(self, spec: WorkerSpec) -> None:
        if spec.adapter_kind != "demo":
            raise ValueError("DEMO worker cannot execute remote adapters")
        self.spec = spec

    def validate(self, profile_revision_id: UUID | None = None) -> ValidationReport:
        binding = self.spec.model_binding
        compatible = (
            profile_revision_id is None
            if binding.mode == "none"
            else profile_revision_id in binding.allowed_profile_revision_ids
        )
        return ValidationReport(
            valid=compatible,
            health="healthy" if compatible else "misconfigured",
            issues=() if compatible else ("incompatible_model_binding",),
            demo=True,
        )
