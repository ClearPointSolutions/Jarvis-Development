"""API configuration loaded exclusively from server-side environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server-only API settings with safe local defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="JARVIS_",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    public_origin: str = "http://127.0.0.1:3000"
    database_url: str = Field(
        default="postgresql+psycopg://jarvis_v1_dev@127.0.0.1:55432/jarvis_v1_test",
        validation_alias=AliasChoices("DATABASE_URL", "JARVIS_DATABASE_URL"),
    )
    csrf_hmac_key_file: Path | None = None
    session_cookie_name: str = Field(default="jarvis_session", pattern=r"^[a-z][a-z0-9_]*$")
    session_idle_seconds: int = Field(default=1_800, ge=60, le=86_400)
    session_absolute_seconds: int = Field(default=43_200, ge=300, le=604_800)
    session_touch_interval_seconds: int = Field(default=60, ge=1, le=3_600)
    cookie_secure: bool = False
    login_window_seconds: int = Field(default=900, ge=60, le=86_400)
    login_account_limit: int = Field(default=5, ge=1, le=100)
    login_network_limit: int = Field(default=20, ge=1, le=1_000)
    login_base_delay_seconds: int = Field(default=1, ge=0, le=60)
    login_max_delay_seconds: int = Field(default=300, ge=1, le=3_600)
    api_instance_id: str = Field(default="api-local", min_length=1, max_length=160)
    artifact_root: Path = Path("var/artifacts")
    event_inline_bytes: int = Field(default=32_768, ge=1_024, le=65_536)
    event_max_bytes: int = Field(default=65_536, ge=4_096, le=65_536)
    event_replay_page_size: int = Field(default=250, ge=1, le=1_000)
    sse_keepalive_seconds: float = Field(default=15.0, ge=1.0, le=60.0)
    sse_poll_seconds: float = Field(default=2.0, ge=0.1, le=30.0)
    sse_max_connections: int = Field(default=20, ge=1, le=1_000)
    event_notify_channel: Literal["jarvis_v1_events"] = "jarvis_v1_events"

    @model_validator(mode="after")
    def validate_security_boundaries(self) -> Settings:
        parsed = urlsplit(self.public_origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("public_origin must be an absolute HTTP(S) origin")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username:
            raise ValueError(
                "public_origin must not contain credentials, a path, query, or fragment"
            )
        if self.event_inline_bytes >= self.event_max_bytes:
            raise ValueError("event_inline_bytes must be smaller than event_max_bytes")
        if self.session_idle_seconds > self.session_absolute_seconds:
            raise ValueError("session idle lifetime cannot exceed absolute lifetime")
        if self.login_base_delay_seconds > self.login_max_delay_seconds:
            raise ValueError("login base delay cannot exceed maximum delay")
        if self.env == "production" and not self.cookie_secure:
            raise ValueError("production requires Secure session cookies")
        if self.env == "production" and self.csrf_hmac_key_file is None:
            raise ValueError("production requires JARVIS_CSRF_HMAC_KEY_FILE")
        return self

    @property
    def trusted_host(self) -> str:
        hostname = urlsplit(self.public_origin).hostname
        if hostname is None:
            raise ValueError("public_origin has no hostname")
        return hostname


@lru_cache
def get_settings() -> Settings:
    return Settings()
