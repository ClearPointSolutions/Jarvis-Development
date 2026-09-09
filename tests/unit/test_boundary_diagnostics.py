"""A blocked run names the boundary that refused, without leaking native text."""

from jarvis_contracts.enums import FailureClass
from jarvis_orchestrator.providers.base import BoundaryError
from jarvis_orchestrator.runtime.errors import safe_boundary_code
from jarvis_orchestrator.workers.safety import WorkerBoundaryError


def test_worker_and_provider_boundary_codes_are_reported() -> None:
    assert safe_boundary_code(WorkerBoundaryError("source_import_tree_mismatch")) == (
        "source_import_tree_mismatch"
    )
    assert (
        safe_boundary_code(BoundaryError("endpoint_denied", FailureClass.SECURITY_POLICY_DENIED))
        == "endpoint_denied"
    )


def test_an_ordinary_exception_has_no_boundary_code() -> None:
    assert safe_boundary_code(RuntimeError("worker failed")) is None
    assert safe_boundary_code(ValueError("boom")) is None


def test_unsafe_code_shapes_are_refused() -> None:
    """Only a bare identifier reaches the operator-visible channel."""

    for unsafe in (
        "https://user:secret@host/path",
        "connection to 10.0.0.4 refused",
        "key=sk-live-value",
        "traceback\nline two",
        "",
        "a" * 121,
    ):
        error = RuntimeError("native")
        error.code = unsafe  # type: ignore[attr-defined]
        assert safe_boundary_code(error) is None, unsafe


def test_a_non_string_code_is_ignored() -> None:
    error = RuntimeError("native")
    error.code = 500  # type: ignore[attr-defined]
    assert safe_boundary_code(error) is None
