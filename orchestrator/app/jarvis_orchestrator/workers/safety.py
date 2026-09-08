"""Fail-closed path, command and bounded legacy result boundary."""

from __future__ import annotations

import base64
import json
import shlex
from pathlib import PurePosixPath

from pydantic import Field, ValidationError

from jarvis_contracts.base import ContractModel, canonical_json
from jarvis_contracts.enums import FailureClass
from jarvis_contracts.workers import Sha, WorkerValidationReport, validate_absolute_path


class WorkerBoundaryError(RuntimeError):
    def __init__(
        self, code: str, failure_class: FailureClass = FailureClass.CONFIGURATION_INVALID
    ) -> None:
        self.code = code
        self.failure_class = failure_class
        super().__init__(code)


def validation_failure(report: WorkerValidationReport) -> WorkerBoundaryError:
    failure = FailureClass.CONFIGURATION_INVALID
    if "ssh_timeout" in report.health.issues:
        failure = FailureClass.INFRASTRUCTURE_TIMEOUT
    elif report.health.status == "unavailable":
        failure = FailureClass.INFRASTRUCTURE_WORKER_TRANSPORT
    return WorkerBoundaryError("worker_validation_failed", failure)


def contained(root: str, candidate: str) -> str:
    validate_absolute_path(root)
    validate_absolute_path(candidate)
    if candidate == root or not PurePosixPath(candidate).is_relative_to(root):
        raise WorkerBoundaryError("workspace_escape", FailureClass.SECURITY_POLICY_DENIED)
    return candidate


def encoded_argument(payload: ContractModel | dict[str, object], max_bytes: int = 98304) -> str:
    encoded = base64.b64encode(canonical_json(payload)).decode("ascii")
    if len(encoded) > max_bytes:
        raise WorkerBoundaryError("request_oversized")
    return encoded


def remote_command(python_path: str, wrapper_path: str, argument: str) -> str:
    validate_absolute_path(python_path)
    validate_absolute_path(wrapper_path)
    try:
        base64.b64decode(argument, validate=True)
    except ValueError:
        raise WorkerBoundaryError("invalid_base64_argument") from None
    if not argument or len(argument) > 131072:
        raise WorkerBoundaryError("request_oversized")
    return shlex.join((python_path, wrapper_path, argument))


class LegacyResult(ContractModel):
    task_id: str = Field(min_length=1, max_length=80)
    workspace: str = Field(max_length=1024)
    start_head: Sha
    end_head: Sha
    diff_stat: str = Field(max_length=16384)
    error: str | None = Field(max_length=8192)
    execution_status: str = Field(min_length=1, max_length=80)


def parse_sentinel(
    stdout: bytes, exit_code: int, task_key: str, *, max_bytes: int = 65536
) -> LegacyResult:
    """Last schema-valid sentinel wins; identity mismatch always fails closed.

    Malformed trailing sentinels cannot replace an earlier valid record. The caller
    retains a bounded sentinel channel independently from a truncated log prefix.
    """
    if len(stdout) > max_bytes:
        raise WorkerBoundaryError("result_oversized")
    if exit_code != 0:
        raise WorkerBoundaryError("runner_nonzero_exit")
    prefix = b"JARVIS_RESULT_JSON="
    found = False
    result = None
    for line in stdout.splitlines():
        if not line.startswith(prefix):
            continue
        found = True
        if len(line) > max_bytes:
            raise WorkerBoundaryError("result_oversized")
        try:
            candidate = LegacyResult.model_validate_json(line[len(prefix) :])
        except (ValidationError, ValueError):
            continue
        if candidate.task_id != task_key:
            raise WorkerBoundaryError("task_identity_mismatch")
        result = candidate
    if result is None:
        raise WorkerBoundaryError("malformed_sentinel" if found else "missing_sentinel")
    # OpenHands SDK's observed state is explicit, not inferred from prose or exit.
    status = result.execution_status.casefold().removeprefix("conversationexecutionstatus.")
    if status not in {"finished", "error", "stopped"}:
        raise WorkerBoundaryError("impossible_execution_status")
    if (status == "finished") != (result.error is None):
        raise WorkerBoundaryError("inconsistent_execution_status")
    return result


def decode_object(argument: str, max_bytes: int = 131072) -> dict[str, object]:
    if len(argument) > max_bytes:
        raise WorkerBoundaryError("request_oversized")
    try:
        value = json.loads(base64.b64decode(argument, validate=True))
    except (ValueError, UnicodeError):
        raise WorkerBoundaryError("invalid_request") from None
    if not isinstance(value, dict):
        raise WorkerBoundaryError("invalid_request")
    return value
