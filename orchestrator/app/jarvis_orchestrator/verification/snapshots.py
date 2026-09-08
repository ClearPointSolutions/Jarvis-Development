"""Seal committed cumulative source state; never substitute the latest worker diff."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import UUID

from pydantic import JsonValue
from uuid6 import uuid7

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.verification import SealedRepositorySnapshot
from jarvis_orchestrator.verification.artifacts import EvidenceArtifacts
from jarvis_orchestrator.verification.executor import ConfirmedRepository, VerificationExecutor


@dataclass(frozen=True)
class CapturedSource:
    tree_sha: str
    manifest: list[JsonValue]
    files: dict[str, JsonValue]
    cumulative_diff: str
    latest_diff: str
    digest: str


class SnapshotBuilder:
    def __init__(self, executor: VerificationExecutor, artifacts: EvidenceArtifacts) -> None:
        self.executor, self.artifacts = executor, artifacts

    async def capture(
        self, repository: ConfirmedRepository, *, base_sha: str, latest_base_sha: str
    ) -> CapturedSource:
        import re

        if not all(re.fullmatch(r"[a-f0-9]{40}", sha) for sha in (base_sha, latest_base_sha)):
            raise ValueError("invalid snapshot base")
        await self.executor.confirm(repository)
        manager, root = self.executor.manager, repository.root
        raw, truncated = await manager.git(
            root, "ls-tree", "-rz", "--full-tree", repository.head_sha
        )
        if truncated or raw.count(b"\x00") > 1000:
            raise ValueError("complete manifest exceeds V1 snapshot limits")
        manifest: list[JsonValue] = []
        files: dict[str, JsonValue] = {}
        total = 0
        for entry in raw.split(b"\x00"):
            if not entry:
                continue
            metadata, path_bytes = entry.split(b"\t", 1)
            mode, kind, blob = metadata.decode("ascii").split()
            path = path_bytes.decode("utf-8")
            relative = PurePosixPath(path)
            if relative.is_absolute() or ".." in relative.parts or "\\" in path:
                raise ValueError("snapshot path escapes repository")
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise ValueError("symlinks and submodules require an unsupported snapshot policy")
            content, truncated = await manager.git(root, "cat-file", "blob", blob)
            total += len(content)
            if truncated or total > 4194304:
                raise ValueError("complete source exceeds V1 snapshot limits")
            text = content.decode("utf-8", errors="strict")
            if "\x00" in text or text.startswith("version https://git-lfs.github.com/spec/v1"):
                raise ValueError("binary and LFS source require an unsupported snapshot policy")
            files[path] = text
            manifest.append(
                {
                    "path": path,
                    "mode": mode,
                    "blob_sha": blob,
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
        diffs = []
        for base in (base_sha, latest_base_sha):
            diff, truncated = await manager.git(
                root,
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--binary",
                base,
                repository.head_sha,
                "--",
            )
            if truncated:
                raise ValueError("complete diff exceeds V1 snapshot limits")
            diffs.append(diff.decode("utf-8", errors="strict"))
        tree = await manager.scalar(root, "rev-parse", repository.head_sha + "^{tree}")
        await self.executor.confirm(repository)
        return CapturedSource(
            tree,
            manifest,
            files,
            diffs[0],
            diffs[1],
            sha256_digest({"head": repository.head_sha, "tree": tree, "manifest": manifest}),
        )

    async def seal(
        self,
        repository: ConfirmedRepository,
        *,
        repository_id: UUID,
        task_id: UUID,
        attempt_id: UUID,
        worker_result_id: UUID,
        base_sha: str,
        latest_base_sha: str,
    ) -> tuple[SealedRepositorySnapshot, UUID]:
        captured = await self.capture(
            repository, base_sha=base_sha, latest_base_sha=latest_base_sha
        )
        ownership, fence = self.artifacts.ownership, self.artifacts.fence
        async with ownership.fenced(fence) as (session, run):

            async def put(kind: str, value: JsonValue) -> UUID:
                return await self.artifacts.put(session, run, attempt_id, kind, value)

            snapshot = SealedRepositorySnapshot(
                id=uuid7(),
                repository_id=repository_id,
                run_id=run.id,
                task_attempt_id=attempt_id,
                worker_result_id=worker_result_id,
                branch=repository.branch,
                head_sha=repository.head_sha,
                base_sha=base_sha,
                latest_base_sha=latest_base_sha,
                tree_sha=captured.tree_sha,
                content_digest=captured.digest,
                file_count=len(captured.manifest),
                manifest_artifact_id=await put("repository-manifest", captured.manifest),
                source_artifact_id=await put("source-snapshot", captured.files),
                cumulative_diff_artifact_id=await put("cumulative-diff", captured.cumulative_diff),
                latest_diff_artifact_id=await put("latest-attempt-diff", captured.latest_diff),
                created_at=ownership.clock.now(),
            )
            artifact_id = await put("repository-snapshot", snapshot.model_dump(mode="json"))
            await ownership.event(
                session,
                run,
                "file.snapshot_created",
                {
                    "task_id": str(task_id),
                    "task_attempt_id": str(attempt_id),
                    "snapshot_id": str(snapshot.id),
                    "snapshot_artifact_id": str(artifact_id),
                    "head_sha": snapshot.head_sha,
                    "content_digest": snapshot.content_digest,
                },
            )
        return snapshot, artifact_id
