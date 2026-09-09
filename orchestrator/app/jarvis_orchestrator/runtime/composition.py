"""Normal real-mode composition from private infrastructure and immutable run data."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid5

from langchain_core.runnables import RunnableConfig
from pydantic import JsonValue
from sqlalchemy import select
from uuid6 import uuid7

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.registry import ModelProfileSpec, ProviderSpec, WorkerSpec
from jarvis_contracts.workers import (
    PreparedInvocation,
    WorkerInvocationRequest,
    WorkerLimits,
    WorkerResult,
    WorkerSlotFence,
    WorkerTask,
)
from jarvis_contracts.workflow import WorkflowSpec
from jarvis_contracts.workflow_api import WorkflowResolvedSnapshot
from jarvis_orchestrator.providers.runtime import RuntimeModel
from jarvis_orchestrator.runtime.approvals import ProtectedEffect, approval_handler
from jarvis_orchestrator.runtime.configuration import RealRuntimeConfiguration, RepositoryBinding
from jarvis_orchestrator.runtime.effects import EffectAdapter
from jarvis_orchestrator.runtime.errors import RuntimeDependencyError
from jarvis_orchestrator.runtime.model_selection import select_model
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership
from jarvis_orchestrator.runtime.planning import PlanningEffect
from jarvis_orchestrator.verification.artifacts import EvidenceArtifacts
from jarvis_orchestrator.verification.executor import VerificationExecutor
from jarvis_orchestrator.verification.integration import LocalIntegrator
from jarvis_orchestrator.verification.leases import IntegrationLeases
from jarvis_orchestrator.verification.model_reviewer import ModelReviewer
from jarvis_orchestrator.verification.reviews import ReviewerAdapter, ReviewService
from jarvis_orchestrator.verification.runtime import (
    LocalVerificationBinding,
    VerificationEffectAdapter,
)
from jarvis_orchestrator.verification.service import VerificationService
from jarvis_orchestrator.verification.snapshots import SnapshotBuilder
from jarvis_orchestrator.workers.artifacts import WorkerContextReader, WorkerLogPublisher
from jarvis_orchestrator.workers.openhands import OpenHandsSSHAdapter
from jarvis_orchestrator.workers.runtime import WorkerEffectAdapter
from jarvis_orchestrator.workers.source_transfer import import_candidate
from jarvis_orchestrator.workers.transport import OpenSSHTransport, SSHCredentials
from jarvis_orchestrator.workers.workspace import WorktreeManager
from jarvis_orchestrator.workflows.factories import NodeContext, NodeHandler
from jarvis_orchestrator.workflows.state import WorkflowStateV1
from jarvis_orchestrator.workflows.validation import effective_policy
from jarvis_persistence.models import (
    EffectModel,
    TaskAttemptModel,
    TaskModel,
    WorkerInvocationModel,
)


class RealComposition:
    def __init__(self, settings: RealRuntimeConfiguration, artifact_root: Path) -> None:
        self.settings, self.artifact_root = settings, artifact_root

    def approval_parameters(self, workflow_id: UUID) -> dict[str, JsonValue]:
        binding = self.settings.workflows[workflow_id]
        return {
            "binding_digest": sha256_digest(binding),
            "repository_id": str(binding.project.repository_id),
        }

    def approvals(
        self, owner: RunOwnership, fence: RunFence, spec: WorkflowSpec, workflow_id: UUID
    ) -> NodeHandler:
        return approval_handler(owner, fence, spec, self.approval_parameters(workflow_id))

    def model(
        self, owner: RunOwnership, fence: RunFence, context: NodeContext, config: RunnableConfig
    ) -> RuntimeModel:
        selected = config.get("configurable", {})
        profile = next(
            row
            for row in context.snapshot.revisions
            if str(row.revision_id) == selected.get("runtime_model_profile_revision_id")
        )
        provider = next(
            row
            for row in context.snapshot.revisions
            if str(row.revision_id) == selected.get("runtime_provider_revision_id")
        )
        if not isinstance(profile.spec, ModelProfileSpec) or not isinstance(
            provider.spec, ProviderSpec
        ):
            raise RuntimeDependencyError("immutable provider/profile binding is invalid")
        return RuntimeModel(
            self.settings.providers,
            owner,
            fence,
            provider.spec,
            profile.spec,
            provider.revision_id,
            profile.revision_id,
        )

    async def build(
        self,
        owner: RunOwnership,
        fence: RunFence,
        spec: WorkflowSpec,
        snapshot: WorkflowResolvedSnapshot,
        workflow_id: UUID,
    ) -> dict[str, EffectAdapter]:
        binding = self.settings.workflows.get(workflow_id)
        if binding is None:
            raise RuntimeDependencyError("published workflow has no server-side repository binding")
        deployment = self.settings.workers.get(binding.worker_revision_id)
        revision = next(
            (row for row in snapshot.revisions if row.revision_id == binding.worker_revision_id),
            None,
        )
        if deployment is None or revision is None or not isinstance(revision.spec, WorkerSpec):
            raise RuntimeDependencyError("immutable worker deployment binding is unavailable")
        worker = revision.spec
        if worker.adapter_kind != "openhands_ssh_v1" or worker.max_concurrency != 1:
            raise RuntimeDependencyError(
                "first-test composition requires the exclusive legacy worker"
            )
        if binding.project.workspace_root != deployment.workspace_root + "/" + binding.project.slug:
            raise RuntimeDependencyError("legacy runner cannot honor the configured workspace")
        credentials = self.settings.credential_files
        transport = OpenSSHTransport(
            deployment,
            SSHCredentials(
                credentials[deployment.ssh_key_ref], credentials[deployment.host_key_ref]
            ),
            allowed_hosts=frozenset(self.settings.allowed_worker_hosts),
            executable=str(self.settings.ssh_executable),
        )

        async def require_fence(lease: WorkerSlotFence) -> None:
            from jarvis_orchestrator.workers.leases import WorkerSlots

            async with owner.fenced(fence) as (session, _run):
                await WorkerSlots(owner, fence).require(session, lease)

        native = OpenHandsSSHAdapter(
            worker,
            deployment,
            transport,
            require_fence=require_fence,
            publish_log=WorkerLogPublisher(owner, fence, self.artifact_root),
            artifact_reader=WorkerContextReader(owner, fence, self.artifact_root),
        )
        run_root = self.settings.source_root / fence.run_id.hex
        run_root.mkdir(parents=True, exist_ok=True)
        manager = WorktreeManager(run_root, git_executable=str(self.settings.git_executable))
        executor = VerificationExecutor(
            manager, self.settings.executables, path=self.settings.executable_path
        )
        artifacts = EvidenceArtifacts(owner, fence, self.artifact_root)
        request_source = LegacyRequestSource(owner, fence, binding, artifacts)
        worker_effect = WorkerEffectAdapter(owner, fence, worker, native, request_source.request)
        # All dependency checks complete before Organizer inference or worker dispatch.
        report = await native.validate(worker, worker_effect.context())
        if not report.valid:
            raise RuntimeDependencyError(
                "worker dependency preflight failed: " + ",".join(report.health.issues)
            )
        checked: set[UUID] = set()
        reviewer_context: NodeContext | None = None
        reviewer_config: RunnableConfig = {}
        for node in spec.nodes:
            context = NodeContext(node, effective_policy(spec, node), snapshot, "preflight")
            if node.type.value == "worker":
                selector = context.policy.worker_selector
                if selector is None or selector.revision_id != binding.worker_revision_id:
                    raise RuntimeDependencyError(
                        "workflow worker differs from private deployment binding"
                    )
                continue
            if node.type.value not in {"organizer", "architect", "reviewer"}:
                continue
            resolution = select_model(context, (), None, owner.clock.now())
            if resolution.decision != "allow":
                raise RuntimeDependencyError(
                    "required immutable model route has no eligible candidate"
                )
            config: RunnableConfig = {
                "configurable": {
                    "runtime_model_profile_revision_id": str(
                        resolution.selected_profile_revision_id
                    ),
                    "runtime_provider_revision_id": str(resolution.selected_provider_revision_id),
                }
            }
            model = self.model(owner, fence, context, config)
            if not model.profile.structured_json:
                raise RuntimeDependencyError("planning/review requires a structured JSON profile")
            if model.adapter.profile_revision_id not in checked:
                async with asyncio.timeout(self.settings.providers.probe_seconds):
                    status = await model.adapter.validate_connection()
                async with owner.fenced(fence) as (session, run):
                    await owner.event(
                        session,
                        run,
                        "service.health_changed",
                        {
                            "service": "runtime-provider-preflight",
                            "profile_revision_id": str(model.adapter.profile_revision_id),
                            "health": status.health,
                            "issues": list(status.issues),
                            "network_checked": status.network_checked,
                        },
                    )
                if not status.valid:
                    raise RuntimeDependencyError("provider/model dependency preflight failed")
                checked.add(model.adapter.profile_revision_id)
            if node.type.value == "reviewer":
                reviewer_context, reviewer_config = context, config
        if reviewer_context is None:
            raise RuntimeDependencyError("real repository workflows require independent review")

        def reviewer_factory(context: NodeContext, config: RunnableConfig) -> ReviewerAdapter:
            return ModelReviewer(self.model(owner, fence, context, config))

        async def transfer(request: WorkerInvocationRequest, result: WorkerResult) -> Path:
            envelope = await native._rpc(
                "export_candidate",
                worker_effect.context(),
                {
                    "workspace_root": deployment.workspace_root,
                    "prepared": PreparedInvocation(
                        request=request, request_digest=sha256_digest(request)
                    ).model_dump(mode="json"),
                    "result": result.model_dump(mode="json"),
                },
                limit=24 * 1024 * 1024,
            )
            return await import_candidate(manager, result, envelope)

        def no_remote_path(_request: WorkerInvocationRequest) -> Path:
            raise RuntimeDependencyError("remote source requires verified transfer")

        verifier = VerificationService(executor, artifacts)
        snapshots = SnapshotBuilder(executor, artifacts)
        verification = VerificationEffectAdapter(
            LocalIntegrator(
                verifier,
                snapshots,
                IntegrationLeases(owner, fence),
                author_name=self.settings.git_author_name,
                author_email=self.settings.git_author_email,
            ),
            ReviewService(
                executor,
                artifacts,
                reviewer_factory(reviewer_context, reviewer_config),
                timeout_seconds=self.settings.providers.reviewer_seconds,
            ),
            LocalVerificationBinding(
                workflow_id,
                binding.project.repository_id,
                binding.project.base_sha,
                binding.project.branch,
                binding.combined_commands,
                no_remote_path,
                transfer,
            ),
            reviewer_factory=reviewer_factory,
        )
        planner = PlanningEffect(self.settings.providers, owner, fence)
        handlers: dict[str, EffectAdapter] = {}
        for node in spec.nodes:
            if node.type.value in {"organizer", "architect"}:
                handlers[node.id] = planner
            elif node.type.value == "worker":
                handlers[node.id] = worker_effect
            elif node.type.value in {"verify", "reviewer", "integrate"}:
                handlers[node.id] = verification
        return {
            key: ProtectedEffect(adapter, owner, fence, self.approval_parameters(workflow_id))
            for key, adapter in handlers.items()
        }


class LegacyRequestSource:
    def __init__(
        self,
        owner: RunOwnership,
        fence: RunFence,
        binding: RepositoryBinding,
        artifacts: EvidenceArtifacts,
    ) -> None:
        self.owner, self.fence, self.binding = owner, fence, binding
        self.artifacts = artifacts

    async def request(
        self, state: WorkflowStateV1, context: NodeContext, config: RunnableConfig
    ) -> WorkerInvocationRequest:
        key = str(state.get("tasks", {}).get("current_task", ""))
        settings = config.get("configurable", {})
        async with self.owner.fenced(self.fence) as (session, run):
            task = await session.scalar(
                select(TaskModel).where(
                    TaskModel.run_id == run.id,
                    TaskModel.key == key,
                )
            )
            if task is None:
                raise RuntimeDependencyError("worker requires an authoritative current task")
            previous = await session.scalar(
                select(TaskAttemptModel)
                .where(
                    TaskAttemptModel.task_id == task.id,
                )
                .order_by(TaskAttemptModel.attempt_number.desc())
                .limit(1)
            )
            latest = await session.scalar(
                select(WorkerInvocationModel)
                .join(
                    EffectModel,
                    EffectModel.id == WorkerInvocationModel.effect_id,
                )
                .where(
                    EffectModel.run_id == run.id,
                    WorkerInvocationModel.result_json.is_not(None),
                )
                .order_by(WorkerInvocationModel.created_at.desc())
                .limit(1)
            )
            base = self.binding.project.base_sha
            if latest is not None:
                latest_result = WorkerResult.model_validate(latest.result_json)
                base = latest_result.end_head
            attempt_id = uuid5(run.id, "worker-attempt:" + context.execution_id)
            attempt = await session.get(TaskAttemptModel, attempt_id)
            if attempt is None:
                if previous is not None and previous.status not in {"failed", "cancelled"}:
                    raise RuntimeDependencyError("task already has an active or completed attempt")
                attempt = TaskAttemptModel(
                    id=attempt_id,
                    task_id=task.id,
                    attempt_number=previous.attempt_number + 1 if previous else 1,
                    worker_revision_id=self.binding.worker_revision_id,
                    status="running",
                    base_sha=base,
                    started_at=self.owner.clock.now(),
                )
                session.add(attempt)
                task.status = "running"
                await session.flush()
                await self.owner.event(
                    session,
                    run,
                    "task.attempt_started",
                    {
                        "task_id": str(task.id),
                        "task_attempt_id": str(attempt.id),
                        "attempt": attempt.attempt_number,
                    },
                )
            project = self.binding.project.model_copy(update={"base_sha": attempt.base_sha})
            architecture_id = await self.artifacts.put(
                session, run, attempt.id, "architecture", task.verification_json["architecture"]
            )
            return WorkerInvocationRequest(
                invocation_id=uuid7(),
                idempotency_key=context.execution_id,
                run_id=run.id,
                task_id=task.id,
                task_attempt_id=attempt.id,
                worker_revision_id=self.binding.worker_revision_id,
                lease=WorkerSlotFence(
                    lease_id=uuid7(),
                    worker_revision_id=self.binding.worker_revision_id,
                    slot=0,
                    generation=1,
                    run_generation=self.fence.generation,
                    expires_at=self.owner.clock.now() + timedelta(seconds=30),
                ),
                project=project,
                architecture_artifact_id=architecture_id,
                objective=str(settings.get("runtime_objective", "")),
                task=WorkerTask.model_validate(
                    {
                        "key": task.key,
                        "title": task.title,
                        "description": task.description,
                        "acceptance_criteria": task.acceptance_criteria_json,
                        "verification": task.verification_json["commands"],
                    }
                ),
                model_profile_revision_id=UUID(str(settings["runtime_model_profile_revision_id"])),
                limits=WorkerLimits(),
            )
