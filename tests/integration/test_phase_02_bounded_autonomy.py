"""Phase 2 autonomous continuation, wakeup dedup, and budget races."""

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_orchestrator.demo.bootstrap import bootstrap_demo
from jarvis_orchestrator.mission_resources import MissionBudgetDeniedError, reserve
from jarvis_orchestrator.missions import MissionManagerService
from jarvis_persistence.models import (
    ConfigurationModel,
    EffectModel,
    JobModel,
    ManagementTurnModel,
    MissionModel,
    MissionWakeupModel,
    MissionWorkItemModel,
    ModelCallModel,
    RunModel,
)
from tests.integration.test_m2_integrated_api import IntegratedApi, login
from tests.integration.test_m2_integrated_api import integrated_api as integrated_api

pytestmark = pytest.mark.integration


async def create_autonomous_mission(
    api: IntegratedApi,
    factory: async_sessionmaker[AsyncSession],
    *,
    max_calls: int = 20,
) -> tuple[dict[str, str], dict[str, Any]]:
    namespace = "phase-02-" + uuid7().hex
    workflow = await bootstrap_demo(factory, api.owner_id, namespace=namespace)
    async with factory() as session:
        team = await session.scalar(
            select(ConfigurationModel).where(ConfigurationModel.key == namespace + "-team")
        )
    assert team is not None and team.current_revision_id is not None and workflow.version.id
    headers = {"x-csrf-token": (await login(api)).json()["csrf_token"]}
    project = await api.client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "slug": namespace,
            "name": "Bounded autonomous mission",
            "idempotency_key": str(uuid7()),
        },
    )
    assert project.status_code == 201, project.text
    created = await api.client.post(
        "/api/v1/missions",
        headers=headers,
        json={
            "project_id": project.json()["id"],
            "objective": "Deliver two successive verified improvements",
            "constraints": ["Preserve accepted source"],
            "mode": "demo",
            "autonomous": True,
            "limits": {"max_calls": max_calls},
            "team_template_revision_id": str(team.current_revision_id),
            "idempotency_key": str(uuid7()),
        },
    )
    assert created.status_code == 201, created.text
    return headers, created.json()


async def finish(factory: async_sessionmaker[AsyncSession], run_id: UUID) -> None:
    async with factory.begin() as session:
        run = await session.get(RunModel, run_id, with_for_update=True)
        assert run is not None
        run.status = "completed"
        run.started_at = run.started_at or datetime.now(UTC)
        run.completed_at = datetime.now(UTC)
        job = await session.get(JobModel, run.job_id)
        assert job is not None
        job.status = "completed"


async def test_one_direction_creates_two_jobs_then_completes_with_deduped_wakeups(
    integrated_api: IntegratedApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers, mission = await create_autonomous_mission(integrated_api, session_factory)
    mission_id = UUID(str(mission["id"]))
    queued = await integrated_api.client.post(
        f"/api/v1/missions/{mission_id}/messages",
        headers=headers,
        json={
            "body": "Continue automatically until two useful items are verified.",
            "expected_version": mission["version"],
            "idempotency_key": str(uuid7()),
        },
    )
    assert queued.status_code == 202, queued.text
    manager = MissionManagerService(
        session_factory, owner="phase-02-manager", mode="demo", provider_config=None
    )
    await manager.tick()
    async with session_factory() as session:
        first = await session.scalar(
            select(MissionWorkItemModel).where(
                MissionWorkItemModel.mission_id == mission_id,
                MissionWorkItemModel.key == "DEV-001",
            )
        )
        assert first is not None and first.run_id is not None and first.lifecycle == "started"
        first_run_id = first.run_id
    await finish(session_factory, first_run_id)
    for _ in range(50):
        await manager.reconcile_items()
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count(MissionWakeupModel.id)).where(
                MissionWakeupModel.mission_id == mission_id,
                MissionWakeupModel.deduplication_key == f"run-terminal:{first_run_id}:accepted",
            )
        )
        assert count == 1
    await manager.tick()
    async with session_factory() as session:
        second = await session.scalar(
            select(MissionWorkItemModel).where(
                MissionWorkItemModel.mission_id == mission_id,
                MissionWorkItemModel.key == "DEV-002",
            )
        )
        assert second is not None and second.run_id is not None and second.lifecycle == "started"
        assert second.run_id != first_run_id
        second_run_id = second.run_id
    await finish(session_factory, second_run_id)
    for _ in range(50):
        await manager.reconcile_items()
    await manager.tick()
    async with session_factory() as session:
        stored = await session.get(MissionModel, mission_id)
        items = list(
            await session.scalars(
                select(MissionWorkItemModel).where(
                    MissionWorkItemModel.mission_id == mission_id
                )
            )
        )
        assert stored is not None and stored.lifecycle == "completed"
        assert {item.key: item.lifecycle for item in items} == {
            "DEV-001": "accepted",
            "DEV-002": "accepted",
        }


