"""M7 PostgreSQL queue -> compiled workflow -> M5 -> fake SSH acceptance."""

from datetime import timedelta
from itertools import pairwise
from pathlib import Path
from uuid import UUID

import pytest
from langchain_core.runnables import RunnableConfig
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_api.registry.service import RegistryService
from jarvis_contracts.base import sha256_digest
from jarvis_contracts.enums import FailureClass
from jarvis_contracts.failures import RetryRule
from jarvis_contracts.registry import (
    ModelProfileSpec,
    ProviderSpec,
    RetryRegistrySpec,
    RouteCandidate,
    RoutePolicySpec,
    WorkerSpec,
)
from jarvis_contracts.workers import WorkerInvocationRequest
from jarvis_contracts.workflow import VerificationPolicy, WorkerSelector
from jarvis_contracts.workflow_api import WorkflowResolvedRevision
from jarvis_orchestrator.runtime.ownership import RunOwnership, StaleExecutorError
from jarvis_orchestrator.runtime.service import OrchestratorService
from jarvis_orchestrator.workers.configuration import configured_worker_registry
from jarvis_orchestrator.workers.leases import WorkerSlots
from jarvis_orchestrator.workers.safety import WorkerBoundaryError
from jarvis_orchestrator.workers.transport import TransportResult
from jarvis_orchestrator.workflows.factories import NodeContext
from jarvis_orchestrator.workflows.state import WorkflowStateV1
from jarvis_persistence.checkpoints import postgres_saver
from jarvis_persistence.models import (
    ArtifactModel,
    ConfigurationModel,
    ConfigurationRevisionModel,
    EventModel,
    RunLeaseModel,
    RunModel,
    TaskAttemptModel,
    TaskModel,
    WorkerInvocationModel,
    WorkerLeaseModel,
)
from tests.integration.test_m5_effects import InjectedCrash
from tests.integration.test_m5_runtime import acquire, prepare_run
from tests.m7_worker_fixture import FakeWorkerSSH, deployment, worker_request, worker_spec
from tests.unit.test_m4_workflows_compiler import (
    edge,
    external_defaults,
    node,
    resolved_revision,
    snapshot_for,
    spec_for,
)

pytestmark = pytest.mark.integration


