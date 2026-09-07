"""Durable event replay and SSE framing with PostgreSQL wakeups."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Final, Protocol
from uuid import UUID

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis_contracts.api import EventStreamReset
from jarvis_contracts.events import NormalizedEvent
from jarvis_persistence.repositories import (
    EventCursorExpiredError,
    EventRepository,
    RunSequenceGapError,
    UnsupportedEventSchemaError,
)

_CHANNEL: Final = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class WakeupSubscription(Protocol):
    async def wait(self, timeout: float) -> bool: ...


class EventWakeupSource(Protocol):
    def subscribe(self) -> AbstractAsyncContextManager[WakeupSubscription]: ...


class _PostgresSubscription:
    def __init__(self, connection: psycopg.AsyncConnection[object]) -> None:
        self._connection = connection

    async def wait(self, timeout: float) -> bool:
        async for _notification in self._connection.notifies(timeout=timeout, stop_after=1):
            return True
        return False


class PostgresEventWakeups:
    """Dedicated LISTEN connections; notification payloads are never event data."""

    def __init__(self, database_url: str, *, channel: str = "jarvis_v1_events") -> None:
        if _CHANNEL.fullmatch(channel) is None:
            raise ValueError("PostgreSQL notification channel is invalid")
        parsed = make_url(database_url)
        self._conninfo = parsed.set(drivername="postgresql").render_as_string(hide_password=False)
        self._channel = channel

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[WakeupSubscription]:
        connection = await psycopg.AsyncConnection.connect(self._conninfo, autocommit=True)
        try:
            await connection.execute(sql.SQL("LISTEN {}").format(sql.Identifier(self._channel)))
            yield _PostgresSubscription(connection)
        finally:
            await connection.close()


class _PollingSubscription:
    async def wait(self, timeout: float) -> bool:
        await asyncio.sleep(timeout)
        return False


class PollingEventWakeups:
    """Safe fallback and deterministic proof that NOTIFY loss cannot lose delivery."""

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[WakeupSubscription]:
        yield _PollingSubscription()


def encode_event_frame(event: NormalizedEvent) -> str:
    payload = event.model_dump_json(exclude_none=False)
    return f"id: {event.global_position}\nevent: jarvis.event\ndata: {payload}\n\n"


def encode_reset_frame(reset: EventStreamReset) -> str:
    payload = reset.model_dump_json(exclude_none=False)
    return f"event: stream.reset\ndata: {payload}\n\n"


def resolve_event_cursor(*, after: int, last_event_id: str | None) -> int:
    """Honor the standard reconnect header over the initial query cursor."""

    if after < 0:
        raise ValueError("event cursor cannot be negative")
    if last_event_id is None or not last_event_id.strip():
        return after
    if not last_event_id.isascii() or not last_event_id.isdecimal():
        raise ValueError("Last-Event-ID must be a nonnegative integer")
    return int(last_event_id)


class EventStream:
    """Replay committed rows, then use notifications only to reduce query latency."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        repository: EventRepository,
        wakeups: EventWakeupSource,
        page_size: int,
        poll_seconds: float,
        keepalive_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if page_size < 1 or page_size > 1_000:
            raise ValueError("stream page size must be between 1 and 1000")
        if poll_seconds <= 0 or keepalive_seconds <= 0:
            raise ValueError("stream timings must be positive")
        self._sessions = session_factory
        self._repository = repository
        self._wakeups = wakeups
        self._page_size = page_size
        self._poll_seconds = poll_seconds
        self._keepalive_seconds = keepalive_seconds
        self._monotonic = monotonic

    async def iter_frames(
        self,
        *,
        run_id: UUID,
        after: int,
        is_disconnected: Callable[[], Awaitable[bool]] | None = None,
    ) -> AsyncIterator[str]:
        cursor = after
        last_keepalive = self._monotonic()
        async with self._wakeups.subscribe() as subscription:
            while True:
                try:
                    async with self._sessions() as session:
                        page = await self._repository.page(
                            session,
                            run_id=run_id,
                            after=cursor,
                            limit=self._page_size,
                        )
                except EventCursorExpiredError as error:
                    yield encode_reset_frame(
                        EventStreamReset(
                            reason="cursor_expired",
                            earliest_position=error.earliest,
                            latest_position=error.latest,
                        )
                    )
                    return
                except UnsupportedEventSchemaError as error:
                    yield encode_reset_frame(
                        EventStreamReset(
                            reason="unsupported_schema",
                            latest_position=error.global_position,
                        )
                    )
                    return
                except RunSequenceGapError as error:
                    yield encode_reset_frame(
                        EventStreamReset(
                            reason="run_sequence_gap",
                            latest_position=error.global_position,
                        )
                    )
                    return

                for event in page.items:
                    cursor = event.global_position
                    yield encode_event_frame(event)
                if page.next_after is not None:
                    cursor = page.next_after
                    continue
                if is_disconnected is not None and await is_disconnected():
                    return

                await subscription.wait(self._poll_seconds)
                now = self._monotonic()
                if now - last_keepalive >= self._keepalive_seconds:
                    yield ": keepalive\n\n"
                    last_keepalive = now


class SseConnectionLimitError(RuntimeError):
    """A principal exceeded the per-process stream safety limit."""


class SseConnectionLimiter:
    def __init__(self, maximum_per_principal: int) -> None:
        if maximum_per_principal < 1:
            raise ValueError("SSE connection limit must be positive")
        self._maximum = maximum_per_principal
        self._active: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def claim(self, principal_key: str) -> bool:
        async with self._lock:
            active = self._active.get(principal_key, 0)
            if active >= self._maximum:
                return False
            self._active[principal_key] = active + 1
            return True

    async def release(self, principal_key: str) -> None:
        async with self._lock:
            remaining = self._active.get(principal_key, 1) - 1
            if remaining:
                self._active[principal_key] = remaining
            else:
                self._active.pop(principal_key, None)

    @asynccontextmanager
    async def acquire(self, principal_key: str) -> AsyncIterator[None]:
        if not await self.claim(principal_key):
            raise SseConnectionLimitError("SSE connection limit exceeded")
        try:
            yield
        finally:
            await self.release(principal_key)


def parse_sse_data(frame: str) -> dict[str, object]:
    """Small test/debug helper that never interprets event data as markup."""

    data_line = next(line for line in frame.splitlines() if line.startswith("data: "))
    value = json.loads(data_line.removeprefix("data: "))
    if not isinstance(value, dict):
        raise ValueError("SSE frame data must be an object")
    return value
