"""Cross-platform pytest bootstrap."""

from __future__ import annotations

import asyncio
import sys
from typing import Any, cast


def pytest_configure() -> None:
    """Psycopg async requires SelectorEventLoop on Windows."""

    if sys.platform == "win32":
        policy_type = cast(Any, asyncio).WindowsSelectorEventLoopPolicy
        asyncio.set_event_loop_policy(policy_type())
