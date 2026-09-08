"""Explicit no-op fault boundaries for deterministic crash-injection tests."""

from collections.abc import Callable

FaultHook = Callable[[str], None]


def no_fault(_point: str) -> None:
    pass
