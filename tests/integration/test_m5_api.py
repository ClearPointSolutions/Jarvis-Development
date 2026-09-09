from __future__ import annotations

import asyncio
from time import perf_counter
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from uuid6 import uuid7

from jarvis_api.events.sse import EventStream, PollingEventWakeups, parse_sse_data
from jarvis_api.main import create_app
from jarvis_orchestrator.runtime.commands import CommandProcessor
from jarvis_orchestrator.runtime.ownership import RunOwnership
from jarvis_orchestrator.runtime.service import OrchestratorService
from jarvis_persistence.models import JobModel, ProjectModel, RunModel
from jarvis_persistence.repositories import EventRepository
from tests.integration.support import seed_run
from tests.integration.test_m2_integrated_api import KEY, ORIGIN, IntegratedApi, login
from tests.integration.test_m2_integrated_api import integrated_api as integrated_api
from tests.integration.test_m4_workflow_api import command, create
from tests.integration.test_m5_runtime import acquire
from tests.integration.test_m5_service import DelayedAdapter, dispatched, external_run

pytestmark = pytest.mark.integration


async def test_run003_durable_enqueue_auth_idempotency_and_control(
    integrated_api: IntegratedApi,
    database_url: str,
) -> None:
    api = integrated_api
    assert (await api.client.get("/api/v1/runs")).status_code == 401
    headers, draft = await create(api)
    project_body = {
        "idempotency_key": str(uuid7()),
        "slug": f"m5-{uuid7().hex}",
        "name": "M5 local test",
    }
    denied = await api.client.post("/api/v1/projects", json=project_body)
    assert denied.status_code == 403
    project = await api.client.post("/api/v1/projects", json=project_body, headers=headers)
    assert project.status_code == 201, project.text
    publication = await api.client.post(
        f"/api/v1/workflow-templates/{draft['template']['id']}/publish",
        json=command(draft),
        headers=headers,
    )
    assert publication.status_code == 200, publication.text
    start_body = {
        "idempotency_key": str(uuid7()),
        "objective": "Exercise durable local execution",
        "mode": "real",
        "workflow_version_id": publication.json()["version"]["id"],
    }
    path = f"/api/v1/projects/{project.json()['id']}/jobs"
    started = perf_counter()
    response = await api.client.post(path, json=start_body, headers=headers)
    elapsed = perf_counter() - started
    assert response.status_code == 202, response.text
    assert elapsed < 1
    run = response.json()
    assert run["status"] == "queued"
    assert (await api.client.post(path, json=start_body, headers=headers)).json() == run
    assert (await api.client.get(f"/api/v1/runs/{run['id']}")).json() == run
    assert (await api.client.get(f"/api/v1/jobs/{run['job_id']}")).status_code == 200
    assert (await api.client.get(f"/api/v1/runs/{uuid7()}")).status_code == 404
    body = {
        "idempotency_key": str(uuid7()),
        "expected_run_version": run["version"],
        "kind": "pause",
    }
    controlled = await api.client.post(
        f"/api/v1/runs/{run['id']}/commands", json=body, headers=headers
    )
    assert controlled.status_code == 202, controlled.text
    repeat = await api.client.post(f"/api/v1/runs/{run['id']}/commands", json=body, headers=headers)
    assert repeat.json()["command_id"] == controlled.json()["command_id"]
    assert repeat.json()["duplicate"]
    body["idempotency_key"] = str(uuid7())
    assert (
        await api.client.post(f"/api/v1/runs/{run['id']}/commands", json=body, headers=headers)
    ).status_code == 409
    await CommandProcessor(RunOwnership(api.factory, owner="test-control")).apply(run["id"])
    updated = (await api.client.get(f"/api/v1/runs/{run['id']}")).json()
    assert updated["status"] == "pause_requested"
    assert updated["desired_state"] == "paused"
    assert (await api.client.get(f"/api/v1/runs/{run['id']}/commands")).json()["items"][0][
        "status"
    ] == "applied"
    assert (await api.client.get(f"/api/v1/runs/{run['id']}/nodes")).json()["items"] == []
    engine = create_async_engine(
        database_url, connect_args={"options": "-c role=jarvis_v1_orchestrator"}
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        owner, fence = await acquire(factory, UUID(run["id"]))
        url = (
            make_url(database_url)
            .update_query_dict({"options": "-c role=jarvis_v1_orchestrator"})
            .render_as_string(hide_password=False)
        )
        await OrchestratorService(url, owner)._execute(fence)
        assert (await api.client.get(f"/api/v1/runs/{run['id']}")).json()["status"] == "paused"
    finally:
        await engine.dispose()


async def test_run008_active_orchestrator_survives_api_restart_and_sse_replay(
    integrated_api: IntegratedApi,
    database_url: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    api = integrated_api
    await login(api)
    identifier = await external_run(session_factory)
    async with session_factory.begin() as session:
        project = await session.scalar(
            select(ProjectModel).join(JobModel).join(RunModel).where(RunModel.id == identifier)
        )
        assert project is not None
        project.owner_user_id = api.owner_id
    owner, fence = await acquire(session_factory, identifier)
    adapter = DelayedAdapter()
    task = asyncio.create_task(
        OrchestratorService(database_url, owner, adapters={"work": adapter}).execute(fence)
    )
    await dispatched(adapter)
    before = (await api.client.get(f"/api/v1/runs/{identifier}")).json()
    cookies = api.client.cookies
    await api.client.aclose()
    restarted = create_app(
        settings=api.settings, session_factory=api.factory, clock=api.clock, server_key=KEY
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=restarted), base_url=ORIGIN, cookies=cookies
    ) as client:
        assert (await client.get(f"/api/v1/runs/{identifier}")).status_code == 200
        assert not task.done()
        adapter.ready.set()
        await asyncio.wait_for(task, 15)
        after = (await client.get(f"/api/v1/runs/{identifier}")).json()
        assert after["status"] == "completed"
        assert after["thread_id"] == before["thread_id"]
        stream = EventStream(
            session_factory=api.factory,
            repository=EventRepository(),
            wakeups=PollingEventWakeups(),
            page_size=3,
            poll_seconds=0.01,
            keepalive_seconds=1,
        )

        async def disconnected() -> bool:
            return True

        frames = [
            parse_sse_data(frame)
            async for frame in stream.iter_frames(
                run_id=identifier, after=before["last_event_position"], is_disconnected=disconnected
            )
        ]
        assert [frame["run_sequence"] for frame in frames] == list(
            range(before["last_run_sequence"] + 1, after["last_run_sequence"] + 1)
        )
        assert frames[-1]["type"] == "run.completed"


async def test_m5_owner_boundaries_unpublished_versions_and_bounded_inputs(
    integrated_api: IntegratedApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    api = integrated_api
    other = await seed_run(session_factory)
    paths = [
        "/api/v1/projects",
        "/api/v1/jobs",
        "/api/v1/runs",
        f"/api/v1/jobs/{other.job_id}",
        f"/api/v1/runs/{other.run_id}",
        f"/api/v1/runs/{other.run_id}/nodes",
        f"/api/v1/runs/{other.run_id}/commands",
    ]
    for path in paths:
        assert (await api.client.get(path)).status_code == 401
    headers, draft = await create(api)
    for path in paths[3:]:
        assert (await api.client.get(path)).status_code == 404
    for path, excluded in zip(
        paths[:3], (other.project_id, other.job_id, other.run_id), strict=True
    ):
        result = await api.client.get(path + "?limit=1")
        assert result.status_code == 200
        assert str(excluded) not in [row["id"] for row in result.json()["items"]]
    command_body = {"kind": "cancel", "expected_run_version": 0, "idempotency_key": str(uuid7())}
    assert (await api.client.post(paths[-1], json=command_body, headers=headers)).status_code == 404
    body = {
        "slug": f"security-{uuid7().hex}",
        "name": "Scoped project",
        "idempotency_key": str(uuid7()),
    }
    created = await api.client.post(paths[0], json=body, headers=headers)
    assert created.status_code == 201
    assert (await api.client.post(paths[0], json=body, headers=headers)).json() == created.json()
    assert (
        await api.client.post(paths[0], json={**body, "name": "Changed"}, headers=headers)
    ).status_code == 409
    start = {
        "workflow_version_id": draft["version"]["id"],
        "objective": "No unpublished execution",
        "idempotency_key": str(uuid7()),
    }
    path = f"/api/v1/projects/{created.json()['id']}/jobs"
    assert (await api.client.post(path, json=start, headers=headers)).status_code == 404
    assert (await api.client.post(path, json=start)).status_code == 403
    assert (
        await api.client.post(
            path, json=start, headers={**headers, "Origin": "https://untrusted.test"}
        )
    ).status_code == 403
    for change in ({"mode": "shell"}, {"priority": 101}, {"objective": "x" * 8001}):
        assert (
            await api.client.post(path, json={**start, **change}, headers=headers)
        ).status_code == 422
    assert (
        await api.client.post(
            f"/api/v1/projects/{other.project_id}/jobs", json=start, headers=headers
        )
    ).status_code == 404
