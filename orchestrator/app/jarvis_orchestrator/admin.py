"""``jarvis-admin``: operator tooling for the private real-runtime manifest.

``jarvis-admin runtime build`` assembles and validates a
:class:`RealRuntimeConfiguration` from two operator-owned inputs:

* an **infrastructure fragment** -- everything in the manifest that is not a
  per-workflow binding (provider config, worker deployments, credential-file
  paths, host allowlist, source root, verification isolation, executables, git
  author);
* one or more **binding descriptors** -- ``{project_id, workflow_version_id,
  worker_revision_id, worker_project, base_policy, combined_commands}``.

It builds the fiddly nested ``project_workflows`` map, re-checks every
cross-reference that would otherwise fail cryptically at orchestrator startup
(worker deployment present, workspace path derived from the deployment root,
host in the allowlist, project ids consistent, no duplicate binding), runs the
full :class:`RealRuntimeConfiguration` validation, and atomically installs the
result at ``0600`` -- so an operator supplies authoritative ids once instead of
hand-assembling the manifest and copying UUIDs between sections.

With ``--check-registry`` and ``DATABASE_URL`` it additionally verifies, against
the published workflow version's resolved snapshot, the same model/worker
invariants ``RealComposition`` enforces at startup (worker selector, provider
retry classes, structured-JSON planning profiles). It never bypasses that
startup preflight; it surfaces the failures earlier.

It never prints a secret value. The manifest references credential files by
absolute path only -- paths are configuration, not secrets -- and ``--stdout``
emits that manifest verbatim while the human-readable summary goes to stderr.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from jarvis_contracts.enums import FailureClass
from jarvis_contracts.registry import ModelProfileSpec, RetryRegistrySpec, RoutePolicySpec
from jarvis_contracts.verification import VerificationCommand
from jarvis_contracts.workers import WorkerProject
from jarvis_contracts.workflow import WorkflowSpec
from jarvis_contracts.workflow_api import WorkflowResolvedSnapshot
from jarvis_orchestrator.providers.worker_configuration import OpenHandsDeployment
from jarvis_orchestrator.runtime.configuration import RealRuntimeConfiguration, RepositoryBinding
from jarvis_orchestrator.workflows.validation import effective_policy

# Mirrors jarvis_orchestrator.runtime.composition.REQUIRED_MODEL_RETRY_CLASSES,
# the set RealComposition refuses to start without. test_runtime_manifest.py
# asserts the two stay equal so this copy cannot drift.
REQUIRED_MODEL_RETRY_CLASSES: tuple[FailureClass, ...] = (
    FailureClass.PROVIDER_CONTRACT_FAILURE,
    FailureClass.PROVIDER_TRANSIENT,
    FailureClass.PROVIDER_RATE_LIMITED,
    FailureClass.INFRASTRUCTURE_TIMEOUT,
    FailureClass.INFRASTRUCTURE_SERVICE_UNAVAILABLE,
)

_INFRA_FIELDS = set(RealRuntimeConfiguration.model_fields) - {"workflows", "project_workflows"}
_PLANNING_NODES = {"organizer", "architect", "reviewer"}


class ManifestError(RuntimeError):
    """An operator-actionable failure; the message carries no secret value."""


class ManifestBinding(BaseModel):
    """One project/workflow-version binding, before it becomes a RepositoryBinding."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    project_id: UUID
    workflow_version_id: UUID
    worker_revision_id: UUID
    worker_project: WorkerProject
    base_policy: Literal["current", "historical"] = "current"
    combined_commands: tuple[VerificationCommand, ...] = Field(min_length=1, max_length=32)
    project_type: Literal["python", "node", "full_stack"] = "python"
    execution_profile_revision_ids: tuple[UUID, ...] = Field(default=(), max_length=3)


def load_infrastructure(path: Path) -> dict[str, Any]:
    """Load the infrastructure fragment, rejecting per-binding keys."""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ManifestError(f"cannot read infrastructure fragment {path.name}: {error}") from None
    if not isinstance(data, dict):
        raise ManifestError("infrastructure fragment must be a JSON object")
    intruders = sorted(set(data) - _INFRA_FIELDS)
    if intruders:
        raise ManifestError(
            "infrastructure fragment must not contain per-binding keys: " + ", ".join(intruders)
        )
    return data


