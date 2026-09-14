"""jarvis-admin runtime build: assembly, cross-checks, atomic install, redaction."""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from jarvis_orchestrator import admin
from jarvis_orchestrator.runtime import composition
from jarvis_orchestrator.runtime.configuration import RealRuntimeConfiguration

WORKER_REV = uuid4()
PROJECT = uuid4()
REPO = uuid4()
WORKFLOW = uuid4()
WORKSPACE_ROOT = "/opt/jarvis-worker/workspaces"


def _infra(tmp_path: Path) -> dict[str, object]:
    return {
        "workers": {
            str(WORKER_REV): {
                "host_alias": "jarvis-worker",
                "user": "jarvis",
                "ssh_key_ref": "secret:worker-key",
                "host_key_ref": "secret:worker-pin",
                "workspace_root": WORKSPACE_ROOT,
                "runner_path": "/opt/jarvis-worker/developer_task.py",
                "venv_activate": "/opt/jarvis-worker/v1-wrapper/venv/bin/activate",
                "invocation_root": "/opt/jarvis-worker/persistence/v1-invocations",
                "wrapper_path": "/opt/jarvis-worker/v1-wrapper/entry.py",
                "python_path": "/opt/jarvis-worker/v1-wrapper/venv/bin/python",
                "runner_python_path": "/opt/jarvis-worker/venv/bin/python",
            }
        },
        "credential_files": {
            "secret:worker-key": str(tmp_path / "key"),
            "secret:worker-pin": str(tmp_path / "pin"),
        },
        "allowed_worker_hosts": ["jarvis-worker"],
        "source_root": str(tmp_path / "src"),
        "verification_isolation": {
            "broker_argv": [sys.executable, "broker"],
            "image_id": "sha256:" + "a" * 64,
        },
        "executables": {},
        "executable_path": "/usr/bin:/bin",
        "git_executable": sys.executable,
        "ssh_executable": sys.executable,
        "git_author_name": "Jarvis V1",
        "git_author_email": "jarvis-v1@localhost",
    }


def _binding(**overrides: object) -> dict[str, object]:
    slug = str(overrides.pop("slug", "acceptance-app"))
    base: dict[str, object] = {
        "project_id": str(PROJECT),
        "workflow_version_id": str(WORKFLOW),
        "worker_revision_id": str(WORKER_REV),
        "worker_project": {
            "project_id": str(PROJECT),
            "repository_id": str(REPO),
            "slug": slug,
            "workspace_root": f"{WORKSPACE_ROOT}/{slug}",
            "branch": "main",
            "base_sha": "a" * 40,
        },
        "combined_commands": [{"argv": ["python", "-m", "pytest", "-q"]}],
    }
    base.update(overrides)
    return base


def _write(
    tmp_path: Path, infra: dict[str, object], *bindings: dict[str, object]
) -> tuple[Path, list[Path]]:
    infra_path = tmp_path / "infra.json"
    infra_path.write_text(json.dumps(infra), encoding="utf-8")
    paths = []
    for index, binding in enumerate(bindings):
        path = tmp_path / f"binding-{index}.json"
        path.write_text(json.dumps(binding), encoding="utf-8")
        paths.append(path)
    return infra_path, paths


def test_assemble_builds_the_nested_project_workflows_map(tmp_path: Path) -> None:
    config = admin.assemble(_infra(tmp_path), [admin.ManifestBinding.model_validate(_binding())])
    assert isinstance(config, RealRuntimeConfiguration)
    binding = config.repository_binding(PROJECT, WORKFLOW)
    assert binding.worker_revision_id == WORKER_REV
    assert binding.project.workspace_root == f"{WORKSPACE_ROOT}/acceptance-app"


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            {
                "worker_project": {
                    "project_id": str(uuid4()),
                    "repository_id": str(REPO),
                    "slug": "acceptance-app",
                    "workspace_root": f"{WORKSPACE_ROOT}/acceptance-app",
                    "branch": "main",
                    "base_sha": "a" * 40,
                }
            },
            "worker_project.project_id",
        ),
        ({"worker_revision_id": str(uuid4())}, "has no deployment"),
        (
            {
                "worker_project": {
                    "project_id": str(PROJECT),
                    "repository_id": str(REPO),
                    "slug": "acceptance-app",
                    "workspace_root": f"{WORKSPACE_ROOT}/somewhere-else",
                    "branch": "main",
                    "base_sha": "a" * 40,
                }
            },
            "workspace_root must be",
        ),
    ],
)
def test_assemble_rejects_inconsistent_bindings(
    tmp_path: Path, mutate: dict[str, object], match: str
) -> None:
    with pytest.raises(admin.ManifestError, match=match):
        admin.assemble(_infra(tmp_path), [admin.ManifestBinding.model_validate(_binding(**mutate))])


def test_assemble_rejects_a_host_not_in_the_allowlist(tmp_path: Path) -> None:
    infra = _infra(tmp_path)
    infra["allowed_worker_hosts"] = []
    with pytest.raises(admin.ManifestError, match="allowed_worker_hosts"):
        admin.assemble(infra, [admin.ManifestBinding.model_validate(_binding())])


