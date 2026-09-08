"""V1 compatibility wrapper package. Local CLI only; this module never uses SSH.

The controller atomically reserves each UUID. A separate detached supervisor owns
the child process, bounded output, cancellation intent and atomic terminal record.
An incomplete reservation is UNKNOWN, never permission to start a second child.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field

from jarvis_contracts.base import ContractModel, canonical_json, sha256_digest
from jarvis_contracts.workers import PreparedInvocation
from jarvis_orchestrator.workers.capture import LogCapture
from jarvis_orchestrator.workers.safety import WorkerBoundaryError, decode_object, encoded_argument
from jarvis_orchestrator.workers.workspace import local_contained

WRAPPER_VERSION = "1.0"


class WrapperLaunch(ContractModel):
    prepared: PreparedInvocation
    runner_path: str = Field(max_length=1024)
    python_path: str = Field(max_length=1024)
    invocation_root: str = Field(max_length=1024)
    architecture: str = Field(default="", max_length=16000)
    feedback: str = Field(default="", max_length=16000)


def atomic_write(path: Path, content: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".v1-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(100):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if os.name != "nt" or attempt == 99:
                    raise
                # Windows readers/scanners can briefly hold a no-delete-share handle.
                time.sleep(0.01)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def legacy_payload(launch: WrapperLaunch) -> dict[str, object]:
    import shlex

    request = launch.prepared.request
    return {
        "project_slug": request.project.slug,
        "objective": request.objective,
        "architecture": launch.architecture,
        "feedback": launch.feedback,
        "task": {
            "id": request.task.key,
            "title": request.task.title,
            "description": request.task.description,
            "acceptance_criteria": list(request.task.acceptance_criteria),
            "verification_commands": [shlex.join(item.argv) for item in request.task.verification],
        },
    }


class InvocationStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, invocation_id: UUID) -> Path:
        return local_contained(self.root, self.root / str(invocation_id))

    def reserve(self, launch: WrapperLaunch) -> bool:
        prepared = launch.prepared
        if sha256_digest(prepared.request) != prepared.request_digest:
            raise WorkerBoundaryError("request_digest_mismatch")
        directory = self.directory(prepared.request.invocation_id)
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            metadata = self.read(prepared.request.invocation_id)
            if metadata.get("request_digest") != prepared.request_digest:
                raise WorkerBoundaryError("invocation_digest_conflict") from None
            return False
        atomic_write(
            directory / "status.json",
            canonical_json(
                {
                    "wrapper_version": WRAPPER_VERSION,
                    "invocation_id": str(prepared.request.invocation_id),
                    "request_digest": prepared.request_digest,
                    "state": "starting",
                    "source_sequence": 1,
                    "started_at": datetime.now(UTC).isoformat(),
                }
            ),
        )
        return True

    def read(self, invocation_id: UUID) -> dict[str, object]:
        directory = self.directory(invocation_id)
        if not directory.exists():
            return {"state": "absent", "invocation_id": str(invocation_id)}
        try:
            path = local_contained(directory, directory / "status.json")
            if path.stat().st_size > 65536:
                raise ValueError("oversized metadata")
            value = json.loads(path.read_bytes())
            if not isinstance(value, dict):
                raise ValueError("invalid metadata")
            if value.get("state") in {"starting", "running"}:
                observed = datetime.fromisoformat(
                    str(value.get("heartbeat_at", value["started_at"]))
                )
                if (datetime.now(UTC) - observed).total_seconds() > 10:
                    value["state"] = "unknown"
            return value
        except (OSError, ValueError, KeyError):
            return {"state": "unknown", "invocation_id": str(invocation_id)}

    def cancel_intent(self, invocation_id: UUID) -> None:
        directory = self.directory(invocation_id)
        if directory.exists():
            atomic_write(directory / "cancel", b"cancel requested\n")

    def launch(self, launch: WrapperLaunch) -> dict[str, object]:
        if not self.reserve(launch):
            return self.read(launch.prepared.request.invocation_id)
        argument = encoded_argument(launch, 131072)
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        # All three streams detach; a lost initiating SSH does not own this process.
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "jarvis_orchestrator.workers.wrapper",
                encoded_argument({"operation": "supervise", "launch": argument}, 196608),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
        return self.read(launch.prepared.request.invocation_id)


async def supervise(launch: WrapperLaunch) -> None:
    request = launch.prepared.request
    store = InvocationStore(Path(launch.invocation_root))
    directory = store.directory(request.invocation_id)
    # Atomic supervisor claim protects even repeated internal supervisor invocation.
    try:
        (directory / "supervisor.claim").mkdir()
    except FileExistsError:
        return
    metadata = store.read(request.invocation_id)
    if metadata.get("request_digest") != launch.prepared.request_digest:
        raise WorkerBoundaryError("invocation_digest_conflict")
    started = datetime.now(UTC)
    captures = [
        LogCapture(request.limits.max_output_bytes, line_limit=request.limits.max_result_bytes)
        for _ in range(2)
    ]
    process = await asyncio.create_subprocess_exec(
        launch.python_path,
        launch.runner_path,
        encoded_argument(legacy_payload(launch)),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=os.name != "nt",
    )
    assert process.stdout is not None and process.stderr is not None
    last_activity = started

    async def drain(stream: asyncio.StreamReader, capture: LogCapture) -> None:
        nonlocal last_activity
        while block := await stream.read(8192):
            capture.feed(block)
            last_activity = datetime.now(UTC)

    readers = asyncio.gather(drain(process.stdout, captures[0]), drain(process.stderr, captures[1]))
    sequence = 2
    stop_reason: Literal["cancelled", "timeout"] | None = None
    while process.returncode is None:
        now = datetime.now(UTC)
        metadata = {
            **metadata,
            "state": "running",
            "pid": process.pid,
            "process_group": process.pid if os.name != "nt" else None,
            "heartbeat_at": now.isoformat(),
            "last_activity_at": last_activity.isoformat(),
            "source_sequence": sequence,
        }
        atomic_write(directory / "status.json", canonical_json(metadata))
        if (directory / "cancel").exists():
            stop_reason = "cancelled"
        elif (now - started).total_seconds() >= request.limits.max_runtime_seconds:
            stop_reason = "timeout"
        if stop_reason:
            if sys.platform != "win32":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 2)
            except TimeoutError:
                if sys.platform != "win32":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            break
        sequence += 1
        await asyncio.sleep(0.1)
    exit_code = await process.wait()
    # Inherited pipe holders are an unknown outcome, not unlimited waiting.
    try:
        await asyncio.wait_for(readers, 3)
    except TimeoutError:
        stop_reason = "timeout"
    logs = [capture.finish() for capture in captures]
    for name, log in zip(("stdout", "stderr"), logs, strict=True):
        atomic_write(directory / (name + ".log"), log.content)
    sentinel = captures[0].sentinel
    if not sentinel and captures[0].malformed_sentinel_seen:
        sentinel = b"JARVIS_RESULT_JSON=invalid"
    # Raw sentinel is not published: it may contain native exception secrets.
    from jarvis_api.events.redaction import RecursiveRedactor

    safe_sentinel, _ = RecursiveRedactor().redact_text(sentinel.decode(errors="replace"))
    # The ENV redactor would erase the sentinel itself; redact the JSON fields instead.
    if sentinel.startswith(b"JARVIS_RESULT_JSON="):
        try:
            value = json.loads(sentinel.split(b"=", 1)[1])
            safe_sentinel = "JARVIS_RESULT_JSON=" + json.dumps(
                RecursiveRedactor().redact(value).value
            )
        except ValueError:
            safe_sentinel = "JARVIS_RESULT_JSON=invalid"
    atomic_write(directory / "sentinel", safe_sentinel.encode())
    state = (
        "cancelled"
        if stop_reason == "cancelled" and os.name != "nt"
        else "failed"
        if stop_reason or exit_code
        else "succeeded"
    )
    if stop_reason == "cancelled" and os.name == "nt":
        state = "unknown"  # Windows tree termination is not proved by terminating its parent.
    atomic_write(
        directory / "status.json",
        canonical_json(
            {
                **metadata,
                "state": state,
                "exit_code": exit_code,
                "stop_reason": stop_reason,
                "finished_at": datetime.now(UTC).isoformat(),
                "source_sequence": sequence + 1,
                "logs": [
                    {
                        "kind": kind,
                        "sha256": log.digest,
                        "size_bytes": len(log.content),
                        "truncated": log.truncated,
                    }
                    for kind, log in zip(("stdout", "stderr"), logs, strict=True)
                ],
            }
        ),
    )


def main() -> None:
    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        command = decode_object(sys.argv[1], 196608)
        if command.get("operation") == "supervise":
            launch = WrapperLaunch.model_validate(decode_object(str(command["launch"])))
            asyncio.run(supervise(launch))
        elif command.get("operation") == "start":
            launch = WrapperLaunch.model_validate(command["launch"])
            print(json.dumps(InvocationStore(Path(launch.invocation_root)).launch(launch)))
        elif command.get("operation") in {"inspect", "cancel", "collect"}:
            store = InvocationStore(Path(str(command["invocation_root"])))
            invocation_id = UUID(str(command["invocation_id"]))
            metadata = store.read(invocation_id)
            if (
                metadata.get("state") != "absent"
                and metadata.get("request_digest") != command["request_digest"]
            ):
                raise WorkerBoundaryError("invocation_digest_conflict")
            if command["operation"] == "cancel":
                store.cancel_intent(invocation_id)
            if command["operation"] == "collect":
                directory = store.directory(invocation_id)
                if metadata.get("state") not in {"succeeded", "failed", "cancelled"}:
                    raise WorkerBoundaryError("invocation_not_terminal")

                def bounded_log(name: str) -> str:
                    path = local_contained(directory, directory / name)
                    with path.open("rb") as stream:
                        content = stream.read(10485761)
                    if len(content) > 10485760:
                        raise WorkerBoundaryError("log_oversized")
                    return content.decode(errors="replace")

                metadata = {
                    **metadata,
                    "sentinel": bounded_log("sentinel"),
                    "stdout": bounded_log("stdout.log"),
                    "stderr": bounded_log("stderr.log"),
                }
            print(json.dumps(metadata))
        elif command.get("operation") == "repository":
            from jarvis_orchestrator.workers.workspace import WorktreeManager

            result = asyncio.run(
                WorktreeManager(Path(str(command["workspace_root"]))).inspect(
                    Path(str(command["workspace"])),
                    branch=str(command["branch"]),
                    expected_head=str(command["head"]) if command.get("head") else None,
                    base_sha=str(command["base_sha"]) if command.get("base_sha") else None,
                )
            )
            print(result.model_dump_json())
        elif command.get("operation") == "health":
            import shutil

            issues = []
            for name in ("runner_path", "python_path", "venv_activate"):
                if not Path(str(command[name])).is_file():
                    issues.append(name + "_missing")
            for name in ("workspace_root", "invocation_root"):
                path = Path(str(command[name]))
                if not path.is_dir() or not os.access(path, os.W_OK):
                    issues.append(name + "_misconfigured")
            if not shutil.which("git"):
                issues.append("git_missing")
            print(
                json.dumps(
                    {
                        "wrapper_version": WRAPPER_VERSION,
                        "issues": issues,
                        "capabilities": ["code", "filesystem", "shell", "git", "tests"]
                        if not issues
                        else [],
                    }
                )
            )
        else:
            raise WorkerBoundaryError("unsupported_wrapper_operation")
    except Exception:
        print('{"state":"unknown","error":"wrapper_operation_failed"}')
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
