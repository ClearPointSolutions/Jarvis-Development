"""Prepare a new per-run historical workspace without resetting the shared worker."""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.workers import WorkerProject
from jarvis_orchestrator.workers.safety import WorkerBoundaryError
from jarvis_orchestrator.workers.source_transfer import MAX_BUNDLE_BYTES
from jarvis_orchestrator.workers.workspace import WorktreeManager, local_contained


class HistoricalWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: UUID
    worker_revision_id: UUID
    source: WorkerProject
    target: WorkerProject
    author_name: str = Field(min_length=1, max_length=120)
    author_email: str = Field(min_length=1, max_length=200)
    bundle_base64: str | None = Field(default=None, max_length=22369624)
    bundle_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def binding(self) -> HistoricalWorkspace:
        if (
            self.source.project_id != self.target.project_id
            or self.source.repository_id != self.target.repository_id
            or self.target.slug != self.source.slug[:20] + "-history-" + self.run_id.hex
            or self.source.workspace_root == self.target.workspace_root
            or (self.bundle_base64 is None) != (self.bundle_sha256 is None)
        ):
            raise ValueError("historical workspace binding mismatch")
        return self


async def prepare_historical(
    request: HistoricalWorkspace, workspace_root: Path, invocation_root: Path
) -> dict[str, str]:
    from jarvis_orchestrator.workers.wrapper import atomic_write

    source = local_contained(workspace_root, Path(request.source.workspace_root))
    target = local_contained(workspace_root, Path(request.target.workspace_root))
    if (
        source != workspace_root.resolve() / request.source.slug
        or target != workspace_root.resolve() / request.target.slug
    ):
        raise WorkerBoundaryError("historical_workspace_path_mismatch")
    directory = local_contained(invocation_root, invocation_root / "historical")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    digest = sha256_digest(request)
    expected = {
        "request_digest": digest,
        "base_sha": request.target.base_sha,
        "workspace": str(target),
    }
    receipt = directory / (request.run_id.hex + ".receipt.json")
    intent = directory / (request.run_id.hex + ".intent.json")
    if receipt.exists():
        if json.loads(receipt.read_bytes()) != expected:
            raise WorkerBoundaryError("historical_workspace_receipt_mismatch")
        return expected
    if intent.exists() and json.loads(intent.read_bytes()) != expected:
        raise WorkerBoundaryError("historical_workspace_intent_mismatch")
    atomic_write(intent, json.dumps(expected).encode())
    manager = WorktreeManager(workspace_root)
    if not target.exists():
        staging = local_contained(workspace_root, target.with_name(target.name + ".preparing"))
        staging.mkdir(exist_ok=True)
        if not (staging / ".git").exists():
            await manager.git(staging, "init", "-b", request.target.branch)
        await manager.git(staging, "config", "user.name", request.author_name)
        await manager.git(staging, "config", "user.email", request.author_email)
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            bundle = Path(temporary) / "source.bundle"
            if request.bundle_base64 is None:
                # Local source only: never fetch an arbitrary caller URL.
                await manager.git(source, "bundle", "create", str(bundle), "--all")
                if bundle.stat().st_size > MAX_BUNDLE_BYTES:
                    raise WorkerBoundaryError("source_history_exceeds_transfer_limit")
            else:
                content = base64.b64decode(request.bundle_base64, validate=True)
                if (
                    len(content) > MAX_BUNDLE_BYTES
                    or hashlib.sha256(content).hexdigest() != request.bundle_sha256
                ):
                    raise WorkerBoundaryError("historical_bundle_digest_mismatch")
                bundle.write_bytes(content)
            await manager.git(staging, "bundle", "verify", str(bundle))
            await manager.git(staging, "bundle", "unbundle", str(bundle))
        if (
            await manager.scalar(staging, "rev-parse", request.target.base_sha + "^{commit}")
            != request.target.base_sha
        ):
            raise WorkerBoundaryError("historical_base_unavailable")
        await manager.git(
            staging, "update-ref", "refs/heads/" + request.target.branch, request.target.base_sha
        )
        await manager.git(staging, "checkout", request.target.branch)
        observed = await manager.inspect(
            staging, branch=request.target.branch, expected_head=request.target.base_sha
        )
        if observed.git_status != "clean" or observed.metadata_truncated:
            raise WorkerBoundaryError("historical_source_invalid")
        staging.rename(target)
    observed = await manager.inspect(
        target, branch=request.target.branch, expected_head=request.target.base_sha
    )
    if observed.git_status != "clean" or observed.metadata_truncated:
        raise WorkerBoundaryError("historical_source_requires_reconciliation")
    atomic_write(receipt, json.dumps(expected).encode())
    return expected
