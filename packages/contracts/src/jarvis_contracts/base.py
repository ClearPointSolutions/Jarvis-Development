"""Shared strict-model and canonical JSON primitives."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Base for versioned wire contracts.

    Major-version-one contracts reject unknown fields. Models are frozen to make
    accidental in-process replacement impossible; persisted immutability is also
    enforced by PostgreSQL triggers.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


def canonical_json(value: BaseModel | Mapping[str, Any]) -> bytes:
    """Return the canonical UTF-8 representation used for stable digests."""

    if isinstance(value, BaseModel):
        serializable: Any = value.model_dump(mode="json", by_alias=True, exclude_none=False)
    else:
        serializable = value
    return json.dumps(
        serializable,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_digest(value: BaseModel | Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()