def load_bindings(paths: list[Path]) -> list[ManifestBinding]:
    bindings: list[ManifestBinding] = []
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ManifestError(f"cannot read binding {path.name}: {error}") from None
        for entry in raw if isinstance(raw, list) else [raw]:
            try:
                bindings.append(ManifestBinding.model_validate(entry))
            except ValidationError as error:
                raise ManifestError(f"binding in {path.name} is invalid: {error}") from None
    if not bindings:
        raise ManifestError("at least one binding descriptor is required")
    return bindings


def assemble(infra: dict[str, Any], bindings: list[ManifestBinding]) -> RealRuntimeConfiguration:
    """Cross-check bindings against the infrastructure, then build and validate."""

    try:
        deployments = {
            UUID(str(key)): OpenHandsDeployment.model_validate(value)
            for key, value in dict(infra.get("workers", {})).items()
        }
    except (ValidationError, ValueError) as error:
        raise ManifestError(f"infrastructure worker deployment is invalid: {error}") from None
    allowed_hosts = tuple(infra.get("allowed_worker_hosts", ()))

    project_workflows: dict[str, dict[str, Any]] = {}
    for binding in bindings:
        if binding.worker_project.project_id != binding.project_id:
            raise ManifestError(
                f"binding {binding.workflow_version_id}: worker_project.project_id "
                f"{binding.worker_project.project_id} != project_id {binding.project_id}"
            )
        deployment = deployments.get(binding.worker_revision_id)
        if deployment is None:
            raise ManifestError(
                f"binding {binding.workflow_version_id}: worker revision "
                f"{binding.worker_revision_id} has no deployment under 'workers'"
            )
        expected_workspace = f"{deployment.workspace_root}/{binding.worker_project.slug}"
        if binding.worker_project.workspace_root != expected_workspace:
            raise ManifestError(
                f"binding {binding.workflow_version_id}: worker_project.workspace_root must be "
                f"{expected_workspace} (deployment root + project slug)"
            )
        if deployment.host_alias not in allowed_hosts:
            raise ManifestError(
                f"binding {binding.workflow_version_id}: deployment host_alias "
                f"'{deployment.host_alias}' is not in allowed_worker_hosts"
            )
        per_project = project_workflows.setdefault(str(binding.project_id), {})
        if str(binding.workflow_version_id) in per_project:
            raise ManifestError(
                f"duplicate binding for project {binding.project_id} "
                f"workflow {binding.workflow_version_id}"
            )
        per_project[str(binding.workflow_version_id)] = RepositoryBinding(
            worker_revision_id=binding.worker_revision_id,
            project=binding.worker_project,
            base_policy=binding.base_policy,
            combined_commands=binding.combined_commands,
            project_type=binding.project_type,
            execution_profile_revision_ids=binding.execution_profile_revision_ids,
        ).model_dump(mode="json")

    try:
        return RealRuntimeConfiguration.model_validate(
            {**infra, "project_workflows": project_workflows}
        )
    except ValidationError as error:
        raise ManifestError(f"assembled runtime manifest failed validation:\n{error}") from None


def install(config: RealRuntimeConfiguration, target: Path, *, force: bool) -> None:
    """Atomically write the manifest at 0600, refusing a symlink target."""

    if target.is_symlink():
        raise ManifestError(f"refusing to write the manifest through a symlink: {target}")
    if target.exists() and not force:
        raise ManifestError(f"{target} already exists; pass --force to replace it")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = config.model_dump_json(indent=2, by_alias=True).encode("utf-8")
    scratch = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    descriptor = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)
    if os.name == "posix":
        os.chmod(scratch, 0o600)
    os.replace(scratch, target)


async def check_registry(database_url: str, bindings: list[ManifestBinding]) -> list[str]:
    """Verify each bound workflow version against the published resolved snapshot."""

    from jarvis_persistence.database import create_async_database_engine
    from jarvis_persistence.models import WorkflowVersionModel

    problems: list[str] = []
    engine = create_async_database_engine(database_url)
    try:
        async with engine.connect() as connection:
            for binding in bindings:
                row = (
                    await connection.execute(
                        select(
                            WorkflowVersionModel.spec_json,
                            WorkflowVersionModel.resolved_snapshot_json,
                            WorkflowVersionModel.published_at,
                        ).where(WorkflowVersionModel.id == binding.workflow_version_id)
                    )
                ).first()
                tag = f"workflow {binding.workflow_version_id}"
                if row is None:
                    problems.append(f"{tag}: no such workflow version")
                    continue
                spec_json, snapshot_json, published_at = row
                if published_at is None:
                    problems.append(f"{tag}: not published")
                if not snapshot_json:
                    problems.append(f"{tag}: has no resolved snapshot; republish it")
                    continue
                try:
                    spec = WorkflowSpec.model_validate(spec_json)
                    snapshot = WorkflowResolvedSnapshot.model_validate(snapshot_json)
                except ValidationError as error:
                    problems.append(f"{tag}: stored spec/snapshot is unreadable: {error}")
                    continue
                problems.extend(_snapshot_problems(tag, spec, snapshot, binding.worker_revision_id))
    finally:
        await engine.dispose()
    return problems


