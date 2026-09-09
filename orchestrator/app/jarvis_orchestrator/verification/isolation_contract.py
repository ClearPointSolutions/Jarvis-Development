"""Private protocol between Core and the credential-free verification broker."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.verification import VerificationCommand


class CandidateFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: str = Field(min_length=1, max_length=512)
    content: str = Field(max_length=4194304)
    executable: bool = False

    @model_validator(mode="after")
    def safe_file(self) -> CandidateFile:
        path = PurePosixPath(self.path)
        if (
            path.is_absolute()
            or any(part in {"..", ".git"} for part in path.parts)
            or str(path) != self.path
            or "\\" in self.path
            or "\x00" in self.path + self.content
            or self.content.startswith("version https://git-lfs.github.com/spec/v1")
        ):
            raise ValueError("unsupported candidate file")
        return self


class IsolationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    protocol: Literal["jarvis-verification-v1"] = "jarvis-verification-v1"
    run_id: UUID
    execution_id: UUID
    candidate_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    tree_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    files: tuple[CandidateFile, ...] = Field(max_length=1000)
    command: VerificationCommand

    @model_validator(mode="after")
    def bounded_source(self) -> IsolationRequest:
        if len({file.path for file in self.files}) != len(self.files):
            raise ValueError("duplicate candidate path")
        if sum(len(file.content.encode("utf-8")) for file in self.files) > 4194304:
            raise ValueError("candidate exceeds text-only profile")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class IsolationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    protocol: Literal["jarvis-verification-v1"] = "jarvis-verification-v1"
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    run_id: UUID
    execution_id: UUID
    candidate_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    image_id: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    exit_code: Annotated[int, Field(ge=0, le=255)] | None
    timed_out: bool
    stdout: str = Field(max_length=1048576)
    stderr: str = Field(max_length=1048576)
    stdout_truncated: bool
    stderr_truncated: bool

    def require(self, request: IsolationRequest, image_id: str) -> None:
        if (
            self.request_digest != request.digest
            or self.run_id != request.run_id
            or self.execution_id != request.execution_id
            or self.candidate_sha != request.candidate_sha
            or self.image_id != image_id
        ):
            raise ValueError("verification receipt identity mismatch")
