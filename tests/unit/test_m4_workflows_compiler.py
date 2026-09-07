from __future__ import annotations

import asyncio
from itertools import pairwise, permutations
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import JsonValue

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.enums import FailureClass
from jarvis_contracts.failures import RetryRule
from jarvis_contracts.registry import (
    PermissionPolicySpec,
    RegistrySpec,
    RetryRegistrySpec,
    WorkerSpec,
)
from jarvis_contracts.workflow import (
    NodePolicy,
    WorkerSelector,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeType,
    WorkflowOutputs,
    WorkflowSpec,
)
from jarvis_contracts.workflow_api import WorkflowResolvedRevision, WorkflowResolvedSnapshot
from jarvis_contracts.workflow_nodes import NODE_DEFINITIONS
from jarvis_orchestrator.workflows import (
    CompileCache,
    MissingWorkflowHandlerError,
    NodeContext,
    WorkflowCompilationError,
    WorkflowInvariantError,
    WorkflowStateV1,
    compilation_identity,
    compile_workflow,
    normalize_workflow,
    validate_workflow,
    workflow_run_config,
)
from jarvis_orchestrator.workflows.factories import NODE_FACTORIES
from jarvis_orchestrator.workflows.state import max_map, merge_by_id, set_union


def node(node_id: str, kind: str = "router", **kwargs: Any) -> WorkflowNode:
    return WorkflowNode(
        id=node_id,
        type=WorkflowNodeType(kind),
        label=node_id,
        config=kwargs.pop("config", {}),
        **kwargs,
    )


def edge(source: str, target: str, **kwargs: Any) -> WorkflowEdge:
    return WorkflowEdge.model_validate(
        {
            "id": kwargs.pop("id", f"{source}-{target}"),
            "from": source,
            "to": target,
            "kind": kwargs.pop("kind", "always"),
            **kwargs,
        }
    )


def spec_for(
    nodes: tuple[WorkflowNode, ...], edges: tuple[WorkflowEdge, ...] = (), **kwargs: Any
) -> WorkflowSpec:
    return normalize_workflow(
        WorkflowSpec(
            key="compiler-test",
            name="Compiler acceptance",
            entrypoint=nodes[0].id,
            nodes=nodes,
            edges=edges,
            outputs=WorkflowOutputs(result_path="$.final.status"),
            **kwargs,
        )
    )


def resolved_revision(spec: RegistrySpec) -> WorkflowResolvedRevision:
    revision = WorkflowResolvedRevision(
        revision_id=uuid4(),
        configuration_id=uuid4(),
        key=f"test-{spec.kind}",
        revision=1,
        display_name="Compiler test revision",
        spec=spec,
        content_hash="0" * 64,
    )
    payload = {
        "kind": spec.kind,
        "key": revision.key,
        "revision": revision.revision,
        "schema_version": "1.0",
        "spec": {
            "spec": spec.model_dump(mode="json"),
            "display_name": revision.display_name,
            "description": revision.description,
            "enabled": revision.enabled,
            "archived": revision.archived,
        },
    }
    return revision.model_copy(update={"content_hash": sha256_digest(payload)})


def snapshot_for(
    spec: WorkflowSpec, *revisions: WorkflowResolvedRevision
) -> WorkflowResolvedSnapshot:
    return WorkflowResolvedSnapshot(workflow_content_hash=spec.content_hash, revisions=revisions)


def external_defaults() -> tuple[NodePolicy, tuple[WorkflowResolvedRevision, ...]]:
    retry = resolved_revision(RetryRegistrySpec(rules=()))
    permission = resolved_revision(
        PermissionPolicySpec(
            allowed_capabilities=("code", "git", "tests"), git="allow", shell="allow"
        )
    )
    worker = resolved_revision(WorkerSpec(capabilities=("code", "git", "tests")))
    return NodePolicy(
        timeout_seconds=2,
        retry_policy_ref=retry.revision_id,
        permission_policy_ref=permission.revision_id,
        worker_selector=WorkerSelector(revision_id=worker.revision_id),
    ), (retry, permission, worker)


async def result_handler(
    state: WorkflowStateV1, context: NodeContext, config: RunnableConfig
) -> WorkflowStateV1:
    return {"results": {context.execution_id: {"status": "succeeded", "node": context.node.id}}}