async def setup_worker_run(
    factory: async_sessionmaker[AsyncSession],
    *,
    m8: bool = False,
) -> tuple[UUID, WorkerInvocationRequest, WorkerSpec]:
    request = worker_request()
    provider = resolved_revision(ProviderSpec(provider_kind="demo"))
    profile = resolved_revision(
        ModelProfileSpec(
            provider_revision_id=provider.revision_id,
            model_identifier="local-worker-managed-fixture",
            purposes=("developer", "architect", "reviewer") if m8 else ("developer",),
            context_limit=8192,
            output_limit=1024,
        )
    )
    request = request.model_copy(update={"model_profile_revision_id": profile.revision_id})
    worker = worker_spec(request)
    if m8:
        worker = worker.model_copy(update={"capabilities": ("code", "git", "tests")})
    policy, defaults = external_defaults()
    revision = resolved_revision(worker)
    policy = policy.model_copy(
        update={
            "worker_selector": WorkerSelector(revision_id=revision.revision_id),
            "timeout_seconds": 300 if m8 else 30,
        }
    )
    extra: tuple[WorkflowResolvedRevision, ...] = ()
    if m8:
        retry = resolved_revision(
            RetryRegistrySpec(
                rules=tuple(
                    RetryRule(failure_class=kind, max_retries=1, exhaustion_action="fail")
                    for kind in (FailureClass.CODE_TEST_FAILURE, FailureClass.CODE_REVIEW_FAILURE)
                )
            )
        )
        defaults = (retry, *defaults[1:])
        route = resolved_revision(
            RoutePolicySpec(
                candidates=(RouteCandidate(profile_revision_id=profile.revision_id),),
                purposes=("developer", "architect", "reviewer"),
                allow_unknown_health=True,
            )
        )
        extra = (route,)
        policy = policy.model_copy(
            update={
                "model_route_ref": route.revision_id,
                "verification": VerificationPolicy(),
                "retry_policy_ref": retry.revision_id,
            }
        )
    nodes = (
        (
            node("plan", "architect"),
            node("dispatch", "task_dispatch"),
            node("worker", "worker"),
            node("verify", "verify"),
            node("review", "reviewer"),
            node("integrate", "integrate"),
            node("finish", "finalize"),
            node("failed", "finalize", config={"outcome": "failed"}),
        )
        if m8
        else (node("worker", "worker"), node("finish", "finalize"))
    )
    connections = tuple(edge(left.id, right.id) for left, right in pairwise(nodes))
    if m8:
        connections = tuple(
            edge(left.id, right.id)
            for left, right in pairwise(nodes[:7])
            if left.id not in {"verify", "review"}
        )
        for source, target, failure in (
            ("verify", "review", "code.test_failure"),
            ("review", "integrate", "code.review_failure"),
        ):
            connections += (
                edge(source, "worker", kind="retry", retry_class=failure, priority=0),
                edge(
                    source,
                    target,
                    kind="on_result",
                    priority=1,
                    when={"path": "$.outcome.status", "op": "eq", "value": "succeeded"},
                ),
                edge(source, "failed", kind="on_result", fallback=True, priority=2),
            )
    spec = spec_for(
        nodes,
        connections,
        defaults=policy,
    )
    closure = (*defaults[:2], revision, profile, provider, *extra)
    if m8:
        unique = []
        for item in closure:
            key = f"{item.key}-{item.configuration_id.hex}"
            unique.append(
                item.model_copy(
                    update={
                        "key": key,
                        "content_hash": sha256_digest(
                            {
                                "kind": item.spec.kind,
                                "key": key,
                                "revision": item.revision,
                                "schema_version": "1.0",
                                "spec": {
                                    "spec": item.spec.model_dump(mode="json"),
                                    "display_name": item.display_name,
                                    "description": item.description,
                                    "enabled": item.enabled,
                                    "archived": item.archived,
                                },
                            }
                        ),
                    }
                )
            )
        closure = tuple(unique)
        revision = next(item for item in closure if item.revision_id == revision.revision_id)
    run_id = await prepare_run(factory, spec, snapshot_for(spec, *closure))
    request = request.model_copy(
        update={
            "run_id": run_id,
            "worker_revision_id": revision.revision_id,
            "lease": request.lease.model_copy(update={"worker_revision_id": revision.revision_id}),
        }
    )
    async with factory.begin() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None
        run.mode = "real"
        session.add(
            ConfigurationModel(
                id=revision.configuration_id,
                kind="worker",
                key=revision.key if m8 else str(revision.configuration_id),
                display_name=revision.display_name if m8 else "Local fake worker",
            )
        )
        await session.flush()
        session.add(
            ConfigurationRevisionModel(
                id=revision.revision_id,
                configuration_id=revision.configuration_id,
                revision=1,
                schema_version="1.0",
                spec_json={
                    "spec": worker.model_dump(mode="json"),
                    "display_name": revision.display_name if m8 else "Local fake worker",
                    "description": revision.description if m8 else "M7 fixture",
                    "enabled": True,
                    "archived": False,
                },
                content_hash=revision.content_hash,
            )
        )
        session.add(
            TaskModel(
                id=request.task_id,
                run_id=run_id,
                key="DEV-001",
                title="Local worker test",
                status="running",
                acceptance_criteria_json=["fixture"],
                verification_json={},
            )
        )
        await session.flush()
        session.add(
            TaskAttemptModel(
                id=request.task_attempt_id,
                task_id=request.task_id,
                attempt_number=1,
                status="running",
                worker_revision_id=revision.revision_id,
                base_sha=request.project.base_sha,
            )
        )
    return run_id, request, worker


