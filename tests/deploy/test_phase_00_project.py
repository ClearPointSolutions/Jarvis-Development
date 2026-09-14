"""Behavioral tests for the disposable Phase 0 project preparation script."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "prepare-phase-00-project.sh"
BASH_EXECUTABLE = shutil.which("bash")


def _tool_available(executable: str | None) -> bool:
    if executable is None:
        return False
    try:
        return (
            subprocess.run([executable, "--version"], capture_output=True, timeout=5).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(
    not (_tool_available(BASH_EXECUTABLE) and _tool_available(shutil.which("git"))),
    reason="functional bash and git are required",
)


def _bash_path(path: Path) -> str:
    value = path.as_posix()
    if len(value) >= 3 and value[1:3] == ":/":
        return f"/{value[0].lower()}{value[2:]}"
    return value


def test_prepare_project_commits_fixture_and_refuses_existing_destination(tmp_path: Path) -> None:
    assert BASH_EXECUTABLE is not None
    destination = tmp_path / "phase-00-project"
    command = [BASH_EXECUTABLE, _bash_path(SCRIPT), _bash_path(destination)]

    created = subprocess.run(command, text=True, capture_output=True)
    assert created.returncode == 0, created.stderr
    head_before = subprocess.check_output(
        ["git", "-C", destination, "rev-parse", "HEAD"], text=True
    ).strip()
    readme_before = (destination / "README.md").read_bytes()
    assert f"base_sha={head_before}" in created.stdout
    assert not (destination / "__pycache__").exists()

    repeated = subprocess.run(command, text=True, capture_output=True)
    assert repeated.returncode != 0
    assert "destination already exists" in repeated.stderr
    assert (
        subprocess.check_output(["git", "-C", destination, "rev-parse", "HEAD"], text=True).strip()
        == head_before
    )
    assert (destination / "README.md").read_bytes() == readme_before
