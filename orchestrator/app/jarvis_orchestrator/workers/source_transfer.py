"""Bounded Git-object transfer; remote paths are never treated as Core paths."""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
from pathlib import Path

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.workers import PreparedInvocation, WorkerResult
from jarvis_orchestrator.workers.safety import WorkerBoundaryError
from jarvis_orchestrator.workers.workspace import WorktreeManager, local_contained

MAX_BUNDLE_BYTES = 16 * 1024 * 1024


async def export_candidate(
    prepared: PreparedInvocation, result: WorkerResult, workspace_root: Path, staging_root: Path
) -> dict[str, object]:
    """Called only by the fixed wrapper operation over authenticated pinned SSH."""
    request = prepared.request
    if (
        sha256_digest(request) != prepared.request_digest
        or result.request_digest != prepared.request_digest
        or result.invocation_id != request.invocation_id
        or result.workspace_root != request.project.workspace_root
        or result.branch != request.project.branch
        or result.status != "succeeded"
    ):
        raise WorkerBoundaryError("source_transfer_identity_mismatch")
    manager = WorktreeManager(workspace_root)
    root = local_contained(workspace_root, Path(request.project.workspace_root))
    before = await manager.inspect(root, branch=result.branch, expected_head=result.end_head)
    if before.git_status != "clean" or before.metadata_truncated:
        raise WorkerBoundaryError("source_transfer_requires_clean_candidate")
    if before.tree_digest != result.repository_snapshot.tree_digest:
        raise WorkerBoundaryError("source_transfer_tree_mismatch")
    with tempfile.TemporaryDirectory(prefix="source-v1-", dir=staging_root) as temporary:
        bundle = Path(temporary) / "candidate.bundle"
        await manager.git(root, "bundle", "create", str(bundle), result.branch)
        with bundle.open("rb") as stream:
            content = stream.read(MAX_BUNDLE_BYTES + 1)
        if len(content) > MAX_BUNDLE_BYTES:
            raise WorkerBoundaryError("source_history_exceeds_transfer_limit")
        await manager.inspect(root, branch=result.branch, expected_head=result.end_head)
    return {
        "invocation_id": str(result.invocation_id),
        "request_digest": prepared.request_digest,
        "head_sha": result.end_head,
        "tree_digest": before.tree_digest,
        "bundle_sha256": hashlib.sha256(content).hexdigest(),
        "bundle_base64": base64.b64encode(content).decode("ascii"),
    }


async def import_candidate(
    manager: WorktreeManager, result: WorkerResult, envelope: dict[str, object]
) -> Path:
    """Import only Git objects into a fresh server-owned directory.

    Hooks, local configuration, remote URLs and ignored/untracked files are never
    transferred. Full source is subsequently sealed by the existing M8 policy.
    The original branch history and all tracked blobs are retained without filters.
    """
    if (
        envelope.get("invocation_id") != str(result.invocation_id)
        or envelope.get("request_digest") != result.request_digest
        or envelope.get("head_sha") != result.end_head
        or envelope.get("tree_digest") != result.repository_snapshot.tree_digest
    ):
        raise WorkerBoundaryError("source_transfer_identity_mismatch")
    encoded = envelope.get("bundle_base64")
    if not isinstance(encoded, str) or len(encoded) > (MAX_BUNDLE_BYTES + 2) // 3 * 4:
        raise WorkerBoundaryError("source_transfer_size_invalid")
    try:
        content = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise WorkerBoundaryError("source_transfer_encoding_invalid") from None
    if len(content) > MAX_BUNDLE_BYTES or hashlib.sha256(content).hexdigest() != envelope.get(
        "bundle_sha256"
    ):
        raise WorkerBoundaryError("source_transfer_digest_mismatch")
    # One private object store per run retains locally created integration commits
    # across successive Worker bundles. The first-test composition serializes runs.
    root = local_contained(manager.root, manager.root / "repository")
    receipt = manager.root / "current-candidate.json"
    expected = {
        "request_digest": result.request_digest,
        "head_sha": result.end_head,
        "branch": result.branch,
        "invocation_id": str(result.invocation_id),
    }
    fresh = not root.exists()
    reuse = False
    if root.exists():
        if not receipt.is_file() or receipt.stat().st_size > 4096:
            raise WorkerBoundaryError("source_import_requires_reconciliation")
        previous = json.loads(receipt.read_text())
        reuse = previous == expected
        previous_snapshot = await manager.inspect(
            root, branch=previous["branch"], expected_head=previous["head_sha"]
        )
        if previous_snapshot.git_status != "clean" or previous_snapshot.metadata_truncated:
            raise WorkerBoundaryError("source_import_changed")
        if previous["branch"] != result.branch:
            raise WorkerBoundaryError("source_import_branch_changed")
    if fresh:
        root.mkdir(parents=True)
    if not reuse:
        with tempfile.TemporaryDirectory(prefix="bundle-v1-", dir=manager.root) as temporary:
            bundle = Path(temporary) / "candidate.bundle"
            bundle.write_bytes(content)
            if fresh:
                await manager.git(root, "init", "-b", result.branch)
            await manager.git(root, "bundle", "verify", str(bundle))
            await manager.git(root, "bundle", "unbundle", str(bundle))
            # Explicit detached object validation before checkout. No remote fetch,
            # executable Git config, hooks, or remote protocol is permitted.
            if (
                await manager.scalar(root, "rev-parse", result.end_head + "^{commit}")
                != result.end_head
            ):
                raise WorkerBoundaryError("source_import_commit_mismatch")
            tree = await manager.scalar(root, "rev-parse", result.end_head + "^{tree}")
            if hashlib.sha256(tree.encode()).hexdigest() != result.repository_snapshot.tree_digest:
                raise WorkerBoundaryError("source_import_tree_mismatch")
            entries, truncated = await manager.git(root, "ls-tree", "-r", result.end_head)
            if truncated or any(
                line and not line.startswith((b"100644 ", b"100755 "))
                for line in entries.splitlines()
            ):
                raise WorkerBoundaryError("source_import_unsupported_file_type")
            await manager.git(
                root,
                "update-ref",
                f"refs/jarvis-candidates/{result.invocation_id.hex}",
                result.end_head,
            )
            await manager.git(root, "reset", "--hard", result.end_head)
        from jarvis_orchestrator.workers.wrapper import atomic_write

        atomic_write(
            receipt,
            json.dumps(expected).encode(),
        )
    observed = await manager.inspect(root, branch=result.branch, expected_head=result.end_head)
    if (
        observed.git_status != "clean"
        or observed.tree_digest != result.repository_snapshot.tree_digest
        or observed.manifest_digest != result.repository_snapshot.manifest_digest
        or observed.file_count != result.repository_snapshot.file_count
    ):
        raise WorkerBoundaryError("source_import_changed")
    return root
