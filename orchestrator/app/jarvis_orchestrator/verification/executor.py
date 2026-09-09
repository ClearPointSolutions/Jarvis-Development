"""Execute validated commands at an independently confirmed repository root."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from uuid import UUID

from jarvis_api.events.redaction import RecursiveRedactor
from jarvis_contracts.verification import ParsedVerification, VerificationCommand
from jarvis_orchestrator.verification.parsers import parse_output
from jarvis_orchestrator.verification.process import ProcessResult, run_process
from jarvis_orchestrator.workers.workspace import WorktreeManager


@dataclass(frozen=True)
class ConfirmedRepository:
    root: Path
    branch: str
    head_sha: str


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    process: ProcessResult
    parsed: ParsedVerification
    cwd: str
    argv: tuple[str, ...]
    environment_keys: tuple[str, ...]


class VerificationExecutor:
    recoverable = False

    async def execute_bound(
        self,
        repository: ConfirmedRepository,
        command: VerificationCommand,
        *,
        run_id: UUID,
        execution_id: UUID,
    ) -> VerificationResult:
        return await self.execute(repository, command)

    def __init__(
        self,
        manager: WorktreeManager,
        executables: Mapping[str, tuple[str, ...]],
        *,
        path: str,
    ) -> None:
        for entry in executables.values():
            if not entry or not Path(entry[0]).is_absolute() or not Path(entry[0]).is_file():
                raise ValueError("verification executables must be server-confirmed absolute files")
            if Path(entry[0]).suffix.lower() in {".cmd", ".bat", ".ps1", ".sh"}:
                raise ValueError("verification executable must not invoke an implicit shell")
        self.manager = manager
        self.executables = MappingProxyType(dict(executables))
        self.path = path

    async def confirm(self, repository: ConfirmedRepository) -> None:
        if repository.root.absolute() != repository.root.resolve():
            raise ValueError("symlink repository root is not supported")
        snapshot = await self.manager.inspect(
            repository.root, branch=repository.branch, expected_head=repository.head_sha
        )
        if snapshot.git_status != "clean" or snapshot.metadata_truncated:
            raise ValueError("verification requires a complete clean repository snapshot")
        manifest, truncated = await self.manager.git(repository.root, "ls-files", "--stage", "-z")
        if truncated or any(
            entry and not entry.startswith((b"100644 ", b"100755 "))
            for entry in manifest.split(b"\x00")
        ):
            raise ValueError("verification rejects symlink and submodule traversal")

    async def execute(
        self, repository: ConfirmedRepository, command: VerificationCommand
    ) -> VerificationResult:
        # Revalidate even when an internal caller used model_construct/model_copy.
        command = VerificationCommand.model_validate(command.model_dump())
        await self.confirm(repository)
        executable = self.executables.get(command.argv[0])
        if executable is None:
            raise ValueError("verification tool is not configured")
        argv = (*executable, *command.argv[1:])
        environment = {
            key: value for key, value in os.environ.items() if key.upper() == "SYSTEMROOT"
        }
        environment.update({"PATH": self.path, "CI": "1", "NO_COLOR": "1", "TZ": "UTC"})
        environment.update({str(key): value for key, value in command.environment.items()})
        result = await run_process(
            argv,
            cwd=repository.root,
            environment=environment,
            timeout=command.timeout_seconds,
            limit=command.max_output_bytes,
        )
        await self.confirm(repository)
        redactor = RecursiveRedactor()
        result = ProcessResult(
            result.exit_code,
            result.timed_out,
            redactor.redact_text(result.stdout.decode(errors="replace"))[0].encode(),
            redactor.redact_text(result.stderr.decode(errors="replace"))[0].encode(),
            result.stdout_truncated,
            result.stderr_truncated,
        )
        parsed = parse_output(
            command.parser,
            (result.stdout + result.stderr).decode(errors="replace"),
            result.exit_code,
        )
        return VerificationResult(
            not result.timed_out and result.exit_code in command.expected_exit_codes,
            result,
            parsed,
            str(repository.root),
            command.argv,
            tuple(sorted(environment)),
        )
