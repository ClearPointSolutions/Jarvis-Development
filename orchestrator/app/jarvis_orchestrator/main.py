"""Dedicated orchestrator process foundation.

The runtime deliberately has no job-execution behavior in M0. M1 adds durable
contracts and persistence only; queue execution starts in M5.
"""

import asyncio
import logging

LOGGER = logging.getLogger(__name__)


async def serve() -> None:
    LOGGER.info("Jarvis orchestrator foundation started; execution loop is not enabled")
    await asyncio.Event().wait()


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())


if __name__ == "__main__":
    run()
