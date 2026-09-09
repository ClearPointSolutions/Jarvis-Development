"""Freeze private deployment selection into a non-secret immutable run snapshot."""

from __future__ import annotations

from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import select
from uuid6 import uuid7

from jarvis_contracts.base import sha256_digest
from jarvis_orchestrator.runtime.errors import RuntimeDependencyError
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership
from jarvis_persistence.models import JobModel, RunConfigSnapshotModel


def configuration_digest(version_id: UUID, payload: dict[str, JsonValue]) -> str:
    identity = {"version_id": str(version_id), "snapshot": payload["snapshot"]}
    if "repository_binding" in payload:
        identity["repository_binding"] = payload["repository_binding"]
    return sha256_digest(identity)


async def freeze_binding(
    owner: RunOwnership, fence: RunFence, identity: dict[str, JsonValue]
) -> None:
    async with owner.fenced(fence) as (session, run):
        job = await session.get(JobModel, run.job_id)
        if job is None or str(job.project_id) != identity["project_id"]:
            raise RuntimeDependencyError("project does not match repository binding")
        if str(run.workflow_version_id) != identity["workflow_version_id"]:
            raise RuntimeDependencyError("workflow does not match repository binding")
        original = await session.get(RunConfigSnapshotModel, run.config_snapshot_id)
        if original is None:
            raise RuntimeDependencyError("immutable configuration is unavailable")
        prior = original.effective_spec_json.get("repository_binding")
        if prior is not None:
            if prior == identity:
                return
            # Add source lifecycle facts to an older bound run without changing
            # any of its existing authority. Preserve both immutable snapshots.
            if not (
                "lifecycle" not in prior
                and "lifecycle" in identity
                and prior == {key: value for key, value in identity.items() if key != "lifecycle"}
            ):
                raise RuntimeDependencyError(
                    "immutable repository binding changed; reconciliation required"
                )
        payload = {**original.effective_spec_json, "repository_binding": identity}
        digest = configuration_digest(run.workflow_version_id, payload)
        frozen = await session.scalar(
            select(RunConfigSnapshotModel).where(RunConfigSnapshotModel.snapshot_hash == digest)
        )
        if frozen is None:
            frozen = RunConfigSnapshotModel(
                id=uuid7(),
                workflow_version_id=original.workflow_version_id,
                schema_version=original.schema_version,
                resolved_revisions_json=original.resolved_revisions_json,
                effective_spec_json=payload,
                snapshot_hash=digest,
            )
            session.add(frozen)
            await session.flush()
        # Preserve the original immutable row. This one-time association happens
        # under the run fence before inference/dispatch; subsequent builds compare.
        run.config_snapshot_id = frozen.id
        await owner.event(
            session,
            run,
            "run.configuration_bound",
            {
                "config_snapshot_id": str(frozen.id),
                "binding": identity,
            },
        )
