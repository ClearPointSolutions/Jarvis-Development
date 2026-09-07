#!/usr/bin/env python3
"""Deterministic high-confidence secret and credential-file scanner."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_SIZE = 2_000_000
ALLOWED_ENV_FILES = {".env.example"}
PROHIBITED_SUFFIXES = {".key", ".p12", ".pfx", ".jks"}
PATTERNS = {
    "private key": re.compile(rb"-{5}BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-{5}"),
    "OpenAI-style key": re.compile(rb"\bsk-[A-Za-z0-9_-]{24,}\b"),
    "GitHub token": re.compile(rb"\b(?:gh[opusr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    "AWS access key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
}


def repository_paths() -> list[Path]:
    safe_root = ROOT.as_posix()
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={safe_root}",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / raw.decode("utf-8") for raw in result.stdout.split(b"\0") if raw]


def scan(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        name = path.name.lower()
        if (name.startswith(".env") and name not in ALLOWED_ENV_FILES) or (
            path.suffix.lower() in PROHIBITED_SUFFIXES
        ):
            findings.append(f"prohibited credential file: {relative}")
            continue
        if path.stat().st_size > MAX_FILE_SIZE:
            continue
        content = path.read_bytes()
        if b"\0" in content:
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(content):
                findings.append(f"{label}: {relative}")
    return findings


def self_test() -> bool:
    with tempfile.TemporaryDirectory() as directory:
        canary = Path(directory) / "canary.txt"
        canary.write_text("-----BEGIN " + "PRIVATE KEY-----\nnot-a-real-key\n", encoding="utf-8")
        return bool(scan([canary]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        if self_test():
            print("secret scanner canary: detected")
            return 0
        print("secret scanner canary: NOT detected", file=sys.stderr)
        return 1

    findings = scan(repository_paths())
    if findings:
        print("Secret scan failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("secret scan: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
