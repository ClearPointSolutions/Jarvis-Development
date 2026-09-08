"""Transport-independent runtime boundaries for workers and publication.

M5 owns durable preparation, dispatch identity, cancellation and reconciliation.
Implementations return normalized WorkflowStateV1 through EffectObservation;
native transport objects and credentials never cross this boundary. M7 may bind
an SSH invocation protocol behind WorkerAdapter without changing the graph.
"""

from typing import Protocol

from jarvis_contracts.registry import ValidationReport, WorkerSpec
from jarvis_orchestrator.runtime.effects import EffectAdapter


class WorkerAdapter(EffectAdapter, Protocol):
    def validate(self, worker: WorkerSpec) -> ValidationReport: ...
    async def health(self) -> ValidationReport: ...


class PublicationAdapter(EffectAdapter, Protocol):
    """Publication identity is the ledger identity, never a browser-generated ref."""

    async def health(self) -> ValidationReport: ...
