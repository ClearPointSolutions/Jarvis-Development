"""Password, opaque-token, CSRF, and identifier hashing primitives."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import os
import re
import secrets
import unicodedata
from pathlib import Path

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,63}$")
MINIMUM_PASSWORD_LENGTH = 12


class PasswordPolicyError(ValueError):
    """A bootstrap credential does not satisfy the local owner policy."""


class PasswordManager:
    """OWASP-aligned Argon2id hashing with equivalent unknown-user work."""

    def __init__(self) -> None:
        self._hasher = PasswordHasher(
            time_cost=2,
            memory_cost=19_456,
            parallelism=1,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(32))

    @property
    def dummy_hash(self) -> str:
        return self._dummy_hash

    def hash(self, password: str) -> str:
        if len(password) < MINIMUM_PASSWORD_LENGTH:
            raise PasswordPolicyError(
                f"owner password must be at least {MINIMUM_PASSWORD_LENGTH} characters"
            )
        if len(password) > 1_024:
            raise PasswordPolicyError("owner password exceeds the maximum length")
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError:
            return False


def normalize_username(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError("username must be 3-64 lower-case ASCII letters, digits, '.', '_' or '-'")
    if normalized == "migration-unassigned":
        raise ValueError("username is reserved")
    return normalized


def new_session_token() -> str:
    # 32 random bytes provide 256 bits of entropy before URL-safe encoding.
    return secrets.token_urlsafe(32)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def derive_csrf_token(session_token: str, server_key: bytes | None) -> str:
    key = server_key if server_key is not None else hashlib.sha256(session_token.encode()).digest()
    digest = hmac.new(
        key,
        b"jarvis-v1-csrf\0" + session_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def keyed_fingerprint(server_key: bytes, purpose: str, value: str) -> str:
    return hmac.new(
        server_key,
        purpose.encode("ascii") + b"\0" + value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def client_network(value: str | None) -> str:
    if value is None:
        return "unknown"
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return "unknown"
    prefix = 24 if address.version == 4 else 64
    return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False))


def load_server_key(path: Path | None, *, production: bool) -> bytes | None:
    if path is None:
        return None
    if path.is_symlink():
        raise ValueError("CSRF key file must not be a symbolic link")
    content = path.read_bytes().strip()
    if len(content) < 32 or len(content) > 4_096:
        raise ValueError("CSRF key file must contain between 32 and 4096 bytes")
    if production and os.name != "nt" and path.stat().st_mode & 0o077:
        raise ValueError("CSRF key file permissions must deny group and other access")
    return content