def parallel_spec() -> tuple[WorkflowSpec, WorkflowResolvedSnapshot]:
    policy, revisions = external_defaults()
    spec = spec_for(
        (
            node("fan", "fanout", config={"children": ["left", "right"], "join_id": "join"}),
            node("left", "worker"),
            node("right", "worker"),
            node("right-more"),
            node("join", "join", config={"fanout_id": "fan"}),
            node("finish", "finalize"),
        ),
        (
            edge("fan", "left"),
            edge("fan", "right"),
            edge("left", "join"),
            edge("right", "right-more"),
            edge("right-more", "join"),
            edge("join", "finish"),
        ),
        defaults=policy,
    )
    return spec, snapshot_for(spec, *revisions)


async def test_wf003_compiles_static_nodes_streams_and_reconstructs_deterministically() -> None:
    spec = spec_for((node("start"), node("finish", "finalize")), (edge("start", "finish"),))
    snapshot = snapshot_for(spec)
    graph = compile_workflow(spec, snapshot)
    assert set(graph.get_graph().nodes) == {"__start__", "start", "finish", "__end__"}
    output = await graph.ainvoke({})
    assert output["final"] == {"status": "completed"}
    assert output["counters"] == {"visit:main:start": 1, "visit:main:finish": 1}
    updates = [chunk async for chunk in graph.astream({}, stream_mode="updates")]
    assert [next(iter(chunk)) for chunk in updates] == ["start", "finish"]
    reconstructed_spec = WorkflowSpec.model_validate(spec.model_dump(mode="json", by_alias=True))
    reconstructed_snapshot = WorkflowResolvedSnapshot.model_validate(
        snapshot.model_dump(mode="json")
    )
    reconstructed = compile_workflow(reconstructed_spec, reconstructed_snapshot)
    assert await reconstructed.ainvoke({}) == output
    assert compilation_identity(spec, snapshot) == compilation_identity(
        reconstructed_spec, reconstructed_snapshot
    )
    assert set(NODE_FACTORIES) == set(NODE_DEFINITIONS) == set(WorkflowNodeType)


async def test_wf003_long_acyclic_graph_uses_derived_superstep_budget() -> None:
    nodes = (*(node(f"step-{index}") for index in range(40)), node("finish", "finalize"))
    edges = tuple(edge(first.id, second.id) for first, second in pairwise(nodes))
    spec = spec_for(nodes, edges)
    graph = compile_workflow(spec, snapshot_for(spec))
    output = await graph.ainvoke({})
    assert output["final"]["status"] == "completed"
    assert len(output["counters"]) == 41
    assert graph.config is not None and graph.config["recursion_limit"] == 43


async def test_wf003_large_retry_policy_runs_beyond_langgraph_default_limit() -> None:
    retry = resolved_revision(
        RetryRegistrySpec(
            rules=(
                RetryRule(
                    failure_class=FailureClass.CODE_TEST_FAILURE,
                    max_retries=30,
                    exhaustion_action="fail",
                ),
            )
        )
    )
    spec = spec_for(
        (
            node("retry", policy=NodePolicy(retry_policy_ref=retry.revision_id)),
            node("fail", "finalize", config={"outcome": "failed"}),
        ),
        (
            edge("retry", "retry", kind="retry", retry_class=FailureClass.CODE_TEST_FAILURE),
            edge("retry", "fail", kind="on_result", fallback=True),
        ),
    )
    graph = compile_workflow(spec, snapshot_for(spec, retry))
    output = await graph.ainvoke({"outcome": {"failure_class": "code.test_failure"}})
    assert output["counters"]["visit:main:retry"] == 31
    assert output["final"]["status"] == "failed"


def test_stable_thread_binding_preserves_native_namespace_and_input() -> None:
    original: RunnableConfig = {
        "configurable": {"checkpoint_ns": "native:child", "metadata": "run"}
    }
    bound = workflow_run_config("stable-run", original)
    assert bound["configurable"]["checkpoint_ns"] == "native:child"
    assert "thread_id" not in original["configurable"]
    assert workflow_run_config("stable-run", bound) == bound
    with pytest.raises(ValueError, match="stable checkpoint"):
        workflow_run_config("different-run", bound)
    with pytest.raises(ValueError, match="stable run"):
        workflow_run_config("")


