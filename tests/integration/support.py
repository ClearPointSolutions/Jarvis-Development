from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_persistence.models import (
    JobModel,
    ProjectModel,
    RunConfigSnapshotModel,
    RunModel,
    WorkflowTemplateModel,
    WorkflowVersionModel,
)

NOW = datetime(2026, 9, 7, 15, 0, tzinfo=UTC)


@dataclass(frozen=True)
class SeededRun:
    project_id: UUID
    job_id: UUID
    run_id: UUID
    workflow_version_id: UUID
    snapshot_id: UUID


async def seed_run(factory: async_sessionmaker[AsyncSession]) -> SeededRun:
    project_id = uuid7()
    workflow_template_id = uuid7()
    workflow_version_id = uuid7()
    snapshot_id = uuid7()
    job_id = uuid7()
    run_id = uuid7()
    async with factory.begin() as session:
        session.add(
            ProjectModel(
                id=project_id,
                slug=f"project-{project_id}",
                name="Integration project",
                status="active",
            )
        )
        session.add(
            WorkflowTemplateModel(
                id=workflow_template_id,
                key=f"workflow-{workflow_template_id}",
                name="Integration workflow",
            )
        )
        await session.flush()
        session.add(
            WorkflowVersionModel(
                id=workflow_version_id,
                workflow_template_id=workflow_template_id,
                version=1,
                spec_version="1.0",
                compiler_version="compat-1",
                spec_json={"spec_version": "1.0"},
                layout_json={},
                content_hash="a" * 64,
                published_at=NOW,
            )
        )
        await session.flush()
        session.add(
            RunConfigSnapshotModel(
                id=snapshot_id,
                workflow_version_id=workflow_version_id,
                schema_version="1.0",
                resolved_revisions_json=[],
                effective_spec_json={"mode": "demo"},
                snapshot_hash=uuid7().hex + uuid7().hex,
            )
        )
        session.add(
            JobModel(
                id=job_id,
                project_id=project_id,
                objective="Exercise M1 persistence",
                status="queued",
            )
        )
        await session.flush()
        session.add(
            RunModel(
                id=run_id,
                job_id=job_id,
                run_number=1,
                workflow_version_id=workflow_version_id,
                config_snapshot_id=snapshot_id,
                langgraph_thread_id=f"thread-{run_id}",
                status="queued",
                desired_state="running",
                claimable_at=NOW,
            )
        )
    return SeededRun(
        project_id=project_id,
        job_id=job_id,
        run_id=run_id,
        workflow_version_id=workflow_version_id,
        snapshot_id=snapshot_id,
    )
