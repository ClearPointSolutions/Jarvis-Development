"""M7 local adapter/security acceptance; no homelab or socket access."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from tests.m7_worker_fixture import FakeWorkerSSH, deployment, worker_request, worker_spec

from jarvis_contracts.workers import WorkerProject
from jarvis_orchestrator.workers.base import WorkerCallContext
from jarvis_orchestrator.workers.capture import LogCapture
from jarvis_orchestrator.workers.openhands import OpenHandsSSHAdapter
from jarvis_orchestrator.workers.safety import WorkerBoundaryError, contained, remote_command
from jarvis_orchestrator.workers.transport import OpenSSHTransport, SSHCredentials
from jarvis_orchestrator.workers.workspace import local_contained, task_branch


def context() -> WorkerCallContext:
    return WorkerCallContext(datetime.now(UTC) + timedelta(minutes=2), uuid4())


@pytest.mark.parametrize("scenario", ["success", "dirty", "disconnect_after"])
async def test_success_and_duplicate_reconnect(scenario: str) -> None:
    request = worker_request()
    transport = FakeWorkerSSH(scenario)
    adapter = OpenHandsSSHAdapter(worker_spec(request), deployment(), transport)
    prepared = await adapter.prepare(request, request.lease, context())
    handle = await adapter.start(prepared, context())
    assert await adapter.start(prepared, context()) == handle
    assert transport.starts == 1
    if scenario != "disconnect_after":
        result = await adapter.collect(handle, context())
        assert result.status == "succeeded" and result.generation == request.lease.generation
        assert result.repository_snapshot.git_status == (
            "dirty" if scenario == "dirty" else "clean"
        )
    else:
        assert (await adapter.reconcile(handle, context())).state == "running"


@pytest.mark.parametrize(
    "scenario,code",
    [
        ("malformed", "malformed_sentinel"),
        ("missing", "missing_sentinel"),
        ("nonzero", "runner_nonzero_exit"),
        ("timeout", "runner_timeout"),
        ("mismatched", "task_identity_mismatch"),
        ("traversal", "workspace_escape"),
    ],
)
async def test_result_failures(scenario: str, code: str) -> None:
    request = worker_request()
    adapter = OpenHandsSSHAdapter(worker_spec(request), deployment(), FakeWorkerSSH(scenario))
    handle = await adapter.start(
        await adapter.prepare(request, request.lease, context()), context()
    )
    with pytest.raises(WorkerBoundaryError, match=code):
        await adapter.collect(handle, context())


@pytest.mark.parametrize(
    "scenario", ["wrong_root", "wrong_head", "missing_runner", "host_key_mismatch"]
)
async def test_preflight_fails_closed(scenario: str) -> None:
    request = worker_request()
    transport = FakeWorkerSSH(scenario)
    adapter = OpenHandsSSHAdapter(worker_spec(request), deployment(), transport)
    with pytest.raises(WorkerBoundaryError):
        await adapter.prepare(request, request.lease, context())
    assert transport.starts == 0


async def test_disconnect_before_start_is_confirmed_absent() -> None:
    request = worker_request()
    transport = FakeWorkerSSH("disconnect_before")
    adapter = OpenHandsSSHAdapter(worker_spec(request), deployment(), transport)
    prepared = await adapter.prepare(request, request.lease, context())
    with pytest.raises(WorkerBoundaryError, match="invocation_outcome_absent"):
        await adapter.start(prepared, context())
    assert (await adapter.reconcile(adapter.restore(prepared), context())).safe_to_start
    assert transport.starts == 0


@pytest.mark.parametrize(
    "scenario,expected", [("running", "cancelled"), ("cancel_unknown", "unknown")]
)
async def test_targeted_cancellation(scenario: str, expected: str) -> None:
    request = worker_request()
    transport = FakeWorkerSSH(scenario)
    transport.invocations["unrelated"] = {"state": "running"}
    adapter = OpenHandsSSHAdapter(worker_spec(request), deployment(), transport)
    handle = await adapter.start(
        await adapter.prepare(request, request.lease, context()), context()
    )
    assert (await adapter.cancel(handle, "user cancellation", context())).status == expected
    assert (await adapter.cancel(handle, "user cancellation", context())).status == expected
    assert transport.invocations["unrelated"]["state"] == "running"


async def test_digest_and_model_binding_mismatch_reject() -> None:
    request = worker_request()
    adapter = OpenHandsSSHAdapter(worker_spec(request), deployment(), FakeWorkerSSH())
    await adapter.prepare(request, request.lease, context())
    with pytest.raises(WorkerBoundaryError, match="digest_conflict"):
        await adapter.prepare(
            request.model_copy(update={"objective": "changed"}), request.lease, context()
        )
    with pytest.raises(WorkerBoundaryError, match="incompatible_model_binding"):
        await adapter.prepare(
            request.model_copy(update={"model_profile_revision_id": uuid4()}),
            request.lease,
            context(),
        )


async def test_unknown_invocation_cannot_restart_or_collect() -> None:
    request = worker_request()
    transport = FakeWorkerSSH("unknown")
    adapter = OpenHandsSSHAdapter(worker_spec(request), deployment(), transport)
    prepared = await adapter.prepare(request, request.lease, context())
    handle = await adapter.start(prepared, context())
    assert (await adapter.reconcile(handle, context())).state == "unknown"
    with pytest.raises(WorkerBoundaryError, match="outcome_unknown"):
        await adapter.start(prepared, context())
    with pytest.raises(WorkerBoundaryError, match="not_terminal"):
        await adapter.collect(handle, context())
    assert transport.starts == 1


@pytest.mark.parametrize("field", ["generation", "invocation_id", "request_digest"])
async def test_forged_handle_rejected(field: str) -> None:
    request = worker_request()
    transport = FakeWorkerSSH()
    adapter = OpenHandsSSHAdapter(worker_spec(request), deployment(), transport)
    prepared = await adapter.prepare(request, request.lease, context())
    handle = await adapter.start(prepared, context())
    value = 999 if field == "generation" else uuid4() if field == "invocation_id" else "f" * 64
    with pytest.raises(WorkerBoundaryError, match="identity_mismatch"):
        await adapter.collect(handle.model_copy(update={field: value}), context())


async def test_missing_requested_capability_prevents_start() -> None:
    request = worker_request()
    transport = FakeWorkerSSH()
    worker = worker_spec(request).model_copy(update={"capabilities": ("code",)})
    adapter = OpenHandsSSHAdapter(worker, deployment(), transport)
    with pytest.raises(WorkerBoundaryError, match="capability_missing"):
        await adapter.prepare(request, request.lease, context())
    assert transport.starts == 0


async def test_silent_worker_is_observed_stalled() -> None:
    request = worker_request()
    transport = FakeWorkerSSH("running")
    adapter = OpenHandsSSHAdapter(worker_spec(request), deployment(), transport)
    handle = await adapter.start(
        await adapter.prepare(request, request.lease, context()), context()
    )
    transport.invocations[str(handle.invocation_id)]["started_at"] = (
        datetime.now(UTC) - timedelta(hours=1)
    ).isoformat()
    status = await adapter.inspect(handle, context())
    assert status.possibly_stalled and status.state == "running"


async def test_health_diagnostics_cannot_publish_arbitrary_worker_text() -> None:
    canary = "sk-proj-" + "synthetic" * 5

    class UnsafeHealth(FakeWorkerSSH):
        def respond(self, operation: str, payload: dict[str, object]) -> dict[str, object]:
            result = super().respond(operation, payload)
            if operation == "health":
                result["issues"] = [canary]
            return result

    request = worker_request()
    spec = worker_spec(request)
    adapter = OpenHandsSSHAdapter(spec, deployment(), UnsafeHealth())
    report = await adapter.validate(spec, context())
    assert not report.valid
    assert report.health.issues == ("invalid_health_response",)
    assert canary not in report.model_dump_json()


@pytest.mark.parametrize(
    "slug",
    ["../escape", "/escape", "a;b", "$(id)", "a\n", "a\x00", "..\\escape", "%2e%2e", "a`id`"],
)
def test_slug_injection(slug: str) -> None:
    data = worker_request().project.model_dump()
    data["slug"] = slug
    with pytest.raises(ValidationError):
        WorkerProject.model_validate(data)


@pytest.mark.parametrize(
    "path", ["/root/../escape", "/escape", "/root/%2e%2e/x", "/root/a;id", "/root/a\\b"]
)
def test_path_injection(path: str) -> None:
    with pytest.raises((ValueError, WorkerBoundaryError)):
        contained("/root", path)


def test_command_and_branch_breakout() -> None:
    for argument in ("a';id", "$(id)", "x\n", "`id`"):
        with pytest.raises(WorkerBoundaryError):
            remote_command("/usr/bin/python", "/wrapper/entry.py", argument)
    with pytest.raises(WorkerBoundaryError):
        task_branch(uuid4(), "DEV;id", 1)


def test_pinned_ssh_options_and_host_denial(tmp_path: Path) -> None:
    key, pin = tmp_path / "key", tmp_path / "pin"
    key.touch()
    pin.touch()
    transport = OpenSSHTransport(
        deployment(), SSHCredentials(key, pin), allowed_hosts=frozenset({"localhost"})
    )
    argv = transport.argv("fixed command")
    assert "StrictHostKeyChecking=yes" in argv
    assert "UpdateHostKeys=no" in argv and "IdentityAgent=none" in argv
    with pytest.raises(WorkerBoundaryError, match="host_not_allowed"):
        OpenSSHTransport(
            deployment().model_copy(update={"host_alias": "192.168.40.106"}),
            SSHCredentials(key, pin),
            allowed_hosts=frozenset({"localhost"}),
        )


@pytest.mark.parametrize(
    "diagnostic,expected",
    [
        (b"Host key verification failed", "host_key_mismatch"),
        (b"Permission denied", "authentication_failed"),
        (b"Connection refused", "host_unreachable"),
        (b"", "ssh_timeout"),
    ],
)
async def test_transport_failure_mapping_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, diagnostic: bytes, expected: str
) -> None:
    class Process:
        def __init__(self) -> None:
            self.stdout = asyncio.StreamReader()
            self.stderr = asyncio.StreamReader()
            self.returncode: int | None = None
            self.killed = False
            if diagnostic:
                self.stderr.feed_data(diagnostic)
                self.stdout.feed_eof()
                self.stderr.feed_eof()

        async def wait(self) -> int:
            self.returncode = 255
            return 255

        def kill(self) -> None:
            self.killed = True
            self.stdout.feed_eof()
            self.stderr.feed_eof()

    process = Process()

    async def spawn(*argv: object, **kwargs: object) -> Process:
        assert "StrictHostKeyChecking=yes" in argv
        assert "shell" not in kwargs
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    key, pin = tmp_path / "key", tmp_path / "pin"
    key.touch()
    pin.touch()
    transport = OpenSSHTransport(
        deployment(), SSHCredentials(key, pin), allowed_hosts=frozenset({"localhost"})
    )
    with pytest.raises(WorkerBoundaryError, match=expected):
        await transport.execute("fixed", timeout=2 if diagnostic else 0.05, limit=1024)
    assert process.killed == (expected == "ssh_timeout")


def test_bounded_split_secret_capture() -> None:
    secrets = [
        "sk-proj-" + "A" * 32,
        "ghp_" + "B" * 32,
        "synthetic-authorization",
        "synthetic-private-material",
        "synthetic-db-password",
        "synthetic-cookie",
        "synthetic-env",
    ]
    key_label = "PRIVATE" + " KEY"
    output = (
        f"{secrets[0]}\n{secrets[1]}\nAuthorization: {secrets[2]}\n"
        f"-----BEGIN {key_label}-----\n{secrets[3]}\n-----END {key_label}-----\n"
        f"postgresql://user:{secrets[4]}@localhost/db\nCookie: {secrets[5]}\nVALUE={secrets[6]}\n"
    ).encode()
    capture = LogCapture(1024)
    for byte in output:
        capture.feed(bytes([byte]))
    capture.feed(b"z" * 1000000)
    log = capture.finish()
    assert log.truncated and len(log.content) <= 1024
    assert all(value.encode() not in log.content for value in secrets)


def test_symlink_escape_if_available(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    link = root / "escape"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        # Windows may deny symlink creation; canonical parent containment is still checked.
        with pytest.raises(WorkerBoundaryError):
            local_contained(root, root / ".." / "escape")
        return
    with pytest.raises(WorkerBoundaryError):
        local_contained(root, link / "file")
