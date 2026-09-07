"""Deterministic test clocks and UUID generators shared by persistence tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    def __init__(self, current: datetime) -> None:
        if current.tzinfo is None:
            raise ValueError("FrozenClock requires a timezone-aware value")
        self._current = current

    def now(self) -> datetime:
        return self._current

    def advance(self, delta: timedelta) -> None:
        self._current += delta


class IdGenerator(Protocol):
    def next(self) -> UUID: ...


class SequenceIdGenerator:
    def __init__(self, start: int = 1) -> None:
        self._next = start

    def next(self) -> UUID:
        value = UUID(int=self._next)
        self._next += 1
        return value