async def test_wf003_conditional_priority_and_fallback_are_executable() -> None:
    spec = spec_for(
        (
            node("route"),
            node("first", "finalize"),
            node("second", "finalize"),
            node("other", "finalize"),
        ),
        (
            edge(
                "route",
                "second",
                kind="on_result",
                priority=2,
                when={"op": "eq", "path": "$.node.result", "value": "ok"},
            ),
            edge(
                "route",
                "first",
                kind="on_result",
                priority=1,
                when={"op": "eq", "path": "$.node.result", "value": "ok"},
            ),
            edge("route", "other", kind="on_result", fallback=True),
        ),
    )
    graph = compile_workflow(spec, snapshot_for(spec))
    output = await graph.ainvoke({"node": {"result": "ok"}})
    assert "main:first:1" in output["results"]
    assert "main:second:1" not in output["results"]
    fallback = await graph.ainvoke({"node": {"result": "unknown"}})
    assert "main:other:1" in fallback["results"]


@pytest.mark.parametrize(
    "failure_class", [None, "code.test_failure", "infrastructure.worker_transport"]
)
async def test_wf003_classified_failure_route_matches_only_its_declared_class(
    failure_class: str | None,
) -> None:
    spec = spec_for(
        (
            node("route"),
            node("failed", "finalize", config={"outcome": "failed"}),
            node("fallback", "finalize", config={"outcome": "blocked"}),
        ),
        (
            edge("route", "failed", kind="on_failure", retry_class="code.test_failure"),
            edge("route", "fallback", fallback=True),
        ),
    )
    graph = compile_workflow(spec, snapshot_for(spec))
    output = await graph.ainvoke({"outcome": {"failure_class": failure_class}})
    assert output["final"]["status"] == (
        "failed" if failure_class == "code.test_failure" else "blocked"
    )


async def test_wf003_retry_limits_are_snapshotted_and_failure_class_budgets_are_separate() -> None:
    code = FailureClass.CODE_TEST_FAILURE
    infrastructure = FailureClass.INFRASTRUCTURE_WORKER_TRANSPORT
    retry = resolved_revision(
        RetryRegistrySpec(
            rules=tuple(
                RetryRule(failure_class=kind, max_retries=limit, exhaustion_action="fail")
                for kind, limit in ((code, 2), (infrastructure, 3))
            )
        )
    )
    spec = spec_for(
        (
            node("retry", policy=NodePolicy(retry_policy_ref=retry.revision_id)),
            node("fail", "finalize", config={"outcome": "failed"}),
        ),
        (
            edge("retry", "retry", id="code-retry", kind="retry", retry_class=code, priority=1),
            edge(
                "retry",
                "retry",
                id="infra-retry",
                kind="retry",
                retry_class=infrastructure,
                priority=2,
            ),
            edge("retry", "fail", kind="on_result", fallback=True),
        ),
    )
    graph = compile_workflow(spec, snapshot_for(spec, retry))
    failed = await graph.ainvoke({"outcome": {"failure_class": code.value}})
    assert failed["counters"][f"retry:retry:{code}"] == 2
    assert failed["counters"]["visit:main:retry"] == 3
    infra = await graph.ainvoke({"outcome": {"failure_class": infrastructure.value}})
    assert infra["counters"][f"retry:retry:{infrastructure}"] == 3
    assert f"retry:retry:{code}" not in infra["counters"]
    assert infra["final"]["status"] == "failed"


@pytest.mark.parametrize(
    "progress, bound, error", [(True, 2, None), (False, 2, "monotonic"), (True, 1, "hard bound")]
)
async def test_wf003_task_iteration_is_monotonic_and_bounded(
    progress: bool, bound: int, error: str | None
) -> None:
    defaults, revisions = external_defaults()
    spec = spec_for(
        (
            node("dispatch", "task_dispatch"),
            node("integrate", "integrate"),
            node("finish", "finalize"),
        ),
        (
            edge(
                "dispatch",
                "integrate",
                kind="iterate",
                when={"op": "lt", "path": "$.tasks.terminal_count", "value": 2},
                iteration_key="tasks",
                progress_path="$.tasks.terminal_count",
                max_iterations=bound,
            ),
            edge("integrate", "dispatch"),
            edge("dispatch", "finish", kind="on_result", fallback=True),
        ),
        defaults=defaults,
    )

    async def integrate(
        state: WorkflowStateV1, context: NodeContext, config: RunnableConfig
    ) -> WorkflowStateV1:
        count = state["tasks"]["terminal_count"]
        assert isinstance(count, int)
        return {"tasks": {"terminal_count": count + int(progress), "total_count": 2}}

    graph = compile_workflow(
        spec, snapshot_for(spec, *revisions), handlers={"integrate": integrate}
    )
    if error:
        with pytest.raises(WorkflowInvariantError, match=error):
            await graph.ainvoke({"tasks": {"terminal_count": 0, "total_count": 2}})
    else:
        output = await graph.ainvoke({"tasks": {"terminal_count": 0, "total_count": 2}})
        assert output["tasks"]["terminal_count"] == 2
        assert output["counters"]["iterate:tasks"] == 2


