"""Explicit server-side legacy import; never a browser command execution path."""

import shlex
from dataclasses import dataclass

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.verification import VerificationCommand


@dataclass(frozen=True)
class LegacyCorrection:
    original_digest: str
    removed_prefix: str
    command: VerificationCommand


def normalize_legacy(command: str) -> LegacyCorrection:
    if not 1 <= len(command) <= 8192 or "\x00" in command:
        raise ValueError("invalid legacy command")
    prefix = next(
        (
            f"cd {root} && "
            for root in ("/app", "/workspace", "/project", "/repo")
            if command.startswith(f"cd {root} && ")
        ),
        None,
    )
    if prefix is None:
        raise ValueError("legacy correction requires an explicitly recognized leading cd")
    remainder = command[len(prefix) :]
    # This migration supports a single argv command, not arbitrary legacy shell.
    if any(character in remainder for character in ";&|<>`$\n\r"):
        raise ValueError("legacy shell syntax is not supported")
    return LegacyCorrection(
        original_digest=sha256_digest({"command": command}),
        removed_prefix=prefix,
        command=VerificationCommand(argv=tuple(shlex.split(remainder))),
    )
