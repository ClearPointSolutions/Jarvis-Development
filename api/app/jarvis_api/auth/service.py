"""Durable single-owner login, session, revocation, and rate-limit service."""

from __future__ import annotations

import asyncio
import hmac
import math
import secrets
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_api.auth.audit import AuthAuditWriter
from jarvis_api.auth.crypto import (
    PasswordManager,
    client_network,
    derive_csrf_token,
    keyed_fingerprint,
    new_session_token,
    normalize_username,
    sha256_text,
)
from jarvis_api.auth.repository import AuthRepository
from jarvis_api.config import Settings
from jarvis_contracts.enums import EventSeverity
from jarvis_contracts.event_registry import (
    LoginFailedData,
    LoginSucceededData,
    LogoutData,
    SessionRevokedData,
)
from jarvis_contracts.ids import SessionId, UserId
from jarvis_persistence.models import LoginRateLimitModel, SessionModel, UserModel
from jarvis_persistence.testing import Clock, SystemClock


@dataclass(frozen=True)
class ClientMetadata:
    ip_address: str | None
    user_agent: str | None

    @property
    def network(self) -> str:
        return client_network(self.ip_address)


@dataclass(frozen=True)
class AuthPrincipal:
    user_id: UserId
    username: str
    role: str
    session_id: SessionId
    idle_expires_at: datetime
    absolute_expires_at: datetime
    session_token: str = field(repr=False)
    csrf_token: str = field(repr=False)


@dataclass(frozen=True)
class LoginResult:
    principal: AuthPrincipal | None
    retry_after_seconds: int