async def test_wf005_parallel_order_preserves_results_and_joins_once() -> None:
    spec, snapshot = parallel_spec()
    outputs = []
    for slow in ("left", "right"):
        completions: list[str] = []

        async def handler(
            state: WorkflowStateV1,
            context: NodeContext,
            config: RunnableConfig,
            slow_node: str = slow,
            completed: list[str] = completions,
        ) -> WorkflowStateV1:
            if context.node.id == slow_node:
                await asyncio.sleep(0.02)
            completed.append(context.node.id)
            return await result_handler(state, context, config)

        graph = compile_workflow(spec, snapshot, handlers={"left": handler, "right": handler})
        output = await graph.ainvoke({})
        assert completions[-1] == slow
        assert (
            output["expected_children"]
            == output["completed_children"]
            == ["fan:1:left", "fan:1:right"]
        )
        assert set(output["child_results"]) == {"fan:1:left", "fan:1:right"}
        assert len(output["child_results"]["fan:1:right"]) == 2
        assert output["counters"]["visit:main:join"] == 1
        assert "main:finish:1" in output["results"]
        outputs.append(output)
    assert outputs[0] == outputs[1]


async def test_wf005_duplicate_completed_children_do_not_double_apply_or_release_join_twice() -> (
    None
):
    spec, snapshot = parallel_spec()
    graph = compile_workflow(
        spec, snapshot, handlers={"left": result_handler, "right": result_handler}
    )
    first = await graph.ainvoke({})
    redelivered = await graph.ainvoke(
        {
            "child_results": first["child_results"],
            "completed_children": first["completed_children"] * 2,
        }
    )
    assert redelivered == first
    assert redelivered["counters"]["visit:main:join"] == 1


async def test_wf005_parallel_child_failure_cannot_derive_final_success() -> None:
    spec, snapshot = parallel_spec()

    async def failed(
        state: WorkflowStateV1, context: NodeContext, config: RunnableConfig
    ) -> WorkflowStateV1:
        return {
            "results": {
                context.execution_id: {"status": "failed", "failure_class": "code.test_failure"}
            }
        }

    graph = compile_workflow(spec, snapshot, handlers={"left": failed, "right": result_handler})
    output = await graph.ainvoke({})
    assert output["final"]["status"] == "failed"
    assert len(output["child_results"]) == 2
    assert output["counters"]["visit:main:join"] == 1


def test_wf005_reducers_are_order_independent_idempotent_and_reject_conflicts() -> None:
    deliveries: list[dict[str, JsonValue]] = [
        {"a": {"value": 1}},
        {"b": {"value": 2}},
        {"a": {"value": 1}},
    ]
    for ordering in permutations(deliveries):
        result: dict[str, JsonValue] = {}
        for delivery in ordering:
            result = merge_by_id(result, delivery)
        assert result == {"a": {"value": 1}, "b": {"value": 2}}
    assert set_union(["b", "a"], ["a", "c"]) == ["a", "b", "c"]
    assert max_map({"a": 2}, {"a": 1, "b": 3}) == {"a": 2, "b": 3}
    with pytest.raises(WorkflowInvariantError, match="Conflicting"):
        merge_by_id({"a": 1}, {"a": 2})
    with pytest.raises(WorkflowInvariantError, match="nonnegative"):
        max_map({}, {"a": -1})


async def test_missing_external_handler_and_undeclared_output_fail_closed() -> None:
    defaults, revisions = external_defaults()
    spec = spec_for(
        (node("worker", "worker"), node("finish", "finalize")),
        (edge("worker", "finish"),),
        defaults=defaults,
    )
    snapshot = snapshot_for(spec, *revisions)
    with pytest.raises(MissingWorkflowHandlerError, match="no bound service"):
        await compile_workflow(spec, snapshot).ainvoke({})

    async def invalid(
        state: WorkflowStateV1, context: NodeContext, config: RunnableConfig
    ) -> WorkflowStateV1:
        return {"counters": {"retry:other": 999}}

    with pytest.raises(WorkflowInvariantError, match="outside its declared"):
        await compile_workflow(spec, snapshot, handlers={"worker": invalid}).ainvoke({})


