"""M5 effect adapter for authoritative local M8 verification, review and integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from pydantic import JsonValue
from sqlalchemy import select

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.verification import (
    ReviewDecision,
    ReviewEvidence,
    SealedRepositorySnapshot,
    VerificationCommand,
)
from jarvis_contracts.workers import WorkerInvocationRequest, WorkerResult
from jarvis_orchestrator.runtime.effects import EffectObservation
from jarvis_orchestrator.verification.executor import ConfirmedRepository
from jarvis_orchestrator.verification.integration import LocalIntegrator
from jarvis_orchestrator.verification.reviews import ReviewService
from jarvis_orchestrator.workflows.factories import NodeContext
from jarvis_orchestrator.workflows.state import WorkflowStateV1
from jarvis_persistence.models import (
    EffectModel,
    EventModel,
    TaskAttemptModel,
    TaskModel,
    WorkerInvocationModel,
)


@dataclass(frozen=True)
class LocalVerificationBinding:
    """Server-owned configuration, explicitly pinned to a published workflow.

    The resolver translates an adapter's persisted workspace identity to a local
    root. Neither a browser request nor WorkerResult supplies this filesystem map.
    """

    workflow_version_id: UUID
    repository_id: UUID
    initial_sha: str
    initial_branch: str
    combined_commands: tuple[VerificationCommand, ...]
    resolve_root: Callable[[WorkerInvocationRequest], Path]


class VerificationEffectAdapter:
    idempotent = True

    def __init__(
        self,
        integrator: LocalIntegrator,
        reviewer: ReviewService,
        binding: LocalVerificationBinding,
    ) -> None:
        if not 1 <= len(binding.combined_commands) <= 32:
            raise ValueError("combined verification configuration is required")
        self.integrator, self.reviewer, self.binding = integrator, reviewer, binding
        self.artifacts = integrator.verifier.artifacts
        self.owner, self.fence = self.artifacts.ownership, self.artifacts.fence

    async def inspect(self, identity: str) -> EffectObservation:
        async with self.owner.fenced(self.fence) as (session, run):
            effect = await session.scalar(
                select(EffectModel).where(
                    EffectModel.run_id == run.id, EffectModel.external_id == identity
                )
            )
            if effect is None:
                return EffectObservation("absent")
            if effect.status == "cancelled":
                return EffectObservation("cancelled")
            if effect.result_json is not None:
                return EffectObservation("succeeded", cast(WorkflowStateV1, effect.result_json))
            # Services reconcile their own durable receipts. Uncertain started
            # external operations raise AmbiguousEffectError rather than replay.
            return EffectObservation("absent")

    async def cancel(self, identity: str) -> None:
        async with self.owner.fenced(self.fence) as (session, run):
            effect = await session.scalar(
                select(EffectModel).where(
                    EffectModel.run_id == run.id, EffectModel.external_id == identity
                )
            )
            if effect is not None and effect.result_json is None:
                effect.status = "cancelled"

    async def dispatch(
        self, identity: str, state: WorkflowStateV1, context: NodeContext, config: RunnableConfig
    ) -> None:
        kind = context.node.type.value
        if kind not in {"verify", "reviewer", "integrate"}:
            raise ValueError("unsupported verification effect")
        async with self.owner.fenced(self.fence) as (session, run):
            if run.workflow_version_id != self.binding.workflow_version_id:
                raise ValueError("verification binding does not match immutable workflow")
            effect = await session.scalar(
                select(EffectModel).where(
                    EffectModel.run_id == run.id, EffectModel.external_id == identity
                )
            )
            task = await session.scalar(
                select(TaskModel).where(
                    TaskModel.run_id == run.id,
                    TaskModel.key == str(state.get("tasks", {}).get("current_task", "")),
                )
            )
            if effect is None or task is None or effect.kind != kind:
                raise ValueError("M8 requires a prepared effect and durable current task")
            if effect.result_json is not None or effect.status == "cancelled":
                return
            attempt = await session.scalar(
                select(TaskAttemptModel)
                .where(TaskAttemptModel.task_id == task.id)
                .order_by(TaskAttemptModel.attempt_number.desc())
                .limit(1)
            )
            if attempt is None:
                raise ValueError("M8 requires an existing worker attempt")
            invocation = await session.scalar(
                select(WorkerInvocationModel)
                .join(EffectModel, EffectModel.id == WorkerInvocationModel.effect_id)
                .where(
                    EffectModel.run_id == run.id,
                    EffectModel.task_attempt_id == attempt.id,
                    WorkerInvocationModel.result_json.is_not(None),
                )
                .order_by(WorkerInvocationModel.created_at.desc())
                .limit(1)
            )
            if invocation is None:
                raise ValueError("M8 requires a persisted M7 worker result")
            request = WorkerInvocationRequest.model_validate(invocation.request_json)
            result = WorkerResult.model_validate(invocation.result_json)
            if (
                result.status != "succeeded"
                or request.project.repository_id != self.binding.repository_id
                or result.end_head != attempt.result_sha
                or result.task_attempt_id != attempt.id
            ):
                raise ValueError("worker result is not a successful current candidate")
            effect.task_attempt_id = attempt.id
            configuration_digest = sha256_digest(
                {
                    "workflow_version_id": str(self.binding.workflow_version_id),
                    "repository_id": str(self.binding.repository_id),
                    "initial_sha": self.binding.initial_sha,
                    "combined_commands": [
                        command.model_dump(mode="json")
                        for command in self.binding.combined_commands
                    ],
                    "task_commands": [
                        command.model_dump(mode="json") for command in request.task.verification
                    ],
                }
            )
            prior_digest = effect.request_json.get("verification_configuration_digest")
            if prior_digest is not None and prior_digest != configuration_digest:
                raise ValueError("verification configuration changed during effect recovery")
            effect.request_json = {
                **effect.request_json,
                "verification_configuration_digest": configuration_digest,
            }
            effect_id, task_id, attempt_id = effect.id, task.id, attempt.id
            saved_snapshot = effect.request_json.get("snapshot_artifact_id")
            criteria = tuple(task.acceptance_criteria_json)
            title = task.title
            workflow_id, config_id = run.workflow_version_id, run.config_snapshot_id
        repository = ConfirmedRepository(
            self.binding.resolve_root(request), result.branch, result.end_head
        )
        await self.integrator.leases.initialize(
            self.binding.repository_id,
            base_sha=self.binding.initial_sha,
            branch=self.binding.initial_branch,
        )
        if kind == "verify":
            if saved_snapshot is None:
                snapshot, snapshot_id = await self.integrator.snapshots.seal(
                    repository,
                    repository_id=self.binding.repository_id,
                    task_id=task_id,
                    attempt_id=attempt_id,
                    worker_result_id=result.invocation_id,
                    base_sha=self.binding.initial_sha,
                    latest_base_sha=request.project.base_sha,
                )
                async with self.owner.fenced(self.fence) as (session, _run):
                    effect = await session.get(EffectModel, effect_id)
                    assert effect is not None
                    effect.request_json = {
                        **effect.request_json,
                        "snapshot_artifact_id": str(snapshot_id),
                    }
            else:
                snapshot_id = UUID(str(saved_snapshot))
                snapshot = SealedRepositorySnapshot.model_validate(
                    await self.artifacts.read(snapshot_id)
                )
            passed, reports = await self.integrator.verifier.run(
                repository,
                snapshot,
                request.task.verification,
                task_id=task_id,
                operation_id=effect_id,
            )
            update: WorkflowStateV1 = {
                "verification": {
                    "passed": passed,
                    "snapshot_artifact_id": str(snapshot_id),
                    "report_artifact_ids": [str(item) for item in reports],
                },
                "outcome": {"status": "succeeded"}
                if passed
                else {"status": "failed", "failure_class": "code.test_failure"},
            }
        else:
            verification = state.get("verification", {})
            if verification.get("passed") is not True:
                raise ValueError("failed verification cannot dispatch Reviewer or integration")
            snapshot = SealedRepositorySnapshot.model_validate(
                await self.artifacts.read(UUID(str(verification["snapshot_artifact_id"])))
            )
            if snapshot.task_attempt_id != attempt_id or snapshot.head_sha != result.end_head:
                raise ValueError("verification channel does not bind current attempt")
            if kind == "reviewer":
                async with self.owner.fenced(self.fence) as (session, run):
                    history = (
                        await session.scalars(
                            select(EventModel)
                            .where(
                                EventModel.run_id == run.id,
                                EventModel.data_json["task_id"].astext == str(task_id),
                                EventModel.type.in_(
                                    ("review.failed", "failure.classified", "retry.budget_consumed")
                                ),
                            )
                            .order_by(EventModel.global_position.desc())
                            .limit(100)
                        )
                    ).all()
                    history_id = await self.artifacts.put(
                        session,
                        run,
                        attempt_id,
                        "failure-history",
                        [{"type": e.type, "data": e.data_json} for e in reversed(history)],
                    )
                evidence = ReviewEvidence(
                    objective=request.objective,
                    workflow_version_id=workflow_id,
                    config_snapshot_id=config_id,
                    task_id=task_id,
                    task_attempt_id=attempt_id,
                    task_title=title,
                    acceptance_criteria=criteria,
                    snapshot=snapshot,
                    verification_artifact_ids=tuple(
                        UUID(str(v))
                        for v in cast(list[JsonValue], verification["report_artifact_ids"])
                    ),
                    prior_feedback_artifact_ids=tuple(
                        UUID(e.data_json["feedback_artifact_id"])
                        for e in history
                        if "feedback_artifact_id" in e.data_json
                    ),
                    failure_history_artifact_id=history_id,
                    architecture_artifact_ids=(request.architecture_artifact_id,)
                    if request.architecture_artifact_id
                    else (),
                )
                decision, feedback, valid = await self.reviewer.run(
                    repository, evidence, operation_id=effect_id
                )
                passed = valid and decision.verdict == "PASS"
                update = {
                    "review": {
                        "passed": passed,
                        "valid": valid,
                        "feedback_artifact_id": str(feedback),
                    },
                    "outcome": {"status": "succeeded"}
                    if passed
                    else {
                        "status": "failed",
                        "failure_class": "code.review_failure"
                        if valid
                        else "code.implementation_failure",
                    },
                }
            else:
                review_state = state.get("review", {})
                if review_state.get("passed") is not True:
                    raise ValueError("integration requires a passing review")
                decision = ReviewDecision.model_validate(
                    await self.artifacts.read(UUID(str(review_state["feedback_artifact_id"])))
                )
                integrated = await self.integrator.integrate(
                    repository,
                    snapshot,
                    decision,
                    effect_id=effect_id,
                    task_id=task_id,
                    combined_commands=self.binding.combined_commands,
                )
                if integrated.status == "queued":
                    while integrated.status == "queued":
                        await asyncio.sleep(0.1)
                        async with self.owner.fenced(self.fence) as (session, run):
                            if run.desired_state == "cancelled":
                                effect = await session.get(EffectModel, effect_id)
                                assert effect is not None
                                effect.status = "cancelled"
                                return
                        integrated = await self.integrator.integrate(
                            repository,
                            snapshot,
                            decision,
                            effect_id=effect_id,
                            task_id=task_id,
                            combined_commands=self.binding.combined_commands,
                        )
                passed = integrated.status == "completed"
                update = {
                    "outcome": {"status": "succeeded"}
                    if passed
                    else {"status": "failed", "failure_class": integrated.status}
                }
                if passed:
                    tasks = deepcopy(state.get("tasks", {}))
                    items = cast(dict[str, dict[str, JsonValue]], tasks.get("items", {}))
                    if task.key in items:
                        items[task.key]["status"] = "completed"
                        tasks["terminal_count"] = sum(
                            i.get("status") == "completed" for i in items.values()
                        )
                    update["tasks"] = tasks
        async with self.owner.fenced(self.fence) as (session, run):
            effect = await session.get(EffectModel, effect_id)
            attempt = await session.get(TaskAttemptModel, attempt_id)
            task = await session.get(TaskModel, task_id)
            assert effect is not None and attempt is not None and task is not None
            if run.desired_state == "cancelled":
                effect.status = "cancelled"
                return
            effect.result_json = cast(dict[str, JsonValue], update)
            if not passed:
                attempt.status, task.status = "failed", "waiting"
                attempt.completed_at = self.owner.clock.now()
            elif kind == "integrate":
                attempt.status, task.status = "succeeded", "succeeded"
                attempt.completed_at = self.owner.clock.now()
                await self.owner.event(
                    session,
                    run,
                    "task.succeeded",
                    {"task_id": str(task_id), "task_attempt_id": str(attempt_id)},
                )
            else:
                attempt.status = "reviewing"
