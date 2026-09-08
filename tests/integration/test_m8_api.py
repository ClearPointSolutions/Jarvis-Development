"""Real authenticated API role can inspect, but cannot mutate, integration evidence."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_persistence.models import IntegrationHeadModel, JobModel, ProjectModel, RunModel
from tests.integration.test_m2_integrated_api import IntegratedApi, login
from tests.integration.test_m2_integrated_api import integrated_api as integrated_api
from tests.integration.test_m5_runtime import prepare_run

pytestmark = pytest.mark.integration


async def test_owner_scoped_integration_read_and_no_browser_mutation(
    integrated_api: IntegratedApi, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    api = integrated_api
    run_id = await prepare_run(session_factory)
    url = f"/api/v1/runs/{run_id}/integration-heads"
    assert (await api.client.get(url)).status_code == 401
    headers = {"x-csrf-token": (await login(api)).json()["csrf_token"]}
    assert (await api.client.get(url)).status_code == 404
    async with session_factory.begin() as session:
        project = await session.scalar(
            select(ProjectModel).join(JobModel).join(RunModel).where(RunModel.id == run_id)
        )
        assert project is not None
        project.owner_user_id = api.owner_id
        session.add(
            IntegrationHeadModel(
                run_id=run_id,
                repository_id=uuid7(),
                base_sha="a" * 40,
                head_sha="b" * 40,
                branch="sealed-generation",
                generation=2,
            )
        )
    response = await api.client.get(url)
    assert response.status_code == 200
    assert response.json()["items"][0]["head_sha"] == "b" * 40
    assert (
        await api.client.post(
            url,
            headers=headers,
            json={"argv": ["python", "-c", "print('injection')"], "cwd": "/app", "passed": True},
        )
    ).status_code == 405
    assert (await api.client.get(url + "?limit=1001")).status_code == 422
    assert (await api.client.get(url)).json() == response.json()
