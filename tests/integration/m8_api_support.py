"""Publish and enqueue the local M8 fixture through the actual authenticated API."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_contracts.workers import WorkerInvocationRequest
from jarvis_contracts.workflow_api import WorkflowResolvedSnapshot
from jarvis_persistence.models import (
    ConfigurationModel,
    ConfigurationRevisionModel,
    RunConfigSnapshotModel,
    RunModel,
    TaskModel,
    WorkflowVersionModel,
)
from tests.integration.test_m2_integrated_api import IntegratedApi
from tests.integration.test_m4_workflow_api import command, create


async def enqueue(
    api: IntegratedApi,
    sessions: async_sessionmaker[AsyncSession],
    request: WorkerInvocationRequest,
) -> WorkerInvocationRequest:
    async with sessions.begin() as session:
        run = await session.get(RunModel, request.run_id)
        assert run is not None
        config = await session.get(RunConfigSnapshotModel, run.config_snapshot_id)
        version = await session.get(WorkflowVersionModel, run.workflow_version_id)
        assert config is not None and version is not None
        spec = version.spec_json
        snapshot = WorkflowResolvedSnapshot.model_validate(config.effective_spec_json["snapshot"])
        for revision in snapshot.revisions:
            configuration = await session.get(ConfigurationModel, revision.configuration_id)
            if configuration is None:
                configuration = ConfigurationModel(
                    id=revision.configuration_id,
                    kind=revision.spec.kind,
                    key=revision.key,
                    display_name=revision.display_name,
                )
                session.add(configuration)
                await session.flush()
                session.add(
                    ConfigurationRevisionModel(
                        id=revision.revision_id,
                        configuration_id=revision.configuration_id,
                        revision=revision.revision,
                        schema_version="1.0",
                        content_hash=revision.content_hash,
                        spec_json={
                            "spec": revision.spec.model_dump(mode="json"),
                            "display_name": revision.display_name,
                            "description": revision.description,
                            "enabled": revision.enabled,
                            "archived": revision.archived,
                        },
                    )
                )
                await session.flush()
            configuration.current_revision_id = revision.revision_id
    headers, document = await create(api)
    spec = {**spec, "key": document["template"]["key"]}
    endpoint = f"/api/v1/workflow-templates/{document['template']['id']}"
    saved = await api.client.put(
        endpoint + "/draft", headers=headers, json={**command(document), "spec": spec, "layout": {}}
    )
    assert saved.status_code == 200, saved.text
    published = await api.client.post(
        endpoint + "/publish", headers=headers, json=command(saved.json())
    )
    assert published.status_code == 200, published.text
    project = await api.client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "slug": "m8-" + uuid7().hex,
            "name": "Local M8 repository",
            "idempotency_key": str(uuid7()),
        },
    )
    assert project.status_code == 201, project.text
    queued = await api.client.post(
        f"/api/v1/projects/{project.json()['id']}/jobs",
        headers=headers,
        json={
            "workflow_version_id": published.json()["version"]["id"],
            "objective": request.objective,
            "mode": "real",
            "idempotency_key": str(uuid7()),
        },
    )
    assert queued.status_code == 202, queued.text
    new_run = UUID(queued.json()["id"])
    async with sessions.begin() as session:
        task = await session.get(TaskModel, request.task_id)
        assert task is not None
        task.run_id = new_run
    return request.model_copy(
        update={
            "run_id": new_run,
            "project": request.project.model_copy(
                update={"project_id": UUID(project.json()["id"])}
            ),
        }
    )
