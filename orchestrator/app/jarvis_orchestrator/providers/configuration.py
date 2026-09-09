"""Server-owned provider bindings; immutable run snapshots remain authoritative."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jarvis_contracts.registry import ModelProfileSpec, ProviderSpec
from jarvis_orchestrator.providers.base import BaseAdapter, BoundaryError
from jarvis_orchestrator.providers.ollama import OllamaAdapter
from jarvis_orchestrator.providers.openai import OpenAIAdapter


class ProviderRuntimeConfig(BaseModel):
    """This file is private to the orchestrator, never a browser contract.

    Endpoint grants are exact. Credential files are indexed by immutable provider
    revision, so editing a registry entry cannot borrow another provider's key.
    Loading configuration does not contact any endpoint or read credentials.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    allowed_endpoints: tuple[str, ...] = ()
    credential_files: dict[UUID, Path] = Field(default_factory=dict, repr=False)
    probe_seconds: float = Field(default=15, ge=1, le=60)
    reviewer_seconds: float = Field(default=300, ge=1, le=3600)

    @field_validator("allowed_endpoints")
    @classmethod
    def valid_endpoints(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            # Reuse the connection contract's URL guards, without accepting
            # normalization that broadens an exact server-owned grant.
            parsed = ProviderSpec(provider_kind="ollama", base_url=value)
            if parsed.base_url != value:
                raise ValueError("endpoint grants must use canonical URLs")
        if len(set(values)) != len(values):
            raise ValueError("duplicate endpoint grants")
        return values

    @field_validator("credential_files")
    @classmethod
    def absolute_files(cls, values: dict[UUID, Path]) -> dict[UUID, Path]:
        if any(not path.is_absolute() for path in values.values()):
            raise ValueError("credential files must be absolute")
        return values

    @classmethod
    def load(cls, path: Path) -> ProviderRuntimeConfig:
        with path.open("rb") as source:
            payload = source.read(65537)
        if len(payload) > 65536:
            raise ValueError("provider runtime configuration exceeds 64 KiB")
        return cls.model_validate_json(payload)

    def adapter(
        self,
        provider: ProviderSpec,
        profile: ModelProfileSpec,
        provider_revision_id: UUID,
        profile_revision_id: UUID,
    ) -> BaseAdapter:
        arguments = (provider, profile, provider_revision_id, profile_revision_id)
        endpoints = frozenset(self.allowed_endpoints)
        if provider.provider_kind == "ollama":
            return OllamaAdapter(*arguments, allowed_endpoints=endpoints)
        if provider.provider_kind != "openai":
            raise ValueError("real provider configuration refuses demo adapters")
        path = self.credential_files.get(provider_revision_id)

        def resolve(_reference: str) -> str:
            if path is None:
                raise BoundaryError("missing_credential")
            try:
                with path.open("rb") as source:
                    raw = source.read(16385)
                value = raw.decode("utf-8").strip()
            except (OSError, UnicodeError):
                raise BoundaryError("credential_unavailable") from None
            if not value or len(raw) > 16384 or any(c.isspace() for c in value):
                raise BoundaryError("invalid_credential")
            return value

        return OpenAIAdapter(
            *arguments,
            allowed_endpoints=endpoints,
            secret_ref=str(provider_revision_id) if path is not None else None,
            secret_resolver=resolve,
        )
