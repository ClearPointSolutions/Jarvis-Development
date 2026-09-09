"""Crash recovery uses local durable bundles and immutable candidate worktrees."""

from pathlib import Path

import pytest

from jarvis_orchestrator.workers.candidate_store import import_candidate, recover_candidate
from jarvis_orchestrator.workers.safety import WorkerBoundaryError
from jarvis_orchestrator.workers.source_transfer import export_candidate
from jarvis_orchestrator.workers.workspace import WorktreeManager
from tests.unit.test_source_transfer import candidate


@pytest.mark.parametrize(
    "point",
    [
        "before_object_import",
        "after_object_import",
        "before_ref_update",
        "after_ref_update",
        "after_checkout",
        "before_receipt",
        "after_receipt",
    ],
)
async def test_import_crash_recovers_without_worker(tmp_path: Path, point: str) -> None:
    prepared, result, remote = await candidate(tmp_path)
    envelope = await export_candidate(prepared, result, remote.parent, tmp_path)
    manager = WorktreeManager(tmp_path / "core")

    def fault(observed: str) -> None:
        if observed == point:
            raise RuntimeError("injected import interruption")

    with pytest.raises(RuntimeError, match="injected"):
        await import_candidate(manager, result, envelope, fault=fault)
    offline = remote.with_name("offline")
    assert remote.resolve().is_relative_to(tmp_path.resolve())
    assert offline.resolve().is_relative_to(tmp_path.resolve()) and not offline.exists()
    remote.rename(offline)
    recovered = await recover_candidate(manager, result)
    assert recovered is not None and (recovered / "first.py").read_text() == "answer = 42\n"
    assert await manager.scalar(recovered, "rev-parse", "HEAD") == result.end_head
    assert await recover_candidate(manager, result) == recovered


async def test_receipt_never_overwrites_modified_candidate(tmp_path: Path) -> None:
    prepared, result, remote = await candidate(tmp_path)
    envelope = await export_candidate(prepared, result, remote.parent, tmp_path)
    manager = WorktreeManager(tmp_path / "core")
    root = await import_candidate(manager, result, envelope)
    (root / "first.py").write_text("unrelated modification\n")
    with pytest.raises(WorkerBoundaryError, match="changed"):
        await recover_candidate(manager, result)
    assert (root / "first.py").read_text() == "unrelated modification\n"
