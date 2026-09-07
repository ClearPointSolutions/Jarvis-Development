from __future__ import annotations

from uuid import uuid4

import pytest

from jarvis_contracts.workflow import WorkflowSpec
from jarvis_contracts.workflow_api import WorkflowResolvedSnapshot
from jarvis_orchestrator.workflows import (
    CompileCache,
    compilation_identity,
    compile_workflow,
    workflow_run_config,
)
from jarvis_persistence.checkpoints import postgres_saver
from tests.unit.test_m4_workflows_compiler import (
    edge,
    node,
    parallel_spec,
    result_handler,
    snapshot_for,
    spec_for,
)

pytestmark = [pytest.mark.integration, pytest.mark.compatibility]


async def test_wf003_compiler_postgres_stream_and_resume_after_process_reconstruction(
    database_url: str,
) -> None:
    spec = spec_for((node("first"), node("finish", "finalize")), (edge("first", "finish"),))
    snapshot = snapshot_for(spec)
    config = workflow_run_config(
        f"m4-compiler-{uuid4()}", {"configurable": {"jarvis_workflow_version_id": str(uuid4())}}
    )
    assert "checkpoint_ns" not in config["configurable"]
    async with postgres_saver(database_url, setup=True) as saver:
        cache = CompileCache()
        graph = compile_workflow(
            spec, snapshot, checkpointer=saver, cache=cache, interrupt_before=["finish"]
        )
        updates = [chunk async for chunk in graph.astream({}, config, stream_mode="updates")]
        assert "first" in updates[0]
        waiting = await graph.aget_state(config)
        assert waiting.next == ("finish",)
        assert waiting.config["configurable"]["thread_id"] == config["configurable"]["thread_id"]
        assert waiting.config["configurable"]["checkpoint_ns"] == ""
        cache.close()

    reconstructed_spec = WorkflowSpec.model_validate_json(spec.model_dump_json(by_alias=True))
    reconstructed_snapshot = WorkflowResolvedSnapshot.model_validate_json(
        snapshot.model_dump_json()
    )
    assert compilation_identity(spec, snapshot) == compilation_identity(
        reconstructed_spec, reconstructed_snapshot
    )
    async with postgres_saver(database_url, setup=True) as saver:
        graph = compile_workflow(reconstructed_spec, reconstructed_snapshot, checkpointer=saver)
        restored = await graph.aget_state(config)
        assert restored.values == waiting.values
        resumed = await graph.ainvoke(None, config)
        assert resumed["final"] == {"status": "completed"}
        assert resumed["counters"]["visit:main:first"] == 1
        assert resumed["counters"]["visit:main:finish"] == 1
        assert (await graph.aget_state(config)).next == ()


async def test_wf005_native_parallel_checkpoints_preserve_langgraph_namespaces_and_join_once(
    database_url: str,
) -> None:
    spec, snapshot = parallel_spec()
    config = workflow_run_config(f"m4-parallel-{uuid4()}")
    handlers = {"left": result_handler, "right": result_handler}
    async with postgres_saver(database_url, setup=True) as saver:
        graph = compile_workflow(
            spec, snapshot, checkpointer=saver, handlers=handlers, interrupt_before=["finish"]
        )
        await graph.ainvoke({}, config)
        waiting = await graph.aget_state(config)
        assert waiting.next == ("finish",)
        assert waiting.values["counters"]["visit:main:join"] == 1
        checkpoints = [item async for item in saver.alist(config)]
        namespaces = {item.config["configurable"]["checkpoint_ns"] for item in checkpoints}
        assert "" in namespaces
        assert any(value.startswith("left:") for value in namespaces)
        assert any(value.startswith("right:") for value in namespaces)

    async with postgres_saver(database_url, setup=True) as saver:
        reconstructed = compile_workflow(spec, snapshot, checkpointer=saver, handlers=handlers)
        output = await reconstructed.ainvoke(None, config)
        assert output["counters"]["visit:main:join"] == 1
        assert output["expected_children"] == output["completed_children"]
        assert len(output["child_results"]) == 2
        assert output["final"]["status"] == "completed"