@pytest.mark.parametrize("scenario", ["success", "restart", "stale", "late_cancel", "unknown"])
async def test_real_queue_compiler_orchestrator_fake_ssh(
    database_url: str,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    scenario: str,
) -> None:
    run_id, request, _worker = await setup_worker_run(session_factory)

    class LocalTransport(FakeWorkerSSH):
        async def execute(self, command: str, *, timeout: float, limit: int) -> TransportResult:
            response = await super().execute(command, timeout=timeout, limit=limit)
            if scenario == "stale" and self.operations[-1] == "collect":
                async with session_factory.begin() as session:
                    lease = await session.scalar(
                        select(WorkerLeaseModel).where(WorkerLeaseModel.run_id == run_id)
                    )
                    assert lease is not None
                    lease.expires_at = lease.acquired_at
            if scenario == "late_cancel" and self.operations[-1] == "collect":
                async with session_factory.begin() as session:
                    run = await session.get(RunModel, run_id)
                    assert run is not None
                    run.desired_state = "cancelled"
            return response

    transport = LocalTransport("unknown" if scenario == "unknown" else "success")

    async def source(
        state: WorkflowStateV1, context: NodeContext, config: RunnableConfig
    ) -> WorkerInvocationRequest:
        return request

    registry = configured_worker_registry(
        {request.worker_revision_id: deployment()}, lambda _deployment: transport, source, tmp_path
    )

    # Exercise the real durable queue claim, not a directly inserted run lease.
    async with session_factory.begin() as session:
        queued = await session.get(RunModel, run_id)
        assert queued is not None
        queued.priority = 1000000
    owner = RunOwnership(session_factory, owner=str(uuid7()))
    await owner.register()
    fence = await owner.claim()
    assert fence is not None and fence.run_id == run_id
    async with postgres_saver(database_url, setup=True):
        pass
    service = OrchestratorService(database_url, owner, worker_registry=registry)
    if scenario == "restart":

        def crash(point: str) -> None:
            if point == "after_dispatch_before_result":
                raise InjectedCrash()

        owner.fault = crash
        with pytest.raises(InjectedCrash):
            await service._execute(fence)
        async with session_factory.begin() as session:
            lease = await session.scalar(
                select(RunLeaseModel).where(
                    RunLeaseModel.run_id == run_id, RunLeaseModel.released_at.is_(None)
                )
            )
            assert lease is not None
            lease.expires_at = owner.clock.now() - timedelta(seconds=1)
        owner, fence = await acquire(session_factory, run_id)
        service = OrchestratorService(database_url, owner, worker_registry=registry)
    if scenario in {"stale", "late_cancel", "unknown"}:
        await service.execute(fence)
    else:
        await service._execute(fence)
    async with session_factory() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None and run.status == (
            "blocked"
            if scenario in {"stale", "unknown"}
            else "cancelled"
            if scenario == "late_cancel"
            else "completed"
        ), run.result_summary if run else None
        invocation = await session.scalar(
            select(WorkerInvocationModel)
            .join(WorkerLeaseModel)
            .where(WorkerLeaseModel.run_id == run_id)
        )
        assert invocation is not None
        attempt = await session.get(TaskAttemptModel, request.task_attempt_id)
        assert attempt is not None
        if scenario in {"stale", "late_cancel"}:
            assert invocation.result_json is None and invocation.diagnostic_result_json is not None
            assert attempt.result_sha is None and attempt.status == "running"
        elif scenario != "unknown":
            assert invocation.result_json is not None and attempt.result_sha == "b" * 40
        else:
            assert invocation.result_json is None and attempt.result_sha is None
        events = list(
            (
                await session.scalars(select(EventModel.type).where(EventModel.run_id == run_id))
            ).all()
        )
        assert "worker.lease_acquired" in events
        assert ("worker.invocation_completed" in events) == (scenario in {"success", "restart"})
        assert ("artifact.created" in events) == (scenario != "unknown")
        artifacts = list(
            (
                await session.scalars(select(ArtifactModel).where(ArtifactModel.run_id == run_id))
            ).all()
        )
        assert len(artifacts) == (0 if scenario == "unknown" else 2)
    assert transport.starts == 1


async def test_slots_reconcile_expiry_and_fence_old_generation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id, request, spec = await setup_worker_run(session_factory)
    owner, fence = await acquire(session_factory, run_id)
    slots = WorkerSlots(owner, fence)
    first = await slots.acquire(request.worker_revision_id, request.task_attempt_id, spec)
    # A new revision must still report capacity held by its historical revision.
    async with session_factory.begin() as session:
        previous = await session.get(ConfigurationRevisionModel, request.worker_revision_id)
        assert previous is not None
        next_revision = uuid7()
        session.add(
            ConfigurationRevisionModel(
                id=next_revision,
                configuration_id=previous.configuration_id,
                revision=2,
                schema_version="1.0",
                spec_json=previous.spec_json,
                content_hash="e" * 64,
            )
        )
    observed = await RegistryService(session_factory).get_revision(next_revision)
    assert observed.worker_runtime is not None
    assert observed.worker_runtime.slots_in_use == 1
    assert observed.worker_runtime.last_heartbeat_at is not None
    async with session_factory() as session:
        assert not await session.scalar(
            text(
                "SELECT has_column_privilege('jarvis_v1_api',"
                "'control.worker_leases','token_hash','SELECT')"
            )
        )
        assert not await session.scalar(
            text(
                "SELECT has_column_privilege('jarvis_v1_api',"
                "'control.worker_invocations','request_json','SELECT')"
            )
        )
        assert await session.scalar(
            text(
                "SELECT has_column_privilege('jarvis_v1_api',"
                "'control.worker_leases','renewed_at','SELECT')"
            )
        )
    with pytest.raises(DBAPIError):
        async with session_factory.begin() as session:
            lease = await session.get(WorkerLeaseModel, first.lease_id)
            assert lease is not None
            lease.generation += 1
            await session.flush()
    async with session_factory.begin() as session:
        lease = await session.get(WorkerLeaseModel, first.lease_id)
        assert lease is not None
        lease.expires_at = owner.clock.now() - timedelta(seconds=1)
    with pytest.raises(WorkerBoundaryError, match="capacity"):
        await slots.acquire(request.worker_revision_id, request.task_attempt_id, spec)
    with pytest.raises(WorkerBoundaryError, match="requires_reconciliation"):
        await slots.release(first, reconciled_terminal=False)
    await slots.release(first, reconciled_terminal=True)
    second = await slots.acquire(request.worker_revision_id, request.task_attempt_id, spec)
    assert second.slot == 0 and second.generation == first.generation + 1
    async with owner.fenced(fence) as (session, _run):
        with pytest.raises(StaleExecutorError):
            await slots.require(session, first)
        await slots.require(session, second)
    await slots.release(second, reconciled_terminal=True)