def test_assemble_rejects_a_duplicate_binding(tmp_path: Path) -> None:
    binding = admin.ManifestBinding.model_validate(_binding())
    with pytest.raises(admin.ManifestError, match="duplicate binding"):
        admin.assemble(_infra(tmp_path), [binding, binding])


def test_infrastructure_fragment_rejects_binding_keys(tmp_path: Path) -> None:
    infra = _infra(tmp_path)
    infra["project_workflows"] = {}
    path = tmp_path / "infra.json"
    path.write_text(json.dumps(infra), encoding="utf-8")
    with pytest.raises(admin.ManifestError, match="per-binding keys"):
        admin.load_infrastructure(path)


def test_install_is_atomic_private_and_symlink_safe(tmp_path: Path) -> None:
    config = admin.assemble(_infra(tmp_path), [admin.ManifestBinding.model_validate(_binding())])
    target = tmp_path / "runtime.json"

    admin.install(config, target, force=False)
    assert RealRuntimeConfiguration.load(target).repository_binding(PROJECT, WORKFLOW)
    if sys.platform != "win32":
        assert stat.S_IMODE(target.stat().st_mode) & 0o077 == 0

    with pytest.raises(admin.ManifestError, match="already exists"):
        admin.install(config, target, force=False)
    admin.install(config, target, force=True)

    link = tmp_path / "link.json"
    if sys.platform != "win32":
        link.symlink_to(target)
        with pytest.raises(admin.ManifestError, match="symlink"):
            admin.install(config, link, force=True)


def test_runtime_inspect_reports_configured_not_live_verified(tmp_path: Path) -> None:
    infra = _infra(tmp_path)
    credentials = cast(dict[str, object], infra["credential_files"])
    for path in credentials.values():
        Path(cast(str, path)).write_text("fixture", encoding="utf-8")
    config = admin.assemble(infra, [admin.ManifestBinding.model_validate(_binding())])
    target = tmp_path / "runtime.json"
    admin.install(config, target, force=False)

    report = admin.inspect_runtime(target)

    assert report["status"] == "configured_unverified"
    assert report["manifest_sha256"]
    assert report["verification_image_id"] == "sha256:" + "a" * 64
    assert "No worker, provider" in str(report["note"])


def test_runtime_inspect_rejects_missing_credentials_and_shared_runner_python(
    tmp_path: Path,
) -> None:
    infra = _infra(tmp_path)
    workers = cast(dict[str, object], infra["workers"])
    worker = cast(dict[str, object], next(iter(workers.values())))
    worker["runner_python_path"] = worker["python_path"]
    config = admin.assemble(infra, [admin.ManifestBinding.model_validate(_binding())])
    target = tmp_path / "runtime.json"
    admin.install(config, target, force=False)

    with pytest.raises(admin.ManifestError, match="legacy runner environment"):
        admin.inspect_runtime(target)


def test_cli_stdout_emits_a_reloadable_manifest_and_summary_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    infra_path, [binding_path] = _write(tmp_path, _infra(tmp_path), _binding())

    rc = admin.main(
        ["runtime", "build", "--infra", str(infra_path), "--binding", str(binding_path), "--stdout"]
    )
    captured = capsys.readouterr()

    assert rc == 0
    reloaded = RealRuntimeConfiguration.model_validate_json(captured.out)
    assert reloaded.repository_binding(PROJECT, WORKFLOW).worker_revision_id == WORKER_REV
    assert "1 binding(s)" in captured.err
    assert f"project {PROJECT} -> workflow {WORKFLOW}" in captured.err


def test_cli_out_install_refuses_overwrite_without_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    infra_path, [binding_path] = _write(tmp_path, _infra(tmp_path), _binding())
    out = tmp_path / "out" / "runtime.json"
    argv = [
        "runtime",
        "build",
        "--infra",
        str(infra_path),
        "--binding",
        str(binding_path),
        "--out",
        str(out),
    ]

    assert admin.main(argv) == 0
    assert out.exists()
    assert admin.main(argv) == 2
    assert admin.main([*argv, "--force"]) == 0


def test_cli_requires_out_or_stdout(tmp_path: Path) -> None:
    infra_path, [binding_path] = _write(tmp_path, _infra(tmp_path), _binding())
    with pytest.raises(SystemExit) as exit_info:
        admin.main(["runtime", "build", "--infra", str(infra_path), "--binding", str(binding_path)])
    assert exit_info.value.code == 2


def test_required_retry_classes_match_the_runtime_preflight() -> None:
    assert admin.REQUIRED_MODEL_RETRY_CLASSES == composition.REQUIRED_MODEL_RETRY_CLASSES


def test_check_registry_needs_a_database_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    infra_path, [binding_path] = _write(tmp_path, _infra(tmp_path), _binding())
    rc = admin.main(
        [
            "runtime",
            "build",
            "--infra",
            str(infra_path),
            "--binding",
            str(binding_path),
            "--stdout",
            "--check-registry",
        ]
    )
    assert rc == 2  # ManifestError -> exit 2, no DB contacted
