"""Local source workspace boundary; never merges, pushes or removes worktrees."""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from pathlib import Path
from uuid import UUID

from jarvis_contracts.workers import WorkerRepositorySnapshot, validate_branch
from jarvis_orchestrator.workers.safety import WorkerBoundaryError
from jarvis_orchestrator.workers.transport import bounded_read


def task_branch(run_id: UUID, task_key: str, attempt: int) -> str:
    import re

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", task_key) or not 1 <= attempt <= 100000:
        raise WorkerBoundaryError("invalid_task_identity")
    return validate_branch(f"jarvis/{run_id.hex}/{task_key}-a{attempt}")


def local_contained(root: Path, target: Path) -> Path:
    root = root.resolve()
    resolved = target.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise WorkerBoundaryError("workspace_escape")
    # Resolve checks existing symlinks, including an escaping parent of a new path.
    return resolved


class WorktreeManager:
    def __init__(
        self, workspace_root: Path, *, git_executable: str = "git", metadata_limit: int = 1048576
    ) -> None:
        self.root = workspace_root.resolve()
        self.git_executable = git_executable
        self.metadata_limit = metadata_limit

    async def git(self, cwd: Path, *argv: str) -> tuple[bytes, bool]:
        if sys.platform == "win32":

            def run_windows() -> tuple[bytes, bool]:
                with asyncio.Runner(loop_factory=asyncio.ProactorEventLoop) as runner:
                    return runner.run(self._git_native(cwd, *argv))

            return await asyncio.to_thread(run_windows)
        return await self._git_native(cwd, *argv)

    async def _git_native(self, cwd: Path, *argv: str) -> tuple[bytes, bool]:
        local_contained(self.root, cwd)
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("GIT_")
        }
        environment.update(
            {
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
            }
        )
        process = await asyncio.create_subprocess_exec(
            self.git_executable,
            "-c",
            "core.hooksPath=" + os.devnull,
            "-c",
            "core.fsmonitor=false",
            "-c",
            "protocol.allow=never",
            *argv,
            cwd=cwd,
            env=environment,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert process.stdout is not None and process.stderr is not None
        readers = asyncio.gather(
            bounded_read(process.stdout, self.metadata_limit), bounded_read(process.stderr, 4096)
        )
        try:
            async with asyncio.timeout(30):
                output = await asyncio.shield(readers)
                code = await process.wait()
        except (TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                process.kill()
            await process.wait()
            await readers
            raise
        if code:
            raise WorkerBoundaryError("repository_inspection_failed")
        return output[0]

    async def scalar(self, cwd: Path, *argv: str) -> str:
        output, truncated = await self.git(cwd, *argv)
        if truncated:
            raise WorkerBoundaryError("repository_metadata_oversized")
        return output.decode("utf-8", errors="strict").strip()

    async def create(
        self, repository: Path, *, run_id: UUID, task_key: str, attempt: int, base_sha: str
    ) -> tuple[Path, str]:
        import re

        if not re.fullmatch(r"[a-f0-9]{40}", base_sha):
            raise WorkerBoundaryError("invalid_base_sha")
        repository = local_contained(self.root, repository)
        actual_root = Path(await self.scalar(repository, "rev-parse", "--show-toplevel")).resolve()
        if actual_root != repository:
            raise WorkerBoundaryError("repository_root_mismatch")
        resolved_base = await self.scalar(
            repository, "rev-parse", "--verify", base_sha + "^{commit}"
        )
        if resolved_base != base_sha:
            raise WorkerBoundaryError("base_sha_mismatch")
        branch = task_branch(run_id, task_key, attempt)
        target = local_contained(
            self.root, self.root / "worktrees" / run_id.hex / f"{task_key}-a{attempt}"
        )
        if target.exists():
            await self.inspect(target, branch=branch, expected_head=base_sha)
            return target, branch
        target.parent.mkdir(parents=True, exist_ok=True)
        await self.git(repository, "worktree", "add", "-b", branch, str(target), base_sha)
        await self.inspect(target, branch=branch, expected_head=base_sha)
        return target, branch

    async def inspect(
        self,
        workspace: Path,
        *,
        branch: str,
        expected_head: str | None = None,
        base_sha: str | None = None,
    ) -> WorkerRepositorySnapshot:
        validate_branch(branch)
        workspace = local_contained(self.root, workspace)
        actual_root = Path(await self.scalar(workspace, "rev-parse", "--show-toplevel")).resolve()
        if actual_root != workspace:
            raise WorkerBoundaryError("repository_root_mismatch")
        actual_branch = await self.scalar(workspace, "symbolic-ref", "--short", "HEAD")
        head = await self.scalar(workspace, "rev-parse", "--verify", "HEAD")
        if actual_branch != branch or (expected_head is not None and expected_head != head):
            raise WorkerBoundaryError("repository_identity_mismatch")
        status, status_truncated = await self.git(
            workspace, "status", "--porcelain=v1", "-z", "--untracked-files=all"
        )
        manifest, manifest_truncated = await self.git(workspace, "ls-files", "--stage", "-z")
        tree = await self.scalar(workspace, "rev-parse", "HEAD^{tree}")
        diff, diff_truncated = await self.git(
            workspace, "diff", "--no-ext-diff", "--no-textconv", "--binary", base_sha or head, "--"
        )
        # Bracket inspection with HEAD checks; later M8 seals verification/review evidence.
        if head != await self.scalar(workspace, "rev-parse", "HEAD"):
            raise WorkerBoundaryError("repository_changed_during_inspection")

        def digest(value: bytes) -> str:
            return hashlib.sha256(value).hexdigest()

        return WorkerRepositorySnapshot(
            head_sha=head,
            tree_digest=digest(tree.encode()),
            status_digest=digest(status),
            git_status="dirty" if status or status_truncated else "clean",
            file_count=manifest.count(b"\x00"),
            manifest_digest=digest(manifest),
            diff_digest=digest(diff),
            metadata_truncated=status_truncated or manifest_truncated or diff_truncated,
        )