async def test_data002_cache_binds_service_lifetimes_and_freezes_mutable_snapshot_data() -> None:
    defaults, revisions = external_defaults()
    spec = spec_for(
        (node("worker", "worker"), node("finish", "finalize")),
        (edge("worker", "finish"),),
        defaults=defaults,
    )
    snapshot = snapshot_for(spec, *revisions)
    cache = CompileCache(max_entries=2)
    saver_one, saver_two = InMemorySaver(), InMemorySaver()
    graph = compile_workflow(
        spec, snapshot, handlers={"worker": result_handler}, checkpointer=saver_one, cache=cache
    )
    assert graph is compile_workflow(
        spec, snapshot, handlers={"worker": result_handler}, checkpointer=saver_one, cache=cache
    )
    other = compile_workflow(
        spec, snapshot, handlers={"worker": result_handler}, checkpointer=saver_two, cache=cache
    )
    assert other is not graph

    async def alternate(
        state: WorkflowStateV1, context: NodeContext, config: RunnableConfig
    ) -> WorkflowStateV1:
        return {"results": {context.execution_id: "alternate"}}

    changed = compile_workflow(
        spec, snapshot, handlers={"worker": alternate}, checkpointer=saver_one, cache=cache
    )
    assert changed is not graph and len(cache) == 2
    next(node for node in spec.nodes if node.id == "worker").config["task_source"] = "tampered"
    output = await graph.ainvoke({}, workflow_run_config(str(uuid4())))
    assert output["results"]["main:worker:1"]["status"] == "succeeded"
    with pytest.raises(WorkflowCompilationError):
        compile_workflow(spec, snapshot)
    cache.close()
    assert len(cache) == 0
    clean = spec_for((node("finish", "finalize"),))
    with pytest.raises(RuntimeError, match="closed service"):
        compile_workflow(clean, snapshot_for(clean), cache=cache)


async def test_data002_handler_cannot_mutate_compiled_config_or_snapshot() -> None:
    defaults, revisions = external_defaults()
    spec = spec_for(
        (node("worker", "worker"), node("finish", "finalize")),
        (edge("worker", "finish"),),
        defaults=defaults,
    )
    snapshot = snapshot_for(spec, *revisions)
    observed: list[JsonValue] = []

    async def mutating(
        state: WorkflowStateV1, context: NodeContext, config: RunnableConfig
    ) -> WorkflowStateV1:
        observed.append(context.node.config["task_source"])
        context.node.config["task_source"] = "mutated handler copy"
        for revision in context.snapshot.revisions:
            if isinstance(revision.spec, WorkerSpec):
                assert "mutation" not in revision.spec.labels
                revision.spec.labels["mutation"] = "private copy"
        return {}

    graph = compile_workflow(spec, snapshot, handlers={"worker": mutating})
    assert await graph.ainvoke({}) == await graph.ainvoke({})
    assert observed == ["current_task", "current_task"]
    assert snapshot.snapshot_hash == snapshot_for(spec, *revisions).snapshot_hash
    with pytest.raises(ValueError, match="existing workflow"):
        compile_workflow(spec, snapshot, handlers={"unknown": mutating})
    with pytest.raises(ValueError, match="Only external"):
        compile_workflow(spec, snapshot, handlers={"finish": mutating})


@pytest.mark.parametrize("capacity", [0, 257])
def test_cache_has_explicit_resource_bounds(capacity: int) -> None:
    with pytest.raises(ValueError, match="capacity"):
        CompileCache(capacity)


def test_compile_rejects_unsupported_version_and_tampered_snapshot() -> None:
    spec = spec_for((node("finish", "finalize"),))
    with pytest.raises(WorkflowCompilationError) as error:
        compile_workflow(spec.model_copy(update={"spec_version": "1.0"}), snapshot_for(spec))
    assert not error.value.report.valid
    snapshot = snapshot_for(spec).model_copy(update={"workflow_content_hash": "0" * 64})
    assert not validate_workflow(spec, snapshot).valid
    with pytest.raises(WorkflowCompilationError):
        compile_workflow(spec, snapshot)
