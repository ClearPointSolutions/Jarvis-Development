"""Phase 1 mission API, receipt, stale reply, and manual launch acceptance."""

from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_contracts.missions import ManagerDecision
from jarvis_orchestrator.demo.bootstrap import bootstrap_demo
from jarvis_orchestrator.missions import MissionManagerService
from jarvis_persistence.models import (
    ConfigurationModel,
    ManagementTurnModel,
    MissionMessageModel,
    MissionModel,
    MissionWorkItemModel,
    ModelResponseReceiptModel,
)
from tests.integration.test_m2_integrated_api import IntegratedApi, login
from tests.integration.test_m2_integrated_api import integrated_api as integrated_api

pytestmark = pytest.mark.integration


async def team(
    factory: async_sessionmaker[AsyncSession], namespace: str, workflow_id: UUID
) -> dict[str, str]:
    async with factory() as session:
        rows = list(
            await session.scalars(
                select(ConfigurationModel).where(ConfigurationModel.key.like(namespace + "-%"))
            )
        )
        refs = {row.key.removeprefix(namespace + "-"): row.current_revision_id for row in rows}
    assert refs["team"] and workflow_id
    return {"team_template_revision_id": str(refs["team"])}


async def test_persistent_mission_manager_stale_turn_and_idempotent_manual_launch(
    integrated_api: IntegratedApi,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    api = integrated_api
    namespace = "phase-01-" + uuid7().hex
    workflow = await bootstrap_demo(session_factory, api.owner_id, namespace=namespace)
    headers = {"x-csrf-token": (await login(api)).json()["csrf_token"]}
    project = await api.client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "slug": "phase-01-" + uuid7().hex,
            "name": "Persistent mission",
            "idempotency_key": str(uuid7()),
        },
    )
    assert project.status_code == 201, project.text
    body = {
        "project_id": project.json()["id"],
        "objective": "Build a bounded durable capability",
        "constraints": ["Preserve existing behavior"],
        "mode": "demo",
        **(await team(session_factory, namespace, workflow.version.id)),
        "idempotency_key": str(uuid7()),
    }
    assert (await api.client.post("/api/v1/missions", json=body)).status_code == 403
    wrong_mode = {**body, "mode": "real", "idempotency_key": str(uuid7())}
    assert (
        await api.client.post("/api/v1/missions", headers=headers, json=wrong_mode)
    ).status_code == 422
    created = await api.client.post("/api/v1/missions", headers=headers, json=body)
    assert created.status_code == 201, created.text
    assert (
        await api.client.post("/api/v1/missions", headers=headers, json=body)
    ).json() == created.json()
    mission_id = created.json()["id"]
    message = {
        "body": "Prepare a small backlog",
        "expected_version": created.json()["version"],
        "idempotency_key": str(uuid7()),
    }
    queued = await api.client.post(
        f"/api/v1/missions/{mission_id}/messages", headers=headers, json=message
    )
    assert queued.status_code == 202, queued.text
    assert (
        await api.client.post(
            f"/api/v1/missions/{mission_id}/messages", headers=headers, json=message
        )
    ).json() == queued.json()
    manager = MissionManagerService(
        session_factory, owner="phase-01-manager", mode="demo", provider_config=None
    )
    await manager.tick()
    messages = (await api.client.get(f"/api/v1/missions/{mission_id}/messages")).json()["items"]
    assert [row["sequence"] for row in messages] == [1, 2]
    assert [row["role"] for row in messages] == ["user", "manager"]
    items = (await api.client.get(f"/api/v1/missions/{mission_id}/work-items")).json()["items"]
    assert len(items) == 1 and items[0]["lifecycle"] == "ready"
    current = (await api.client.get(f"/api/v1/missions/{mission_id}")).json()
    update_turn = await api.client.post(
        f"/api/v1/missions/{mission_id}/messages",
        headers=headers,
        json={
            "body": "Raise the existing item's priority",
            "expected_version": current["version"],
            "idempotency_key": str(uuid7()),
        },
    )
    assert update_turn.status_code == 202
    assert await manager.claim() == UUID(update_turn.json()["id"])
    await manager.apply(
        UUID(update_turn.json()["id"]),
        ManagerDecision.model_validate(
            {
                "action": "propose",
                "message": "I updated the pending item without replacing its identity.",
                "work_items": [
                    {
                        "key": "DEV-001",
                        "title": "Revised bounded capability",
                        "objective": "Build the bounded capability with the revised priority",
                        "acceptance_criteria": ["Affected tests pass"],
                        "priority": 10,
                    }
                ],
            }
        ),
    )
    updated_items = (await api.client.get(f"/api/v1/missions/{mission_id}/work-items")).json()[
        "items"
    ]
    assert updated_items[0]["id"] == items[0]["id"]
    assert updated_items[0]["priority"] == 10
    current = (await api.client.get(f"/api/v1/missions/{mission_id}")).json()
    second = await api.client.post(
        f"/api/v1/missions/{mission_id}/messages",
        headers=headers,
        json={
            "body": "Reconsider the plan",
            "expected_version": current["version"],
            "idempotency_key": str(uuid7()),
        },
    )
    assert second.status_code == 202
    queued_version = (await api.client.get(f"/api/v1/missions/{mission_id}")).json()["version"]
    revised = await api.client.put(
        f"/api/v1/missions/{mission_id}/directive",
        headers=headers,
        json={
            "objective": "Build the revised bounded capability",
            "constraints": ["No publication"],
            "expected_version": queued_version,
            "idempotency_key": str(uuid7()),
        },
    )
    assert revised.status_code == 200, revised.text
    await manager.tick()
    async with session_factory() as session:
        stale = await session.get(ManagementTurnModel, UUID(second.json()["id"]))
        assert stale is not None and stale.status == "stale" and stale.response_json is not None
        assert await session.get(ModelResponseReceiptModel, stale.model_call_id) is not None
        persisted = await session.get(MissionModel, UUID(mission_id))
        assert (
            persisted is not None and persisted.objective == "Build the revised bounded capability"
        )
        ordered = list(
            await session.scalars(
                select(MissionMessageModel)
                .where(MissionMessageModel.mission_id == persisted.id)
                .order_by(MissionMessageModel.sequence)
            )
        )
        assert ordered[-1].disposition == "stale"
    current = (await api.client.get(f"/api/v1/missions/{mission_id}")).json()
    refreshed = await api.client.post(
        f"/api/v1/missions/{mission_id}/messages",
        headers=headers,
        json={
            "body": "Refresh the pending backlog for the new directive",
            "expected_version": current["version"],
            "idempotency_key": str(uuid7()),
        },
    )
    assert refreshed.status_code == 202
    await manager.tick()
    launch_version = (await api.client.get(f"/api/v1/missions/{mission_id}")).json()["version"]
    launch_body = {
        "expected_mission_version": launch_version,
        "idempotency_key": str(uuid7()),
    }
    path = f"/api/v1/missions/{mission_id}/work-items/{items[0]['id']}/start"
    launched = await api.client.post(path, headers=headers, json=launch_body)
    assert launched.status_code == 202, launched.text
    repeated = await api.client.post(path, headers=headers, json=launch_body)
    assert repeated.status_code == 202 and repeated.json()["id"] == launched.json()["id"]
    recovered = await api.client.post(
        path,
        headers=headers,
        json={"expected_mission_version": 1, "idempotency_key": str(uuid7())},
    )
    assert recovered.status_code == 202 and recovered.json()["id"] == launched.json()["id"]
    async with session_factory() as session:
        item = await session.get(MissionWorkItemModel, UUID(items[0]["id"]))
        assert item is not None and str(item.run_id) == launched.json()["id"]
