"""Immutable candidate checkouts over one append-only Core Git object store."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.workers import WorkerResult
from jarvis_orchestrator.workers.safety import WorkerBoundaryError
from jarvis_orchestrator.workers.source_transfer import MAX_BUNDLE_BYTES
from jarvis_orchestrator.workers.workspace import WorktreeManager, local_contained


def immutable(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
            if sys.platform != "win32":
                directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        except FileExistsError:
            if path.read_bytes() != content:
                raise WorkerBoundaryError("immutable_source_identity_changed") from None
    finally:
        temporary.unlink(missing_ok=True)


def identity(result: WorkerResult) -> dict[str, object]:
    return {
        "invocation_id": str(result.invocation_id),
        "request_digest": result.request_digest,
        "head_sha": result.end_head,
        "branch": result.branch,
        "result_digest": sha256_digest(result),
    }


def read_json(path: Path) -> dict[str, object]:
    with path.open("rb") as stream:
        content = stream.read(4097)
    if len(content) > 4096:
        raise WorkerBoundaryError("source_receipt_oversized")
    result = json.loads(content)
    if not isinstance(result, dict):
        raise WorkerBoundaryError("source_receipt_invalid")
    return result


async def validate_checkout(
    manager: WorktreeManager, root: Path, branch: str, result: WorkerResult
) -> None:
    observed = await manager.inspect(root, branch=branch, expected_head=result.end_head)
    if (
        observed.git_status != "clean"
        or observed.metadata_truncated
        or observed.tree_digest != result.repository_snapshot.tree_digest
        or observed.manifest_digest != result.repository_snapshot.manifest_digest
        or observed.file_count != result.repository_snapshot.file_count
    ):
        raise WorkerBoundaryError("source_import_changed")


async def cached_candidate(manager: WorktreeManager, result: WorkerResult) -> Path | None:
    receipt = manager.root / "candidate-receipts" / (result.invocation_id.hex + ".json")
    if receipt.exists():
        recorded = read_json(receipt)
        expected = identity(result)
        if any(recorded.get(key) != value for key, value in expected.items()):
            raise WorkerBoundaryError("source_receipt_identity_changed")
        legacy = recorded.get("checkout") == "repository"
        checkout = "repository" if legacy else "c/" + result.invocation_id.hex
        branch = result.branch if legacy else "jarvis-candidates/" + result.invocation_id.hex
        if recorded.get("checkout") != checkout or recorded.get("local_branch") != branch:
            raise WorkerBoundaryError("source_receipt_checkout_changed")
        root = local_contained(manager.root, manager.root / checkout)
        await validate_checkout(manager, root, branch, result)
        return root
    # Adopt a verified pre-upgrade receipt without changing its checkout.
    legacy_receipt = manager.root / "current-candidate.json"
    if legacy_receipt.exists():
        recorded = read_json(legacy_receipt)
        expected = {key: value for key, value in identity(result).items() if key != "result_digest"}
        if recorded == expected:
            root = manager.root / "repository"
            await validate_checkout(manager, root, result.branch, result)
            immutable(
                receipt,
                json.dumps(
                    {**identity(result), "checkout": "repository", "local_branch": result.branch},
                    sort_keys=True,
                ).encode(),
            )
            return root
    return None


async def import_candidate(
    manager: WorktreeManager,
    result: WorkerResult,
    envelope: dict[str, object],
    *,
    fault: Callable[[str], None] = lambda _point: None,
) -> Path:
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
    digest = hashlib.sha256(content).hexdigest()
    if len(content) > MAX_BUNDLE_BYTES or digest != envelope.get("bundle_sha256"):
        raise WorkerBoundaryError("source_transfer_digest_mismatch")
    cached = await cached_candidate(manager, result)
    if cached is not None:
        return cached
    key = result.invocation_id.hex
    imports = manager.root / "imports"
    bundle = imports / (key + ".bundle")
    intent = imports / (key + ".json")
    immutable(bundle, content)
    immutable(
        intent, json.dumps({**identity(result), "bundle_sha256": digest}, sort_keys=True).encode()
    )
    fault("before_object_import")
    repository = manager.root / "repository"
    marker = manager.root / "candidate-store.json"
    if not marker.exists():
        if repository.exists() and not (manager.root / "current-candidate.json").exists():
            raise WorkerBoundaryError("source_store_requires_reconciliation")
        immutable(marker, b'{"version":"1.0"}')
    elif marker.read_bytes() != b'{"version":"1.0"}':
        raise WorkerBoundaryError("source_store_identity_changed")
    repository.mkdir(parents=True, exist_ok=True)
    if not (repository / ".git").exists():
        await manager.git(repository, "init", "-b", result.branch)
    await manager.git(repository, "bundle", "verify", str(bundle))
    await manager.git(repository, "bundle", "unbundle", str(bundle))
    fault("after_object_import")
    if (
        await manager.scalar(repository, "rev-parse", result.end_head + "^{commit}")
        != result.end_head
    ):
        raise WorkerBoundaryError("source_import_commit_mismatch")
    tree = await manager.scalar(repository, "rev-parse", result.end_head + "^{tree}")
    if hashlib.sha256(tree.encode()).hexdigest() != result.repository_snapshot.tree_digest:
        raise WorkerBoundaryError("source_import_tree_mismatch")
    entries, truncated = await manager.git(repository, "ls-tree", "-r", result.end_head)
    if truncated or any(
        line and not line.startswith((b"100644 ", b"100755 ")) for line in entries.splitlines()
    ):
        raise WorkerBoundaryError("source_import_unsupported_file_type")
    fault("before_ref_update")
    reference = "refs/jarvis-candidates/" + key
    existing = await manager.scalar(repository, "for-each-ref", "--format=%(objectname)", reference)
    if existing and existing != result.end_head:
        raise WorkerBoundaryError("candidate_ref_identity_changed")
    if not existing:
        await manager.git(repository, "update-ref", reference, result.end_head, "0" * 40)
    fault("after_ref_update")
    root = local_contained(manager.root, manager.root / "c" / key)
    branch = "jarvis-candidates/" + key
    if not root.exists():
        root.parent.mkdir(parents=True, exist_ok=True)
        existing = await manager.scalar(
            repository, "for-each-ref", "--format=%(objectname)", "refs/heads/" + branch
        )
        if existing and existing != result.end_head:
            raise WorkerBoundaryError("candidate_checkout_identity_changed")
        if existing:
            await manager.git(repository, "worktree", "add", str(root), branch)
        else:
            await manager.git(
                repository, "worktree", "add", "-b", branch, str(root), result.end_head
            )
    await validate_checkout(manager, root, branch, result)
    fault("after_checkout")
    receipt = {**identity(result), "checkout": "c/" + key, "local_branch": branch}
    fault("before_receipt")
    immutable(
        manager.root / "candidate-receipts" / (key + ".json"),
        json.dumps(receipt, sort_keys=True).encode(),
    )
    fault("after_receipt")
    return root


async def recover_candidate(manager: WorktreeManager, result: WorkerResult) -> Path | None:
    cached = await cached_candidate(manager, result)
    if cached is not None:
        return cached
    key = result.invocation_id.hex
    intent_path = manager.root / "imports" / (key + ".json")
    if not intent_path.exists():
        return None
    intent = read_json(intent_path)
    if any(intent.get(name) != value for name, value in identity(result).items()):
        raise WorkerBoundaryError("source_import_intent_changed")
    with (manager.root / "imports" / (key + ".bundle")).open("rb") as stream:
        content = stream.read(MAX_BUNDLE_BYTES + 1)
    return await import_candidate(
        manager,
        result,
        {
            "invocation_id": str(result.invocation_id),
            "request_digest": result.request_digest,
            "head_sha": result.end_head,
            "tree_digest": result.repository_snapshot.tree_digest,
            "bundle_sha256": intent["bundle_sha256"],
            "bundle_base64": base64.b64encode(content).decode("ascii"),
        },
    )
