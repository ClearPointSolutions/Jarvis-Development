"""Deterministic SSH RPC fixture: no sockets, host resolution or external processes."""

from __future__ import annotations

import json
import shlex
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.enums import FailureClass
from jarvis_contracts.registry import ModelBinding, WorkerSpec
from jarvis_contracts.workers import (
    WorkerInvocationRequest,
    WorkerLimits,
    WorkerProject,
    WorkerSlotFence,
    WorkerTask,
)
from jarvis_orchestrator.providers.worker_configuration import OpenHandsDeployment
from jarvis_orchestrator.workers.safety import WorkerBoundaryError, decode_object
from jarvis_orchestrator.workers.transport import TransportResult
from jarvis_orchestrator.workers.wrapper import WrapperLaunch


def worker_request() -> WorkerInvocationRequest:
    revision = uuid4()
    return WorkerInvocationRequest(
        invocation_id=uuid4(),
        idempotency_key=str(uuid4()),
        run_id=uuid4(),
        task_id=uuid4(),
        task_attempt_id=uuid4(),
        worker_revision_id=revision,
        lease=WorkerSlotFence(
            lease_id=uuid4(),
            worker_revision_id=revision,
            slot=0,
            generation=1,
            run_generation=1,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        ),
        project=WorkerProject(
            project_id=uuid4(),
            repository_id=uuid4(),
            slug="fixture",
            workspace_root="/local/workspaces/fixture",
            branch="jarvis/fixture/DEV-001-a1",
            base_sha="a" * 40,
        ),
        objective="Build a local fixture",
        task=WorkerTask(
            key="DEV-001",
            title="Fixture",
            description="Create fixture",
            acceptance_criteria=("Fixture exists",),
        ),
        model_profile_revision_id=uuid4(),
        limits=WorkerLimits(max_output_bytes=4096),
    )


def worker_spec(request: WorkerInvocationRequest) -> WorkerSpec:
    return WorkerSpec(
        adapter_kind="openhands_ssh_v1",
        capabilities=("code", "git"),
        model_binding=ModelBinding(
            mode="worker_managed", allowed_profile_revision_ids=(request.model_profile_revision_id,)
        ),
        deployment_configured=True,
    )


def deployment() -> OpenHandsDeployment:
    return OpenHandsDeployment(
        host_alias="localhost",
        user="fixture",
        ssh_key_ref="secret:fixture-key",
        host_key_ref="secret:fixture-pin",
        workspace_root="/local/workspaces",
        invocation_root="/local/v1-invocations",
        runner_path="/local/runner.py",
        venv_activate="/local/venv/bin/activate",
        python_path="/local/venv/bin/python",
        wrapper_path="/local/v1-wrapper/entry.py",
    )


class FakeWorkerSSH:
    def __init__(self, scenario: str = "success") -> None:
        self.scenario = scenario
        self.invocations: dict[str, dict[str, object]] = {}
        self.starts = 0
        self.operations: list[str] = []
        self.requests: dict[str, WorkerInvocationRequest] = {}

    async def execute(self, command: str, *, timeout: float, limit: int) -> TransportResult:
        argv = shlex.split(command)
        assert len(argv) == 3 and argv[:2] == [
            "/local/venv/bin/python",
            "/local/v1-wrapper/entry.py",
        ]
        payload = decode_object(argv[2])
        operation = str(payload["operation"])
        self.operations.append(operation)
        if self.scenario == "host_key_mismatch":
            raise WorkerBoundaryError(
                "host_key_mismatch", FailureClass.INFRASTRUCTURE_WORKER_TRANSPORT
            )
        result = self.respond(operation, payload)
        encoded = json.dumps(result).encode()
        return TransportResult(encoded[:limit], b"", 0, len(encoded) > limit)

    def respond(self, operation: str, payload: dict[str, object]) -> dict[str, object]:
        if operation == "health":
            return {
                "wrapper_version": "1.0",
                "capabilities": ["code", "git"],
                "issues": ["runner_path_missing"] if self.scenario == "missing_runner" else [],
            }
        if operation == "repository":
            if self.scenario in {"wrong_root", "wrong_head"}:
                raise WorkerBoundaryError("repository_identity_mismatch")
            return {
                "head_sha": payload["head"],
                "tree_digest": "b" * 64,
                "status_digest": "c" * 64,
                "git_status": "dirty" if self.scenario == "dirty" else "clean",
                "file_count": 1,
                "manifest_digest": "d" * 64,
                "diff_digest": "e" * 64,
            }
        identity = str(payload.get("invocation_id", ""))
        if operation == "start":
            if self.scenario == "disconnect_before":
                raise WorkerBoundaryError(
                    "ssh_unavailable", FailureClass.INFRASTRUCTURE_WORKER_TRANSPORT
                )
            launch = WrapperLaunch.model_validate(payload["launch"])
            request = launch.prepared.request
            identity = str(request.invocation_id)
            if identity in self.invocations:
                if self.invocations[identity]["request_digest"] != launch.prepared.request_digest:
                    raise WorkerBoundaryError("invocation_digest_conflict")
                return self.invocations[identity]
            self.starts += 1
            assert sha256_digest(request) == launch.prepared.request_digest
            self.requests[identity] = request
            self.invocations[identity] = {
                "invocation_id": identity,
                "request_digest": launch.prepared.request_digest,
                "state": "running"
                if self.scenario in {"running", "disconnect_after", "cancel_unknown", "unknown"}
                else "succeeded",
                "source_sequence": 2,
                "started_at": datetime.now(UTC).isoformat(),
            }
            if self.scenario == "disconnect_after":
                raise WorkerBoundaryError(
                    "ssh_unavailable", FailureClass.INFRASTRUCTURE_WORKER_TRANSPORT
                )
            return self.invocations[identity]
        if operation == "inspect":
            if self.scenario == "unknown" and identity in self.invocations:
                raise WorkerBoundaryError(
                    "host_unreachable", FailureClass.INFRASTRUCTURE_WORKER_TRANSPORT
                )
            return self.invocations.get(identity, {"state": "absent", "invocation_id": identity})
        if operation == "cancel":
            record = self.invocations[identity]
            record["state"] = "unknown" if self.scenario == "cancel_unknown" else "cancelled"
            return record
        if operation == "collect":
            request = self.requests[identity]
            sentinel = "JARVIS_RESULT_JSON=" + json.dumps(
                {
                    "task_id": "forged" if self.scenario == "mismatched" else request.task.key,
                    "workspace": "/escape"
                    if self.scenario == "traversal"
                    else request.project.workspace_root,
                    "start_head": request.project.base_sha,
                    "end_head": "b" * 40,
                    "diff_stat": "1 file",
                    "error": None,
                    "execution_status": "finished",
                }
            )
            if self.scenario == "malformed":
                sentinel = "JARVIS_RESULT_JSON=oops"
            if self.scenario == "missing":
                sentinel = ""
            return {
                **self.invocations[identity],
                "sentinel": sentinel,
                "stdout": "worker output\n",
                "stderr": "",
                "source_sequence": 3,
                "exit_code": 1 if self.scenario == "nonzero" else 0,
                "stop_reason": "timeout" if self.scenario == "timeout" else None,
                "finished_at": datetime.now(UTC).isoformat(),
            }
        raise AssertionError("Unexpected fake SSH operation")
