"""Bounded staging with independent sentinel extraction and redacted publication."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from jarvis_api.events.redaction import RecursiveRedactor


@dataclass(frozen=True)
class RedactedLog:
    content: bytes
    digest: str
    truncated: bool


class LogCapture:
    def __init__(self, limit: int, *, line_limit: int = 65536) -> None:
        if not 1024 <= limit <= 104857600 or not 1024 <= line_limit <= 262144:
            raise ValueError("invalid capture limits")
        self.limit = limit
        self.line_limit = line_limit
        self.staging = bytearray()
        self.line = bytearray()
        self.truncated = False
        self.line_overflow = False
        self.sentinel = b""
        self.malformed_sentinel_seen = False

    def feed(self, block: bytes) -> None:
        # Caller reads bounded chunks; lines may span any number of chunks.
        for part in block.splitlines(keepends=True):
            remaining = self.line_limit - len(self.line)
            self.line.extend(part[:remaining])
            self.line_overflow |= len(part) > remaining
            if part.endswith(b"\n"):
                self._line_finished()

    def _line_finished(self) -> None:
        line = bytes(self.line)
        if line.startswith(b"JARVIS_RESULT_JSON="):
            if not self.line_overflow:
                # Structure validation belongs to parser; keep last schema-valid record.
                from jarvis_orchestrator.workers.safety import LegacyResult

                try:
                    LegacyResult.model_validate_json(line.split(b"=", 1)[1])
                except ValueError:
                    self.malformed_sentinel_seen = True
                else:
                    self.sentinel = line
            else:
                self.malformed_sentinel_seen = True
        if (
            not self.truncated
            and not self.line_overflow
            and len(self.staging) + len(line) <= self.limit
        ):
            self.staging.extend(line)
        else:
            self.truncated = True
        self.line.clear()
        self.line_overflow = False

    def finish(self, redactor: RecursiveRedactor | None = None) -> RedactedLog:
        if self.line:
            self._line_finished()
        safe, _ = (redactor or RecursiveRedactor()).redact_text(
            self.staging.decode("utf-8", errors="replace")
        )
        # Redaction placeholders can grow; truncate only complete lines afterwards.
        encoded = safe.encode()
        if len(encoded) > self.limit:
            encoded = encoded[: self.limit].rsplit(b"\n", 1)[0]
            self.truncated = True
        if self.truncated:
            encoded = b"[output truncated]\n" + encoded[: self.limit - 20]
        return RedactedLog(encoded, hashlib.sha256(encoded).hexdigest(), self.truncated)
