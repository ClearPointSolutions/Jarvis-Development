"""Demo effects with durable identity and real tasks, artifacts and event writes.

These adapters simulate external dependencies only. Routing, counters, leases,
commands and checkpoints remain exclusively in the existing M4/M5 runtime.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from typing import cast

from langchain_core.runnables import RunnableConfig
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from jarvis_api.events.artifacts import LocalEventArtifactStore
from jarvis_api.events.normalizer import EventIntent
from jarvis_api.events.redaction import RecursiveRedactor
from jarvis_api.routing.observability import AccountingService
from jarvis_api.routing.policies import calculate_cost
from jarvis_contracts.base import canonical_json
from jarvis_contracts.demo import DemoFixture
from jarvis_contracts.enums import EventMode, EventSeverity, EventVisibility, FailureClass
from jarvis_contracts.events import EventScope, EventSource
from jarvis_contracts.registry import (
    AccountingRecord,
    ModelProfileSpec,
    ProviderFailure,
    ProviderRequest,
    ProviderSpec,
    Usage,
)
from jarvis_orchestrator.demo.fixtures import (
    injected_failure,
    repository_fixture,
    snapshot_digest,
    task_plan,
)
from jarvis_orchestrator.demo.safety import validate_demo_snapshot
from jarvis_orchestrator.providers.demo import DemoAdapter, DemoScenario
from jarvis_orchestrator.runtime.effects import EffectObservation
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership
from jarvis_orchestrator.workflows.factories import NodeContext
from jarvis_orchestrator.workflows.state import WorkflowStateV1
from jarvis_persistence.models import (
    EffectModel,
    RunModel,
    TaskAttemptModel,
    TaskDependencyModel,
    TaskModel,
)


class DemoEffectAdapter:
    """Receipts share the effect transaction, so reconstruction never repeats work."""

    idempotent = True

    def __init__(
        self,
        ownership: RunOwnership,
        fence: RunFence,
        artifact_root: Path,
        fixture: DemoFixture,
    ) -> None:
        self.ownership, self.fence, self.fixture = ownership, fence, fixture
        self.artifacts = LocalEventArtifactStore(artifact_root)

    async def inspect(self, identity: str) -> EffectObservation:
        async with self.ownership.fenced(self.fence) as (session, run):
            effect = await session.scalar(
                select(EffectModel).where(
                    EffectModel.run_id == run.id,
                    EffectModel.external_id == identity,
                )
            )
            if effect is None:
                return EffectObservation("absent")
            if effect.status == "cancelled":
                return EffectObservation("cancelled")
            if effect.result_json is not None:
                return EffectObservation("succeeded", cast(WorkflowStateV1, effect.result_json))
            return EffectObservation("absent")

    async def cancel(self, identity: str) -> None:
        async with self.ownership.fenced(self.fence) as (session, run):
            effect = await session.scalar(
                select(EffectModel).where(
                    EffectModel.run_id == run.id,
                    EffectModel.external_id == identity,
                )
            )
            if effect is not None and effect.status != "cancelled":
                effect.status = "cancelled"
                await self.ownership.event(
                    session,
                    run,
                    "worker.cancelled",
                    {
                        "invocation_id": identity,
                    },
                )

    async def artifact(
        self,
        session: AsyncSession,
        run: RunModel,
        name: str,
        content: JsonValue,
    ) -> str:
        safe = RecursiveRedactor().redact(content).value
        reference = await self.artifacts.put(
            session,
            content=canonical_json({"content": safe}),
            scope=EventScope(run_id=run.id),
            relation=name,
            media_type="application/json",
        )
        await self.ownership.writer.append(
            session,
            EventIntent(
                occurred_at=self.fixture.clock,
                type="artifact.created",
                severity=EventSeverity.INFO,
                mode=EventMode.DEMO,
                visibility=EventVisibility.OWNER,
                scope=EventScope(run_id=run.id),
                source=EventSource(kind="orchestrator", name="demo-adapter"),
                correlation_id=str(run.id),
                data={"name": name, "summary": "DEMO immutable evidence"},
                artifact_refs=(reference,),
            ),
        )
        return str(reference.artifact_id)

    async def model(
        self,
        session: AsyncSession,
        context: NodeContext,
        config: RunnableConfig,
        result: dict[str, JsonValue],
        failure: FailureClass | None = None,
    ) -> dict[str, JsonValue]:
        settings = config.get("configurable", {})
        profile_row = next(
            r
            for r in context.snapshot.revisions
            if str(r.revision_id) == settings["runtime_model_profile_revision_id"]
        )
        provider_row = next(
            r
            for r in context.snapshot.revisions
            if str(r.revision_id) == settings["runtime_provider_revision_id"]
        )
        if not isinstance(profile_row.spec, ModelProfileSpec) or not isinstance(
            provider_row.spec, ProviderSpec
        ):
            raise ValueError("DEMO model requires normalized provider/profile contracts")
        adapter = DemoAdapter(
            provider_row.spec,
            profile_row.spec,
            provider_row.revision_id,
            profile_row.revision_id,
            scenario=DemoScenario(
                text=canonical_json(result).decode(),
                failures=(
                    ProviderFailure(
                        failure_class=failure,
                        code="demo.transient",
                        message="DEMO transient provider failure",
                        retryable=True,
                    ),
                )
                if failure
                else (),
                usage=Usage(
                    input_tokens=32,
                    output_tokens=16,
                    total_tokens=48,
                    provenance="estimated",
                ),
            ),
        )
        response = await adapter.invoke(
            ProviderRequest(
                purpose=context.node.type.value,
                text=str(settings.get("runtime_objective", "")),
                output_tokens=min(512, profile_row.spec.output_limit),
                correlation_id=context.execution_id,
                run_id=self.fence.run_id,
                structured_schema={"type": "object"},
            )
        )
        if (response.failure and response.failure.failure_class != failure) or (
            not response.failure and response.structured is None
        ):
            raise ValueError("DEMO normalized model contract failed")
        record = AccountingRecord(
            id=uuid7(),
            profile_revision_id=profile_row.revision_id,
            provider_revision_id=provider_row.revision_id,
            correlation_id=str(self.fence.run_id),
            run_id=self.fence.run_id,
            node_id=context.node.id,
            latency_ms=0,
            usage=response.usage,
            pricing=profile_row.spec.pricing,
            cost=calculate_cost(response.usage, profile_row.spec.pricing),
            outcome="failed" if response.failure else "completed",
            created_at=self.fixture.clock,
            demo=True,
        )
        await AccountingService(self.ownership.sessions).record_in_session(
            session,
            record,
            idempotency_key=context.execution_id,
        )
        return response.structured or {}

    async def dispatch(
        self,
        identity: str,
        state: WorkflowStateV1,
        context: NodeContext,
        config: RunnableConfig,
    ) -> None:
        validate_demo_snapshot(context.snapshot)
        await asyncio.sleep(self.fixture.delay_seconds)
        async with self.ownership.fenced(self.fence) as (session, run):
            if run.mode != "demo":
                raise ValueError("DEMO adapter cannot execute a real run")
            effect = await session.scalar(
                select(EffectModel).where(
                    EffectModel.run_id == run.id,
                    EffectModel.external_id == identity,
                )
            )
            if effect is None:
                raise ValueError("DEMO dispatch requires the prepared M5 effect")
            if effect.result_json is not None or effect.status == "cancelled":
                return
            if run.desired_state == "cancelled":
                effect.status = "cancelled"
                return
            update = await self._execute(session, run, state, context, config)
            effect.result_json = cast(
                dict[str, JsonValue], RecursiveRedactor().redact(cast(JsonValue, update)).value
            )

    async def _execute(
        self,
        session: AsyncSession,
        run: RunModel,
        state: WorkflowStateV1,
        context: NodeContext,
        config: RunnableConfig,
    ) -> WorkflowStateV1:
        kind = context.node.type.value
        visit = int(context.execution_id.rsplit(":", 1)[1])
        key = str(state.get("tasks", {}).get("current_task", ""))
        task = await session.scalar(
            select(TaskModel).where(
                TaskModel.run_id == run.id,
                TaskModel.key == key,
            )
        )
        if task is None and context.node.type.value in {"verify", "reviewer"}:
            task = await session.scalar(
                select(TaskModel)
                .where(
                    TaskModel.run_id == run.id,
                    TaskModel.status == "succeeded",
                )
                .order_by(TaskModel.key.desc())
                .limit(1)
            )
            if task is not None:
                key = task.key
        attempt = (
            await session.scalar(
                select(TaskAttemptModel)
                .where(
                    TaskAttemptModel.task_id == task.id,
                )
                .order_by(TaskAttemptModel.attempt_number.desc())
                .limit(1)
            )
            if task
            else None
        )
        number = attempt.attempt_number if attempt else 0
        failure = injected_failure(self.fixture, kind, key, number, visit)
        info: dict[str, JsonValue] = {
            "workflow_node_id": context.node.id,
            "summary": f"DEMO {kind}",
        }
        if task:
            info["task_id"] = str(task.id)
        if kind in {"organizer", "architect", "reviewer"}:
            await self.ownership.event(session, run, "model.call_started", info)
        if kind == "organizer":
            objective = str(config.get("configurable", {}).get("runtime_objective", ""))
            info.update(
                await self.model(
                    session,
                    context,
                    config,
                    {
                        "summary": "DEMO objective: " + " ".join(objective.split())[:1000],
                        "seed": self.fixture.seed,
                    },
                    failure=failure,
                )
            )
            await self.ownership.event(
                session,
                run,
                "service.health_changed",
                {
                    "service": "DEMO dependencies",
                    "health": "degraded" if failure else self.fixture.health,
                },
            )
            await self.ownership.event(
                session,
                run,
                "model.health_changed",
                {
                    "provider_revision_id": str(
                        config.get("configurable", {})["runtime_provider_revision_id"]
                    ),
                    "status": "degraded" if failure else self.fixture.health,
                    "circuit_state": "closed",
                    "failure_count": int(failure is not None),
                    "version": visit,
                },
            )
        elif kind == "architect":
            plan = task_plan()
            await self.model(
                session, context, config, {"tasks": [p.model_dump(mode="json") for p in plan]}
            )
            rows = {}
            items: dict[str, JsonValue] = {}
            for item in plan:
                row = TaskModel(
                    id=uuid7(),
                    run_id=run.id,
                    key=item.key,
                    title=item.title,
                    status="pending",
                    weight=item.weight,
                    acceptance_criteria_json=list(item.acceptance_criteria),
                    verification_json={"fixture": "greeting.v1"},
                )
                session.add(row)
                rows[item.key] = row
                items[item.key] = {"status": "pending", "dependencies": list(item.dependencies)}
                await session.flush()
                await self.ownership.event(
                    session,
                    run,
                    "task.created",
                    {
                        "task_id": str(row.id),
                        "task_key": row.key,
                        "title": row.title,
                    },
                )
            for item in plan:
                for dep in item.dependencies:
                    session.add(
                        TaskDependencyModel(
                            run_id=run.id,
                            task_id=rows[item.key].id,
                            depends_on_task_id=rows[dep].id,
                        )
                    )
                await self.ownership.event(
                    session,
                    run,
                    "task.dependencies_set",
                    {
                        "task_id": str(rows[item.key].id),
                        "dependencies": list(item.dependencies),
                    },
                )
            await self.ownership.event(session, run, "model.call_completed", info)
            return {
                "tasks": {"items": items, "total_count": len(plan), "terminal_count": 0},
                "outcome": {"status": "succeeded"},
            }
        elif kind == "worker":
            if task is None:
                raise ValueError("DEMO developer requires a durable selected task")
            if failure is None:
                task.status = "ready"
                await self.ownership.event(session, run, "task.ready", info)
                number += 1
                attempt = TaskAttemptModel(
                    id=uuid7(),
                    task_id=task.id,
                    attempt_number=number,
                    worker_revision_id=context.policy.worker_selector.revision_id
                    if context.policy.worker_selector
                    else None,
                    status="running",
                    started_at=self.ownership.clock.now(),
                )
                session.add(attempt)
                task.status = "running"
                await session.flush()
                info.update(task_attempt_id=str(attempt.id), attempt=number)
                info["feedback"] = state.get("verification", {}).get(
                    "feedback",
                    state.get("review", {}).get("feedback", "Initial fixture implementation"),
                )
                await self.ownership.event(session, run, "task.attempt_started", info)
                await self.ownership.event(session, run, "worker.invocation_dispatched", info)
                await self.ownership.event(
                    session,
                    run,
                    "command.started",
                    {
                        **info,
                        "display_command": "DEMO fixture edit (no shell execution)",
                        "cwd": ".",
                    },
                )
                files = repository_fixture(key, number, self.fixture)
                attempt.result_sha = snapshot_digest(files)
                source = await self.artifact(
                    session, run, f"{key}-attempt-{number}-source", cast(JsonValue, files)
                )
                info.update(snapshot_digest=attempt.result_sha, source_artifact_id=source)
                await self.ownership.event(session, run, "file.write_completed", info)
                await self.ownership.event(
                    session, run, "command.completed", {**info, "exit_code": 0}
                )
                await self.ownership.event(session, run, "worker.invocation_completed", info)
            else:
                await self.ownership.event(
                    session,
                    run,
                    "worker.invocation_failed",
                    {
                        **info,
                        "failure_class": failure.value,
                        "coding_started": False,
                    },
                )
        elif kind in {"verify", "reviewer", "integrate"}:
            if task is None or attempt is None or attempt.result_sha is None:
                raise ValueError("DEMO evidence requires an authoritative task attempt")
            files = repository_fixture(key, number, self.fixture)
            if snapshot_digest(files) != attempt.result_sha:
                raise ValueError("DEMO repository snapshot changed before review")
            info.update(
                task_attempt_id=str(attempt.id), attempt=number, snapshot_digest=attempt.result_sha
            )
            if kind == "integrate":
                attempt.status, task.status = "succeeded", "succeeded"
                attempt.completed_at = self.ownership.clock.now()
                await self.ownership.event(session, run, "task.succeeded", info)
                tasks = deepcopy(state["tasks"])
                task_items = cast(dict[str, dict[str, JsonValue]], tasks["items"])
                task_items[key]["status"] = "completed"
                tasks["terminal_count"] = sum(
                    i["status"] == "completed" for i in task_items.values()
                )
                return {"tasks": tasks, "outcome": {"status": "succeeded"}}
            stage = "verifying" if kind == "verify" else "reviewing"
            if attempt.status != "succeeded":
                attempt.status = stage
            await self.ownership.event(session, run, f"task.{stage}", info)
            prefix = "test" if kind == "verify" else "review"
            await self.ownership.event(session, run, f"{prefix}.started", info)
            if kind == "reviewer":
                await self.model(
                    session,
                    context,
                    config,
                    {"passed": failure is None, "snapshot_digest": attempt.result_sha},
                )
                await self.ownership.event(session, run, "model.call_completed", info)
            report = await self.artifact(
                session,
                run,
                f"{key}-{number}-{prefix}-report",
                {
                    **info,
                    "passed": failure is None,
                    "files": cast(JsonValue, sorted(files)),
                    "feedback": "Greeting must include the name"
                    if failure
                    else "Fixture checks pass",
                },
            )
            info.update(report_artifact_id=report, passed=failure is None)
            await self.ownership.event(
                session, run, f"{prefix}.failed" if failure else f"{prefix}.completed", info
            )
            if failure:
                attempt.status, task.status = "failed", "waiting"
                attempt.completed_at = self.ownership.clock.now()
                await self.ownership.event(
                    session,
                    run,
                    "task.retry_scheduled",
                    {
                        **info,
                        "failure_class": failure.value,
                        "next_attempt": number + 1,
                    },
                )
            channel = "verification" if kind == "verify" else "review"
            return cast(
                WorkflowStateV1,
                {
                    channel: {
                        "passed": failure is None,
                        "snapshot_digest": attempt.result_sha,
                        "report_artifact_id": report,
                        "feedback": "Greeting must include the name"
                        if failure
                        else "Fixture checks pass",
                    },
                    "outcome": {"status": "failed", "failure_class": failure.value}
                    if failure
                    else {"status": "succeeded"},
                },
            )
        elif kind == "github_publish":
            info.update(
                publication_id=f"DEMO-{run.id}",
                branch=f"DEMO/run-{run.id}",
                ci=self.fixture.ci,
                summary="DEMO publication completed; no remote repository",
            )
            await self.ownership.event(session, run, "git.push_started", info)
            await self.ownership.event(session, run, "git.ci_updated", {**info, "ci": "pending"})
            await self.ownership.event(session, run, "git.pr_created", info)
            await self.ownership.event(session, run, "git.ci_updated", info)
            await self.artifact(session, run, "DEMO-final-result", info)
            run.result_summary = str(info["summary"])
            if self.fixture.ci == "failure":
                failure = FailureClass.CODE_TEST_FAILURE
                run.result_summary = "DEMO publication CI failed; no remote repository"
        else:
            raise ValueError("No allowlisted DEMO effect for node type")
        if kind in {"organizer", "reviewer"}:
            await self.ownership.event(
                session, run, "model.call_failed" if failure else "model.call_completed", info
            )
        return {
            "results": {context.execution_id: info},
            "outcome": {"status": "failed", "failure_class": failure.value}
            if failure
            else {"status": "succeeded"},
        }
