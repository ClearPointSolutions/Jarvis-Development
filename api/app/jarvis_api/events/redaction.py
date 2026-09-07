"""Recursive, irreversible redaction for event-bound structured data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from pydantic import JsonValue

_SECRET_FIELD: Final = re.compile(
    r"(?:^|[_-])(?:api[_-]?key|access[_-]?key|client[_-]?secret|token|password|passwd|"
    r"authorization|cookie|private[_-]?key|connection[_-]?(?:string|url)|database[_-]?url)"
    r"(?:$|[_-])",
    re.IGNORECASE,
)
_HIDDEN_REASONING_FIELDS: Final = frozenset(
    {
        "analysis",
        "chain_of_thought",
        "hidden_reasoning",
        "internal_reasoning",
        "provider_reasoning",
        "reasoning",
        "scratchpad",
    }
)
_PRIVATE_KEY: Final = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_BEARER: Final = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")
_CREDENTIAL_URL: Final = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^\s/@:]+)(?::[^\s/@]*)?@")
_ENV_ASSIGNMENT: Final = re.compile(
    r"(?im)^(\s*[A-Z_][A-Z0-9_]*(?:TOKEN|PASSWORD|SECRET|API_KEY|PRIVATE_KEY)\s*=)\s*[^\r\n]*"
)
_INLINE_ASSIGNMENT: Final = re.compile(
    r"(?i)\b(password|passwd|token|api[_-]?key|client[_-]?secret)\s*([:=])\s*"
    r"([^\s,;]+)"
)


@dataclass(frozen=True)
class RedactionReport:
    """Rule counts without removed values or reversible fingerprints."""

    value: JsonValue
    rule_counts: dict[str, int]

    @property
    def count(self) -> int:
        return sum(self.rule_counts.values())


class RecursiveRedactor:
    """Remove secrets and hidden reasoning before persistence or formatting."""

    def __init__(self, known_secret_values: tuple[str, ...] = ()) -> None:
        self._known_secrets = tuple(value for value in known_secret_values if len(value) >= 4)

    def redact(self, value: JsonValue) -> RedactionReport:
        counts: dict[str, int] = {}
        redacted = self._redact_value(value, counts)
        return RedactionReport(value=redacted, rule_counts=counts)

    def redact_text(self, value: str) -> tuple[str, dict[str, int]]:
        counts: dict[str, int] = {}
        return self._redact_string(value, counts), counts

    def _redact_value(self, value: JsonValue, counts: dict[str, int]) -> JsonValue:
        if isinstance(value, dict):
            result: dict[str, JsonValue] = {}
            for raw_key, item in value.items():
                key = str(raw_key)
                normalized_key = key.casefold().replace("-", "_")
                if normalized_key in _HIDDEN_REASONING_FIELDS:
                    self._increment(counts, "hidden_reasoning")
                    continue
                if _SECRET_FIELD.search(normalized_key):
                    result[key] = self._placeholder(self._field_kind(normalized_key))
                    self._increment(counts, "secret_field")
                    continue
                result[key] = self._redact_value(item, counts)
            return result
        if isinstance(value, list):
            return [self._redact_value(item, counts) for item in value]
        if isinstance(value, str):
            return self._redact_string(value, counts)
        return value

    def _redact_string(self, value: str, counts: dict[str, int]) -> str:
        result = value
        for secret in self._known_secrets:
            matches = result.count(secret)
            if matches:
                result = result.replace(secret, self._placeholder("known_secret"))
                self._increment(counts, "known_secret", matches)

        result, count = _PRIVATE_KEY.subn(self._placeholder("private_key"), result)
        self._increment(counts, "private_key", count)
        result, count = _BEARER.subn(self._placeholder("bearer_token"), result)
        self._increment(counts, "bearer_token", count)
        result, count = _CREDENTIAL_URL.subn(
            lambda match: f"{match.group(1)}{self._placeholder('credentials')}@",
            result,
        )
        self._increment(counts, "credential_url", count)
        result, count = _ENV_ASSIGNMENT.subn(
            lambda match: f"{match.group(1)}{self._placeholder('environment_secret')}",
            result,
        )
        self._increment(counts, "environment_assignment", count)
        result, count = _INLINE_ASSIGNMENT.subn(
            lambda match: f"{match.group(1)}{match.group(2)}{self._placeholder('credential')}",
            result,
        )
        self._increment(counts, "inline_credential", count)
        return result

    @staticmethod
    def _increment(counts: dict[str, int], rule: str, amount: int = 1) -> None:
        if amount:
            counts[rule] = counts.get(rule, 0) + amount

    @staticmethod
    def _placeholder(kind: str) -> str:
        return f"[REDACTED:{kind}]"

    @staticmethod
    def _field_kind(field_name: str) -> str:
        if "password" in field_name or "passwd" in field_name:
            return "password"
        if "cookie" in field_name:
            return "cookie"
        if "authorization" in field_name:
            return "authorization"
        if "private" in field_name:
            return "private_key"
        if "connection" in field_name or "database" in field_name:
            return "connection_string"
        return "token"
