"""Core-side candidate sealing and receipt validation; no Docker authority required."""

from __future__ import annotations

import asyncio
import subprocess
from typing import Literal
from uuid import UUID

from jarvis_api.events.redaction import RecursiveRedactor
from jarvis_contracts.verification import VerificationCommand
from jarvis_orchestrator.verification.executor import (
    ConfirmedRepository,
    VerificationExecutor,
    VerificationResult,
)
from jarvis_orchestrator.verification.isolation_contract import (
    CandidateFile,
    IsolationReceipt,
    IsolationRequest,
)
from jarvis_orchestrator.verification.parsers import parse_output, verification_passed
from jarvis_orchestrator.verification.process import ProcessResult
from jarvis_orchestrator.verification.profiles import ExecutionProfileCatalog
from jarvis_orchestrator.workers.workspace import WorktreeManager


class IsolatedVerificationExecutor(VerificationExecutor):
    recoverable = True

    def __init__(
        self,
        manager: WorktreeManager,
        broker_argv: tuple[str, ...],
        image_id: str,
        *,
        profiles: ExecutionProfileCatalog | None = None,
        project_type: Literal["python", "node", "full_stack"] = "python",
    ) -> None:
        super().__init__(manager, {}, path="")
        self.broker_argv, self.image_id = broker_argv, image_id
        self.profiles, self.project_type = profiles, project_type

    async def execute_bound(
        self,
        repository: ConfirmedRepository,
        command: VerificationCommand,
        *,
        run_id: UUID,
        execution_id: UUID,
    ) -> VerificationResult:
        await self.confirm(repository)
        raw, truncated = await self.manager.git(
            repository.root, "ls-tree", "-rz", "--full-tree", repository.head_sha
        )
        if truncated or raw.count(b"\x00") > 1000:
            raise ValueError("isolated candidate exceeds source profile")
        files = []
        total = 0
        for entry in raw.split(b"\x00"):
            if not entry:
                continue
            metadata, path = entry.split(b"\t", 1)
            mode, kind, blob = metadata.decode("ascii").split()
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise ValueError("unsupported isolated candidate mode")
            content, truncated = await self.manager.git(repository.root, "cat-file", "blob", blob)
            total += len(content)
            if truncated or total > 4194304:
                raise ValueError("isolated candidate exceeds source profile")
            files.append(
                CandidateFile(
                    path=path.decode("utf-8"),
                    content=content.decode("utf-8"),
                    executable=mode == "100755",
                )
            )
        tree, truncated = await self.manager.git(
            repository.root, "rev-parse", repository.head_sha + "^{tree}"
        )
        if truncated:
            raise ValueError("candidate tree identity unavailable")
        preflight = None
        if command.profile_revision_id is not None:
            if self.profiles is None:
                raise ValueError("selected execution profile is not configured")
            preflight = self.profiles.resolve(
                command, project_type=self.project_type, files=tuple(files)
            )
        request = IsolationRequest(
            run_id=run_id,
            execution_id=execution_id,
            candidate_sha=repository.head_sha,
            tree_sha=tree.decode().strip(),
            files=tuple(files),
            command=command,
            profile=preflight.profile if preflight else None,
            dependency_digest=preflight.dependency_digest if preflight else None,
        )
        # The trusted broker has its own timeout and durable container identity;
        # loss of this transport never grants a second invocation identity.
        response = await asyncio.to_thread(
            subprocess.run,
            self.broker_argv,
            input=request.model_dump_json().encode(),
            capture_output=True,
            check=True,
            timeout=command.timeout_seconds + 60,
        )
        if len(response.stdout) > 13 * 1024 * 1024:
            raise ValueError("oversized isolated verification receipt")
        receipt = IsolationReceipt.model_validate_json(response.stdout)
        receipt.require(request, preflight.profile.image_id if preflight else self.image_id)
        await self.confirm(repository)
        redactor = RecursiveRedactor()
        result = ProcessResult(
            receipt.exit_code,
            receipt.timed_out,
            redactor.redact_text(receipt.stdout)[0].encode(),
            redactor.redact_text(receipt.stderr)[0].encode(),
            receipt.stdout_truncated,
            receipt.stderr_truncated,
        )
        parsed = parse_output(
            command.parser, (result.stdout + result.stderr).decode(), result.exit_code
        )
        return VerificationResult(
            verification_passed(command, parsed, result),
            result,
            parsed,
            "/work/project",
            command.argv,
            tuple(sorted({"PATH", "HOME", "TMPDIR", "CI", "NO_COLOR", "TZ", *command.environment})),
            preflight.profile.revision_id if preflight else None,
            preflight.profile.profile_digest if preflight else None,
            receipt.image_id,
            receipt.dependency_digest,
            preflight.lockfile_path if preflight else None,
            preflight.lockfile_digest if preflight else None,
            receipt.dependency_prepared,
            receipt.preparation_stdout,
            receipt.preparation_stderr,
            receipt.preparation_output_truncated,
            preflight.profile.spec.dependencies.registry_allowlist if preflight else (),
        )
