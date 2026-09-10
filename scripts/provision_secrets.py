#!/usr/bin/env python3
"""Idempotent, least-privilege provisioning of Docker Compose secret files.

`deploy/compose.production.yml` mounts file-backed secrets. Outside Swarm, Docker
Compose bind-mounts each host file as-is, so a secret written by a root shell as
``0600 root:root`` is unreadable to the non-root ``10001:10001`` user the Python
image runs as. First installs used to work around that by hand. This module does
it correctly and repeatably instead:

* creates the secret directory and every required secret file;
* generates values with :mod:`secrets`, sized to each consumer's documented
  minimum and maximum length;
* sets owner, group and mode so the container UID can read them and nothing else
  can (never group- or world-readable);
* is idempotent -- an existing in-range value is kept, only its metadata is
  repaired;
* refuses to touch a symlink or a non-regular file, and refuses to overwrite an
  out-of-range existing value unless ``--force`` is given;
* never writes a secret value to stdout, stderr or a log.

It is POSIX-only (it needs ``os.chown``); on other platforms it exits 2.

Usage::

    python3 scripts/provision_secrets.py --secret-dir /opt/jarvis-v1/secrets
    python3 scripts/provision_secrets.py --secret-dir /opt/jarvis-v1/secrets --check
"""

from __future__ import annotations

import argparse
import os
import secrets
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

CONTAINER_UID = 10001
"""UID/GID the deploy/python.Dockerfile runtime stage runs as."""

CONTAINER_GID = 10001

DEFAULT_FILE_MODE = 0o600
DEFAULT_DIR_MODE = 0o700


@dataclass(frozen=True)
class SecretSpec:
    """One required secret file and the bounds its consumer enforces."""

    name: str
    min_length: int
    max_length: int
    generate: Callable[[], str]
    consumers: str


# Lengths mirror the runtime checks: scripts/bootstrap_database.py and
# scripts/container_entrypoint.py require 24..1024 characters for the database
# passwords; api/app/jarvis_api/auth/crypto.py requires 32..4096 bytes for the
# CSRF key.
SPECS: tuple[SecretSpec, ...] = (
    SecretSpec(
        "bootstrap_password",
        24,
        1024,
        lambda: secrets.token_urlsafe(32),
        "postgres superuser + scripts/bootstrap_database.py",
    ),
    SecretSpec(
        "migrator_password",
        24,
        1024,
        lambda: secrets.token_urlsafe(32),
        "alembic migrate + owner-bootstrap",
    ),
    SecretSpec(
        "api_password",
        24,
        1024,
        lambda: secrets.token_urlsafe(32),
        "jarvis_v1_api_login",
    ),
    SecretSpec(
        "orchestrator_password",
        24,
        1024,
        lambda: secrets.token_urlsafe(32),
        "jarvis_v1_orchestrator_login",
    ),
    SecretSpec(
        "csrf_key",
        32,
        4096,
        lambda: secrets.token_hex(32),
        "JARVIS_CSRF_HMAC_KEY_FILE",
    ),
)

SECRET_NAMES: tuple[str, ...] = tuple(spec.name for spec in SPECS)


class ProvisioningError(RuntimeError):
    """A condition that must stop provisioning; the message is value-free."""


def _is_posix() -> bool:
    return os.name == "posix"


def _require_posix() -> None:
    if not _is_posix():
        raise ProvisioningError(
            "secret provisioning requires a POSIX host (needs os.chown); "
            "run it on the Jarvis-Core machine"
        )


def _running_as_root() -> bool:
    if sys.platform == "win32":
        return False
    return os.geteuid() == 0


def _chown(path: Path, uid: int, gid: int) -> None:
    if sys.platform == "win32":  # pragma: no cover - guarded by _require_posix
        raise ProvisioningError("ownership changes require a POSIX host")
    os.chown(path, uid, gid)


def _lstat_or_none(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _reject_unsafe_node(path: Path, info: os.stat_result) -> None:
    if stat.S_ISLNK(info.st_mode):
        raise ProvisioningError(f"{path.name} is a symlink; refusing to follow or replace it")
    if not stat.S_ISREG(info.st_mode):
        raise ProvisioningError(
            f"{path.name} exists but is not a regular file; refusing to touch it"
        )


def _read_length(path: Path) -> int:
    """Length of the stripped text value, or -1 if it is not valid UTF-8 text."""

    try:
        return len(path.read_text(encoding="utf-8").strip())
    except UnicodeDecodeError:
        return -1


def _apply_metadata(path: Path, *, uid: int, gid: int, file_mode: int) -> bool:
    """Set mode and (as root) ownership. Return True when something changed."""

    changed = False
    current = stat.S_IMODE(path.stat().st_mode)
    if current != file_mode:
        os.chmod(path, file_mode)
        changed = True
    if _running_as_root():
        info = path.stat()
        if info.st_uid != uid or info.st_gid != gid:
            _chown(path, uid, gid)
            changed = True
    return changed


def _ensure_directory(secret_dir: Path, *, uid: int, gid: int, dir_mode: int) -> None:
    node = _lstat_or_none(secret_dir)
    if node is not None and stat.S_ISLNK(node.st_mode):
        raise ProvisioningError("the secret directory is a symlink; refusing to use it")
    if node is not None and not stat.S_ISDIR(node.st_mode):
        raise ProvisioningError("the secret directory path exists and is not a directory")
    secret_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(secret_dir, dir_mode)
    if _running_as_root():
        info = secret_dir.stat()
        if info.st_uid != uid or info.st_gid != gid:
            _chown(secret_dir, uid, gid)


def _write_new_secret(path: Path, value: str, *, file_mode: int) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, file_mode)
    try:
        os.write(descriptor, value.encode("utf-8"))
    finally:
        os.close(descriptor)
    os.chmod(path, file_mode)


