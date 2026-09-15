"""Immutable execution-profile selection, preflight and evidence identities."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from types import MappingProxyType
from urllib.parse import urlsplit
from uuid import UUID

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.verification import (
    DependencyPolicy,
    ExecutionProfileSpec,
    NetworkPolicy,
    RequiredAcceptanceCheck,
    ResolvedExecutionProfile,
    VerificationCommand,
)
from jarvis_orchestrator.verification.isolation_contract import CandidateFile


class ExecutionProfileError(ValueError):
    """A precise pre-execution capability or repository-profile failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProfileBinding:
    revision_id: UUID
    spec: ExecutionProfileSpec
    image_id: str
    resolved_tool_versions: Mapping[str, str]

    def resolved(self) -> ResolvedExecutionProfile:
        versions = dict(self.resolved_tool_versions)
        if versions != self.spec.tool_versions:
            raise ExecutionProfileError(
                "profile.toolchain_mismatch",
                "Resolved tool versions do not match the approved profile revision",
            )
        return ResolvedExecutionProfile(
            revision_id=self.revision_id,
            spec=self.spec,
            profile_digest=sha256_digest(self.spec),
            image_id=self.image_id,
            resolved_tool_versions=versions,
        )


@dataclass(frozen=True)
class PreflightResult:
    profile: ResolvedExecutionProfile
    lockfile_path: str | None
    lockfile_digest: str | None
    dependency_digest: str | None
    source_digest: str
    file_count: int
    source_bytes: int


class ExecutionProfileCatalog:
    def __init__(self, bindings: Iterable[ProfileBinding]) -> None:
        items = tuple(bindings)
        values = {item.revision_id: item for item in items}
        if not values:
            raise ValueError("at least one execution profile must be configured")
        if len(values) != len(items):
            raise ValueError("duplicate execution profile revision")
        self._bindings = MappingProxyType(values)

    def resolve(
        self,
        command: VerificationCommand,
        *,
        project_type: str,
        files: tuple[CandidateFile, ...],
    ) -> PreflightResult:
        if command.profile_revision_id is None:
            raise ExecutionProfileError(
                "profile.required", "Web-project verification requires an explicit profile revision"
            )
        binding = self._bindings.get(command.profile_revision_id)
        if binding is None:
            raise ExecutionProfileError(
                "profile.unavailable", "Selected execution profile revision is not configured"
            )
        profile = binding.resolved()
        spec = profile.spec
        if project_type not in spec.project_types:
            raise ExecutionProfileError(
                "profile.project_type", "Selected profile does not support this project type"
            )
        program = command.argv[0]
        if program not in spec.supported_commands:
            raise ExecutionProfileError(
                "profile.command_unsupported",
                f"Command {program!r} is not supported by profile {spec.profile_key}",
            )
        if command.timeout_seconds > spec.resources.timeout_seconds:
            raise ExecutionProfileError(
                "profile.timeout_exceeded", "Command exceeds profile timeout"
            )
        if command.max_output_bytes > spec.resources.output_bytes:
            raise ExecutionProfileError(
                "profile.output_exceeded", "Command output bound exceeds profile policy"
            )
        count = len(files)
        size = sum(len(file.content.encode("utf-8")) for file in files)
        if count > spec.max_files or size > spec.max_source_bytes:
            raise ExecutionProfileError(
                "profile.source_too_large", "Repository exceeds the selected profile source bounds"
            )
        allowed = set(spec.source_formats)
        unsupported = sorted(
            file.path
            for file in files
            if PurePosixPath(file.path).suffix.lower() not in allowed
            and PurePosixPath(file.path).name not in set(spec.dependencies.lockfiles)
        )
        if unsupported:
            raise ExecutionProfileError(
                "profile.source_format",
                "Repository contains unsupported source format: " + unsupported[0],
            )
        by_path = {file.path: file for file in files}
        lockfiles = [path for path in spec.dependencies.lockfiles if path in by_path]
        if (
            spec.dependencies.require_lockfile
            and spec.dependencies.manager != "none"
            and not lockfiles
        ):
            raise ExecutionProfileError(
                "dependency.lockfile_required", "Selected profile requires a pinned lockfile"
            )
        lockfile = lockfiles[0] if lockfiles else None
        if lockfile == "package-lock.json":
            manifest = by_path.get("package.json")
            if manifest is None:
                raise ExecutionProfileError(
                    "dependency.manifest_required", "npm preparation requires package.json"
                )
            try:
                parsed = json.loads(by_path[lockfile].content)
                manifest_json = json.loads(manifest.content)
            except json.JSONDecodeError as exc:
                raise ExecutionProfileError(
                    "dependency.lockfile_invalid",
                    "package.json and package-lock.json must be valid JSON",
                ) from exc
            if parsed.get("lockfileVersion") not in {2, 3} or not isinstance(
                parsed.get("packages"), dict
            ):
                raise ExecutionProfileError(
                    "dependency.lockfile_unpinned",
                    "package-lock.json must use lockfileVersion 2/3 with "
                    "package integrity metadata",
                )
            if not isinstance(manifest_json, dict):
                raise ExecutionProfileError(
                    "dependency.manifest_invalid", "package.json must contain an object"
                )
            if spec.dependencies.require_integrity:
                missing_integrity = [
                    path
                    for path, entry in parsed["packages"].items()
                    if path
                    and path.startswith("node_modules/")
                    and isinstance(entry, dict)
                    and not entry.get("link")
                    and not (
                        isinstance(entry.get("integrity"), str)
                        and entry["integrity"].startswith(("sha512-", "sha384-", "sha256-"))
                    )
                ]
                if missing_integrity:
                    raise ExecutionProfileError(
                        "dependency.integrity_required",
                        "package-lock.json dependency lacks approved integrity metadata: "
                        + missing_integrity[0],
                    )
            disallowed_sources = []
            allowlist = set(spec.dependencies.registry_allowlist)
            for path, entry in parsed["packages"].items():
                if not path or not isinstance(entry, dict) or entry.get("link"):
                    continue
                resolved = entry.get("resolved")
                if resolved is None:
                    continue
                source = urlsplit(resolved) if isinstance(resolved, str) else None
                if (
                    source is None
                    or source.scheme != "https"
                    or source.hostname not in allowlist
                    or source.username
                    or source.password
                ):
                    disallowed_sources.append(path)
            if disallowed_sources:
                raise ExecutionProfileError(
                    "dependency.source_disallowed",
                    "package-lock.json dependency source is outside the registry allowlist: "
                    + disallowed_sources[0],
                )
        digest = sha256_digest({"content": by_path[lockfile].content}) if lockfile else None
        dependency_digest = (
            sha256_digest(
                {
                    "profile_digest": profile.profile_digest,
                    "manager": spec.dependencies.manager,
                    "lockfile_path": lockfile,
                    "lockfile_digest": digest,
                    "manifest_digest": sha256_digest({"content": by_path["package.json"].content})
                    if lockfile == "package-lock.json"
                    else None,
                }
            )
            if lockfile
            else None
        )
        return PreflightResult(
            profile=profile,
            lockfile_path=lockfile,
            lockfile_digest=digest,
            dependency_digest=dependency_digest,
            source_digest=sha256_digest(
                {"files": [{"path": file.path, "content": file.content} for file in files]}
            ),
            file_count=count,
            source_bytes=size,
        )


