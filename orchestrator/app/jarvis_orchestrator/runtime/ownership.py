"""Short PostgreSQL queue transactions and fenced executor transactions.

No transaction here spans an adapter await. All event mutations preserve M2's
global-counter-before-aggregate lock order. Higher numeric priority claims first.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import exists, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis_api.events.normalizer import EventIntent, EventNormalizer, EventWriter
from jarvis_api.events.redaction import RecursiveRedactor
from jarvis_contracts.enums import EventMode, EventSeverity, EventVisibility
from jarvis_contracts.event_registry import event_definition
from jarvis_contracts.events import EventScope, EventSource
from jarvis_orchestrator.runtime.faults import FaultHook, no_fault
from jarvis_persistence.models import (
    EventGlobalCounterModel,
    OrchestratorInstanceModel,
    RunLeaseModel,
    RunModel,
)
from jarvis_persistence.repositories import EventRepository, LeaseRepository
from jarvis_persistence.testing import Clock, SystemClock

TERMINAL = frozenset({"completed", "failed", "blocked", "cancelled"})


class StaleExecutorError(RuntimeError):
    """The executor no longer has authority; its transaction must roll back."""


@dataclass(frozen=True)
class RunFence:
    run_id: UUID
    owner: str
    generation: int


def runtime_writer() -> EventWriter:
    return EventWriter(
        normalizer=EventNormalizer(
            redactor=RecursiveRedactor(),
            artifact_sink=None,
            inline_bytes=32_768,
            max_bytes=65_536,
        ),
        repository=EventRepository(),
    )


async def lock_events(session: AsyncSession) -> None:
    counter = await session.scalar(
        select(EventGlobalCounterModel).where(EventGlobalCounterModel.id == 1).with_for_update()
    )
    if counter is None:
        raise RuntimeError("Event store has not been migrated")


class RunOwnership:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        owner: str,
        ttl: timedelta = timedelta(seconds=30),
        clock: Clock | None = None,
        writer: EventWriter | None = None,
        fault: FaultHook = no_fault,
    ) -> None:
        if not owner or len(owner) > 160 or ttl <= timedelta(0):
            raise ValueError("A bounded owner identity and positive lease TTL are required")
        self.sessions = sessions
        self.owner = owner
        self.ttl = ttl
        self.clock = clock or SystemClock()
        self.writer = writer or runtime_writer()
        self.fault = fault

    async def register(self) -> None:
        async with self.sessions.begin() as session:
            if await session.get(OrchestratorInstanceModel, self.owner) is not None:
                raise ValueError("Every process start must use a new orchestrator identity")
            now = self.clock.now()
            session.add(
                OrchestratorInstanceModel(
                    id=self.owner,
                    started_at=now,
                    heartbeat_at=now,
                    draining=False,
                    version="0.1.0",
                )
            )

    async def heartbeat(self, *, draining: bool = False) -> None:
        async with self.sessions.begin() as session:
            row = await session.get(OrchestratorInstanceModel, self.owner, with_for_update=True)
            if row is None:
                raise RuntimeError("Orchestrator is not registered")
            row.heartbeat_at = self.clock.now()
            row.draining = row.draining or draining

    async def event(
        self,
        session: AsyncSession,
        run: RunModel,
        name: str,
        data: dict[str, JsonValue] | None = None,
    ) -> None:
        definition = event_definition(name)
        payload = data or {}
        if definition is None or definition.payload_model is None:
            payload = {"status": run.status, **payload}
        await self.writer.append(
            session,
            EventIntent(
                occurred_at=self.clock.now(),
                type=name,
                severity=EventSeverity.INFO,
                mode=EventMode(run.mode),
                visibility=EventVisibility.OWNER,
                scope=EventScope(
                    run_id=run.id,
                    **{
                        key: value
                        for key, value in (data or {}).items()
                        if key
                        in {"node_execution_id", "workflow_node_id", "task_id", "task_attempt_id"}
                    },
                ),
                source=EventSource(
                    kind="api" if self.owner == "control-api" else "orchestrator",
                    name="runtime",
                    instance_id=self.owner,
                ),
                correlation_id=str(run.id),
                data=payload,
            ),
        )

    async def claim(
        self, *, capacity: int | None = None, mode: Literal["real", "demo"] | None = None
    ) -> RunFence | None:
        async with self.sessions.begin() as session:
            await lock_events(session)
            instance = await session.get(OrchestratorInstanceModel, self.owner)
            if instance is None or instance.draining:
                return None
            now = self.clock.now()
            if capacity is not None:
                active = await session.scalar(
                    select(func.count())
                    .select_from(RunLeaseModel)
                    .where(
                        RunLeaseModel.released_at.is_(None),
                        RunLeaseModel.expires_at > now,
                    )
                )
                if (active or 0) >= capacity:
                    return None
            live = exists().where(
                RunLeaseModel.run_id == RunModel.id,
                RunLeaseModel.released_at.is_(None),
                RunLeaseModel.expires_at > now,
            )
            run = await session.scalar(
                select(RunModel)
                .where(
                    RunModel.status.in_(
                        ("queued", "claiming", "running", "pause_requested", "cancel_requested")
                    ),
                    RunModel.claimable_at <= now,
                    RunModel.mode == mode if mode is not None else true(),
                    ~live,
                )
                .order_by(
                    RunModel.priority.desc(),
                    RunModel.claimable_at,
                    RunModel.created_at,
                    RunModel.id,
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if run is None:
                return None
            previous = await session.scalar(
                select(func.max(RunLeaseModel.generation)).where(
                    RunLeaseModel.run_id == run.id,
                )
            )
            lease = await LeaseRepository(self.clock).acquire(
                session,
                run_id=run.id,
                owner_instance_id=self.owner,
                ttl=self.ttl,
            )
            if lease is None:
                return None
            lease.heartbeat_at = now
            recovering = previous is not None and run.status != "queued"
            run.runtime_json = {**run.runtime_json, "recovering": recovering}
            if recovering:
                await self.event(session, run, "lease.expired")
                await self.event(session, run, "run.recovering")
            run.status = "claiming"
            run.version += 1
            await self.event(session, run, "run.claimed")
            return RunFence(run.id, self.owner, lease.generation)

    @asynccontextmanager
    async def fenced(self, fence: RunFence) -> AsyncIterator[tuple[AsyncSession, RunModel]]:
        async with self.sessions.begin() as session:
            await lock_events(session)
            run = await session.scalar(
                select(RunModel).where(RunModel.id == fence.run_id).with_for_update()
            )
            lease = await session.scalar(
                select(RunLeaseModel)
                .where(
                    RunLeaseModel.run_id == fence.run_id,
                    RunLeaseModel.released_at.is_(None),
                )
                .with_for_update()
            )
            if (
                run is None
                or run.status in TERMINAL
                or lease is None
                or lease.owner_instance_id != fence.owner
                or lease.generation != fence.generation
                or lease.expires_at <= self.clock.now()
            ):
                raise StaleExecutorError("Expired, superseded or terminal run executor")
            yield session, run
            # Reject transactions whose lease expired while application work ran.
            if lease.expires_at <= self.clock.now():
                raise StaleExecutorError("Lease expired before authoritative commit")

    async def renew(self, fence: RunFence) -> None:
        async with self.fenced(fence) as (session, _run):
            lease = await session.scalar(
                select(RunLeaseModel).where(
                    RunLeaseModel.run_id == fence.run_id,
                    RunLeaseModel.generation == fence.generation,
                )
            )
            assert lease is not None
            lease.heartbeat_at = self.clock.now()
            lease.expires_at = self.clock.now() + self.ttl

    async def release(self, fence: RunFence) -> None:
        async with self.fenced(fence) as (session, _run):
            await self.release_in(session, fence)

    async def release_in(self, session: AsyncSession, fence: RunFence) -> None:
        lease = await session.scalar(
            select(RunLeaseModel).where(
                RunLeaseModel.run_id == fence.run_id,
                RunLeaseModel.generation == fence.generation,
                RunLeaseModel.owner_instance_id == fence.owner,
            )
        )
        if lease is None:
            raise StaleExecutorError("Run lease disappeared")
        lease.released_at = self.clock.now()
