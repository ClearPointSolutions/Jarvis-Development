"""Real disposable Git objects transferred across distinct local source roots."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from tests.m7_worker_fixture import worker_request

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.workers import PreparedInvocation, WorkerResult
from jarvis_orchestrator.workers.safety import WorkerBoundaryError
from jarvis_orchestrator.workers.source_transfer import export_candidate, import_candidate
from jarvis_orchestrator.workers.workspace import WorktreeManager


async def candidate(tmp_path: Path) -> tuple[PreparedInvocation, WorkerResult, Path]:
    root = tmp_path / "worker" / "project"
    root.mkdir(parents=True)
    manager = WorktreeManager(tmp_path / "worker")
    await manager.git(root, "init", "-b", "main")
    await manager.git(root, "config", "user.name", "Transfer fixture")
    await manager.git(root, "config", "user.email", "fixture@localhost")
    (root / "first.py").write_text("answer = 42\n")
    await manager.git(root, "add", "first.py")
    await manager.git(root, "commit", "-m", "first")
    head = await manager.scalar(root, "rev-parse", "HEAD")
    request = worker_request()
    request = request.model_copy(
        update={
            "project": request.project.model_copy(
                update={
                    "branch": "main",
                    "base_sha": head,
                    "workspace_root": str(root),
                }
            )
        }
    )
    prepared = PreparedInvocation(request=request, request_digest=sha256_digest(request))
    snapshot = await manager.inspect(root, branch="main", expected_head=head)
    result = WorkerResult(
        invocation_id=request.invocation_id,
        task_id=request.task_id,
        task_attempt_id=request.task_attempt_id,
        request_digest=prepared.request_digest,
        generation=1,
        status="succeeded",
        workspace_root="/worker/project",
        branch="main",
        start_head=head,
        end_head=head,
        repository_snapshot=snapshot,
        artifact_manifest=(),
        summary="fixture",
        model_profile_revision_id=request.model_profile_revision_id,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        source_sequence=1,
    ).model_copy(update={"workspace_root": str(root)})
    return prepared, result, root


async def test_full_history_transfer_reuse_and_cumulative_work(tmp_path: Path) -> None:
    prepared, result, remote = await candidate(tmp_path)
    core = tmp_path / "core"
    core.mkdir()
    manager = WorktreeManager(core)
    envelope = await export_candidate(prepared, result, remote.parent, tmp_path)
    imported = await import_candidate(manager, result, envelope)
    assert imported != remote
    assert (imported / "first.py").read_text() == "answer = 42\n"
    assert await import_candidate(manager, result, envelope) == imported
    # Create a Core-only integration commit and prove the next transfer retains
    # its objects/refs, even though the Worker has never seen that merge commit.
    await manager.git(imported, "config", "user.name", "Core fixture")
    await manager.git(imported, "config", "user.email", "fixture@localhost")
    await manager.git(imported, "branch", "core-integration", result.end_head)
    remote_manager = WorktreeManager(remote.parent)
    (remote / "second.py").write_text("from first import answer\n")
    await remote_manager.git(remote, "add", "second.py")
    await remote_manager.git(remote, "commit", "-m", "second")
    head = await remote_manager.scalar(remote, "rev-parse", "HEAD")
    request = prepared.request.model_copy(update={"invocation_id": uuid4()})
    second_prepared = PreparedInvocation(request=request, request_digest=sha256_digest(request))
    second = result.model_copy(
        update={
            "invocation_id": request.invocation_id,
            "request_digest": second_prepared.request_digest,
            "end_head": head,
            "repository_snapshot": await remote_manager.inspect(remote, branch="main"),
        }
    )
    second_envelope = await export_candidate(second_prepared, second, remote.parent, tmp_path)
    assert await import_candidate(manager, second, second_envelope) == imported
    assert (imported / "first.py").is_file() and (imported / "second.py").is_file()
    assert await manager.scalar(imported, "rev-parse", "core-integration") == result.end_head
    assert (
        await manager.scalar(
            imported, "rev-parse", f"refs/jarvis-candidates/{result.invocation_id.hex}"
        )
        == result.end_head
    )


@pytest.mark.parametrize(
    "field", ["head_sha", "tree_digest", "request_digest", "bundle_sha256", "bundle_base64"]
)
async def test_transfer_tampering_rejected(tmp_path: Path, field: str) -> None:
    prepared, result, remote = await candidate(tmp_path)
    envelope = await export_candidate(prepared, result, remote.parent, tmp_path)
    envelope[field] = "invalid"
    with pytest.raises(WorkerBoundaryError):
        await import_candidate(WorktreeManager(tmp_path / "core"), result, envelope)


async def test_transfer_refuses_dirty_source_and_modified_mirror(tmp_path: Path) -> None:
    prepared, result, remote = await candidate(tmp_path)
    envelope = await export_candidate(prepared, result, remote.parent, tmp_path)
    core = tmp_path / "core"
    core.mkdir()
    manager = WorktreeManager(core)
    imported = await import_candidate(manager, result, envelope)
    (imported / "first.py").write_text("unreviewed change")
    with pytest.raises(WorkerBoundaryError, match="changed"):
        await import_candidate(manager, result, envelope)
    (remote / "new.txt").write_text("untracked source")
    with pytest.raises(WorkerBoundaryError, match="clean"):
        await export_candidate(prepared, result, remote.parent, tmp_path)