async def test_budget_reservations_serialize_and_reject_currency_mismatch(
    integrated_api: IntegratedApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _headers, created = await create_autonomous_mission(
        integrated_api, session_factory, max_calls=1
    )
    mission_id = UUID(str(created["id"]))

    async def attempt(action: str) -> str:
        async with session_factory.begin() as session:
            mission = await session.get(MissionModel, mission_id, with_for_update=True)
            assert mission is not None
            try:
                await reserve(
                    session,
                    mission,
                    action_id=action,
                    kind="manager_inference",
                    liability={"calls": 1},
                    currency="USD",
                    now=datetime.now(UTC),
                )
            except MissionBudgetDeniedError as error:
                return str(error)
            return "allowed"

    outcomes = await asyncio.gather(attempt("race-a"), attempt("race-b"))
    assert sorted(outcomes) == ["allowed", "budget_calls_exceeded"]
    async with session_factory.begin() as session:
        mission = await session.get(MissionModel, mission_id, with_for_update=True)
        assert mission is not None
        with pytest.raises(MissionBudgetDeniedError, match="currency_mismatch"):
            await reserve(
                session,
                mission,
                action_id="wrong-currency",
                kind="manager_inference",
                liability={"calls": 0, "cost_amount": "1"},
                currency="EUR",
                now=datetime.now(UTC),
            )


async def test_reconciliation_requeues_only_the_existing_ambiguous_identity(
    integrated_api: IntegratedApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers, mission = await create_autonomous_mission(integrated_api, session_factory)
    queued = await integrated_api.client.post(
        f"/api/v1/missions/{mission['id']}/messages",
        headers=headers,
        json={
            "body": "Create bounded work.",
            "expected_version": mission["version"],
            "idempotency_key": str(uuid7()),
        },
    )
    assert queued.status_code == 202, queued.text
    manager = MissionManagerService(
        session_factory, owner="phase-02-reconcile", mode="demo", provider_config=None
    )
    await manager.tick()
    effect_id = uuid7()
    async with session_factory.begin() as session:
        item = await session.scalar(
            select(MissionWorkItemModel).where(
                MissionWorkItemModel.mission_id == UUID(str(mission["id"]))
            )
        )
        assert item is not None and item.run_id is not None
        run = await session.get(RunModel, item.run_id, with_for_update=True)
        assert run is not None
        run.status = "blocked"
        run.result_summary = "Runtime requires effect reconciliation"
        job = await session.get(JobModel, run.job_id)
        assert job is not None
        job.status = "blocked"
        session.add(
            EffectModel(
                id=effect_id,
                run_id=run.id,
                kind="worker",
                idempotency_key="stable-remote-identity",
                request_digest="a" * 64,
                request_json={"node": "worker"},
                status="unknown",
                fence_generation=1,
                external_id="surviving-invocation-1",
            )
        )
        expected_version = run.version
        run_id = run.id
    response = await integrated_api.client.post(
        f"/api/v1/runs/{run_id}/reconciliation",
        headers=headers,
        json={
            "effect_id": str(effect_id),
            "expected_run_version": expected_version,
            "idempotency_key": str(uuid7()),
        },
    )
    assert response.status_code == 202, response.text
    assert response.json()["queued_for_inspection"] is True
    async with session_factory() as session:
        effect = await session.get(EffectModel, effect_id)
        run = await session.get(RunModel, run_id)
        assert effect is not None and effect.status == "unknown"
        assert effect.external_id == "surviving-invocation-1"
        assert run is not None and run.status == "queued"


async def test_pause_before_inference_consumes_no_manager_attempt_or_call(
    integrated_api: IntegratedApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers, mission = await create_autonomous_mission(integrated_api, session_factory)
    queued = await integrated_api.client.post(
        f"/api/v1/missions/{mission['id']}/messages",
        headers=headers,
        json={
            "body": "Plan one bounded item.",
            "expected_version": mission["version"],
            "idempotency_key": str(uuid7()),
        },
    )
    assert queued.status_code == 202, queued.text
    current = await integrated_api.client.get(f"/api/v1/missions/{mission['id']}")
    paused = await integrated_api.client.post(
        f"/api/v1/missions/{mission['id']}/controls",
        headers=headers,
        json={
            "scope": "mission",
            "action": "pause",
            "expected_version": current.json()["version"],
            "idempotency_key": str(uuid7()),
        },
    )
    assert paused.status_code == 200, paused.text
    manager = MissionManagerService(
        session_factory, owner="phase-02-paused", mode="demo", provider_config=None
    )
    await manager.tick()
    async with session_factory() as session:
        turn = await session.scalar(
            select(ManagementTurnModel).where(
                ManagementTurnModel.mission_id == UUID(str(mission["id"]))
            )
        )
        assert turn is not None
        calls = await session.scalar(
            select(func.count(ModelCallModel.id)).where(
                ModelCallModel.management_turn_id == turn.id
            )
        )
        assert turn.status == "queued" and turn.attempt_count == 0
        assert calls == 0


async def test_idle_autonomous_poll_does_not_create_inference(
    integrated_api: IntegratedApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _headers, mission = await create_autonomous_mission(integrated_api, session_factory)
    manager = MissionManagerService(
        session_factory, owner="phase-02-idle", mode="demo", provider_config=None
    )
    assert await manager.poll() is None
    async with session_factory() as session:
        turns = await session.scalar(
            select(func.count(ManagementTurnModel.id)).where(
                ManagementTurnModel.mission_id == UUID(str(mission["id"]))
            )
        )
        assert turns == 0
