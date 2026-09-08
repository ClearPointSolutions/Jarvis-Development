"""Fence native PostgresSaver writes in the checkpoint transaction itself.

The pinned saver routes checkpoint/blob/pending writes through `_cursor`. Taking
the run row lock in that same PostgreSQL transaction prevents ownership changing
between the fence check and checkpoint commit. No LangGraph schema is replaced.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection, AsyncCursor
from psycopg.rows import DictRow, dict_row

from jarvis_orchestrator.runtime.ownership import RunFence, StaleExecutorError
from jarvis_persistence.checkpoints import psycopg_connection_string


class FencedPostgresSaver(AsyncPostgresSaver):
    def __init__(self, connection: AsyncConnection[DictRow], fence: RunFence) -> None:
        super().__init__(connection)
        self.connection = connection
        self.fence = fence

    @asynccontextmanager
    async def _cursor(self, *, pipeline: bool = False) -> AsyncIterator[AsyncCursor[DictRow]]:
        async with (
            self.lock,
            self.connection.transaction(),
            self.connection.cursor(
                binary=True,
                row_factory=dict_row,
            ) as cursor,
        ):
            if pipeline:
                await cursor.execute(
                    "SELECT id FROM control.runs WHERE id = %s FOR UPDATE",
                    (self.fence.run_id,),
                )
                await self._check(cursor)
            yield cursor
            if pipeline:
                await self._check(cursor)

    async def _check(self, cursor: AsyncCursor[DictRow]) -> None:
        await cursor.execute(
            "SELECT 1 FROM control.run_leases l JOIN control.runs r ON r.id=l.run_id "
            "WHERE l.run_id=%s AND l.owner_instance_id=%s AND l.generation=%s "
            "AND l.released_at IS NULL AND l.expires_at > clock_timestamp() "
            "AND r.status NOT IN ('completed','failed','blocked','cancelled')",
            (self.fence.run_id, self.fence.owner, self.fence.generation),
        )
        if await cursor.fetchone() is None:
            raise StaleExecutorError("Checkpoint write rejected by run lease fence")


@asynccontextmanager
async def fenced_saver(database_url: str, fence: RunFence) -> AsyncIterator[FencedPostgresSaver]:
    connection = await AsyncConnection.connect(
        psycopg_connection_string(database_url),
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    try:
        await connection.execute("SET search_path TO langgraph, public")
        yield FencedPostgresSaver(connection, fence)
    finally:
        await connection.close()
