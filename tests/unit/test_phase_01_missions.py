"""Pure Phase 1 proposal guards."""

import pytest
from pydantic import ValidationError

from jarvis_contracts.missions import ManagerDecision


def test_manager_response_bounds_actions_scope_and_dependency_cycles() -> None:
    with pytest.raises(ValidationError):
        ManagerDecision.model_validate(
            {"action": "wait", "message": "wait", "work_items": [{"key": "DEV-1"}]}
        )
    with pytest.raises(ValidationError, match="acyclic"):
        ManagerDecision.model_validate(
            {
                "action": "propose",
                "message": "cyclic",
                "work_items": [
                    {
                        "key": "DEV-1",
                        "title": "one",
                        "objective": "one",
                        "acceptance_criteria": ["done"],
                        "dependencies": ["DEV-2"],
                    },
                    {
                        "key": "DEV-2",
                        "title": "two",
                        "objective": "two",
                        "acceptance_criteria": ["done"],
                        "dependencies": ["DEV-1"],
                    },
                ],
            }
        )


def test_ordinary_manager_answer_cannot_mutate_backlog() -> None:
    decision = ManagerDecision(action="explain", message="Current mission scope")
    assert decision.work_items == ()
