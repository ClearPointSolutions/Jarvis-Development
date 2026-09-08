"""Worker lifecycle independent of graph and implementation-specific process details."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from jarvis_contracts.registry import WorkerSpec
from jarvis_contracts.workers import (
    CancelResult,
    PreparedInvocation,
    ReconciliationResult,
    WorkerEvent,
    WorkerHealth,
    WorkerInvocationHandle,
    WorkerInvocationRequest,
    WorkerInvocationStatus,
    WorkerResult,
    WorkerSlotFence,
    WorkerValidationReport,
)


@dataclass(frozen=True)
class WorkerCallContext:
    deadline: datetime
    correlation_id: UUID


class WorkerAdapter(Protocol):
    async def validate(
        self, worker: WorkerSpec, context: WorkerCallContext
    ) -> WorkerValidationReport: ...
    async def health(self, worker: WorkerSpec, context: WorkerCallContext) -> WorkerHealth: ...
    async def prepare(
        self, request: WorkerInvocationRequest, lease: WorkerSlotFence, context: WorkerCallContext
    ) -> PreparedInvocation: ...
    async def start(
        self, prepared: PreparedInvocation, context: WorkerCallContext
    ) -> WorkerInvocationHandle: ...
    async def inspect(
        self, handle: WorkerInvocationHandle, context: WorkerCallContext
    ) -> WorkerInvocationStatus: ...
    def events(
        self, handle: WorkerInvocationHandle, after_source_sequence: int, context: WorkerCallContext
    ) -> AsyncIterator[WorkerEvent]: ...
    async def cancel(
        self, handle: WorkerInvocationHandle, reason: str, context: WorkerCallContext
    ) -> CancelResult: ...
    async def collect(
        self, handle: WorkerInvocationHandle, context: WorkerCallContext
    ) -> WorkerResult: ...
    async def reconcile(
        self, handle: WorkerInvocationHandle, context: WorkerCallContext
    ) -> ReconciliationResult: ...
