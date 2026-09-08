"""Worker selection by immutable revision and adapter kind, shared with DEMO."""

from collections.abc import Callable, Mapping
from uuid import UUID

from jarvis_contracts.registry import WorkerSpec
from jarvis_orchestrator.runtime.effects import EffectAdapter
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership
from jarvis_orchestrator.workers.safety import WorkerBoundaryError

WorkerFactory = Callable[[RunOwnership, RunFence, UUID, WorkerSpec], EffectAdapter]


class WorkerRuntimeRegistry:
    def __init__(self, factories: Mapping[str, WorkerFactory]) -> None:
        self.factories = dict(factories)

    def resolve(
        self,
        revision_id: UUID,
        worker: WorkerSpec,
        ownership: RunOwnership,
        fence: RunFence,
        *,
        demo: bool,
    ) -> EffectAdapter:
        if demo and worker.adapter_kind != "demo":
            raise WorkerBoundaryError("demo_worker_boundary_denied")
        if not demo and worker.adapter_kind == "demo":
            raise WorkerBoundaryError("real_worker_boundary_denied")
        factory = self.factories.get(worker.adapter_kind)
        if factory is None:
            raise WorkerBoundaryError("worker_adapter_unconfigured")
        return factory(ownership, fence, revision_id, worker)
