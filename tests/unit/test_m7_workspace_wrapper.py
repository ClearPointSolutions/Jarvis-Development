"""Actual disposable local Git and worker process tests; no SSH sockets."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
from tests.m7_worker_fixture import worker_request

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.workers import PreparedInvocation
from jarvis_orchestrator.workers.safety import WorkerBoundaryError
from jarvis_orchestrator.workers.workspace import WorktreeManager
from jarvis_orchestrator.workers.wrapper import InvocationStore, WrapperLaunch


async def test_isolated_real_worktrees_preserve_result_branches(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    for argv in (
        ["init", "-b", "main"],
        ["config", "user.name", "Fixture"],
        ["config", "user.email", "fixture@localhost"],
        ["commit", "--allow-empty", "-m", "base"],
    ):
        subprocess.run(["git", *argv], cwd=repository, check=True, capture_output=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()
    manager = WorktreeManager(tmp_path)
    request = worker_request()
    first, branch = await manager.create(
        repository, run_id=request.run_id, task_key="DEV-001", attempt=1, base_sha=base
    )
    second, second_branch = await manager.create(
        repository, run_id=request.run_id, task_key="DEV-002", attempt=1, base_sha=base
    )
    assert first != second and branch != second_branch
    assert (await manager.inspect(first, branch=branch, expected_head=base)).git_status == "clean"
    (first / "result.txt").write_text("only first attempt")
    assert (await manager.inspect(first, branch=branch)).git_status == "dirty"
    assert not (second / "result.txt").exists()
    assert (await manager.inspect(second, branch=second_branch)).git_status == "clean"
    with pytest.raises(WorkerBoundaryError, match="identity_mismatch"):
        await manager.inspect(first, branch=branch, expected_head="f" * 40)
    assert await manager.create(
        repository, run_id=request.run_id, task_key="DEV-001", attempt=1, base_sha=base
    ) == (first, branch)


def launch_fixture(tmp_path: Path) -> WrapperLaunch:
    request = worker_request()
    runner = tmp_path / "runner.py"
    runner.write_text(
        "import base64,json,sys\np=json.loads(base64.b64decode(sys.argv[1]))\n"
        "print('JARVIS_RESULT_JSON='+json.dumps({'task_id':p['task']['id'],"
        "'workspace':'/local/workspaces/fixture','start_head':'a'*40,'end_head':'b'*40,"
        "'diff_stat':'','error':None,'execution_status':'finished'}))\n"
    )
    return WrapperLaunch(
        prepared=PreparedInvocation(request=request, request_digest=sha256_digest(request)),
        runner_path=str(runner),
        python_path=sys.executable,
        invocation_root=str(tmp_path / "invocations"),
    )


async def test_detached_wrapper_runs_once_and_persists_terminal(tmp_path: Path) -> None:
    launch = launch_fixture(tmp_path)
    store = InvocationStore(Path(launch.invocation_root))
    identity = launch.prepared.request.invocation_id
    store.launch(launch)
    store.launch(launch)
    for _ in range(150):
        record = InvocationStore(Path(launch.invocation_root)).read(identity)
        if record["state"] in {"succeeded", "failed", "cancelled"}:
            break
        await asyncio.sleep(0.1)
    assert record["state"] == "succeeded", record
    assert record["exit_code"] == 0
    sentinel = (store.directory(identity) / "sentinel").read_text()
    assert json.loads(sentinel.split("=", 1)[1])["task_id"] == "DEV-001"
    changed = launch.prepared.request.model_copy(update={"objective": "different"})
    with pytest.raises(WorkerBoundaryError, match="digest_conflict"):
        store.launch(
            launch.model_copy(
                update={
                    "prepared": PreparedInvocation(
                        request=changed, request_digest=sha256_digest(changed)
                    )
                }
            )
        )


def test_partial_reservation_never_relaunches(tmp_path: Path) -> None:
    launch = launch_fixture(tmp_path)
    store = InvocationStore(Path(launch.invocation_root))
    store.directory(launch.prepared.request.invocation_id).mkdir()
    assert store.read(launch.prepared.request.invocation_id)["state"] == "unknown"
    with pytest.raises(WorkerBoundaryError):
        store.launch(launch)


async def test_wrapper_bounded_secret_logs_keep_final_sentinel(tmp_path: Path) -> None:
    launch = launch_fixture(tmp_path)
    runner = Path(launch.runner_path)
    original = runner.read_text()
    runner.write_text(
        "print('sk-proj-' + 'S'*32)\nprint('VALUE=synthetic-env-value')\nprint('x'*2000000)\n"
        + original
    )
    store = InvocationStore(Path(launch.invocation_root))
    store.launch(launch)
    identity = launch.prepared.request.invocation_id
    for _ in range(150):
        record = store.read(identity)
        # Coverage instrumentation can delay the first heartbeat past the
        # staleness threshold. Unknown is not a terminal outcome; keep polling
        # the same invocation without relaunching it or weakening the guard.
        if record["state"] in {"succeeded", "failed", "cancelled"}:
            break
        await asyncio.sleep(0.1)
    assert record["state"] == "succeeded"
    output = (store.directory(identity) / "stdout.log").read_bytes()
    assert len(output) <= launch.prepared.request.limits.max_output_bytes
    assert b"S" * 32 not in output and b"synthetic-env-value" not in output
    assert b"truncated" in output
    assert "DEV-001" in (store.directory(identity) / "sentinel").read_text()


async def test_wrapper_cancel_does_not_stop_unrelated_process(tmp_path: Path) -> None:
    launch = launch_fixture(tmp_path)
    Path(launch.runner_path).write_text("import time\ntime.sleep(60)\n")
    store = InvocationStore(Path(launch.invocation_root))
    identity = launch.prepared.request.invocation_id
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        store.launch(launch)
        for _ in range(150):
            if store.read(identity)["state"] == "running":
                break
            await asyncio.sleep(0.1)
        store.cancel_intent(identity)
        store.cancel_intent(identity)
        for _ in range(150):
            record = store.read(identity)
            if record["state"] not in {"starting", "running"}:
                break
            await asyncio.sleep(0.1)
        assert record["state"] == ("unknown" if sys.platform == "win32" else "cancelled")
        assert unrelated.poll() is None
        assert store.directory(identity).is_dir()
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)
