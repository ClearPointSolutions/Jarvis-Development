"""M6 implementations of the reusable worker/publication effect boundaries."""

from jarvis_contracts.registry import ValidationReport, WorkerSpec
from jarvis_orchestrator.demo.adapters import DemoEffectAdapter
from jarvis_orchestrator.providers.demo import DemoWorker


class DemoWorkerAdapter(DemoEffectAdapter):
    def validate(self, worker: WorkerSpec) -> ValidationReport:
        return DemoWorker(worker).validate()

    async def health(self) -> ValidationReport:
        return ValidationReport(
            valid=self.fixture.health in {"healthy", "degraded"},
            health=self.fixture.health,
            demo=True,
        )


class DemoPublicationAdapter(DemoEffectAdapter):
    async def health(self) -> ValidationReport:
        return ValidationReport(
            valid=self.fixture.health in {"healthy", "degraded"},
            health=self.fixture.health,
            demo=True,
        )