class AuthService:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        *,
        server_key: bytes | None,
        clock: Clock | None = None,
        password_manager: PasswordManager | None = None,
        repository: AuthRepository | None = None,
        audit: AuthAuditWriter | None = None,
    ) -> None:
        self._factory = factory
        self._settings = settings
        self._server_key = server_key
        self._fingerprint_key = server_key or secrets.token_bytes(32)
        self._clock = clock or SystemClock()
        self._passwords = password_manager or PasswordManager()
        self._repository = repository or AuthRepository()
        self._audit = audit or AuthAuditWriter(instance_id=settings.api_instance_id)

    @property
    def password_manager(self) -> PasswordManager:
        return self._passwords

    def _subject(self, username: str) -> tuple[str | None, str]:
        try:
            normalized = normalize_username(username)
            source = normalized
        except ValueError:
            normalized = None
            source = unicodedata.normalize("NFKC", username).strip().casefold()
        return normalized, keyed_fingerprint(self._fingerprint_key, "login-account", source)

    def _rate_keys(self, account_hash: str, network: str) -> tuple[tuple[str, str], ...]:
        return (
            ("account", account_hash),
            ("network", keyed_fingerprint(self._fingerprint_key, "login-network", network)),
        )

    def _reset_windows(
        self, rows: dict[tuple[str, str], LoginRateLimitModel], now: datetime
    ) -> None:
        window = timedelta(seconds=self._settings.login_window_seconds)
        for row in rows.values():
            if now - row.window_started_at >= window:
                row.failed_count = 0
                row.window_started_at = now
                row.locked_until = None
                row.updated_at = now

    @staticmethod
    def _blocked_seconds(rows: dict[tuple[str, str], LoginRateLimitModel], now: datetime) -> int:
        remaining = [
            (row.locked_until - now).total_seconds()
            for row in rows.values()
            if row.locked_until is not None and row.locked_until > now
        ]
        return max(0, math.ceil(max(remaining, default=0)))

    def _record_failure(
        self, rows: dict[tuple[str, str], LoginRateLimitModel], now: datetime
    ) -> int:
        for (scope, _), row in rows.items():
            row.failed_count += 1
            threshold = (
                self._settings.login_account_limit
                if scope == "account"
                else self._settings.login_network_limit
            )
            if row.failed_count >= threshold and self._settings.login_base_delay_seconds > 0:
                exponent = min(row.failed_count - threshold, 30)
                delay = min(
                    self._settings.login_max_delay_seconds,
                    self._settings.login_base_delay_seconds * (2**exponent),
                )
                row.locked_until = now + timedelta(seconds=delay)
            row.updated_at = now
        return self._blocked_seconds(rows, now)

    async def login(
        self,
        *,
        username: str,
        password: str,
        metadata: ClientMetadata,
        correlation_id: str,
        previous_session_token: str | None = None,
    ) -> LoginResult:
        normalized, account_hash = self._subject(username)
        keys = self._rate_keys(account_hash, metadata.network)
        now = self._clock.now()
        result: LoginResult

        # Argon2 is intentionally expensive. Perform it before acquiring the global event lock,
        # then confirm that the credential row is unchanged inside the write transaction.
        async with self._factory() as read_session:
            candidate_user = (
                await self._repository.find_user(read_session, normalized)
                if normalized is not None
                else None
            )
            candidate_hash = (
                candidate_user.password_hash
                if candidate_user is not None and candidate_user.enabled
                else self._passwords.dummy_hash
            )
        preverified = await asyncio.to_thread(self._passwords.verify, candidate_hash, password)

        async with self._factory.begin() as session:
            # Every login writes an audit event. Acquire the global event lock before auth rows.
            await self._repository.lock_event_counter(session)
            rows = await self._repository.lock_rate_limits(session, keys=keys, now=now)
            self._reset_windows(rows, now)
            preexisting_delay = self._blocked_seconds(rows, now)
            user = (
                await self._repository.find_user(session, normalized)
                if normalized is not None
                else None
            )

            if preexisting_delay > 0:
                await self._audit_login_failed(
                    session,
                    account_hash=account_hash,
                    now=now,
                    correlation_id=correlation_id,
                    retry_after=preexisting_delay,
                )
                result = LoginResult(None, preexisting_delay)
            else:
                current_hash = (
                    user.password_hash
                    if user is not None and user.enabled
                    else self._passwords.dummy_hash
                )
                valid = preverified
                if current_hash != candidate_hash:
                    valid = await asyncio.to_thread(self._passwords.verify, current_hash, password)
                if user is None or not user.enabled or not valid:
                    retry_after = self._record_failure(rows, now)
                    await self._audit_login_failed(
                        session,
                        account_hash=account_hash,
                        now=now,
                        correlation_id=correlation_id,
                        retry_after=retry_after,
                    )
                    result = LoginResult(None, retry_after)
                else:
                    account_row = rows[("account", account_hash)]
                    account_row.failed_count = 0
                    account_row.locked_until = None
                    account_row.window_started_at = now
                    account_row.updated_at = now
                    if self._passwords.needs_rehash(user.password_hash):
                        user.password_hash = await asyncio.to_thread(self._passwords.hash, password)
                    user.last_login_at = now
                    if previous_session_token:
                        await self._rotate_previous(
                            session,
                            token=previous_session_token,
                            now=now,
                            correlation_id=correlation_id,
                        )
                    principal = await self._new_session(
                        session,
                        user=user,
                        now=now,
                        metadata=metadata,
                        correlation_id=correlation_id,
                    )
                    result = LoginResult(principal, 0)
        return result

    async def _audit_login_failed(
        self,
        session: AsyncSession,
        *,
        account_hash: str,
        now: datetime,
        correlation_id: str,
        retry_after: int,
    ) -> None:
        await self._audit.append(
            session,
            event_type="auth.login_failed",
            payload=LoginFailedData(
                subject_fingerprint=account_hash,
                rate_limited=retry_after > 0,
                retry_after_seconds=retry_after,
            ),
            occurred_at=now,
            correlation_id=correlation_id,
            severity=EventSeverity.WARNING,
        )

    async def _new_session(
        self,
        session: AsyncSession,
        *,
        user: UserModel,
        now: datetime,
        metadata: ClientMetadata,
        correlation_id: str,
    ) -> AuthPrincipal:
        token = new_session_token()
        csrf = derive_csrf_token(token, self._server_key)
        absolute = now + timedelta(seconds=self._settings.session_absolute_seconds)
        idle = min(now + timedelta(seconds=self._settings.session_idle_seconds), absolute)
        row = SessionModel(
            id=uuid7(),
            user_id=user.id,
            token_hash=sha256_text(token),
            csrf_secret_hash=sha256_text(csrf),
            created_at=now,
            last_seen_at=now,
            expires_at=idle,
            absolute_expires_at=absolute,
            ip_prefix=metadata.network,
            user_agent_hash=(sha256_text(metadata.user_agent) if metadata.user_agent else None),
        )
        await self._repository.create_session(session, row)
        await self._audit.append(
            session,
            event_type="auth.login_succeeded",
            payload=LoginSucceededData(
                user_id=UserId(user.id),
                session_id=SessionId(row.id),
                client_network=metadata.network,
            ),
            occurred_at=now,
            correlation_id=correlation_id,
            severity=EventSeverity.SUCCESS,
        )
        return self._principal(row, user, token, csrf)

    async def _rotate_previous(
        self,
        session: AsyncSession,
        *,
        token: str,
        now: datetime,
        correlation_id: str,
    ) -> None:
        pair = await self._repository.get_session_with_user(session, sha256_text(token), lock=True)
        if pair is None:
            return
        previous, previous_user = pair
        if previous.revoked_at is not None:
            return
        previous.revoked_at = now
        previous.revoke_reason = "rotated_on_login"
        await self._audit.append(
            session,
            event_type="auth.session_revoked",
            payload=SessionRevokedData(
                user_id=UserId(previous_user.id),
                session_id=SessionId(previous.id),
                reason="rotated_on_login",
            ),
            occurred_at=now,
            correlation_id=correlation_id,
            severity=EventSeverity.INFO,
        )

    def _principal(
        self, row: SessionModel, user: UserModel, token: str, csrf: str
    ) -> AuthPrincipal:
        return AuthPrincipal(
            user_id=UserId(user.id),
            username=user.username,
            role=user.role,
            session_id=SessionId(row.id),
            idle_expires_at=row.expires_at,
            absolute_expires_at=row.absolute_expires_at,
            session_token=token,
            csrf_token=csrf,
        )

    async def authenticate(
        self, *, session_token: str, correlation_id: str
    ) -> AuthPrincipal | None:
        if len(session_token) < 32 or len(session_token) > 256:
            return None
        token_hash = sha256_text(session_token)
        now = self._clock.now()
        revoke_reason: str | None = None
        async with self._factory.begin() as session:
            pair = await self._repository.get_session_with_user(session, token_hash, lock=True)
            if pair is None:
                return None
            row, user = pair
            csrf = derive_csrf_token(session_token, self._server_key)
            if row.revoked_at is not None:
                return None
            if not user.enabled:
                revoke_reason = "user_disabled"
            elif now >= row.absolute_expires_at:
                revoke_reason = "absolute_expired"
            elif now >= row.expires_at:
                revoke_reason = "idle_expired"
            elif not hmac.compare_digest(row.csrf_secret_hash, sha256_text(csrf)):
                revoke_reason = "csrf_key_changed"
            else:
                if now - row.last_seen_at >= timedelta(
                    seconds=self._settings.session_touch_interval_seconds
                ):
                    row.last_seen_at = now
                    row.expires_at = min(
                        now + timedelta(seconds=self._settings.session_idle_seconds),
                        row.absolute_expires_at,
                    )
                return self._principal(row, user, session_token, csrf)

        if revoke_reason is not None:
            await self._revoke_expired(
                token_hash=token_hash,
                reason=revoke_reason,
                now=now,
                correlation_id=correlation_id,
            )
        return None

    async def _revoke_expired(
        self,
        *,
        token_hash: str,
        reason: str,
        now: datetime,
        correlation_id: str,
    ) -> None:
        async with self._factory.begin() as session:
            await self._repository.lock_event_counter(session)
            pair = await self._repository.get_session_with_user(session, token_hash, lock=True)
            if pair is None:
                return
            row, user = pair
            if row.revoked_at is not None:
                return
            row.revoked_at = now
            row.revoke_reason = reason
            await self._audit.append(
                session,
                event_type="auth.session_revoked",
                payload=SessionRevokedData(
                    user_id=UserId(user.id), session_id=SessionId(row.id), reason=reason
                ),
                occurred_at=now,
                correlation_id=correlation_id,
                severity=EventSeverity.INFO,
            )

    def valid_csrf(self, principal: AuthPrincipal, candidate: str | None) -> bool:
        return candidate is not None and hmac.compare_digest(principal.csrf_token, candidate)

    async def logout(self, principal: AuthPrincipal, *, correlation_id: str) -> bool:
        now = self._clock.now()
        async with self._factory.begin() as session:
            await self._repository.lock_event_counter(session)
            row = await self._repository.get_session_by_id(
                session, UUID(str(principal.session_id)), lock=True
            )
            if row is None or row.revoked_at is not None:
                return False
            row.revoked_at = now
            row.revoke_reason = "owner_logout"
            await self._audit.append(
                session,
                event_type="auth.logout",
                payload=LogoutData(user_id=principal.user_id, session_id=principal.session_id),
                occurred_at=now,
                correlation_id=correlation_id,
                severity=EventSeverity.INFO,
            )
            return True
