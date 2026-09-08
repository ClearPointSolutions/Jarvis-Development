"""Disposable-browser-only deterministic effect, through the real M5 service."""

import asyncio
import os
import sys
from time import monotonic

from langchain_core.runnables import RunnableConfig
from sqlalchemy.engine import make_url
from tests.integration.test_m5_effects import DeterministicAdapter
from uuid6 import uuid7

from jarvis_orchestrator.runtime.effects import EffectObservation
from jarvis_orchestrator.runtime.ownership import RunOwnership
from jarvis_orchestrator.runtime.service import OrchestratorService
from jarvis_orchestrator.workflows.factories import NodeContext
from jarvis_orchestrator.workflows.state import WorkflowStateV1
from jarvis_persistence.database import create_async_database_engine, create_async_session_factory


class BrowserEffect(DeterministicAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.deadlines: dict[str, float] = {}

    async def dispatch(
        self, identity: str, state: WorkflowStateV1, context: NodeContext, config: RunnableConfig
    ) -> None:
        await super().dispatch(identity, state, context, config)
        self.deadlines.setdefault(identity, monotonic() + 10)

    async def inspect(self, identity: str) -> EffectObservation:
        if identity not in self.cancellations and monotonic() < self.deadlines.get(identity, 0):
            return EffectObservation("running")
        return await super().inspect(identity)


async def main() -> None:
    url = os.environ["DATABASE_URL"]
    parsed = make_url(url)
    if parsed.host not in {"127.0.0.1", "localhost", "::1"} or not (
        parsed.database or ""
    ).startswith("jarvis_m2_browser_"):
        raise ValueError("Browser adapter requires the disposable loopback verification database")
    engine = create_async_database_engine(url)
    owner = RunOwnership(create_async_session_factory(engine), owner=str(uuid7()))
    try:
        await OrchestratorService(url, owner, adapters={"browser_work": BrowserEffect()}).serve(
            asyncio.Event()
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(main())
    else:
        asyncio.run(main())
