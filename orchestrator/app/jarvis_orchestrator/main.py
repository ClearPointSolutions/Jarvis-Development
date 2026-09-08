"""Dedicated durable orchestrator entrypoint; no public listener or shell."""

import asyncio
import logging
import signal
import sys
from datetime import timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from uuid6 import uuid7

from jarvis_orchestrator.runtime.ownership import RunOwnership
from jarvis_orchestrator.runtime.service import OrchestratorService
from jarvis_persistence.database import create_async_database_engine, create_async_session_factory


class OrchestratorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JARVIS_ORCHESTRATOR_")
    database_url: str = Field(validation_alias="DATABASE_URL")
    max_concurrency: int = Field(default=2, ge=1, le=64)
    global_concurrency: int = Field(default=2, ge=1, le=256)
    lease_seconds: int = Field(default=30, ge=5, le=600)
    poll_seconds: float = Field(default=0.2, ge=0.01, le=1)
    grace_seconds: float = Field(default=10, ge=0, le=300)
    runtime_mode: Literal["real", "demo"] = "real"
    artifact_root: Path = Field(
        default=Path("var/artifacts"), validation_alias="JARVIS_ARTIFACT_ROOT"
    )


async def serve() -> None:
    settings = OrchestratorSettings()
    if settings.runtime_mode == "demo":
        from jarvis_orchestrator.demo.safety import install_network_guard

        install_network_guard(settings.database_url)
    engine = create_async_database_engine(settings.database_url)
    ownership = RunOwnership(
        create_async_session_factory(engine),
        owner=str(uuid7()),
        ttl=timedelta(seconds=settings.lease_seconds),
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    previous = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, lambda *_args: loop.call_soon_threadsafe(stop.set))
    try:
        await OrchestratorService(
            settings.database_url,
            ownership,
            max_concurrency=settings.max_concurrency,
            global_concurrency=settings.global_concurrency,
            poll_seconds=settings.poll_seconds,
            grace_seconds=settings.grace_seconds,
            demo=settings.runtime_mode == "demo",
            artifact_root=settings.artifact_root,
        ).serve(stop)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        await engine.dispose()


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(serve())
    else:
        asyncio.run(serve())


if __name__ == "__main__":
    run()