def _revision_spec(snapshot: WorkflowResolvedSnapshot, revision_id: UUID | None) -> object | None:
    if revision_id is None:
        return None
    return next(
        (rev.spec for rev in snapshot.revisions if rev.revision_id == revision_id),
        None,
    )


def _snapshot_problems(
    tag: str, spec: WorkflowSpec, snapshot: WorkflowResolvedSnapshot, worker_revision_id: UUID
) -> list[str]:
    problems: list[str] = []
    for node in spec.nodes:
        policy = effective_policy(spec, node)
        if node.type.value == "worker":
            selector = policy.worker_selector
            if selector is None or selector.revision_id != worker_revision_id:
                problems.append(
                    f"{tag}: worker node {node.id} selects "
                    f"{selector.revision_id if selector else None}, "
                    f"binding worker is {worker_revision_id}"
                )
            continue
        if node.type.value not in _PLANNING_NODES:
            continue
        retry = _revision_spec(snapshot, policy.retry_policy_ref)
        if not isinstance(retry, RetryRegistrySpec):
            problems.append(f"{tag}: node {node.id} has no immutable retry policy")
        else:
            covered = {rule.failure_class for rule in retry.rules if rule.max_retries > 0}
            missing = [item.value for item in REQUIRED_MODEL_RETRY_CLASSES if item not in covered]
            if missing:
                problems.append(
                    f"{tag}: node {node.id} retry policy has no retries for " + ", ".join(missing)
                )
        route = _revision_spec(snapshot, policy.model_route_ref)
        candidates = route.candidates if isinstance(route, RoutePolicySpec) else ()
        if not candidates:
            problems.append(f"{tag}: node {node.id} has no immutable model route")
        for candidate in candidates:
            profile = _revision_spec(snapshot, candidate.profile_revision_id)
            if not isinstance(profile, ModelProfileSpec) or not profile.structured_json:
                problems.append(
                    f"{tag}: node {node.id} profile {candidate.profile_revision_id} "
                    f"is not a structured-JSON planning profile"
                )
    return problems


