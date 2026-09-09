"""Dedicated bounded queue consumer; HTTP requests never own execution."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from contextlib import suppress
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, cast

from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from jarvis_contracts.workflow import WorkflowSpec
from jarvis_contracts.workflow_api import WorkflowResolvedSnapshot
from jarvis_orchestrator.runtime.binding import configuration_digest
from jarvis_orchestrator.runtime.checkpoints import fenced_saver
from jarvis_orchestrator.runtime.commands import CommandProcessor
from jarvis_orchestrator.runtime.effects import EffectAdapter, EffectLedger
from jarvis_orchestrator.runtime.nodes import NodeRuntime
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership, StaleExecutorError
from jarvis_orchestrator.workers.registry import WorkerRuntimeRegistry
from jarvis_orchestrator.workflows import compile_workflow, workflow_run_config
from jarvis_orchestrator.workflows.state import WorkflowStateV1
from jarvis_persistence.models import (
    JobModel,
    NodeExecutionModel,
    RunConfigSnapshotModel,
    WorkflowVersionModel,
)

if TYPE_CHECKING:
    from jarvis_orchestrator.runtime.composition import RealComposition


class OrchestratorService:
    def __init__(
        self,
        database_url: str,
        ownership: RunOwnership,
        *,
        max_concurrency: int = 2,
        global_concurrency: int = 2,
        poll_seconds: float = 0.2,
        grace_seconds: float = 10,
        adapters: Mapping[str, EffectAdapter] | None = None,
        demo: bool = False,
        artifact_root: Path = Path("var/artifacts"),
        worker_registry: WorkerRuntimeRegistry | None = None,
        verification_factory: Callable[[RunOwnership, RunFence], EffectAdapter] | None = None,
        real_composition: RealComposition | None = None,
    ) -> None:
        if (
            not 1 <= max_concurrency <= 64
            or not 1 <= global_concurrency <= 256
            or poll_seconds <= 0
            or grace_seconds < 0
        ):
            raise ValueError("Invalid orchestrator resource limits")
        self.database_url = database_url
        self.ownership = ownership
        self.max_concurrency = max_concurrency
        self.global_concurrency = global_concurrency
        self.poll_seconds = poll_seconds
        self.grace_seconds = grace_seconds
        self.adapters = dict(adapters or {})
        self.demo = demo
        self.artifact_root = artifact_root
        self.worker_registry = worker_registry
        self.verification_factory = verification_factory
        self.real_composition = real_composition
        self.commands = CommandProcessor(ownership)
        self.active: dict[RunFence, asyncio.Task[None]] = {}

    async def serve(self, stop: asyncio.Event) -> None:
        if self.demo:
            # Cold adapter imports can consume a short lease and block its
            # heartbeat. Load trusted runtime code before claiming any work.
            for module in (
                "jarvis_orchestrator.demo.adapters",
                "jarvis_orchestrator.demo.boundaries",
                "jarvis_orchestrator.demo.decision",
                "jarvis_orchestrator.demo.safety",
            ):
                await asyncio.to_thread(import_module, module)
        await self.ownership.register()
        try:
            while not stop.is_set():
                try:
                    await self.tick()
                except OperationalError:
                    logging.getLogger(__name__).warning(
                        "Database unavailable; queue polling will retry"
                    )
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), self.poll_seconds)
        finally:
            await self.ownership.heartbeat(draining=True)
            if self.active:
                deadline = asyncio.get_running_loop().time() + self.grace_seconds
                pending = set(self.active.values())
                while pending and asyncio.get_running_loop().time() < deadline:
                    for fence, task in self.active.items():
                        if not task.done():
                            with suppress(StaleExecutorError):
                                await self.ownership.renew(fence)
                    _, pending = await asyncio.wait(
                        pending,
                        timeout=min(
                            self.poll_seconds, max(0, deadline - asyncio.get_running_loop().time())
                        ),
                    )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*self.active.values(), return_exceptions=True)
                # Expired leases are recovered normally; no unsafe result is inferred.

    async def tick(self) -> None:
        await self.ownership.heartbeat()
        await self.commands.poll()
        if self.real_composition is not None:
            from jarvis_orchestrator.runtime.approvals import expire_approvals

            await expire_approvals(self.ownership)
        for fence, task in list(self.active.items()):
            if task.done():
                del self.active[fence]
                task.result()
            else:
                try:
                    await self.ownership.renew(fence)
                except StaleExecutorError:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    del self.active[fence]
        while len(self.active) < self.max_concurrency:
            claimed = await self.ownership.claim(
                capacity=self.global_concurrency, mode="demo" if self.demo else "real"
            )
            if claimed is None:
                break
            self.active[claimed] = asyncio.create_task(self.execute(claimed))

    async def execute(self, fence: RunFence) -> None:
        try:
            await self._execute(fence)
        except StaleExecutorError:
            logging.getLogger(__name__).warning(
                "Discarded stale executor run=%s generation=%s", fence.run_id, fence.generation
            )
            return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            from jarvis_orchestrator.runtime.errors import RuntimeDependencyError

            # Never emit native exception text; it may contain credentials/output.
            logging.getLogger(__name__).warning(
                "Runtime exception_type=%s run=%s", type(error).__name__, fence.run_id
            )
            try:
                async with self.ownership.fenced(fence) as (session, run):
                    run.status = "blocked"
                    run.result_summary = (
                        str(error)
                        if isinstance(error, RuntimeDependencyError)
                        else "Runtime requires configuration or effect reconciliation"
                    )
                    run.current_node = None
                    run.completed_at = self.ownership.clock.now()
                    run.version += 1
                    job = await session.get(JobModel, run.job_id)
                    assert job is not None
                    job.status = "blocked"
                    for node in (
                        await session.scalars(
                            select(NodeExecutionModel).where(
                                NodeExecutionModel.run_id == run.id,
                                NodeExecutionModel.status.in_(
                                    ("running", "queued", "waiting", "interrupted")
                                ),
                            )
                        )
                    ).all():
                        node.status = "failed"
                        node.completed_at = self.ownership.clock.now()
                        await self.ownership.event(
                            session, run, "node.failed", {"node_execution_id": str(node.id)}
                        )
                    await self.ownership.event(session, run, "run.blocked")
                    await self.ownership.release_in(session, fence)
            except StaleExecutorError:
                pass

    async def _execute(self, fence: RunFence) -> None:
        async with self.ownership.fenced(fence) as (session, run):
            version = await session.get(WorkflowVersionModel, run.workflow_version_id)
            snapshot_row = await session.get(RunConfigSnapshotModel, run.config_snapshot_id)
            if version is None or version.published_at is None or snapshot_row is None:
                raise ValueError("Run has no published immutable workflow")
            spec = WorkflowSpec.model_validate(version.spec_json)
            snapshot = WorkflowResolvedSnapshot.model_validate(
                snapshot_row.effective_spec_json["snapshot"]
            )
            if snapshot.workflow_content_hash != version.content_hash:
                raise ValueError("Workflow and snapshot hash disagree")
            if (
                snapshot_row.workflow_version_id != version.id
                or snapshot_row.snapshot_hash
                != configuration_digest(version.id, snapshot_row.effective_spec_json)
            ):
                raise ValueError("Immutable run snapshot identity is invalid")
            thread = run.langgraph_thread_id
            job = await session.get(JobModel, run.job_id)
            assert job is not None
            objective = job.objective
            mode = run.mode
            fixture_data = run.runtime_json.get("demo_fixture", {})
            job.status = "active"
            cancelling = run.desired_state == "cancelled"
            first = run.started_at is None
            run.started_at = run.started_at or self.ownership.clock.now()
            run.status = {"paused": "pause_requested", "cancelled": "cancel_requested"}.get(
                run.desired_state, "running"
            )
            run.version += 1
            if first or run.runtime_json.get("recovering"):
                await self.ownership.event(
                    session, run, "run.started" if first else "run.recovered"
                )
        nodes = NodeRuntime(self.ownership, fence)
        ledger = EffectLedger(self.ownership, fence)
        adapters = self.adapters
        decision_handler = None
        worker_registry = self.worker_registry
        if (mode == "demo") != self.demo:
            raise ValueError("Orchestrator runtime mode does not match queued run")
        if self.real_composition is not None:
            if self.demo:
                raise ValueError("DEMO cannot construct real infrastructure adapters")
            adapters = await self.real_composition.build(
                self.ownership, fence, spec, snapshot, version.id
            )
            decision_handler = await self.real_composition.approvals(
                self.ownership, fence, spec, version.id
            )
            from jarvis_contracts.workflow_nodes import NODE_DEFINITIONS

            missing_handlers = [
                node.id
                for node in spec.nodes
                if NODE_DEFINITIONS[node.type].external
                and node.type.value != "approval"
                and node.id not in adapters
            ]
            if missing_handlers:
                raise ValueError("required runtime handlers are unavailable")
        if self.demo:
            from jarvis_contracts.demo import DemoFixture
            from jarvis_orchestrator.demo.adapters import DemoEffectAdapter
            from jarvis_orchestrator.demo.boundaries import (
                DemoPublicationAdapter,
                DemoWorkerAdapter,
            )
            from jarvis_orchestrator.demo.decision import demo_decision
            from jarvis_orchestrator.demo.safety import validate_demo_snapshot
            from jarvis_orchestrator.runtime.adapters import PublicationAdapter

            if mode != "demo":
                raise ValueError("Demo service refuses real runs")
            validate_demo_snapshot(snapshot)
            adapter = DemoEffectAdapter(
                self.ownership, fence, self.artifact_root, DemoFixture.model_validate(fixture_data)
            )
            worker_registry = WorkerRuntimeRegistry(
                {
                    "demo": lambda owner, claimed, _revision, _spec: DemoWorkerAdapter(
                        owner, claimed, self.artifact_root, adapter.fixture
                    )
                }
            )
            publication: PublicationAdapter = DemoPublicationAdapter(
                self.ownership, fence, self.artifact_root, adapter.fixture
            )
            adapters = {
                node.id: publication if node.type.value == "github_publish" else adapter
                for node in spec.nodes
                if node.type.value
                in {
                    "organizer",
                    "architect",
                    "worker",
                    "verify",
                    "reviewer",
                    "integrate",
                    "github_publish",
                }
            }
            decision_handler = demo_decision(self.ownership, fence)
        if worker_registry is not None:
            from jarvis_contracts.registry import WorkerSpec
            from jarvis_orchestrator.workflows.validation import effective_policy

            if (mode == "demo") != self.demo:
                raise ValueError("Worker registry runtime mode mismatch")
            adapters = dict(adapters)
            for workflow_node in spec.nodes:
                if workflow_node.type.value != "worker":
                    continue
                selector = effective_policy(spec, workflow_node).worker_selector
                revision = next(
                    (
                        item
                        for item in snapshot.revisions
                        if selector and item.revision_id == selector.revision_id
                    ),
                    None,
                )
                if revision is None or not isinstance(revision.spec, WorkerSpec):
                    raise ValueError("Worker revision missing from immutable snapshot")
                adapters[workflow_node.id] = worker_registry.resolve(
                    revision.revision_id, revision.spec, self.ownership, fence, demo=self.demo
                )
        if self.verification_factory is not None:
            if self.demo:
                raise ValueError("local repository verification cannot replace DEMO fixtures")
            verification_adapter = self.verification_factory(self.ownership, fence)
            adapters = dict(adapters)
            for workflow_node in spec.nodes:
                if workflow_node.type.value in {"verify", "reviewer", "integrate"}:
                    adapters[workflow_node.id] = verification_adapter
        if cancelling:
            await ledger.cancel_pending(adapters)
        async with fenced_saver(self.database_url, fence) as saver:
            graph = compile_workflow(
                spec,
                snapshot,
                checkpointer=saver,
                middleware=nodes.wrap,
                route_observer=nodes.route,
                handlers={
                    **{
                        key: ledger.handler(adapter)
                        for key, adapter in adapters.items()
                        if key in {node.id for node in spec.nodes}
                    },
                    **(
                        {
                            node.id: decision_handler
                            for node in spec.nodes
                            if node.type.value == "approval"
                        }
                        if decision_handler
                        else {}
                    ),
                },
            )
            config = workflow_run_config(thread)
            config["configurable"] = {
                **config.get("configurable", {}),
                "runtime_objective": objective,
            }
            saved = await graph.aget_state(config)
            value: WorkflowStateV1 | Command[object] | None = {} if not saved.values else None
            if any(task.interrupts for task in saved.tasks):
                async with self.ownership.fenced(fence) as (session, run):
                    wait = run.runtime_json.get("wait")
                    # An existing interrupt is already a safe boundary. A pause
                    # during durable backoff must not resume it just to pause again.
                    if run.desired_state == "paused":
                        run.status = "paused"
                        run.runtime_json = {**run.runtime_json, "recovering": False}
                        run.version += 1
                        await self.ownership.event(session, run, "run.paused")
                        await self.ownership.release_in(session, fence)
                        return
                if not isinstance(wait, dict):
                    raise ValueError("Checkpoint interrupt has no durable control record")
                value = Command(resume=wait)
            async for _chunk in graph.astream(value, config, stream_mode="updates"):
                pass
            saved = await graph.aget_state(config)
            self.ownership.fault("after_checkpoint_before_projection")
            async with self.ownership.fenced(fence) as (session, run):
                await self.ownership.event(
                    session,
                    run,
                    "graph.checkpointed",
                    {"checkpoint_id": saved.config.get("configurable", {}).get("checkpoint_id")},
                )
                if any(task.interrupts for task in saved.tasks):
                    wait = run.runtime_json.get("wait", {})
                    run.status = (
                        "approval_required"
                        if wait.get("kind") in {"demo_decision", "approval"}
                        else "paused"
                        if wait.get("kind") == "pause"
                        else "queued"
                    )
                    for node in (
                        await session.scalars(
                            select(NodeExecutionModel).where(
                                NodeExecutionModel.run_id == run.id,
                                NodeExecutionModel.status.in_(("running", "queued", "waiting")),
                            )
                        )
                    ).all():
                        node.status = "interrupted"
                        await self.ownership.event(
                            session, run, "node.interrupted", {"node_execution_id": str(node.id)}
                        )
                    if run.status == "paused":
                        await self.ownership.event(session, run, "run.paused")
                else:
                    final = cast(WorkflowStateV1, saved.values)
                    status = (
                        "cancelled"
                        if run.desired_state == "cancelled"
                        else final.get("final", {}).get("status", "blocked")
                    )
                    if status not in {"completed", "failed", "blocked", "cancelled"}:
                        status = "blocked"
                    run.status = str(status)
                    run.current_node = None
                    if run.status in {"failed", "blocked"}:
                        run.result_summary = (
                            "Workflow ended with a classified failure or policy block"
                        )
                    run.completed_at = self.ownership.clock.now()
                    job = await session.get(JobModel, run.job_id)
                    assert job is not None
                    job.status = run.status
                    await self.ownership.event(session, run, f"run.{run.status}")
                run.runtime_json = {**run.runtime_json, "recovering": False}
                run.version += 1
                await self.ownership.release_in(session, fence)
