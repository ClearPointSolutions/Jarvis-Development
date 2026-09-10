"""Executable checks for scripts/provision_secrets.py.

Ownership assertions only run as root (chown needs privilege); mode, length,
idempotency, refusal and no-secret-in-output checks run on any POSIX host.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only provisioning")

from scripts.provision_secrets import (  # noqa: E402  (guarded import)
    SPECS,
    ProvisioningError,
    check,
    main,
    provision,
)

IS_ROOT = sys.platform != "win32" and os.geteuid() == 0


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def test_provision_creates_every_secret_with_locked_down_metadata(tmp_path: Path) -> None:
    secret_dir = tmp_path / "secrets"
    results = provision(secret_dir)

    assert {r.name for r in results} == {s.name for s in SPECS}
    assert {r.outcome for r in results} == {"created"}
    for spec in SPECS:
        path = secret_dir / spec.name
        info = path.stat()
        assert stat.S_ISREG(info.st_mode)
        assert stat.S_IMODE(info.st_mode) & 0o077 == 0
        assert spec.min_length <= len(_read(path)) <= spec.max_length
        if IS_ROOT:
            assert (info.st_uid, info.st_gid) == (10001, 10001)
    assert stat.S_IMODE(secret_dir.stat().st_mode) & 0o077 == 0


def test_provision_is_idempotent_and_keeps_values(tmp_path: Path) -> None:
    secret_dir = tmp_path / "secrets"
    provision(secret_dir)
    before = {s.name: _read(secret_dir / s.name) for s in SPECS}

    results = provision(secret_dir)

    assert {r.outcome for r in results} <= {"kept", "repaired"}
    assert {s.name: _read(secret_dir / s.name) for s in SPECS} == before
    assert check(secret_dir) == []


def test_provision_repairs_a_loosened_mode_without_rewriting_the_value(tmp_path: Path) -> None:
    secret_dir = tmp_path / "secrets"
    provision(secret_dir)
    target = secret_dir / "api_password"
    value = _read(target)
    os.chmod(target, 0o644)

    outcomes = {r.name: r.outcome for r in provision(secret_dir)}

    assert outcomes["api_password"] == "repaired"
    assert stat.S_IMODE(target.stat().st_mode) & 0o077 == 0
    assert _read(target) == value


def test_provision_refuses_a_symlink(tmp_path: Path) -> None:
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    (tmp_path / "elsewhere").write_text("x" * 40, encoding="utf-8")
    (secret_dir / "csrf_key").symlink_to(tmp_path / "elsewhere")

    with pytest.raises(ProvisioningError, match="symlink"):
        provision(secret_dir)


def test_provision_refuses_a_non_regular_file(tmp_path: Path) -> None:
    secret_dir = tmp_path / "secrets"
    (secret_dir / "migrator_password").mkdir(parents=True)

    with pytest.raises(ProvisioningError, match="not a regular file"):
        provision(secret_dir)


def test_provision_refuses_to_overwrite_a_short_existing_value(tmp_path: Path) -> None:
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    (secret_dir / "migrator_password").write_text("too-short", encoding="utf-8")

    with pytest.raises(ProvisioningError, match="out-of-range"):
        provision(secret_dir)

    outcomes = {r.name: r.outcome for r in provision(secret_dir, force=True)}
    assert outcomes["migrator_password"] == "regenerated"
    assert check(secret_dir) == []


def test_provision_rejects_a_group_readable_file_mode(tmp_path: Path) -> None:
    with pytest.raises(ProvisioningError, match="group or other access"):
        provision(tmp_path / "secrets", file_mode=0o640)


def test_check_reports_specific_problems(tmp_path: Path) -> None:
    secret_dir = tmp_path / "secrets"
    provision(secret_dir)
    (secret_dir / "csrf_key").unlink()
    os.chmod(secret_dir / "api_password", 0o604)

    problems = check(secret_dir)

    assert any("csrf_key" in p and "missing" in p for p in problems)
    assert any("api_password" in p and "group/other" in p for p in problems)


def test_cli_exits_zero_and_never_echoes_a_secret(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret_dir = tmp_path / "secrets"

    rc = main(["--secret-dir", str(secret_dir)])
    captured = capsys.readouterr()

    assert rc == 0
    combined = captured.out + captured.err
    for spec in SPECS:
        assert _read(secret_dir / spec.name) not in combined
    assert main(["--secret-dir", str(secret_dir), "--check"]) == 0
