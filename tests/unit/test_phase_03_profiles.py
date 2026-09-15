"""Phase 3 profile, evidence, acceptance-check, and context invariants."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.verification import (
    DependencyPolicy,
    ExecutionProfileSpec,
    NetworkPolicy,
    RequiredAcceptanceCheck,
    ResourceBounds,
    VerificationCommand,
)
from jarvis_orchestrator.verification.isolation_contract import CandidateFile
from jarvis_orchestrator.verification.parsers import parse_output, verification_passed
from jarvis_orchestrator.verification.process import ProcessResult
from jarvis_orchestrator.verification.profiles import (
    ExecutionProfileCatalog,
    ExecutionProfileError,
    ProfileBinding,
    bind_required_checks,
    evidence_identity,
    profile_templates,
)
from jarvis_orchestrator.verification.repository_context import (
    InsufficientRepositoryContextError,
    build_repository_context,
)

PROFILE_ID = UUID("00000000-0000-0000-0000-000000000301")
IMAGE_ID = "sha256:" + "a" * 64


def node_profile(**changes: object) -> ExecutionProfileSpec:
    values = {
        "profile_key": "node-build-v1",
        "project_types": ("node", "full_stack"),
        "image_reference": "jarvis-node:approved",
        "supported_commands": ("npm", "node", "vitest", "tsc", "next", "eslint"),
        "tool_versions": {"node": "20.20.2", "npm": "10.8.2"},
        "resources": ResourceBounds(memory_mb=1024),
        "dependencies": DependencyPolicy(
            manager="npm",
            lockfiles=("package-lock.json",),
            registry_allowlist=("registry.npmjs.org",),
        ),
        "network": NetworkPolicy(preparation="registry_allowlist"),
        "source_formats": ("", ".json", ".js", ".ts", ".tsx", ".md"),
    }
    values.update(changes)
    return ExecutionProfileSpec.model_validate(values)


def catalog(profile: ExecutionProfileSpec | None = None) -> ExecutionProfileCatalog:
    spec = profile or node_profile()
    return ExecutionProfileCatalog(
        (ProfileBinding(PROFILE_ID, spec, IMAGE_ID, spec.tool_versions),)
    )


def files(lock: str = '{"lockfileVersion":3,"packages":{}}') -> tuple[CandidateFile, ...]:
    return (
        CandidateFile(path="package.json", content='{"scripts":{"build":"next build"}}'),
        CandidateFile(path="package-lock.json", content=lock),
        CandidateFile(path="src/app.ts", content="export const answer = 42;"),
    )


def command(**changes: object) -> VerificationCommand:
    values = {
        "argv": ("npm", "run", "build"),
        "parser": "next",
        "purpose": "build",
        "profile_revision_id": PROFILE_ID,
    }
    values.update(changes)
    return VerificationCommand.model_validate(values)


def test_profile_preflight_binds_image_toolchain_lockfile_and_source() -> None:
    result = catalog().resolve(command(), project_type="node", files=files())
    assert result.profile.image_id == IMAGE_ID
    assert result.profile.profile_digest == sha256_digest(result.profile.spec)
    assert result.lockfile_path == "package-lock.json"
    assert result.lockfile_digest
    assert result.file_count == 3


def test_three_supported_profile_templates_are_safe_and_distinct() -> None:
    templates = profile_templates()
    assert [item.profile_key for item in templates] == [
        "python-pytest-v1",
        "node-build-v1",
        "browser-acceptance-v1",
    ]
    assert all(item.network.deny_public_internet for item in templates)
    assert templates[-1].network.verification == "application_loopback"


@pytest.mark.parametrize(
    ("candidate", "code"),
    [
        (
            VerificationCommand(argv=("pytest",), profile_revision_id=PROFILE_ID),
            "profile.command_unsupported",
        ),
        (command(timeout_seconds=1201), "profile.timeout_exceeded"),
    ],
)
def test_profile_capability_failures_are_actionable(
    candidate: VerificationCommand, code: str
) -> None:
    with pytest.raises(ExecutionProfileError) as caught:
        catalog().resolve(candidate, project_type="node", files=files())
    assert caught.value.code == code


def test_lockfile_is_required_and_integrity_shape_is_validated() -> None:
    with pytest.raises(ExecutionProfileError, match="pinned lockfile"):
        catalog().resolve(command(), project_type="node", files=files()[::2])
    with pytest.raises(ExecutionProfileError, match="integrity metadata"):
        catalog().resolve(command(), project_type="node", files=files("{}"))
    untrusted = '{"lockfileVersion":3,"packages":{"node_modules/example":{"version":"1.0.0"}}}'
    with pytest.raises(ExecutionProfileError, match="lacks approved integrity"):
        catalog().resolve(command(), project_type="node", files=files(untrusted))
    wrong_registry = (
        '{"lockfileVersion":3,"packages":'
        '{"node_modules/example":{"version":"1.0.0",'
        '"integrity":"sha512-YWJj",'
        '"resolved":"https://packages.example.test/example.tgz"}}}'
    )
    with pytest.raises(ExecutionProfileError, match="outside the registry allowlist"):
        catalog().resolve(command(), project_type="node", files=files(wrong_registry))


def test_dependency_identity_binds_manifest_and_lockfile() -> None:
    baseline = catalog().resolve(command(), project_type="node", files=files())
    changed_lock = catalog().resolve(
        command(),
        project_type="node",
        files=files('{"lockfileVersion":3,"packages":{"":{"name":"changed"}}}'),
    )
    changed_manifest_files = tuple(
        file.model_copy(update={"content": '{"name":"changed"}'})
        if file.path == "package.json"
        else file
        for file in files()
    )
    changed_manifest = catalog().resolve(
        command(), project_type="node", files=changed_manifest_files
    )
    assert baseline.dependency_digest != changed_lock.dependency_digest
    assert baseline.dependency_digest != changed_manifest.dependency_digest


def test_required_checks_cannot_be_removed_or_replaced() -> None:
    protected = command(required_check_id="acceptance.browser")
    required = (
        RequiredAcceptanceCheck(
            check_id="acceptance.browser",
            purpose="build",
            profile_revision_id=PROFILE_ID,
            command=protected,
        ),
    )
    assert bind_required_checks((), required) == (protected,)
    extra = command(argv=("npm", "test"), purpose="unit")
    assert bind_required_checks((extra,), required) == (extra, protected)
    with pytest.raises(ExecutionProfileError) as caught:
        bind_required_checks(
            (protected.model_copy(update={"argv": ("npm", "run", "easier")}),), required
        )
    assert caught.value.code == "verification.required_check_changed"


def test_required_unit_and_browser_checks_require_real_nonempty_reports() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        RequiredAcceptanceCheck(
            check_id="acceptance.unit",
            purpose="unit",
            profile_revision_id=PROFILE_ID,
            command=command(
                purpose="unit", required_check_id="acceptance.unit", require_nonempty_suite=False
            ),
        )
    with pytest.raises(ValueError, match="Playwright"):
        RequiredAcceptanceCheck(
            check_id="acceptance.browser",
            purpose="browser",
            profile_revision_id=PROFILE_ID,
            command=command(
                purpose="browser",
                required_check_id="acceptance.browser",
                require_nonempty_suite=True,
            ),
        )


def test_evidence_identity_changes_for_every_security_bound_input() -> None:
    resolved = catalog().resolve(command(), project_type="node", files=files()).profile
    required: tuple[RequiredAcceptanceCheck, ...] = ()
    baseline = evidence_identity(
        source_sha="1" * 40,
        profile=resolved,
        dependency_digest="2" * 64,
        command=command(),
        required_checks=required,
    )
    assert baseline != evidence_identity(
        source_sha="3" * 40,
        profile=resolved,
        dependency_digest="2" * 64,
        command=command(),
        required_checks=required,
    )
    required_changed = (
        RequiredAcceptanceCheck(
            check_id="acceptance.browser",
            purpose="build",
            profile_revision_id=PROFILE_ID,
            command=command(required_check_id="acceptance.browser"),
        ),
    )
    assert baseline != evidence_identity(
        source_sha="1" * 40,
        profile=resolved,
        dependency_digest="2" * 64,
        command=command(),
        required_checks=required_changed,
    )
    assert baseline != evidence_identity(
        source_sha="1" * 40,
        profile=resolved,
        dependency_digest="4" * 64,
        command=command(),
        required_checks=required,
    )
    changed_image = resolved.model_copy(update={"image_id": "sha256:" + "b" * 64})
    assert baseline != evidence_identity(
        source_sha="1" * 40,
        profile=changed_image,
        dependency_digest="2" * 64,
        command=command(),
        required_checks=required,
    )


def test_empty_or_truncated_required_suite_cannot_pass() -> None:
    required = command(
        argv=("vitest", "run"), parser="vitest", purpose="unit", require_nonempty_suite=True
    )
    empty = parse_output("vitest", "No test files found", 0)
    complete = ProcessResult(0, False, b"", b"", False, False)
    assert not verification_passed(required, empty, complete)
    parsed = parse_output("vitest", "Tests 1 passed", 0)
    truncated = ProcessResult(0, False, b"Tests 1 passed", b"", True, False)
    assert not verification_passed(required, parsed, truncated)
    assert verification_passed(required, parsed, complete)


def test_repository_context_is_single_revision_bounded_and_records_omissions() -> None:
    context = build_repository_context(
        context_id=UUID(int=1),
        repository_id=UUID(int=2),
        run_id=UUID(int=3),
        source_sha="1" * 40,
        tree_sha="2" * 40,
        files=(
            CandidateFile(path="package.json", content="{}"),
            CandidateFile(path="src/app.ts", content="x" * 3800),
            CandidateFile(path="docs/large.md", content="y" * 3800),
        ),
        relevant_paths=("src/app.ts",),
        project_brief="Build the approved form journey",
        directives=("Keep validation behavior",),
        decisions=("Use the Python API",),
        outcomes=("Initial project accepted",),
        max_bytes=4096,
        created_at=datetime(2026, 9, 15, tzinfo=UTC),
    )
    assert context.snapshot.source_sha == "1" * 40
    assert context.snapshot.selection == "bounded"
    assert context.snapshot.coverage == "sufficient"
    assert context.snapshot.omitted_paths == ("docs/large.md",)
    assert "cannot override" in context.security_preamble


def test_complete_review_fails_instead_of_claiming_partial_coverage() -> None:
    with pytest.raises(InsufficientRepositoryContextError, match="complete review"):
        build_repository_context(
            context_id=UUID(int=1),
            repository_id=UUID(int=2),
            run_id=UUID(int=3),
            source_sha="1" * 40,
            tree_sha="2" * 40,
            files=(CandidateFile(path="src/app.ts", content="x" * 5000),),
            max_bytes=4096,
            require_complete=True,
            created_at=datetime(2026, 9, 15, tzinfo=UTC),
        )
