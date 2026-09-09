"""Provision a named disposable loopback SSH protocol worker for acceptance.

Never discovers or contacts a homelab target. Existing containers/directories are
rejected rather than overwritten. Generated private material stays outside Git.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def command(*argv: str) -> str:
    return subprocess.run(
        argv,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    ).stdout.strip()


def provision(directory: Path, name: str, port: int) -> None:
    existing = command("docker", "ps", "-a", "--format", "{{.Names}}").splitlines()
    if name in existing:
        raise ValueError("Disposable fixture name already exists; choose a new name")
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    if os.name != "nt":
        directory.chmod(0o700)
    command(
        "docker", "build", "-f", "deploy/python.Dockerfile", "-t", "jarvis-v1-mvp-python:local", "."
    )
    command(
        "docker",
        "build",
        "-f",
        "tests/fixtures/runtime-worker/Dockerfile",
        "-t",
        "jarvis-v1-protocol-worker:local",
        ".",
    )
    command("ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(directory / "client_key"))
    command(
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--label",
        "jarvis.disposable=protocol",
        "-p",
        f"127.0.0.1:{port}:2222",
        "jarvis-v1-protocol-worker:local",
    )
    command(
        "docker",
        "cp",
        str(directory / "client_key.pub"),
        f"{name}:/home/jarvis/.ssh/authorized_keys",
    )
    command("docker", "exec", name, "chown", "10001:10001", "/home/jarvis/.ssh/authorized_keys")
    command("docker", "exec", name, "chmod", "600", "/home/jarvis/.ssh/authorized_keys")
    public_key = command("docker", "exec", name, "cat", "/etc/ssh/ssh_host_ed25519_key.pub")
    # Pin from the container we created, never trust a network keyscan.
    kind, key, *_ = public_key.split()
    (directory / "known_hosts").write_text(f"[127.0.0.1]:{port} {kind} {key}\n")
    prefix = ("docker", "exec", "--user", "10001:10001", name)
    command(*prefix, "git", "init", "-b", "main", "/workspaces/fixture")
    git = (*prefix, "git", "-C", "/workspaces/fixture")
    command(*git, "config", "user.name", "Protocol fixture")
    command(*git, "config", "user.email", "fixture@localhost")
    command(
        *prefix,
        "python",
        "-c",
        "from pathlib import Path; "
        "Path('/workspaces/fixture/.gitignore').write_text('__pycache__/\\n.pytest_cache/\\n')",
    )
    command(*git, "add", ".gitignore")
    command(*git, "commit", "-m", "Initial fixture")
    (directory / "base-sha.txt").write_text(command(*git, "rev-parse", "HEAD") + "\n")
    print(f"Disposable SSH fixture ready: {name} at loopback port {port}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--name", default="jarvis-v1-ci-protocol-worker")
    parser.add_argument("--port", type=int, default=22249)
    args = parser.parse_args()
    provision(args.directory, args.name, args.port)


if __name__ == "__main__":
    main()
