"""OpenHands-over-SSH implements the generic lifecycle behind a bounded RPC."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from pydantic import ValidationError

from jarvis_api.events.redaction import RecursiveRedactor
from jarvis_contracts.base import sha256_digest
from jarvis_contracts.enums import FailureClass
from jarvis_contracts.registry import WorkerSpec
from jarvis_contracts.workers import (
    CancelResult,
    PreparedInvocation,
    ReconciliationResult,
    WorkerArtifact,
    WorkerEvent,
    WorkerHealth,
    WorkerInvocationHandle,
    WorkerInvocationRequest,
    WorkerInvocationStatus,
    WorkerRepositorySnapshot,
    WorkerResult,
    WorkerSlotFence,
    WorkerValidationReport,
)
from jarvis_orchestrator.providers.worker_configuration import (
    OpenHandsDeployment,
    validate_model_binding,
)
from jarvis_orchestrator.workers.base import WorkerCallContext
from jarvis_orchestrator.workers.safety import (
    WorkerBoundaryError,
    contained,
    encoded_argument,
    parse_sentinel,
    remote_command,
    validation_failure,
)
from jarvis_orchestrator.workers.transport import SSHTransport
from jarvis_orchestrator.workers.wrapper import WrapperLaunch

LogPublisher = Callable[[WorkerInvocationRequest, str, bytes], Awaitable[None]]


class OpenHandsSSHAdapter:
    def __init__(
        self,
        worker: WorkerSpec,
        deployment: OpenHandsDeployment,
        transport: SSHTransport,
        *,
        publish_log: LogPublisher | None = None,
        artifact_reader: Callable[[UUID], Awaitable[str]] | None = None,
        require_fence: Callable[[WorkerSlotFence], Awaitable[None]] | None = None,
    ) -> None:
        self.worker = worker
        self.deployment = deployment
        self.transport = transport
        self.require_fence = require_fence
        self.publish_log = publish_log
        self.artifact_reader = artifact_reader
        self.prepared: dict[UUID, PreparedInvocation] = {}

    async def authorize(self, lease: WorkerSlotFence) -> None:
        if self.require_fence is not None:
            await self.require_fence(lease)
        elif lease.expires_at <= datetime.now(UTC):
            raise WorkerBoundaryError("stale_worker_fence")

    async def _rpc(
        self,
        operation: str,
        context: WorkerCallContext,
        values: dict[str, object] | None = None,
        *,
        limit: int = 65536,
    ) -> dict[str, object]:
        deployment = self.deployment
        if deployment.wrapper_path is None or deployment.python_path is None:
            raise WorkerBoundaryError("wrapper_unconfigured")
        timeout = min(
            deployment.timeouts.connect_seconds + 30,
            (context.deadline - datetime.now(UTC)).total_seconds(),
        )
        if timeout <= 0:
            raise WorkerBoundaryError("invocation_deadline", FailureClass.INFRASTRUCTURE_TIMEOUT)
        command = remote_command(
            deployment.python_path,
            deployment.wrapper_path,
            encoded_argument(
                {
                    "operation": operation,
                    "invocation_root": deployment.invocation_root,
                    **(values or {}),
                },
                131072,
            ),
        )
        response = await self.transport.execute(command, timeout=timeout, limit=limit)
        if response.exit_code != 0 or response.truncated:
            raise WorkerBoundaryError("wrapper_rpc_failed")
        try:
            data = json.loads(response.stdout)
        except (ValueError, UnicodeError):
            raise WorkerBoundaryError("wrapper_protocol_invalid") from None
        if not isinstance(data, dict):
            raise WorkerBoundaryError("wrapper_protocol_invalid")
        return data

    async def health(self, worker: WorkerSpec, context: WorkerCallContext) -> WorkerHealth:
        try:
            data = await self._rpc(
                "health",
                context,
                {
                    name: getattr(self.deployment, name)
                    for name in (
                        "runner_path",
                        "python_path",
                        "venv_activate",
                        "workspace_root",
                        "invocation_root",
                    )
                },
            )
            if data.get("wrapper_version") != "1.0":
                raise WorkerBoundaryError("wrapper_version_mismatch")
            capabilities = tuple(
                str(value) for value in cast(list[object], data.get("capabilities", []))
            )
            issues = tuple(str(value) for value in cast(list[object], data.get("issues", [])))
            if set(issues) - {
                "runner_path_missing",
                "python_path_missing",
                "venv_activate_missing",
                "workspace_root_misconfigured",
                "invocation_root_misconfigured",
                "git_missing",
            }:
                raise WorkerBoundaryError("invalid_health_response")
            if set(worker.capabilities) - set(capabilities):
                issues += ("capability_missing",)
            return WorkerHealth(
                status="healthy" if not issues else "misconfigured",
                observed_at=datetime.now(UTC),
                capabilities=capabilities,
                issues=issues,
                network_checked=True,
            )
        except (WorkerBoundaryError, ValidationError) as error:
            code = (
                error.code if isinstance(error, WorkerBoundaryError) else "invalid_health_response"
            )
            unavailable = code in {"host_unreachable", "ssh_timeout", "ssh_unavailable"}
            return WorkerHealth(
                status="unavailable" if unavailable else "misconfigured",
                observed_at=datetime.now(UTC),
                issues=(code,),
            )

    async def validate(
        self, worker: WorkerSpec, context: WorkerCallContext
    ) -> WorkerValidationReport:
        health = await self.health(worker, context)
        valid = (
            health.status == "healthy"
            and worker.adapter_kind == "openhands_ssh_v1"
            and worker.max_concurrency == 1
        )
        return WorkerValidationReport(valid=valid, health=health, exclusive_workspace=True)

    async def prepare(
        self, request: WorkerInvocationRequest, lease: WorkerSlotFence, context: WorkerCallContext
    ) -> PreparedInvocation:
        if request.lease != lease:
            raise WorkerBoundaryError("stale_worker_fence")
        await self.authorize(lease)
        if not validate_model_binding(self.worker, request.model_profile_revision_id).valid:
            raise WorkerBoundaryError("incompatible_model_binding")
        if set(request.required_capabilities) - set(self.worker.capabilities):
            raise WorkerBoundaryError("capability_missing")
        expected = contained(
            self.deployment.workspace_root,
            self.deployment.workspace_root + "/" + request.project.slug,
        )
        if request.project.workspace_root != expected:
            raise WorkerBoundaryError("workspace_identity_mismatch")
        report = await self.validate(self.worker, context)
        if not report.valid:
            raise validation_failure(report)
        prepared = PreparedInvocation(request=request, request_digest=sha256_digest(request))
        previous = self.prepared.get(request.invocation_id)
        if previous is not None and previous != prepared:
            raise WorkerBoundaryError("invocation_digest_conflict")
        if previous is not None:
            observation = await self.reconcile(self.restore(previous), context)
            if observation.state == "unknown":
                raise WorkerBoundaryError("invocation_outcome_unknown")
            if observation.state != "absent":
                return previous
        # Independent preflight prevents the legacy runner initializing an arbitrary repo.
        await self.repository(request, context, request.project.base_sha)
        self.prepared[request.invocation_id] = prepared
        return prepared

    def restore(self, prepared: PreparedInvocation) -> WorkerInvocationHandle:
        if sha256_digest(prepared.request) != prepared.request_digest:
            raise WorkerBoundaryError("request_digest_mismatch")
        self.prepared[prepared.request.invocation_id] = prepared
        return WorkerInvocationHandle(
            invocation_id=prepared.request.invocation_id,
            request_digest=prepared.request_digest,
            worker_revision_id=prepared.request.worker_revision_id,
            generation=prepared.request.lease.generation,
        )

    def request(self, handle: WorkerInvocationHandle) -> WorkerInvocationRequest:
        prepared = self.prepared.get(handle.invocation_id)
        if prepared is None or self.restore(prepared) != handle:
            raise WorkerBoundaryError("invocation_identity_mismatch")
        return prepared.request

    async def start(
        self, prepared: PreparedInvocation, context: WorkerCallContext
    ) -> WorkerInvocationHandle:
        handle = self.restore(prepared)
        state = await self.reconcile(handle, context)
        if state.state == "unknown":
            raise WorkerBoundaryError("invocation_outcome_unknown")
        if state.safe_to_start:
            await self.prepare(prepared.request, prepared.request.lease, context)
            request = prepared.request
            architecture = ""
            feedback: list[str] = []
            if request.architecture_artifact_id or request.feedback_artifact_ids:
                if self.artifact_reader is None:
                    raise WorkerBoundaryError("worker_context_artifacts_unconfigured")
                if request.architecture_artifact_id:
                    architecture = await self.artifact_reader(request.architecture_artifact_id)
                for artifact_id in request.feedback_artifact_ids:
                    feedback.append(await self.artifact_reader(artifact_id))
            launch = WrapperLaunch(
                prepared=prepared,
                runner_path=self.deployment.runner_path,
                python_path=self.deployment.runner_python_path
                or self.deployment.venv_activate.rsplit("/", 1)[0] + "/python",
                invocation_root=self.deployment.invocation_root,
                architecture=RecursiveRedactor().redact_text(architecture)[0],
                feedback=RecursiveRedactor().redact_text("\n".join(feedback))[0],
            )
            try:
                await self.authorize(request.lease)
                await self._rpc("start", context, {"launch": launch.model_dump(mode="json")})
            except WorkerBoundaryError:
                observation = await self.reconcile(handle, context)
                if observation.state in {"absent", "unknown"}:
                    raise WorkerBoundaryError(
                        "invocation_outcome_" + observation.state,
                        FailureClass.INFRASTRUCTURE_WORKER_TRANSPORT,
                    ) from None
        return handle

    async def inspect(
        self, handle: WorkerInvocationHandle, context: WorkerCallContext
    ) -> WorkerInvocationStatus:
        self.request(handle)
        data = await self._rpc("inspect", context, handle.model_dump(mode="json"))
        state = data.get("state")
        if state not in {
            "absent",
            "starting",
            "running",
            "succeeded",
            "failed",
            "cancelled",
            "unknown",
        }:
            raise WorkerBoundaryError("invalid_invocation_state")
        if state != "absent" and (
            data.get("invocation_id") != str(handle.invocation_id)
            or data.get("request_digest") != handle.request_digest
        ):
            raise WorkerBoundaryError("invocation_identity_mismatch")
        activity = data.get("last_activity_at", data.get("started_at"))
        observed = datetime.fromisoformat(str(activity)) if activity else None
        return WorkerInvocationStatus(
            invocation_id=handle.invocation_id,
            state=state,
            source_sequence=int(str(data.get("source_sequence", 0))),
            last_activity_at=observed,
            possibly_stalled=state == "running"
            and observed is not None
            and (datetime.now(UTC) - observed).total_seconds()
            > self.deployment.timeouts.heartbeat_seconds * 3,
        )

    async def reconcile(
        self, handle: WorkerInvocationHandle, context: WorkerCallContext
    ) -> ReconciliationResult:
        try:
            observation = await self.inspect(handle, context)
            return ReconciliationResult(
                invocation_id=handle.invocation_id,
                state=observation.state,
                safe_to_start=observation.state == "absent",
            )
        except WorkerBoundaryError:
            return ReconciliationResult(invocation_id=handle.invocation_id, state="unknown")

    async def events(
        self, handle: WorkerInvocationHandle, after_source_sequence: int, context: WorkerCallContext
    ) -> AsyncIterator[WorkerEvent]:
        observed = await self.inspect(handle, context)
        if observed.source_sequence > after_source_sequence and observed.state != "absent":
            yield WorkerEvent(
                invocation_id=handle.invocation_id,
                source_sequence=observed.source_sequence,
                occurred_at=datetime.now(UTC),
                type="worker.heartbeat",
            )

    async def cancel(
        self, handle: WorkerInvocationHandle, reason: str, context: WorkerCallContext
    ) -> CancelResult:
        self.request(handle)
        try:
            await self._rpc("cancel", context, handle.model_dump(mode="json"))
            for _ in range(30):
                observed = await self.inspect(handle, context)
                if observed.state in {"cancelled", "absent"}:
                    return CancelResult(invocation_id=handle.invocation_id, status="cancelled")
                if observed.state in {"failed", "succeeded"}:
                    return CancelResult(
                        invocation_id=handle.invocation_id, status="already_terminal"
                    )
                if observed.state == "unknown":
                    break
                await asyncio.sleep(0.1)
        except WorkerBoundaryError:
            pass
        return CancelResult(invocation_id=handle.invocation_id, status="unknown")

    async def repository(
        self, request: WorkerInvocationRequest, context: WorkerCallContext, head: str
    ) -> WorkerRepositorySnapshot:
        data = await self._rpc(
            "repository",
            context,
            {
                "workspace_root": self.deployment.workspace_root,
                "workspace": request.project.workspace_root,
                "branch": request.project.branch,
                "head": head,
                "base_sha": request.project.base_sha,
            },
        )
        return WorkerRepositorySnapshot.model_validate(data)

    async def collect(
        self, handle: WorkerInvocationHandle, context: WorkerCallContext
    ) -> WorkerResult:
        request = self.request(handle)
        data = await self._rpc(
            "collect",
            context,
            handle.model_dump(mode="json"),
            limit=min(104857600, request.limits.max_output_bytes * 12 + 262144),
        )
        if (
            data.get("invocation_id") != str(handle.invocation_id)
            or data.get("request_digest") != handle.request_digest
        ):
            raise WorkerBoundaryError("invocation_identity_mismatch")
        artifacts = []
        if data.get("state") not in {"succeeded", "failed"}:
            raise WorkerBoundaryError("invocation_not_terminal")
        for kind in ("stdout", "stderr"):
            raw = str(data.get(kind, "")).encode()
            if len(raw) > request.limits.max_output_bytes:
                raise WorkerBoundaryError("log_oversized")
            safe = RecursiveRedactor().redact_text(raw.decode(errors="replace"))[0].encode()
            if self.publish_log:
                await self.publish_log(request, kind, safe)
            artifacts.append(
                WorkerArtifact(
                    kind=kind,
                    sha256=hashlib.sha256(safe).hexdigest(),
                    size_bytes=len(safe),
                )
            )
        if data.get("stop_reason") == "timeout":
            raise WorkerBoundaryError("runner_timeout", FailureClass.INFRASTRUCTURE_TIMEOUT)
        legacy = parse_sentinel(
            str(data.get("sentinel", "")).encode(),
            int(str(data.get("exit_code", -1))),
            request.task.key,
            max_bytes=request.limits.max_result_bytes,
        )
        if data.get("state") == "failed" and legacy.error is None:
            raise WorkerBoundaryError("inconsistent_wrapper_state")
        contained(self.deployment.workspace_root, legacy.workspace)
        if (
            legacy.workspace != request.project.workspace_root
            or legacy.start_head != request.project.base_sha
        ):
            raise WorkerBoundaryError("repository_identity_mismatch")
        snapshot = await self.repository(request, context, legacy.end_head)
        return WorkerResult(
            invocation_id=handle.invocation_id,
            task_id=request.task_id,
            task_attempt_id=request.task_attempt_id,
            request_digest=handle.request_digest,
            generation=handle.generation,
            status="succeeded" if legacy.error is None else "failed",
            workspace_root=legacy.workspace,
            branch=request.project.branch,
            start_head=legacy.start_head,
            end_head=legacy.end_head,
            repository_snapshot=snapshot,
            artifact_manifest=tuple(artifacts),
            summary="Worker invocation collected",
            error=None if legacy.error is None else "runner_implementation_failure",
            model_profile_revision_id=request.model_profile_revision_id,
            started_at=datetime.fromisoformat(str(data["started_at"])),
            finished_at=datetime.fromisoformat(str(data["finished_at"])),
            source_sequence=int(str(data["source_sequence"])),
        )
