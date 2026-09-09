"""Resolve accepted project history once, before freezing a new run's source base."""

from __future__ import annotations

from pydantic import JsonValue
from sqlalchemy import func, select

from jarvis_contracts.workers import WorkerInvocationRequest, WorkerResult
from jarvis_orchestrator.runtime.configuration import RepositoryBinding
from jarvis_orchestrator.runtime.errors import RuntimeDependencyError
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership
from jarvis_persistence.models import (
    EffectModel,
    IntegrationHeadModel,
    JobModel,
    RunConfigSnapshotModel,
    RunModel,
    WorkerInvocationModel,
)


async def accepted_source(
    owner: RunOwnership, fence: RunFence, binding: RepositoryBinding
) -> dict[str, JsonValue]:
    async with owner.fenced(fence) as (session, run):
        configuration = await session.get(RunConfigSnapshotModel, run.config_snapshot_id)
        assert configuration is not None
        prior_binding = configuration.effective_spec_json.get("repository_binding", {})
        if "lifecycle" in prior_binding:
            return dict(prior_binding["lifecycle"])
        source: dict[str, JsonValue] = {
            "policy": binding.base_policy,
            "source_store_id": str(run.id),
            "previous_run_id": None,
            "worker_base_sha": binding.project.base_sha,
            "integration_base_sha": binding.project.base_sha,
        }
        if prior_binding:
            # An already bound pre-lifecycle run keeps its original run store
            # and seed. Never adopt work accepted after that run was started.
            return source
        previous = (
            await session.execute(
                select(RunModel, IntegrationHeadModel, RunConfigSnapshotModel)
                .select_from(RunModel)
                .join(JobModel, JobModel.id == RunModel.job_id)
                .join(IntegrationHeadModel, IntegrationHeadModel.run_id == RunModel.id)
                .join(
                    RunConfigSnapshotModel, RunConfigSnapshotModel.id == RunModel.config_snapshot_id
                )
                .where(
                    JobModel.project_id == binding.project.project_id,
                    IntegrationHeadModel.repository_id == binding.project.repository_id,
                    RunModel.status == "completed",
                    RunModel.mode == "real",
                    RunModel.id != run.id,
                    func.coalesce(
                        RunConfigSnapshotModel.effective_spec_json["repository_binding"][
                            "lifecycle"
                        ]["policy"].astext,
                        "current",
                    )
                    == "current",
                )
                .order_by(RunModel.completed_at.desc(), RunModel.id.desc())
                .limit(1)
            )
        ).first()
        if previous is None:
            return source
        prior_run, integration, prior_configuration = previous
        invocation = await session.scalar(
            select(WorkerInvocationModel)
            .join(EffectModel)
            .where(
                EffectModel.run_id == prior_run.id, WorkerInvocationModel.result_json.is_not(None)
            )
            .order_by(WorkerInvocationModel.created_at.desc())
            .limit(1)
        )
        if invocation is None:
            raise RuntimeDependencyError(
                "accepted project has no authoritative worker source receipt"
            )
        request = WorkerInvocationRequest.model_validate(invocation.request_json)
        result = WorkerResult.model_validate(invocation.result_json)
        if (
            request.project.project_id != binding.project.project_id
            or request.project.repository_id != binding.project.repository_id
            or request.worker_revision_id != binding.worker_revision_id
            or result.status != "succeeded"
            or result.branch != binding.project.branch
            or result.request_digest != invocation.request_digest
        ):
            raise RuntimeDependencyError("accepted source binding requires reconciliation")
        prior_lifecycle = prior_configuration.effective_spec_json.get("repository_binding", {}).get(
            "lifecycle", {}
        )
        if binding.base_policy == "historical":
            source["seed_store_id"] = prior_lifecycle.get("source_store_id", str(prior_run.id))
            return source
        source.update(
            {
                "source_store_id": prior_lifecycle.get("source_store_id", str(prior_run.id)),
                "previous_run_id": str(prior_run.id),
                "worker_base_sha": result.end_head,
                "integration_base_sha": integration.head_sha,
            }
        )
        return source
