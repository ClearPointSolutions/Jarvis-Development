"""Resource and secret boundaries before schema/compiler processing."""

import pytest
from pydantic import JsonValue

from jarvis_api.errors import ApiProblemError
from jarvis_api.workflows.service import safe_workflow_input


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_nonfinite_json_rejected(value: float) -> None:
    with pytest.raises(ApiProblemError, match=r"workflow\.unsafe_input"):
        safe_workflow_input({"position": value})


def test_depth_count_and_byte_limits_before_recursive_processing() -> None:
    nested: JsonValue = None
    for _ in range(25):
        nested = {"child": nested}
    with pytest.raises(ApiProblemError, match="resource_limit"):
        safe_workflow_input({"tree": nested})
    with pytest.raises(ApiProblemError, match="resource_limit"):
        safe_workflow_input({"items": [0] * 100001})
    with pytest.raises(ApiProblemError, match="resource_limit"):
        safe_workflow_input({"description": "a" * 1048576})


def test_private_keys_and_opaque_locators_are_not_public_workflow_data() -> None:
    payloads: tuple[dict[str, JsonValue], ...] = (
        {"api_key": "arbitrary-canary"},
        {"label": "secret:hidden"},
        {"label": "file:private.env#VALUE"},
    )
    for payload in payloads:
        with pytest.raises(ApiProblemError, match="unsafe_input"):
            safe_workflow_input(payload)
