"""Operational projections honor authentication, project ownership and freshness."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_orchestrator.workers.leases import WorkerSlots
from jarvis_persistence.models import (
    EffectModel,
    JobModel,
    OperationalAlertModel,
    OrchestratorInstanceModel,
    ProjectModel,
    RunModel,
    WorkerInvocationModel,
)
from tests.integration.support import seed_run
from tests.integration.test_m2_integrated_api import IntegratedApi, login
from tests.integration.test_m2_integrated_api import integrated_api as integrated_api
from tests.integration.test_m5_runtime import acquire
from tests.integration.test_m7_workers import setup_worker_run

pytestmark = pytest.mark.integration


async def test_health_requires_owner_and_scopes_runs(
    integrated_api: IntegratedApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    api = integrated_api
    assert (await api.client.get("/api/v1/system/health")).status_code == 401
    await login(api)
    baseline = (await api.client.get("/api/v1/system/health")).json()
    private = await seed_run(session_factory)
    hidden = await api.client.get("/api/v1/system/health")
    assert hidden.status_code == 200
    assert hidden.json()["run_counts"] == baseline["run_counts"]
    async with session_factory.begin() as session:
        await session.execute(
            update(ProjectModel)
            .where(ProjectModel.id == private.project_id)
            .values(owner_user_id=api.owner_id)
        )
        session.add(
            OrchestratorInstanceModel(
                id=str(private.run_id),
                started_at=datetime.now(UTC),
                heartbeat_at=datetime.now(UTC),
                draining=False,
                version="test",
                runtime_mode="real",
                runtime_manifest_sha256="a" * 64,
                runtime_summary_json={
                    "configured": True,
                    "worker_revision_ids": ["worker-revision"],
                    "provider_endpoint_count": 1,
                    "repository_binding_count": 1,
                    "verification_broker_configured": True,
                },
            )
        )
    observed = (await api.client.get("/api/v1/system/health")).json()
    assert observed["orchestrator"] == "healthy"
    assert observed["control_plane"] == "healthy"
    assert observed["execution"] == "configured_unverified"
    assert observed["runtime_manifest"] == "configured"
    assert observed["provider"] == "configured_unverified"
    assert sum(observed["run_counts"].values()) == sum(baseline["run_counts"].values()) + 1
    async with session_factory.begin() as session:
        await session.execute(
            update(OrchestratorInstanceModel).values(
                heartbeat_at=datetime.now(UTC) - timedelta(hours=2)
            )
        )
    stale = (await api.client.get("/api/v1/system/health")).json()
    assert stale["orchestrator"] == "stale" and stale["accepting_instances"] == 0
    assert stale["execution"] == "not_ready"
    assert stale["runtime_manifest"] == "stale"


async def test_diagnostics_alerts_deduplicate_and_record_recovery(
    integrated_api: IntegratedApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    api = integrated_api
    auth = await login(api)
    headers = {"X-CSRF-Token": auth.json()["csrf_token"]}
    async with session_factory.begin() as session:
        await session.execute(
            update(OrchestratorInstanceModel).values(
                heartbeat_at=datetime.now(UTC) - timedelta(hours=2)
            )
        )
    diagnostics = await api.client.get("/api/v1/operations/diagnostics")
    assert diagnostics.status_code == 200
    manager = next(
        item for item in diagnostics.json()["signals"] if item["key"] == "manager_freshness"
    )
    assert manager["status"] == "critical"
    first = await api.client.post(
        "/api/v1/operations/alerts/evaluate",
        json={"idempotency_key": "phase5-first", "stale_after_seconds": 60},
        headers=headers,
    )
    second = await api.client.post(
        "/api/v1/operations/alerts/evaluate",
        json={"idempotency_key": "phase5-second", "stale_after_seconds": 60},
        headers=headers,
    )
    assert first.status_code == 200 and first.json()["opened"] >= 1
    assert second.status_code == 200 and second.json()["opened"] == 0
    async with session_factory.begin() as session:
        rows = (
            await session.scalars(
                select(OperationalAlertModel).where(
                    OperationalAlertModel.owner_user_id == api.owner_id,
                    OperationalAlertModel.kind == "manager_freshness",
                )
            )
        ).all()
        assert len(rows) == 1 and rows[0].occurrences == 2
        await session.execute(
            update(OrchestratorInstanceModel).values(heartbeat_at=datetime.now(UTC))
        )
    recovered = await api.client.post(
        "/api/v1/operations/alerts/evaluate",
        json={"idempotency_key": "phase5-recovered", "stale_after_seconds": 60},
        headers=headers,
    )
    assert recovered.status_code == 200 and recovered.json()["recovered"] >= 1


async def test_diagnostics_stalled_invocation_is_owner_scoped_and_payloads_private(
    integrated_api: IntegratedApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    api = integrated_api
    path = "/api/v1/operations/diagnostics"
    assert (await api.client.get(path)).status_code == 401
    auth = await login(api)
    headers = {"X-CSRF-Token": auth.json()["csrf_token"]}
    async with api.factory() as session:
        assert await session.scalar(text("SELECT current_user")) == "jarvis_v1_api"
    baseline = await api.client.get(path)
    assert baseline.status_code == 200

    def activity(response: dict[str, Any]) -> dict[str, Any]:
        return next(item for item in response["signals"] if item["key"] == "worker_activity")

    initial_count = activity(baseline.json())["count"]
    run_id, request, spec = await setup_worker_run(session_factory)
    owner, fence = await acquire(session_factory, run_id)
    lease = await WorkerSlots(owner, fence).acquire(
        request.worker_revision_id, request.task_attempt_id, spec
    )
    invocation_id, effect_id = uuid7(), uuid7()
    async with session_factory.begin() as session:
        session.add(
            EffectModel(
                id=effect_id,
                run_id=run_id,
                task_attempt_id=request.task_attempt_id,
                kind="worker",
                idempotency_key=str(effect_id),
                request_digest="a" * 64,
                request_json={},
                status="running",
                fence_generation=fence.generation,
            )
        )
        await session.flush()
        session.add(
            WorkerInvocationModel(
                id=invocation_id,
                effect_id=effect_id,
                lease_id=lease.lease_id,
                generation=lease.generation,
                request_digest="b" * 64,
                request_json={"private": "request-payload-canary"},
                diagnostic_result_json={"private": "diagnostic-payload-canary"},
                possibly_stalled=True,
                created_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
    hidden = await api.client.get(path)
    assert hidden.status_code == 200
    assert activity(hidden.json())["count"] == initial_count
    async with session_factory.begin() as session:
        project_id = await session.scalar(
            select(JobModel.project_id).join(RunModel).where(RunModel.id == run_id)
        )
        await session.execute(
            update(ProjectModel)
            .where(ProjectModel.id == project_id)
            .values(owner_user_id=api.owner_id)
        )
    visible = await api.client.get(path)
    assert visible.status_code == 200
    signal = activity(visible.json())
    assert signal["count"] == initial_count + 1
    assert signal["status"] == "critical" and signal["age_seconds"] >= 3600
    assert "payload-canary" not in visible.text
    for column in ("request_json", "result_json", "diagnostic_result_json"):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with api.factory() as session:
                await session.execute(text(f"SELECT {column} FROM control.worker_invocations"))
    for index in range(2):
        result = await api.client.post(
            "/api/v1/operations/alerts/evaluate",
            json={"idempotency_key": f"stalled-{invocation_id}-{index}"},
            headers=headers,
        )
        assert result.status_code == 200
    async with session_factory.begin() as session:
        alert = await session.scalar(
            select(OperationalAlertModel).where(
                OperationalAlertModel.owner_user_id == api.owner_id,
                OperationalAlertModel.kind == "worker_activity",
            )
        )
        assert alert is not None and alert.occurrences >= 2 and alert.status == "active"
        await session.execute(
            update(WorkerInvocationModel)
            .where(WorkerInvocationModel.id == invocation_id)
            .values(possibly_stalled=False, last_activity_at=datetime.now(UTC))
        )
    result = await api.client.post(
        "/api/v1/operations/alerts/evaluate",
        json={"idempotency_key": f"stalled-{invocation_id}-recovered"},
        headers=headers,
    )
    assert result.status_code == 200 and result.json()["recovered"] >= 1
    async with session_factory() as session:
        recovered = await session.get(OperationalAlertModel, alert.id)
        assert recovered is not None and recovered.status == "recovered"
        assert recovered.recovered_at is not None