def profile_templates() -> tuple[ExecutionProfileSpec, ...]:
    """Conservative templates; operators still publish revisions and bind image IDs."""

    shared = ("", ".json", ".md", ".txt", ".yml", ".yaml")
    return (
        ExecutionProfileSpec(
            profile_key="python-pytest-v1",
            project_types=("python", "full_stack"),
            image_reference="jarvis-v1-verification-python:configured",
            supported_commands=("python", "pytest", "ruff", "mypy"),
            tool_versions={"python": "3.12", "pytest": "9"},
            # The retained Python image is prebuilt from verification-requirements.lock.
            # Arbitrary per-project pip installation remains outside this profile.
            dependencies=DependencyPolicy(manager="none", require_lockfile=False),
            network=NetworkPolicy(),
            source_formats=(*shared, ".py", ".toml", ".ini"),
        ),
        ExecutionProfileSpec(
            profile_key="node-build-v1",
            project_types=("node", "full_stack"),
            image_reference="jarvis-v1-verification-node:configured",
            supported_commands=("npm", "node", "npx", "vitest", "tsc", "next", "eslint"),
            tool_versions={"node": "20", "npm": "10"},
            dependencies=DependencyPolicy(
                manager="npm",
                lockfiles=("package-lock.json",),
                registry_allowlist=("registry.npmjs.org",),
            ),
            network=NetworkPolicy(preparation="registry_allowlist"),
            source_formats=(*shared, ".js", ".jsx", ".ts", ".tsx", ".css", ".html"),
        ),
        ExecutionProfileSpec(
            profile_key="browser-acceptance-v1",
            project_types=("node", "full_stack"),
            image_reference="jarvis-v1-verification-browser:configured",
            supported_commands=("npm", "node", "npx", "playwright"),
            tool_versions={"node": "20", "npm": "10", "playwright": "1"},
            resources={"memory_mb": 2048, "pids": 256},
            dependencies=DependencyPolicy(
                manager="npm",
                lockfiles=("package-lock.json",),
                registry_allowlist=("registry.npmjs.org",),
            ),
            network=NetworkPolicy(
                preparation="registry_allowlist", verification="application_loopback"
            ),
            source_formats=(*shared, ".js", ".jsx", ".ts", ".tsx", ".css", ".html"),
        ),
    )


def bind_required_checks(
    task_commands: tuple[VerificationCommand, ...],
    required: tuple[RequiredAcceptanceCheck, ...],
) -> tuple[VerificationCommand, ...]:
    """Return additive task checks plus immutable approved checks.

    A task may add coverage, but a command carrying a protected check ID must be
    byte-for-byte equal to the approved command and cannot replace it.
    """

    protected = {check.check_id: check.command for check in required}
    for command in task_commands:
        if command.required_check_id is None:
            continue
        expected = protected.get(command.required_check_id)
        if expected is None or command != expected:
            raise ExecutionProfileError(
                "verification.required_check_changed",
                f"Required acceptance check {command.required_check_id!r} was replaced",
            )
    additional = tuple(command for command in task_commands if command.required_check_id is None)
    return (*additional, *(check.command for check in required))


def evidence_identity(
    *,
    source_sha: str,
    profile: ResolvedExecutionProfile,
    dependency_digest: str | None,
    command: VerificationCommand,
    required_checks: tuple[RequiredAcceptanceCheck, ...],
) -> str:
    return sha256_digest(
        {
            "source_sha": source_sha,
            "profile_digest": profile.profile_digest,
            "image_id": profile.image_id,
            "dependency_digest": dependency_digest,
            "command": command.model_dump(mode="json"),
            "required_checks": [item.model_dump(mode="json") for item in required_checks],
        }
    )
