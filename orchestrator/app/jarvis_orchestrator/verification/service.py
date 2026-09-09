"""Durable command evidence, with conservative recovery of uncertain executions."""

from typing import Literal
from uuid import UUID, uuid5

from sqlalchemy import select

from jarvis_contracts.verification import (
    SealedRepositorySnapshot,
    VerificationCommand,
    VerificationExecution,
)
from jarvis_orchestrator.runtime.effects import AmbiguousEffectError
from jarvis_orchestrator.verification.artifacts import EvidenceArtifacts
from jarvis_orchestrator.verification.executor import ConfirmedRepository, VerificationExecutor
from jarvis_orchestrator.verification.legacy import LegacyCorrection
from jarvis_persistence.models import EventModel


class VerificationService:
    def __init__(self, executor: VerificationExecutor, artifacts: EvidenceArtifacts) -> None:
        self.executor, self.artifacts = executor, artifacts

    async def correction(self, attempt_id: UUID, correction: LegacyCorrection) -> None:
        owner = self.artifacts.ownership
        async with owner.fenced(self.artifacts.fence) as (session, run):
            artifact = await self.artifacts.put(
                session,
                run,
                attempt_id,
                "legacy-correction",
                {
                    "original_digest": correction.original_digest,
                    "removed_prefix": correction.removed_prefix,
                    "command": correction.command.model_dump(mode="json"),
                },
            )
            await owner.event(
                session,
                run,
                "command.normalized",
                {
                    "task_attempt_id": str(attempt_id),
                    "correction_artifact_id": str(artifact),
                    "removed_prefix": correction.removed_prefix,
                    "working_root_policy": "adapter_confirmed_root",
                },
            )

    async def run(
        self,
        repository: ConfirmedRepository,
        snapshot: SealedRepositorySnapshot,
        commands: tuple[VerificationCommand, ...],
        *,
        task_id: UUID,
        operation_id: UUID,
        phase: Literal["task", "integration"] = "task",
    ) -> tuple[bool, tuple[UUID, ...]]:
        if not 1 <= len(commands) <= 32 or repository.head_sha != snapshot.head_sha:
            raise ValueError("verification requires configured commands and matching snapshot")
        owner, fence = self.artifacts.ownership, self.artifacts.fence
        reports = []
        for index, command in enumerate(commands):
            execution_id = uuid5(operation_id, f"verification:{index}")
            async with owner.fenced(fence) as (session, run):
                prior = await session.scalar(
                    select(EventModel)
                    .where(
                        EventModel.run_id == run.id,
                        EventModel.type.in_(("test.started", "test.completed", "test.failed")),
                        EventModel.data_json["verification_execution_id"].astext
                        == str(execution_id),
                    )
                    .order_by(EventModel.global_position.desc())
                    .limit(1)
                )
            if prior is not None:
                if prior.type == "test.started":
                    raise AmbiguousEffectError("verification execution requires reconciliation")
                artifact_id = UUID(prior.data_json["report_artifact_id"])
                recorded = VerificationExecution.model_validate(
                    await self.artifacts.read(artifact_id)
                )
                if (
                    recorded.snapshot_id != snapshot.id
                    or recorded.command.model_dump(mode="json") != command.model_dump(mode="json")
                    or recorded.source_sha != snapshot.head_sha
                    or recorded.task_id != task_id
                    or recorded.task_attempt_id != snapshot.task_attempt_id
                    or recorded.phase != phase
                ):
                    raise ValueError("verification receipt binding changed")
                await self.executor.confirm(repository)
                reports.append(artifact_id)
                if recorded.status != "passed":
                    return False, tuple(reports)
                continue
            started = VerificationExecution(
                phase=phase,
                id=execution_id,
                run_id=fence.run_id,
                task_id=task_id,
                task_attempt_id=snapshot.task_attempt_id,
                snapshot_id=snapshot.id,
                source_sha=snapshot.head_sha,
                command=command,
                cwd=str(repository.root),
                environment_keys=tuple(sorted(command.environment)),
                started_at=owner.clock.now(),
                status="started",
            )
            async with owner.fenced(fence) as (session, run):
                start_artifact = await self.artifacts.put(
                    session,
                    run,
                    snapshot.task_attempt_id,
                    "verification-start",
                    started.model_dump(mode="json"),
                )
                await owner.event(
                    session,
                    run,
                    "test.started",
                    {
                        "task_id": str(task_id),
                        "task_attempt_id": str(snapshot.task_attempt_id),
                        "verification_execution_id": str(execution_id),
                        "phase": phase,
                        "snapshot_id": str(snapshot.id),
                        "report_artifact_id": str(start_artifact),
                        "source_sha": snapshot.head_sha,
                    },
                )
            owner.fault("m8_after_verification_started")
            result = await self.executor.execute(repository, command)
            async with owner.fenced(fence) as (session, run):
                stdout = await self.artifacts.put(
                    session,
                    run,
                    snapshot.task_attempt_id,
                    "verification-stdout",
                    result.process.stdout.decode(errors="replace"),
                )
                stderr = await self.artifacts.put(
                    session,
                    run,
                    snapshot.task_attempt_id,
                    "verification-stderr",
                    result.process.stderr.decode(errors="replace"),
                )
                completed = started.model_copy(
                    update={
                        "finished_at": owner.clock.now(),
                        "status": "timed_out"
                        if result.process.timed_out
                        else "passed"
                        if result.passed
                        else "failed",
                        "exit_code": result.process.exit_code,
                        "environment_keys": result.environment_keys,
                        "stdout_artifact_id": stdout,
                        "stderr_artifact_id": stderr,
                        "stdout_truncated": result.process.stdout_truncated,
                        "stderr_truncated": result.process.stderr_truncated,
                        "parsed": result.parsed,
                        "failure_class": None if result.passed else "code.test_failure",
                    }
                )
                artifact_id = await self.artifacts.put(
                    session,
                    run,
                    snapshot.task_attempt_id,
                    "verification-result",
                    completed.model_dump(mode="json"),
                )
                feedback_id = None
                if not result.passed:
                    feedback_id = await self.artifacts.put(
                        session,
                        run,
                        snapshot.task_attempt_id,
                        "verification-feedback",
                        {
                            "source_sha": snapshot.head_sha,
                            "command": command.model_dump(mode="json"),
                            "summary": result.parsed.summary,
                            "stdout_excerpt": result.process.stdout[:3000].decode(errors="replace"),
                            "stderr_excerpt": result.process.stderr[:1000].decode(errors="replace"),
                            "excerpt_truncated": len(result.process.stdout) > 3000
                            or len(result.process.stderr) > 1000,
                            "complete_report_artifact_id": str(artifact_id),
                        },
                    )
                await owner.event(
                    session,
                    run,
                    "test.completed" if result.passed else "test.failed",
                    {
                        "task_id": str(task_id),
                        "feedback_artifact_id": str(feedback_id) if feedback_id else None,
                        "task_attempt_id": str(snapshot.task_attempt_id),
                        "verification_execution_id": str(execution_id),
                        "snapshot_id": str(snapshot.id),
                        "report_artifact_id": str(artifact_id),
                        "source_sha": snapshot.head_sha,
                        "passed": result.passed,
                        "phase": phase,
                        "summary": result.parsed.summary,
                        "failure_class": None if result.passed else "code.test_failure",
                    },
                )
            reports.append(artifact_id)
            owner.fault("m8_after_verification_result_persisted")
            if not result.passed:
                return False, tuple(reports)
        return True, tuple(reports)
