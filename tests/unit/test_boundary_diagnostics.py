"""A blocked run names the boundary that refused, without leaking native text."""

from jarvis_contracts.enums import FailureClass
from jarvis_contracts.failures import FailureEvidence, classify_failure
from jarvis_orchestrator.providers.base import BoundaryError
from jarvis_orchestrator.runtime.errors import safe_boundary_code
from jarvis_orchestrator.runtime.nodes import ClassifiedNodeError, boundary_failure_class
from jarvis_orchestrator.workers.safety import WorkerBoundaryError
from jarvis_orchestrator.workflows.factories import MissingWorkflowHandlerError


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


def test_escaped_boundary_error_keeps_its_declared_retry_class() -> None:
    """A worker/provider boundary that escapes its adapter must not degrade to
    orchestration.runtime_error; its declared class drives class-specific retry.
    """

    assert (
        boundary_failure_class(
            WorkerBoundaryError("invocation_deadline", FailureClass.INFRASTRUCTURE_TIMEOUT)
        )
        is FailureClass.INFRASTRUCTURE_TIMEOUT
    )
    # The default carries a real, non-retryable class -- still an explicit signal.
    assert (
        boundary_failure_class(WorkerBoundaryError("wrapper_unconfigured"))
        is FailureClass.CONFIGURATION_INVALID
    )
    assert (
        boundary_failure_class(BoundaryError("stream_dropped", FailureClass.PROVIDER_TRANSIENT))
        is FailureClass.PROVIDER_TRANSIENT
    )
    assert (
        boundary_failure_class(ClassifiedNodeError(FailureClass.CODE_TEST_FAILURE))
        is FailureClass.CODE_TEST_FAILURE
    )
    assert (
        boundary_failure_class(MissingWorkflowHandlerError("x"))
        is FailureClass.CONFIGURATION_INVALID
    )
    assert boundary_failure_class(RuntimeError("native worker crash")) is None


def test_retryable_boundary_class_produces_a_retryable_classification() -> None:
    error = WorkerBoundaryError("invocation_deadline", FailureClass.INFRASTRUCTURE_TIMEOUT)
    classified = classify_failure(
        FailureEvidence(
            explicit_class=boundary_failure_class(error), summary="Node execution failed"
        )
    )
    assert classified.failure_class is FailureClass.INFRASTRUCTURE_TIMEOUT
    assert classified.retryable is True
    # Only the enum crossed: the boundary's own message/code never reaches the
    # classification the operator sees.
    assert classified.summary == "Node execution failed"
    assert classified.code == "unknown"


def test_non_retryable_boundary_class_still_blocks() -> None:
    error = WorkerBoundaryError("workspace_escape", FailureClass.SECURITY_POLICY_DENIED)
    classified = classify_failure(
        FailureEvidence(
            explicit_class=boundary_failure_class(error), summary="Node execution failed"
        )
    )
    assert classified.failure_class is FailureClass.SECURITY_POLICY_DENIED
    assert classified.retryable is False


def test_unsafe_boundary_code_never_leaks_through_the_class_channel() -> None:
    error = WorkerBoundaryError("invocation_deadline", FailureClass.INFRASTRUCTURE_TIMEOUT)
    error.code = "https://user:sk-secret@host/leak"  # a boundary that set an unsafe code
    assert safe_boundary_code(error) is None
    classified = classify_failure(
        FailureEvidence(
            explicit_class=boundary_failure_class(error), summary="Node execution failed"
        )
    )
    assert "secret" not in classified.summary and "secret" not in classified.code
    assert classified.failure_class is FailureClass.INFRASTRUCTURE_TIMEOUT
