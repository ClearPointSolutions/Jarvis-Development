"""Normal real-mode composition from private infrastructure and immutable run data."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid5

from langchain_core.runnables import RunnableConfig
from pydantic import JsonValue
from sqlalchemy import func, select
from uuid6 import uuid7

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.enums import FailureClass
from jarvis_contracts.missions import FixedTeamSelection
from jarvis_contracts.registry import (
    ModelProfileSpec,
    PermissionPolicySpec,
    ProviderSpec,
    RetryRegistrySpec,
    WorkerPoolSpec,
    WorkerSpec,
)
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
from jarvis_orchestrator.providers.budget import bound_budget
from jarvis_orchestrator.providers.runtime import RuntimeModel
from jarvis_orchestrator.runtime.approvals import ProtectedEffect, approval_handler
from jarvis_orchestrator.runtime.binding import freeze_binding
from jarvis_orchestrator.runtime.configuration import RealRuntimeConfiguration, RepositoryBinding
from jarvis_orchestrator.runtime.effects import EffectAdapter
from jarvis_orchestrator.runtime.errors import RuntimeDependencyError
from jarvis_orchestrator.runtime.historical import HistoricalPreparation
from jarvis_orchestrator.runtime.model_selection import select_model
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership
from jarvis_orchestrator.runtime.planning import PlanningEffect
from jarvis_orchestrator.runtime.repository_lifecycle import accepted_source
from jarvis_orchestrator.verification.artifacts import EvidenceArtifacts
from jarvis_orchestrator.verification.integration import LocalIntegrator
from jarvis_orchestrator.verification.isolated_executor import IsolatedVerificationExecutor
from jarvis_orchestrator.verification.leases import IntegrationLeases
from jarvis_orchestrator.verification.model_reviewer import ModelReviewer
from jarvis_orchestrator.verification.profiles import ExecutionProfileCatalog, ProfileBinding
from jarvis_orchestrator.verification.reviews import ReviewerAdapter, ReviewService
from jarvis_orchestrator.verification.runtime import (
    LocalVerificationBinding,
    VerificationEffectAdapter,
)
from jarvis_orchestrator.verification.service import VerificationService
from jarvis_orchestrator.verification.snapshots import SnapshotBuilder
from jarvis_orchestrator.workers.artifacts import WorkerContextReader, WorkerLogPublisher
from jarvis_orchestrator.workers.candidate_store import import_candidate, recover_candidate
from jarvis_orchestrator.workers.openhands import OpenHandsSSHAdapter
from jarvis_orchestrator.workers.runtime import WorkerEffectAdapter
from jarvis_orchestrator.workers.scheduler import AssignmentRequest, EligibleWorker, select_worker
from jarvis_orchestrator.workers.transport import OpenSSHTransport, SSHCredentials
from jarvis_orchestrator.workers.workspace import WorktreeManager
from jarvis_orchestrator.workflows.factories import NodeContext, NodeHandler
from jarvis_orchestrator.workflows.state import WorkflowStateV1
from jarvis_orchestrator.workflows.validation import effective_policy
from jarvis_persistence.models import (
    ConfigurationModel,
    ConfigurationRevisionModel,
    EffectModel,
    JobModel,
    MissionTeamVersionModel,
    MissionWorkItemModel,
    ProjectModel,
    RunConfigSnapshotModel,
    TaskAttemptModel,
    TaskModel,
    WorkerAssignmentModel,
    WorkerHealthModel,
    WorkerInvocationModel,
    WorkerLeaseModel,
    WorkerSlotModel,
)

# A real provider intermittently returns a malformed structured response, times
# out or drops a connection. Without a bound rule those classes are unretryable
# and block the run at its first hiccup, so the gap is reported before starting.
REQUIRED_MODEL_RETRY_CLASSES = (
    FailureClass.PROVIDER_CONTRACT_FAILURE,
    FailureClass.PROVIDER_TRANSIENT,
    FailureClass.PROVIDER_RATE_LIMITED,
    FailureClass.INFRASTRUCTURE_TIMEOUT,
    FailureClass.INFRASTRUCTURE_SERVICE_UNAVAILABLE,
)


def require_provider_retry_rules(context: NodeContext) -> None:
    """Refuse a real model node whose bound retry policy cannot absorb providers."""

    reference = context.policy.retry_policy_ref
    policy = next(
        (
            revision.spec
            for revision in context.snapshot.revisions
            if revision.revision_id == reference
        ),
        None,
    )
    if not isinstance(policy, RetryRegistrySpec):
        raise RuntimeDependencyError(
            f"node {context.node.id} has no immutable retry policy for real model use"
        )
    covered = {rule.failure_class for rule in policy.rules if rule.max_retries > 0}
    missing = [item.value for item in REQUIRED_MODEL_RETRY_CLASSES if item not in covered]
    if missing:
        raise RuntimeDependencyError(
            f"retry policy for node {context.node.id} has no retries for "
            + ", ".join(missing)
            + "; real providers require these rules"
        )


class RealComposition:
    def __init__(self, settings: RealRuntimeConfiguration, artifact_root: Path) -> None:
        self.settings, self.artifact_root = settings, artifact_root

    async def approval_parameters(
        self, owner: RunOwnership, fence: RunFence
    ) -> dict[str, JsonValue]:
        async with owner.fenced(fence) as (session, run):
            snapshot = await session.get(RunConfigSnapshotModel, run.config_snapshot_id)
            if snapshot is None:
                raise RuntimeDependencyError("bound run configuration is unavailable")
            binding = snapshot.effective_spec_json.get("repository_binding")
            if not isinstance(binding, dict):
                raise RuntimeDependencyError("run has no immutable repository binding")
            return {
                "binding_digest": binding["binding_digest"],
                "repository_id": binding["repository_id"],
            }

    async def approvals(
        self, owner: RunOwnership, fence: RunFence, spec: WorkflowSpec, workflow_id: UUID
    ) -> NodeHandler:
        return approval_handler(owner, fence, spec, await self.approval_parameters(owner, fence))

    def model(
        self,
        owner: RunOwnership,
        fence: RunFence,
        context: NodeContext,
        config: RunnableConfig,
        *,
        max_inference_calls: int | None = None,
        mission_id: UUID | None = None,
        team_version_id: UUID | None = None,
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
            bound_budget(
                context,
                max_inference_calls=max_inference_calls,
                mission_id=mission_id,
                team_version_id=team_version_id,
            ),
        )

    async def build(
        self,
        owner: RunOwnership,
        fence: RunFence,
        spec: WorkflowSpec,
        snapshot: WorkflowResolvedSnapshot,
        workflow_id: UUID,
        *,
        dependency_preflight: bool = True,
    ) -> dict[str, EffectAdapter]:
        # V1 has no real publication handler. Refuse before any billed inference
        # or worker dispatch instead of failing at the unreachable publish node.
        unsupported = sorted(node.id for node in spec.nodes if node.type.value == "github_publish")
        if unsupported:
            raise RuntimeDependencyError(
                "GitHub publication is not supported in real mode; remove "
                + ", ".join(unsupported)
                + " from the published workflow"
            )
        async with owner.fenced(fence) as (session, run):
            job = await session.get(JobModel, run.job_id)
            if job is None:
                raise RuntimeDependencyError("run project is unavailable")
            project_id = job.project_id
            project = await session.get(ProjectModel, project_id)
            if project is None:
                raise RuntimeDependencyError("run project is unavailable")
            frozen_config = await session.get(RunConfigSnapshotModel, run.config_snapshot_id)
            team_selection = (
                FixedTeamSelection.model_validate(frozen_config.effective_spec_json["mission_team"])
                if frozen_config is not None and "mission_team" in frozen_config.effective_spec_json
                else None
            )
            mission_id = (
                UUID(str(run.runtime_json["mission_id"]))
                if "mission_id" in run.runtime_json
                else None
            )
            team_version_id = (
                UUID(str(run.runtime_json["team_version_id"]))
                if "team_version_id" in run.runtime_json
                else None
            )
            max_inference_calls = (
                team_selection.budgets.max_inference_calls if team_selection else None
            )
        try:
            binding = self.settings.repository_binding(project_id, workflow_id)
        except ValueError as exc:
            raise RuntimeDependencyError(str(exc)) from None
        if team_selection and team_selection.eligible_worker_revision_ids:
            candidates: list[EligibleWorker] = []
            health_freshness_seconds = 60
            async with owner.fenced(fence) as (session, _run):
                pool_ids = {
                    pool_id
                    for member in team_selection.members
                    if member.may_execute
                    for pool_id in member.worker_pool_revision_ids
                }
                for pool_id in pool_ids:
                    pool_row = await session.get(ConfigurationRevisionModel, pool_id)
                    if pool_row is not None:
                        pool = WorkerPoolSpec.model_validate(pool_row.spec_json["spec"])
                        health_freshness_seconds = min(
                            health_freshness_seconds, pool.health_freshness_seconds
                        )
                for revision_id in team_selection.eligible_worker_revision_ids:
                    revision_row = await session.get(ConfigurationRevisionModel, revision_id)
                    identity = (
                        await session.get(ConfigurationModel, revision_row.configuration_id)
                        if revision_row
                        else None
                    )
                    if revision_row is None or identity is None:
                        continue
                    worker_spec = WorkerSpec.model_validate(revision_row.spec_json["spec"])
                    resource_id = worker_spec.physical_resource_id or str(identity.id)
                    slots_in_use = int(
                        await session.scalar(
                            select(func.count(WorkerLeaseModel.id))
                            .join(WorkerSlotModel, WorkerSlotModel.id == WorkerLeaseModel.slot_id)
                            .where(
                                WorkerSlotModel.physical_resource_id == resource_id,
                                WorkerLeaseModel.released_at.is_(None),
                            )
                        )
                        or 0
                    )
                    health = await session.get(WorkerHealthModel, revision_id)
                    health_report = health.report_json if health else {}
                    candidates.append(
                        EligibleWorker(
                            revision_id=revision_id,
                            physical_resource_id=resource_id,
                            capabilities=frozenset(worker_spec.capabilities),
                            permitted_project_ids=frozenset(worker_spec.permitted_project_ids),
                            execution_profile_ids=frozenset(
                                worker_spec.execution_profile_revision_ids
                            ),
                            capacity=worker_spec.max_concurrency,
                            slots_in_use=slots_in_use,
                            health=str(
                                health_report.get("health", {}).get(
                                    "status", "healthy" if run.mode == "demo" else "unknown"
                                )
                            ),
                            observed_at=health.observed_at
                            if health
                            else owner.clock.now()
                            if run.mode == "demo"
                            else None,
                            enabled=identity.enabled and identity.archived_at is None,
                        )
                    )
            selected, _reason = select_worker(
                AssignmentRequest(
                    id=run.id,
                    mission_id=UUID(str(run.runtime_json["mission_id"])),
                    priority=run.priority,
                    fairness_sequence=(run.id.int % (2**63 - 1)) or 1,
                    project_id=project_id,
                    required_capabilities=frozenset({"code", "git"}),
                    execution_profile_ids=frozenset(
                        UUID(value) for value in project.execution_profile_revision_ids_json
                    ),
                    health_freshness_seconds=health_freshness_seconds,
                ),
                tuple(candidates),
                now=owner.clock.now(),
                allow_saturated=True,
            )
            if selected is None:
                raise RuntimeDependencyError("worker pool is waiting for eligible capacity")
            deployment = self.settings.workers.get(selected.revision_id)
            if deployment is None:
                raise RuntimeDependencyError("selected worker deployment is not configured")
            binding = binding.model_copy(
                update={
                    "worker_revision_id": selected.revision_id,
                    "project": binding.project.model_copy(
                        update={
                            "workspace_root": deployment.workspace_root + "/" + binding.project.slug
                        }
                    ),
                }
            )
        selected_profiles = set(binding.execution_profile_revision_ids)
        stored_profiles = {UUID(value) for value in project.execution_profile_revision_ids_json}
        if binding.project_type != project.project_type or selected_profiles != stored_profiles:
            raise RuntimeDependencyError(
                "private repository binding does not match approved project execution profiles"
            )
        command_profiles = {
            command.profile_revision_id
            for command in binding.combined_commands
            if command.profile_revision_id is not None
        }
        if binding.project_type != "python" and not selected_profiles:
            raise RuntimeDependencyError("web projects require explicit execution profiles")
        if command_profiles - selected_profiles:
            raise RuntimeDependencyError(
                "verification command references an unselected execution profile"
            )
        if selected_profiles - set(self.settings.verification_isolation.profiles):
            raise RuntimeDependencyError("selected execution profile is not installed")
        deployment = self.settings.workers.get(binding.worker_revision_id)
        revision = next(
            (row for row in snapshot.revisions if row.revision_id == binding.worker_revision_id),
            None,
        )
        worker = revision.spec if revision is not None else None
        if worker is None and team_selection is not None:
            async with owner.fenced(fence) as (session, _run):
                row = await session.get(ConfigurationRevisionModel, binding.worker_revision_id)
                worker = WorkerSpec.model_validate(row.spec_json["spec"]) if row else None
        if deployment is None or not isinstance(worker, WorkerSpec):
            raise RuntimeDependencyError("immutable worker deployment binding is unavailable")
        if worker.adapter_kind != "openhands_ssh_v1" or worker.max_concurrency != 1:
            raise RuntimeDependencyError(
                "first-test composition requires the exclusive legacy worker"
            )
        if binding.project.workspace_root != deployment.workspace_root + "/" + binding.project.slug:
            raise RuntimeDependencyError("legacy runner cannot honor the configured workspace")
        if deployment.host_alias not in self.settings.allowed_worker_hosts:
            raise RuntimeDependencyError("worker target is not permitted by the repository binding")
        for node in spec.nodes:
            if node.type.value == "worker":
                selector = effective_policy(spec, node).worker_selector
                permitted = (
                    set(team_selection.eligible_worker_revision_ids)
                    if team_selection
                    else {binding.worker_revision_id}
                )
                if selector is None or binding.worker_revision_id not in permitted:
                    raise RuntimeDependencyError("workflow worker differs from repository binding")
        lifecycle = await accepted_source(owner, fence, binding)
        await freeze_binding(
            owner,
            fence,
            {
                "project_id": str(project_id),
                "workflow_version_id": str(workflow_id),
                "repository_id": str(binding.project.repository_id),
                "worker_revision_id": str(binding.worker_revision_id),
                "binding_digest": sha256_digest(
                    {
                        "repository": binding.model_dump(mode="json", exclude={"base_policy"})
                        if binding.base_policy == "current"
                        else binding.model_dump(mode="json"),
                        "deployment": deployment.model_dump(mode="json"),
                        "verification": self.settings.verification_isolation.model_dump(
                            mode="json"
                        ),
                    }
                ),
                "target_digest": sha256_digest(deployment),
                "lifecycle": lifecycle,
            },
        )
        source_project = binding.project
        target = binding.project.model_copy(update={"base_sha": str(lifecycle["worker_base_sha"])})
        if binding.base_policy == "historical":
            slug = source_project.slug[:20] + "-history-" + fence.run_id.hex
            target = target.model_copy(
                update={"slug": slug, "workspace_root": deployment.workspace_root + "/" + slug}
            )
        binding = binding.model_copy(update={"project": target})
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
        run_root = self.settings.source_root / UUID(str(lifecycle["source_store_id"])).hex
        run_root.mkdir(parents=True, exist_ok=True)
        manager = WorktreeManager(run_root, git_executable=str(self.settings.git_executable))
        configured_profiles = tuple(
            ProfileBinding(revision_id, runtime.spec, runtime.image_id, runtime.tool_versions)
            for revision_id, runtime in self.settings.verification_isolation.profiles.items()
            if not binding.execution_profile_revision_ids
            or revision_id in binding.execution_profile_revision_ids
        )
        executor = IsolatedVerificationExecutor(
            manager,
            self.settings.verification_isolation.broker_argv,
            self.settings.verification_isolation.image_id,
            profiles=ExecutionProfileCatalog(configured_profiles) if configured_profiles else None,
            project_type=binding.project_type,
        )
        if lifecycle["previous_run_id"] is not None:
            # Accepted Core merges and worker commits can have different SHAs,
            # but the next serial worker must start with identical accepted files.
            repository = run_root / "repository"
            worker_tree, _ = await manager.git(
                repository, "rev-parse", binding.project.base_sha + "^{tree}"
            )
            core_tree, _ = await manager.git(
                repository, "rev-parse", str(lifecycle["integration_base_sha"]) + "^{tree}"
            )
            if worker_tree != core_tree:
                raise RuntimeDependencyError(
                    "accepted Core and worker source differ; synchronization required"
                )
        artifacts = EvidenceArtifacts(owner, fence, self.artifact_root)
        historical = (
            HistoricalPreparation(
                owner,
                fence,
                deployment,
                transport,
                self.settings.source_root,
                source_project,
                binding.project,
                binding.worker_revision_id,
                lifecycle,
                git_executable=str(self.settings.git_executable),
                author_name=self.settings.git_author_name,
                author_email=self.settings.git_author_email,
            )
            if binding.base_policy == "historical"
            else None
        )
        request_source = LegacyRequestSource(
            owner,
            fence,
            binding,
            artifacts,
            prepare_workspace=historical.ensure if historical else None,
        )
        worker_effect = WorkerEffectAdapter(owner, fence, worker, native, request_source.request)
        # Cancellation must be constructible while a provider is unavailable.
        # Ordinary execution still completes every dependency check before any
        # Organizer inference or worker dispatch.
        if dependency_preflight:
            report = await native.validate(worker, worker_effect.context())
            if not report.valid:
                raise RuntimeDependencyError(
                    "worker dependency preflight failed: " + ",".join(report.health.issues)
                )
            if historical is not None and native.historical_workspace_version != "1.0":
                raise RuntimeDependencyError(
                    "worker lacks isolated historical workspace capability"
                )
        checked: set[UUID] = set()
        reviewer_context: NodeContext | None = None
        reviewer_config: RunnableConfig = {}
        for node in spec.nodes:
            context = NodeContext(node, effective_policy(spec, node), snapshot, "preflight")
            if node.type.value == "worker":
                selector = context.policy.worker_selector
                permitted_workers = (
                    set(team_selection.eligible_worker_revision_ids)
                    if team_selection is not None
                    else {binding.worker_revision_id}
                )
                if selector is None or binding.worker_revision_id not in permitted_workers:
                    raise RuntimeDependencyError(
                        "selected worker is outside the workflow's frozen team pool"
                    )
                continue
            if node.type.value not in {"organizer", "architect", "reviewer"}:
                continue
            require_provider_retry_rules(context)
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
            model = self.model(
                owner,
                fence,
                context,
                config,
                max_inference_calls=max_inference_calls,
                mission_id=mission_id,
                team_version_id=team_version_id,
            )
            if not model.profile.structured_json:
                raise RuntimeDependencyError("planning/review requires a structured JSON profile")
            if dependency_preflight and model.adapter.profile_revision_id not in checked:
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
            return ModelReviewer(
                self.model(
                    owner,
                    fence,
                    context,
                    config,
                    max_inference_calls=max_inference_calls,
                    mission_id=mission_id,
                    team_version_id=team_version_id,
                )
            )

        async def transfer(request: WorkerInvocationRequest, result: WorkerResult) -> Path:
            cached = await recover_candidate(manager, result)
            if cached is not None:
                return cached
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
                str(lifecycle["integration_base_sha"]),
                binding.project.branch,
                binding.combined_commands,
                no_remote_path,
                transfer,
                candidate_branches=True,
            ),
            reviewer_factory=reviewer_factory,
        )
        planner = PlanningEffect(
            self.settings.providers,
            owner,
            fence,
            max_inference_calls=max_inference_calls,
            mission_id=mission_id,
            team_version_id=team_version_id,
        )
        handlers: dict[str, EffectAdapter] = {}
        for node in spec.nodes:
            if node.type.value in {"organizer", "architect"}:
                handlers[node.id] = planner
            elif node.type.value == "worker":
                handlers[node.id] = worker_effect
            elif node.type.value in {"verify", "reviewer", "integrate"}:
                handlers[node.id] = verification
        parameters = await self.approval_parameters(owner, fence)
        return {
            key: ProtectedEffect(adapter, owner, fence, parameters)
            for key, adapter in handlers.items()
        }


class LegacyRequestSource:
    def __init__(
        self,
        owner: RunOwnership,
        fence: RunFence,
        binding: RepositoryBinding,
        artifacts: EvidenceArtifacts,
        *,
        prepare_workspace: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.owner, self.fence, self.binding = owner, fence, binding
        self.artifacts = artifacts
        self.prepare_workspace = prepare_workspace

    async def request(
        self, state: WorkflowStateV1, context: NodeContext, config: RunnableConfig
    ) -> WorkerInvocationRequest:
        allowed_tools: tuple[str, ...] = ()
        permission_policy_revision_id: UUID | None = None
        if self.prepare_workspace is not None:
            await self.prepare_workspace()
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
            mission_item = await session.scalar(
                select(MissionWorkItemModel).where(MissionWorkItemModel.run_id == run.id)
            )
            if attempt is None:
                if previous is not None and previous.status not in {"failed", "cancelled"}:
                    raise RuntimeDependencyError("task already has an active or completed attempt")
                attempt = TaskAttemptModel(
                    id=attempt_id,
                    task_id=task.id,
                    attempt_number=previous.attempt_number + 1 if previous else 1,
                    worker_revision_id=self.binding.worker_revision_id,
                    # Capacity is reserved before this becomes a semantic coding
                    # attempt. A queued logical assignment survives restarts and
                    # worker saturation without spending an attempt.
                    status="queued",
                    base_sha=base,
                )
                session.add(attempt)
                await session.flush()
                if mission_item is not None:
                    team = await session.get(MissionTeamVersionModel, mission_item.team_version_id)
                    if team is None:
                        raise RuntimeDependencyError("assignment team snapshot is unavailable")
                    selection = FixedTeamSelection.model_validate(team.selection_json)
                    eligible = selection.eligible_worker_revision_ids or (
                        self.binding.worker_revision_id,
                    )
                    if self.binding.worker_revision_id not in eligible:
                        raise RuntimeDependencyError(
                            "configured worker is outside the immutable eligible pool"
                        )
                    session.add(
                        WorkerAssignmentModel(
                            id=uuid7(),
                            mission_id=mission_item.mission_id,
                            team_version_id=team.id,
                            run_id=run.id,
                            task_attempt_id=attempt.id,
                            role_key="developer",
                            priority=run.priority,
                            fairness_sequence=(attempt.id.int % (2**63 - 1)) or 1,
                            required_capabilities_json=["code", "git"],
                            eligible_pool_snapshot_json={
                                "worker_revision_ids": [str(item) for item in eligible],
                                "team_version_id": str(team.id),
                            },
                            snapshot_hash=selection.worker_pool_snapshot_hash
                            or sha256_digest(
                                {"worker_revision_ids": [str(item) for item in eligible]}
                            ),
                            status="queued",
                            queued_reason="awaiting_worker_capacity",
                        )
                    )
            if mission_item is not None:
                team = await session.get(MissionTeamVersionModel, mission_item.team_version_id)
                if team is None:
                    raise RuntimeDependencyError("assignment team snapshot is unavailable")
                selection = FixedTeamSelection.model_validate(team.selection_json)
                if selection.members:
                    member = next(
                        (item for item in selection.members if item.key == "developer"), None
                    ) or next(item for item in selection.members if item.may_execute)
                    worker_row = await session.get(
                        ConfigurationRevisionModel, self.binding.worker_revision_id
                    )
                    if worker_row is None:
                        raise RuntimeDependencyError("selected worker revision is unavailable")
                    worker_spec = WorkerSpec.model_validate(worker_row.spec_json["spec"])
                    permission_row = await session.get(
                        ConfigurationRevisionModel, member.permission_policy_revision_id
                    )
                    permission_identity = (
                        await session.get(ConfigurationModel, permission_row.configuration_id)
                        if permission_row
                        else None
                    )
                    if (
                        permission_row is None
                        or permission_identity is None
                        or not permission_identity.enabled
                        or permission_identity.archived_at is not None
                    ):
                        raise RuntimeDependencyError("current security policy disables assignment")
                    permission = PermissionPolicySpec.model_validate(
                        permission_row.spec_json["spec"]
                    )
                    allowed_tools = tuple(
                        sorted(
                            set(member.allowed_tools)
                            & set(worker_spec.capabilities)
                            & set(permission.allowed_capabilities)
                            - set(permission.denied_capabilities)
                        )
                    )
                    if not {"code", "git"} <= set(allowed_tools):
                        raise RuntimeDependencyError(
                            "role, worker and security tool intersection denies development"
                        )
                    permission_policy_revision_id = member.permission_policy_revision_id
            project = self.binding.project.model_copy(update={"base_sha": attempt.base_sha})
            architecture: JsonValue = task.verification_json["architecture"]
            if settings.get("runtime_instructions"):
                architecture = {
                    "architecture": architecture,
                    "supervisor_instructions": settings["runtime_instructions"],
                }
            architecture_id = await self.artifacts.put(
                session, run, attempt.id, "architecture", architecture
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
                allowed_tools=allowed_tools,
                permission_policy_revision_id=permission_policy_revision_id,
                limits=WorkerLimits(),
            )