def _runtime_build(args: argparse.Namespace) -> int:
    infra = load_infrastructure(args.infra)
    bindings = load_bindings(args.binding)
    config = assemble(infra, bindings)

    if args.check_registry:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise ManifestError(
                "--check-registry needs DATABASE_URL for a read-only registry query"
            )
        if sys.platform == "win32":
            with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
                problems = runner.run(check_registry(database_url, bindings))
        else:
            problems = asyncio.run(check_registry(database_url, bindings))
        if problems:
            print("Registry consistency check failed:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        print("Registry consistency check passed.", file=sys.stderr)

    bound = sum(len(v) for v in config.project_workflows.values())
    print(
        f"Runtime manifest valid: {bound} binding(s), "
        f"{len(config.workers)} worker deployment(s), "
        f"{len(config.allowed_worker_hosts)} allowed host(s).",
        file=sys.stderr,
    )
    for project_id, workflows in config.project_workflows.items():
        for workflow_id in workflows:
            print(f"  project {project_id} -> workflow {workflow_id}", file=sys.stderr)

    if args.stdout:
        sys.stdout.write(config.model_dump_json(indent=2, by_alias=True) + "\n")
    else:
        install(config, args.out, force=args.force)
        print(f"Installed {args.out} (mode 0600).", file=sys.stderr)
    return 0


def inspect_runtime(path: Path) -> dict[str, object]:
    """Validate repeatable local runtime prerequisites without network or inference."""

    try:
        config = RealRuntimeConfiguration.load(path)
        metadata = path.stat()
    except (OSError, ValueError, ValidationError) as error:
        raise ManifestError(f"runtime manifest is unavailable or invalid: {error}") from None
    if not stat.S_ISREG(metadata.st_mode):
        raise ManifestError("runtime manifest must be a regular file")
    if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ManifestError("runtime manifest must deny all group/other permissions")

    problems: list[str] = []
    for reference, credential in config.credential_files.items():
        try:
            details = credential.stat()
        except OSError:
            problems.append(f"credential reference {reference} is unavailable")
            continue
        if not stat.S_ISREG(details.st_mode):
            problems.append(f"credential reference {reference} is not a regular file")
        elif os.name == "posix" and stat.S_IMODE(details.st_mode) & 0o077:
            problems.append(f"credential reference {reference} permits group/other access")

    workers: list[dict[str, object]] = []
    for revision_id, deployment in config.workers.items():
        if deployment.wrapper_path is None or deployment.python_path is None:
            problems.append(f"worker {revision_id} has no V1 wrapper executable")
        if deployment.runner_python_path is None:
            problems.append(f"worker {revision_id} has no separately configured runner Python")
        if deployment.python_path == deployment.runner_python_path:
            problems.append(f"worker {revision_id} reuses the legacy runner environment")
        for reference in (deployment.ssh_key_ref, deployment.host_key_ref):
            if str(reference) not in config.credential_files:
                problems.append(f"worker {revision_id} credential reference is unresolved")
        workers.append(
            {
                "revision_id": str(revision_id),
                "host_alias": deployment.host_alias,
                "wrapper_path": deployment.wrapper_path,
                "runner_path": deployment.runner_path,
                "wrapper_python": deployment.python_path,
                "runner_python": deployment.runner_python_path,
                "strict_host_key_checking": deployment.strict_host_key_checking,
            }
        )

    broker = Path(config.verification_isolation.broker_argv[0])
    if not broker.is_file() or (os.name == "posix" and not os.access(broker, os.X_OK)):
        problems.append("verification broker executable is unavailable")
    if not config.project_workflows and not config.workflows:
        problems.append("no repository binding is configured")
    if problems:
        raise ManifestError("runtime local validation failed: " + "; ".join(problems))

    return {
        "status": "configured_unverified",
        "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "workers": workers,
        "repository_binding_count": sum(len(v) for v in config.project_workflows.values())
        + len(config.workflows),
        "provider_endpoint_count": len(config.providers.allowed_endpoints),
        "verification_image_id": config.verification_isolation.image_id,
        "verification_profile_count": len(config.verification_isolation.profiles),
        "verification_broker": str(broker),
        "note": "No worker, provider, repository, or verifier network probe was performed.",
    }


def _runtime_inspect(args: argparse.Namespace) -> int:
    sys.stdout.write(json.dumps(inspect_runtime(args.manifest), indent=2, sort_keys=True) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis-admin", description="Jarvis V1 operator tooling")
    sub = parser.add_subparsers(dest="command", required=True)
    runtime = sub.add_parser("runtime", help="private real-runtime manifest tooling")
    runtime_sub = runtime.add_subparsers(dest="runtime_command", required=True)
    build = runtime_sub.add_parser("build", help="assemble and validate the runtime manifest")
    build.add_argument("--infra", required=True, type=Path, help="infrastructure fragment JSON")
    build.add_argument(
        "--binding",
        required=True,
        action="append",
        type=Path,
        metavar="PATH",
        help="binding descriptor JSON (repeatable; a file may hold a list)",
    )
    build.add_argument("--out", type=Path, help="atomically install the manifest here (0600)")
    build.add_argument("--stdout", action="store_true", help="print the manifest instead of --out")
    build.add_argument("--force", action="store_true", help="replace an existing --out file")
    build.add_argument(
        "--check-registry",
        action="store_true",
        help="also verify each workflow version against its snapshot (needs DATABASE_URL)",
    )
    build.set_defaults(func=_runtime_build)
    inspect = runtime_sub.add_parser(
        "inspect", help="validate local runtime files without network or inference"
    )
    inspect.add_argument("--manifest", required=True, type=Path)
    inspect.set_defaults(func=_runtime_inspect)
    args = parser.parse_args(argv)

    if getattr(args, "func", None) is _runtime_build and not args.stdout and args.out is None:
        parser.error("runtime build requires --out or --stdout")
    try:
        return int(args.func(args))
    except ManifestError as error:
        print(f"jarvis-admin: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