@dataclass(frozen=True)
class SecretResult:
    name: str
    outcome: str


def provision(
    secret_dir: Path,
    *,
    uid: int = CONTAINER_UID,
    gid: int = CONTAINER_GID,
    force: bool = False,
    file_mode: int = DEFAULT_FILE_MODE,
    dir_mode: int = DEFAULT_DIR_MODE,
) -> list[SecretResult]:
    """Create or repair every required secret. Never returns a secret value."""

    _require_posix()
    if file_mode & 0o077:
        raise ProvisioningError("file mode would allow group or other access")
    _ensure_directory(secret_dir, uid=uid, gid=gid, dir_mode=dir_mode)

    results: list[SecretResult] = []
    for spec in SPECS:
        path = secret_dir / spec.name
        node = _lstat_or_none(path)
        if node is None:
            _write_new_secret(path, spec.generate(), file_mode=file_mode)
            _apply_metadata(path, uid=uid, gid=gid, file_mode=file_mode)
            results.append(SecretResult(spec.name, "created"))
            continue

        _reject_unsafe_node(path, node)
        length = _read_length(path)
        in_range = spec.min_length <= length <= spec.max_length
        if not in_range and not force:
            raise ProvisioningError(
                f"{spec.name} has an out-of-range length; refusing to overwrite it "
                f"(re-run with --force to regenerate)"
            )
        if not in_range:
            path.unlink()
            _write_new_secret(path, spec.generate(), file_mode=file_mode)
            _apply_metadata(path, uid=uid, gid=gid, file_mode=file_mode)
            results.append(SecretResult(spec.name, "regenerated"))
            continue

        repaired = _apply_metadata(path, uid=uid, gid=gid, file_mode=file_mode)
        results.append(SecretResult(spec.name, "repaired" if repaired else "kept"))
    return results


def check(secret_dir: Path, *, uid: int = CONTAINER_UID, gid: int = CONTAINER_GID) -> list[str]:
    """Return a list of human-readable problems; empty means ready."""

    problems: list[str] = []
    if not _is_posix():
        return ["secret provisioning check requires a POSIX host"]
    node = _lstat_or_none(secret_dir)
    if node is None:
        return [f"secret directory {secret_dir} does not exist"]
    if stat.S_ISLNK(node.st_mode) or not stat.S_ISDIR(node.st_mode):
        return [f"{secret_dir} is not a real directory"]
    for spec in SPECS:
        path = secret_dir / spec.name
        entry = _lstat_or_none(path)
        if entry is None:
            problems.append(f"{spec.name}: missing")
            continue
        if stat.S_ISLNK(entry.st_mode) or not stat.S_ISREG(entry.st_mode):
            problems.append(f"{spec.name}: not a regular file")
            continue
        mode = stat.S_IMODE(entry.st_mode)
        if mode & 0o077:
            problems.append(f"{spec.name}: mode {oct(mode)} allows group/other access")
        if _running_as_root() and (entry.st_uid != uid or entry.st_gid != gid):
            problems.append(
                f"{spec.name}: owned by {entry.st_uid}:{entry.st_gid}, expected {uid}:{gid} "
                f"(the container UID cannot read it)"
            )
        length = _read_length(path)
        if not (spec.min_length <= length <= spec.max_length):
            problems.append(
                f"{spec.name}: length {length} outside {spec.min_length}..{spec.max_length}"
            )
    return problems


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Provision Docker Compose secret files with least privilege.",
    )
    parser.add_argument("--secret-dir", required=True, type=Path)
    parser.add_argument("--uid", type=int, default=CONTAINER_UID)
    parser.add_argument("--gid", type=int, default=CONTAINER_GID)
    parser.add_argument(
        "--force",
        action="store_true",
        help="regenerate an existing secret whose length is out of range",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify existing secrets without writing anything; exit 1 on any problem",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    secret_dir = args.secret_dir.expanduser()
    try:
        if args.check:
            problems = check(secret_dir, uid=args.uid, gid=args.gid)
            if problems:
                print("Secret provisioning check failed:", file=sys.stderr)
                for problem in problems:
                    print(f"  - {problem}", file=sys.stderr)
                return 1
            print(f"Secret provisioning check passed: {len(SPECS)} files in {secret_dir}")
            return 0

        if _is_posix() and not _running_as_root():
            print(
                "Note: not running as root; file modes are set but ownership is left unchanged.\n"
                "      Docker Compose must then read the secrets as the same user, or re-run "
                "this as root so the container UID can read them.",
                file=sys.stderr,
            )
        results = provision(
            secret_dir,
            uid=args.uid,
            gid=args.gid,
            force=args.force,
        )
    except ProvisioningError as error:
        print(f"Secret provisioning refused: {error}", file=sys.stderr)
        return 2
    for result in results:
        print(f"  {result.name}: {result.outcome}")
    print(f"Secrets ready in {secret_dir} (owner {args.uid}:{args.gid}, mode 0600).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
