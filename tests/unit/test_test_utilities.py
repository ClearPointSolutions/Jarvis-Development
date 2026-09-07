from datetime import UTC, datetime, timedelta

import pytest

from jarvis_persistence.testing import FrozenClock, SequenceIdGenerator


def test_frozen_clock_and_sequence_ids_are_deterministic() -> None:
    start = datetime(2026, 9, 7, tzinfo=UTC)
    clock = FrozenClock(start)
    identifiers = SequenceIdGenerator(start=7)

    clock.advance(timedelta(seconds=5))
    assert clock.now() == start + timedelta(seconds=5)
    assert identifiers.next().int == 7
    assert identifiers.next().int == 8


def test_frozen_clock_rejects_naive_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FrozenClock(datetime(2026, 9, 7))
