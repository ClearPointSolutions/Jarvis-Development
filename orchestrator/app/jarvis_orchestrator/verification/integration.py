"""Conservative local Git integration: preserve candidates and select sealed generations."""

from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from jarvis_contracts.verification import (
    ReviewDecision,
    SealedRepositorySnapshot,
    VerificationCommand,
)
from jarvis_orchestrator.runtime.ownership import StaleExecutorError
from jarvis_orchestrator.verification.executor import ConfirmedRepository
from jarvis_orchestrator.verification.leases import IntegrationFence, IntegrationLeases
from jarvis_orchestrator.verification.process import run_process
from jarvis_orchestrator.verification.service import VerificationService
from jarvis_orchestrator.verification.snapshots import SnapshotBuilder
from jarvis_orchestrator.workers.safety import WorkerBoundaryError
from jarvis_persistence.models import EffectModel


@dataclass(frozen=True)
class IntegrationResult:
    status: str
    repository: ConfirmedRepository | None = None
    snapshot_artifact_id: UUID | None = None
    report_artifact_ids: tuple[UUID, ...] = ()


class LocalIntegrator:
    def __init__(
        self,
        verifier: VerificationService,
        snapshots: SnapshotBuilder,
        leases: IntegrationLeases,
        *,
        author_name: str,
        author_email: str,
    ) -> None:
        if (
            not author_name
            or not author_email
            or any(c in author_name + author_email for c in "\n\r\x00")
        ):
            raise ValueError("integration requires a configured Git identity")
        self.verifier, self.snapshots, self.leases = verifier, snapshots, leases
        self.author_name, self.author_email = author_name, author_email

    async def _heartbeat(self, fence: IntegrationFence) -> None:
        while True:
            await asyncio.sleep(self.leases.ttl.total_seconds() / 3)
            await self.leases.renew(fence)

    async def invalidate(self, review: ReviewDecision) -> IntegrationResult:
        owner, fence = self.leases.ownership, self.leases.fence
        async with owner.fenced(fence) as (session, run):
            feedback = await self.verifier.artifacts.put(
                session,
                run,
                review.task_attempt_id,
                "review-feedback",
                review.model_dump(mode="json"),
            )
            await owner.event(
                session,
                run,
                "review.snapshot_invalidated",
                {
                    "task_id": str(review.task_id),
                    "task_attempt_id": str(review.task_attempt_id),
                    "review_id": str(review.id),
                    "reviewed_snapshot_id": str(review.reviewed_snapshot_id),
                    "reviewed_head_sha": review.reviewed_head_sha,
                    "feedback_artifact_id": str(feedback),
                    "valid": False,
                    "summary": "Candidate changed before integration advancement",
                },
            )
        return IntegrationResult("code.implementation_failure", report_artifact_ids=(feedback,))

    async def integrate(
        self,
        candidate: ConfirmedRepository,
        snapshot: SealedRepositorySnapshot,
        review: ReviewDecision,
        *,
        effect_id: UUID,
        task_id: UUID,
        combined_commands: tuple[VerificationCommand, ...],
    ) -> IntegrationResult:
        owner, fence = self.leases.ownership, self.leases.fence
        async with owner.fenced(fence) as (session, run):
            effect = await session.get(EffectModel, effect_id)
            if (
                effect is None
                or effect.run_id != run.id
                or effect.kind != "integrate"
                or effect.task_attempt_id != snapshot.task_attempt_id
                or snapshot.run_id != run.id
            ):
                raise ValueError("integration effect does not own candidate evidence")
            receipt = effect.request_json.get("integration_committed")
        if receipt is not None:
            sealed = SealedRepositorySnapshot.model_validate(
                await self.verifier.artifacts.read(UUID(receipt["snapshot_artifact_id"]))
            )
            if sealed.head_sha != receipt["head_sha"] or sealed.branch != receipt["branch"]:
                raise ValueError("integration receipt does not match sealed snapshot")
            restored = ConfirmedRepository(
                Path(receipt["worktree_root"]), receipt["branch"], receipt["head_sha"]
            )
            await self.verifier.executor.confirm(restored)
            return IntegrationResult("completed", restored, UUID(receipt["snapshot_artifact_id"]))
        if (
            review.verdict != "PASS"
            or review.reviewed_head_sha != candidate.head_sha
            or review.reviewed_snapshot_id != snapshot.id
            or review.snapshot_digest != snapshot.content_digest
            or review.task_id != task_id
            or review.task_attempt_id != snapshot.task_attempt_id
        ):
            raise ValueError("integration requires a SHA-bound passing task review")
        try:
            captured = await self.snapshots.capture(
                candidate, base_sha=snapshot.base_sha, latest_base_sha=snapshot.latest_base_sha
            )
        except (ValueError, WorkerBoundaryError):
            return await self.invalidate(review)
        if captured.digest != snapshot.content_digest:
            return await self.invalidate(review)
        lease = await self.leases.acquire(snapshot.repository_id, effect_id)
        if lease is None:
            return IntegrationResult("queued")
        owner, fence = self.leases.ownership, self.leases.fence
        renewal = asyncio.create_task(self._heartbeat(lease))
        try:
            owner.fault("m8_after_integration_lease_acquired")
            manager = self.verifier.executor.manager
            root, branch = await manager.create(
                candidate.root,
                run_id=fence.run_id,
                task_key=f"integration-{effect_id.hex}-g{lease.generation}",
                attempt=1,
                base_sha=lease.base_sha,
            )
            async with owner.fenced(fence) as (session, run):
                await owner.event(
                    session,
                    run,
                    "git.integration_started",
                    {
                        "task_id": str(task_id),
                        "task_attempt_id": str(snapshot.task_attempt_id),
                        "effect_id": str(effect_id),
                        "generation": lease.generation,
                        "base_sha": lease.base_sha,
                        "candidate_sha": candidate.head_sha,
                        "branch": branch,
                    },
                )
            environment = {
                key: value
                for key, value in os.environ.items()
                if key.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP"}
            }
            environment.update(
                {
                    "GIT_TERMINAL_PROMPT": "0",
                    "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_GLOBAL": os.devnull,
                }
            )
            result = await run_process(
                (
                    manager.git_executable,
                    "-c",
                    "core.hooksPath=" + os.devnull,
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "protocol.allow=never",
                    "-c",
                    "commit.gpgSign=false",
                    "-c",
                    "user.name=" + self.author_name,
                    "-c",
                    "user.email=" + self.author_email,
                    "merge",
                    "--no-ff",
                    "--no-edit",
                    candidate.head_sha,
                ),
                cwd=root,
                environment=environment,
                timeout=30,
                limit=1048576,
            )
            owner.fault("m8_during_local_git_integration")
            if result.timed_out:
                raise RuntimeError("local integration outcome requires reconciliation")
            if result.exit_code != 0:
                conflict_files = await manager.scalar(
                    root, "diff", "--name-only", "--diff-filter=U"
                )
                if not conflict_files:
                    raise RuntimeError("local Git failed without a confirmed merge conflict")
                async with owner.fenced(fence) as (session, run):
                    artifact = await self.verifier.artifacts.put(
                        session,
                        run,
                        snapshot.task_attempt_id,
                        "integration-conflict",
                        {
                            "base_sha": lease.base_sha,
                            "candidate_sha": candidate.head_sha,
                            "conflicting_paths": conflict_files,
                            "stdout": result.stdout.decode(errors="replace"),
                            "stderr": result.stderr.decode(errors="replace"),
                        },
                    )
                    await owner.event(
                        session,
                        run,
                        "git.integration_conflict",
                        {
                            "task_id": str(task_id),
                            "task_attempt_id": str(snapshot.task_attempt_id),
                            "effect_id": str(effect_id),
                            "failure_class": "code.git_conflict",
                            "feedback_artifact_id": str(artifact),
                            "candidate_sha": candidate.head_sha,
                        },
                    )
                await manager.git(root, "merge", "--abort")
                await manager.inspect(root, branch=branch, expected_head=lease.base_sha)
                return IntegrationResult("code.git_conflict", report_artifact_ids=(artifact,))
            merged = ConfirmedRepository(
                root, branch, await manager.scalar(root, "rev-parse", "HEAD")
            )
            merged_snapshot, snapshot_artifact = await self.snapshots.seal(
                merged,
                repository_id=snapshot.repository_id,
                task_id=task_id,
                attempt_id=snapshot.task_attempt_id,
                worker_result_id=snapshot.worker_result_id,
                base_sha=snapshot.base_sha,
                latest_base_sha=lease.base_sha,
            )
            passed, reports = await self.verifier.run(
                merged,
                merged_snapshot,
                combined_commands,
                task_id=task_id,
                operation_id=UUID(int=(effect_id.int ^ lease.generation)),
                phase="integration",
            )
            async with owner.fenced(fence) as (session, run):
                gate_report = await self.verifier.artifacts.put(
                    session,
                    run,
                    snapshot.task_attempt_id,
                    "combined-integration-gates",
                    {
                        "passed": passed,
                        "candidate_sha": candidate.head_sha,
                        "integration_sha": merged.head_sha,
                        "snapshot_id": str(merged_snapshot.id),
                        "task_review_id": str(review.id),
                        "execution_artifact_ids": [str(item) for item in reports],
                    },
                )
            owner.fault("m8_after_combined_gates")
            if not passed:
                return IntegrationResult("code.test_failure", merged, snapshot_artifact, reports)
            try:
                await self.verifier.executor.confirm(candidate)
            except (ValueError, WorkerBoundaryError):
                return await self.invalidate(review)
            await self.verifier.executor.confirm(merged)
            _final_snapshot, snapshot_artifact = await self.snapshots.seal(
                merged,
                repository_id=snapshot.repository_id,
                task_id=task_id,
                attempt_id=snapshot.task_attempt_id,
                worker_result_id=snapshot.worker_result_id,
                base_sha=snapshot.base_sha,
                latest_base_sha=lease.base_sha,
            )
            if renewal.done():
                renewal.result()
            owner.fault("m8_before_integration_head_advance")
            await self.leases.advance(
                lease,
                head_sha=merged.head_sha,
                branch=branch,
                snapshot_artifact_id=snapshot_artifact,
                worktree_root=str(merged.root),
                gate_artifact_id=gate_report,
            )
            return IntegrationResult("completed", merged, snapshot_artifact, reports)
        finally:
            renewal.cancel()
            with suppress(asyncio.CancelledError, StaleExecutorError):
                await renewal
            with suppress(StaleExecutorError):
                await self.leases.release(lease)
