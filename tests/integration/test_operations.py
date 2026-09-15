"""Operational projections honor authentication, project ownership and freshness."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from jarvis_persistence.models import OperationalAlertModel, OrchestratorInstanceModel, ProjectModel
from tests.integration.support import seed_run
from tests.integration.test_m2_integrated_api import IntegratedApi, login
from tests.integration.test_m2_integrated_api import integrated_api as integrated_api

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
