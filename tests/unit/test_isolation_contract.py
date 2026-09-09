"""Candidate traversal and receipt substitution cannot cross the broker boundary."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from jarvis_contracts.verification import VerificationCommand
from jarvis_orchestrator.verification.isolation_contract import (
    CandidateFile,
    IsolationReceipt,
    IsolationRequest,
)


@pytest.mark.parametrize(
    "path", ["../secret", "/etc/passwd", ".git/config", "a/../b", "a\\b", "a//b"]
)
def test_candidate_rejects_traversal(path: str) -> None:
    with pytest.raises(ValidationError):
        CandidateFile(path=path, content="canary")


def test_candidate_rejects_duplicate_files_and_oversized_utf8() -> None:
    values = dict(run_id=uuid4(), execution_id=uuid4(), candidate_sha="a" * 40, tree_sha="b" * 40)
    command = VerificationCommand(argv=("pytest",))
    file = CandidateFile(path="test.py", content="x")
    with pytest.raises(ValidationError):
        IsolationRequest(**values, command=command, files=(file, file))
    with pytest.raises(ValidationError):
        IsolationRequest(
            **values, command=command, files=(CandidateFile(path="x", content="é" * 2097153),)
        )


def test_receipt_rejects_candidate_and_invocation_substitution() -> None:
    request = IsolationRequest(
        run_id=uuid4(),
        execution_id=uuid4(),
        candidate_sha="a" * 40,
        tree_sha="b" * 40,
        files=(),
        command=VerificationCommand(argv=("pytest",)),
    )
    image = "sha256:" + "c" * 64
    receipt = IsolationReceipt(
        request_digest=request.digest,
        run_id=request.run_id,
        execution_id=request.execution_id,
        candidate_sha=request.candidate_sha,
        image_id=image,
        exit_code=0,
        timed_out=False,
        stdout="",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
    )
    receipt.require(request, image)
    for changed in (
        request.model_copy(update={"execution_id": uuid4()}),
        request.model_copy(update={"candidate_sha": "d" * 40}),
        request.model_copy(update={"files": (CandidateFile(path="x", content="changed"),)}),
    ):
        with pytest.raises(ValueError, match="identity mismatch"):
            receipt.require(changed, image)
