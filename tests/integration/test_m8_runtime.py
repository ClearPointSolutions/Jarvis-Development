"""Published workflow -> M5 -> M7 local transport -> real Git -> sealed integration."""

import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from langchain_core.runnables import RunnableConfig
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis_contracts.verification import (
    ReviewDecision,
    ReviewEvidence,
    ReviewFinding,
    VerificationCommand,
)
from jarvis_contracts.workers import WorkerInvocationRequest, WorkerVerification
from jarvis_orchestrator.runtime.nodes import RuntimeBlockedError
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership
from jarvis_orchestrator.runtime.service import OrchestratorService
from jarvis_orchestrator.verification.artifacts import EvidenceArtifacts
from jarvis_orchestrator.verification.attempts import TaskAttemptWorkspaces
from jarvis_orchestrator.verification.executor import VerificationExecutor
from jarvis_orchestrator.verification.integration import LocalIntegrator
from jarvis_orchestrator.verification.leases import IntegrationLeases
from jarvis_orchestrator.verification.reviews import ReviewService
from jarvis_orchestrator.verification.runtime import (
    LocalVerificationBinding,
    VerificationEffectAdapter,
)
from jarvis_orchestrator.verification.service import VerificationService
from jarvis_orchestrator.verification.snapshots import SnapshotBuilder
from jarvis_orchestrator.workers.configuration import configured_worker_registry
from jarvis_orchestrator.workers.workspace import WorktreeManager
from jarvis_orchestrator.workflows.factories import NodeContext
from jarvis_orchestrator.workflows.state import WorkflowStateV1
from jarvis_persistence.checkpoints import postgres_saver
from jarvis_persistence.models import (
    EventModel,
    IntegrationHeadModel,
    RunLeaseModel,
    RunModel,
    TaskAttemptModel,
)
from tests.integration.m8_api_support import enqueue
from tests.integration.test_m2_integrated_api import IntegratedApi
from tests.integration.test_m2_integrated_api import integrated_api as integrated_api
from tests.integration.test_m5_effects import DeterministicAdapter, InjectedCrash
from tests.integration.test_m5_runtime import acquire
from tests.integration.test_m7_workers import setup_worker_run
from tests.integration.test_m8_evidence import base_repository, git
from tests.m7_worker_fixture import FakeWorkerSSH, deployment

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "crash_point",
    [
        None,
        "m8_after_verification_started",
        "m8_after_verification_result_persisted",
        "m8_after_reviewer_dispatched",
        "m8_after_review_result_persisted",
        "m8_after_integration_lease_acquired",
        "m8_during_local_git_integration",
        "m8_after_combined_gates",
        "m8_before_integration_head_advance",
        "verification_failure",
        "review_failure",
    ],
)
async def test_m8_published_runtime_local_git(
    database_url: str,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    crash_point: str | None,
    integrated_api: IntegratedApi,
) -> None:
    failure_mode = crash_point in {"verification_failure", "review_failure"}
    review_calls = 0
    run_id, request, _ = await setup_worker_run(session_factory, m8=True)
    if crash_point is None:
        request = await enqueue(integrated_api, session_factory, request)
        run_id = request.run_id
    root = tmp_path / "repository"
    base = base_repository(root)
    manager = WorktreeManager(tmp_path)
    worktree, branch = await manager.create(
        root, run_id=run_id, task_key="DEV-001", attempt=1, base_sha=base
    )
    request = request.model_copy(
        update={
            "project": request.project.model_copy(update={"base_sha": base, "branch": branch}),
            "task": request.task.model_copy(
                update={
                    "verification": (
                        WorkerVerification(
                            argv=(
                                "python",
                                "-c",
                                "from pathlib import Path; "
                                "assert Path('implemented.txt').read_text() "
                                "== 'local implementation'",
                            )
                        ),
                    )
                }
            ),
        }
    )
    async with session_factory.begin() as session:
        attempt = await session.get(TaskAttemptModel, request.task_attempt_id)
        run = await session.get(RunModel, run_id)
        assert attempt is not None and run is not None
        attempt.base_sha = base
        workflow_id = run.workflow_version_id

    class LocalWorker(FakeWorkerSSH):
        def respond(self, operation: str, payload: dict[str, object]) -> dict[str, object]:
            response = super().respond(operation, payload)
            if operation == "health":
                response["capabilities"] = ["code", "git", "tests"]
            if operation == "start" and not (worktree / "implemented.txt").exists():
                (worktree / "implemented.txt").write_text(
                    "incorrect"
                    if crash_point == "verification_failure" and self.starts == 1
                    else "local implementation"
                )
                git(worktree, "add", "implemented.txt")
                git(worktree, "commit", "-m", "local worker implementation")
            if operation == "collect":
                value = json.loads(str(response["sentinel"]).split("=", 1)[1])
                value["end_head"] = git(worktree, "rev-parse", "HEAD")
                response["sentinel"] = "JARVIS_RESULT_JSON=" + json.dumps(value)
            return response

    class Planner(DeterministicAdapter):
        async def dispatch(
            self,
            identity: str,
            state: WorkflowStateV1,
            context: NodeContext,
            config: RunnableConfig,
        ) -> None:
            self.results[identity] = {
                "tasks": {"items": {"DEV-001": {"status": "pending", "dependencies": []}}},
                "outcome": {"status": "succeeded"},
            }

    class Reviewer:
        async def review(
            self, review_id: UUID, evidence: ReviewEvidence, artifacts: EvidenceArtifacts
        ) -> ReviewDecision:
            nonlocal review_calls
            review_calls += 1
            source = await artifacts.read(evidence.snapshot.source_artifact_id)
            assert isinstance(source, dict) and "implemented.txt" in source
            now = artifacts.ownership.clock.now()
            return ReviewDecision(
                id=review_id,
                task_id=evidence.task_id,
                task_attempt_id=evidence.task_attempt_id,
                reviewed_snapshot_id=evidence.snapshot.id,
                reviewed_head_sha=evidence.snapshot.head_sha,
                snapshot_digest=evidence.snapshot.content_digest,
                verdict="FAIL" if crash_point == "review_failure" and review_calls == 1 else "PASS",
                findings=(
                    ReviewFinding(
                        criterion_index=0,
                        summary="Current task needs correction",
                        source_path="implemented.txt",
                    ),
                )
                if crash_point == "review_failure" and review_calls == 1
                else (),
                summary="Local acceptance checked",
                reviewer_revision="local-test-v1",
                started_at=now,
                finished_at=now,
            )

    transport = LocalWorker()

    async def source(
        state: WorkflowStateV1, context: NodeContext, config: RunnableConfig
    ) -> WorkerInvocationRequest:
        nonlocal request, worktree
        async with session_factory() as session:
            previous = await session.get(TaskAttemptModel, request.task_attempt_id)
            assert previous is not None
            failed = previous.status == "failed"
        if failed:
            prepared = await TaskAttemptWorkspaces(
                manager, IntegrationLeases(owner, fence)
            ).prepare(
                root,
                request.project.repository_id,
                request.task_id,
                worker_revision_id=request.worker_revision_id,
            )
            worktree = prepared.root
            request = request.model_copy(
                update={
                    "task_attempt_id": prepared.attempt_id,
                    "project": request.project.model_copy(
                        update={"base_sha": prepared.base_sha, "branch": prepared.branch}
                    ),
                }
            )
        return request

    registry = configured_worker_registry(
        {request.worker_revision_id: deployment()},
        lambda _: transport,
        source,
        integrated_api.settings.artifact_root,
    )

    def verification(owner: RunOwnership, fence: RunFence) -> VerificationEffectAdapter:
        artifacts = EvidenceArtifacts(owner, fence, integrated_api.settings.artifact_root)
        executor = VerificationExecutor(manager, {"python": (sys.executable,)}, path=os.defpath)
        integrator = LocalIntegrator(
            VerificationService(executor, artifacts),
            SnapshotBuilder(executor, artifacts),
            IntegrationLeases(owner, fence),
            author_name="Fixture",
            author_email="fixture@localhost",
        )
        return VerificationEffectAdapter(
            integrator,
            ReviewService(executor, artifacts, Reviewer()),
            LocalVerificationBinding(
                workflow_id,
                request.project.repository_id,
                base,
                "main",
                (
                    VerificationCommand(
                        argv=(
                            "python",
                            "-c",
                            "from pathlib import Path; assert Path('implemented.txt').is_file()",
                        )
                    ),
                ),
                lambda _: worktree,
            ),
        )

    owner, fence = await acquire(session_factory, run_id)
    owner.ttl = timedelta(minutes=10)
    await owner.renew(fence)
    async with postgres_saver(database_url, setup=True):
        pass
    service = OrchestratorService(
        database_url,
        owner,
        adapters={"plan": Planner()},
        worker_registry=registry,
        verification_factory=verification,
    )
    if crash_point and not failure_mode:

        def crash(point: str) -> None:
            if point == crash_point:
                raise InjectedCrash()

        owner.fault = crash
        with pytest.raises(InjectedCrash):
            await service._execute(fence)
        async with session_factory.begin() as session:
            lease = await session.scalar(
                select(RunLeaseModel).where(
                    RunLeaseModel.run_id == run_id,
                    RunLeaseModel.generation == fence.generation,
                )
            )
            assert lease is not None
            lease.expires_at = owner.clock.now() - timedelta(seconds=1)
        owner, fence = await acquire(session_factory, run_id)
        owner.ttl = timedelta(minutes=10)
        await owner.renew(fence)
        service = OrchestratorService(
            database_url,
            owner,
            adapters={"plan": Planner()},
            worker_registry=registry,
            verification_factory=verification,
        )
        if crash_point in {"m8_after_verification_started", "m8_after_reviewer_dispatched"}:
            with pytest.raises(RuntimeBlockedError):
                await service._execute(fence)
            async with session_factory() as session:
                head = await session.get(
                    IntegrationHeadModel, (run_id, request.project.repository_id)
                )
                assert head is not None and head.head_sha == base
                assert not (
                    await session.scalars(
                        select(EventModel).where(
                            EventModel.run_id == run_id, EventModel.type == "task.succeeded"
                        )
                    )
                ).all()
            assert transport.starts == 1
            return
    await service._execute(fence)
    async with session_factory() as session:
        run = await session.get(RunModel, run_id)
        attempt = await session.get(TaskAttemptModel, request.task_attempt_id)
        assert run is not None and run.status == "completed"
        assert attempt is not None and attempt.status == "succeeded"
        head = await session.get(IntegrationHeadModel, (run_id, request.project.repository_id))
        assert head is not None and head.head_sha != base
        events = (
            await session.scalars(select(EventModel.type).where(EventModel.run_id == run_id))
        ).all()
        for name in (
            "worker.invocation_completed",
            "test.completed",
            "review.completed",
            "git.integration_completed",
            "task.succeeded",
        ):
            assert name in events
    assert transport.starts == (2 if failure_mode else 1)
    if failure_mode:
        async with session_factory() as session:
            budgets = (
                await session.scalars(
                    select(EventModel).where(
                        EventModel.run_id == run_id, EventModel.type == "retry.budget_consumed"
                    )
                )
            ).all()
        expected = (
            "code.test_failure" if crash_point == "verification_failure" else "code.review_failure"
        )
        assert len(budgets) == 1 and budgets[0].data_json["failure_class"] == expected
        assert review_calls == (1 if crash_point == "verification_failure" else 2)
        if crash_point == "review_failure":
            assert list(transport.requests.values())[-1].feedback_artifact_ids
    if crash_point is None:
        response = await integrated_api.client.get(f"/api/v1/runs/{run_id}/integration-heads")
        assert (
            response.status_code == 200 and response.json()["items"][0]["head_sha"] == head.head_sha
        )
        artifact = await integrated_api.client.get(f"/api/v1/artifacts/{head.snapshot_artifact_id}")
        assert artifact.status_code == 200, artifact.text
