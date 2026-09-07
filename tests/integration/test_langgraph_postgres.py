from __future__ import annotations

from importlib.metadata import version
from typing import Any, TypedDict
from uuid import uuid4

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import create_engine, text

from jarvis_persistence.checkpoints import postgres_saver

pytestmark = [pytest.mark.integration, pytest.mark.compatibility]


class ApprovalState(TypedDict, total=False):
    request: str
    approved: bool


def approval_gate(state: ApprovalState) -> ApprovalState:
    decision = interrupt({"kind": "approval", "request": state["request"]})
    return {"approved": bool(decision["approved"])}


def build_approval_graph() -> StateGraph[ApprovalState]:
    builder = StateGraph(ApprovalState)
    builder.add_node("approval", approval_gate)
    builder.add_edge(START, "approval")
    builder.add_edge("approval", END)
    return builder


async def test_postgres_saver_persists_stable_thread_and_resumes_interrupt(
    database_url: str,
) -> None:
    assert version("langgraph-checkpoint-postgres") == "3.1.2"
    thread_id = f"m1-compat-{uuid4()}"
    config: RunnableConfig = {
        "configurable": {
            "thread_id": thread_id,
            "jarvis_run_id": str(uuid4()),
            "jarvis_workflow_version_id": "compatibility-workflow-v1",
        }
    }
    initial: ApprovalState = {"request": "continue?"}
    builder = build_approval_graph()

    async with postgres_saver(database_url, setup=True) as saver:
        graph = builder.compile(checkpointer=saver)
        streamed = [
            chunk async for chunk in graph.astream(initial, config=config, stream_mode="updates")
        ]
        assert any("__interrupt__" in chunk for chunk in streamed)
        waiting = await graph.aget_state(config)
        assert waiting.next == ("approval",)
        assert waiting.values["request"] == "continue?"

    async with postgres_saver(database_url, setup=True) as restarted_saver:
        restarted_graph = builder.compile(checkpointer=restarted_saver)
        restored = await restarted_graph.aget_state(config)
        assert restored.next == ("approval",)
        resume_command: Command[Any] = Command(resume={"approved": True})
        resumed = await restarted_graph.ainvoke(resume_command, config=config)
        assert resumed["approved"] is True
        final = await restarted_graph.aget_state(config)
        assert final.next == ()
        assert final.values["approved"] is True

    engine = create_engine(database_url)
    with engine.connect() as connection:
        tables = set(
            connection.scalars(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'langgraph'"
                )
            )
        )
    engine.dispose()
    assert {"checkpoints", "checkpoint_blobs", "checkpoint_writes"}.issubset(tables)
