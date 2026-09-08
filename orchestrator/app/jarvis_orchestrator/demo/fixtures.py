"""Bounded deterministic fixture data, independent of runtime scheduling."""

from pydantic import Field

from jarvis_contracts.base import ContractModel, sha256_digest
from jarvis_contracts.demo import DemoFixture
from jarvis_contracts.enums import FailureClass


class PlannedTask(ContractModel):
    key: str = Field(pattern=r"^DEV-\d{3}$")
    title: str = Field(min_length=1, max_length=240)
    dependencies: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...]
    weight: int = Field(default=1, ge=1)


def task_plan() -> tuple[PlannedTask, ...]:
    return (
        PlannedTask(
            key="DEV-001",
            title="Implement the greeting fixture",
            acceptance_criteria=("Greeting includes the supplied name",),
        ),
        PlannedTask(
            key="DEV-002",
            title="Document and verify the complete fixture",
            dependencies=("DEV-001",),
            acceptance_criteria=("Documentation and greeting source coexist",),
        ),
    )


def repository_fixture(task: str, attempt: int, fixture: DemoFixture) -> dict[str, str]:
    files = {"greeting.py": 'def greet(name):\n    return "Hello, " + name\n'}
    if task == "DEV-001" and attempt == 1 and fixture.scenario == "canonical":
        files["greeting.py"] = 'def greet(name):\n    return "Hello"\n'
    if task == "DEV-002":
        files["README.md"] = "# DEMO greeting\nUse greet(name) to greet a person.\n"
    return files


def snapshot_digest(files: dict[str, str]) -> str:
    return sha256_digest(files)


def injected_failure(
    fixture: DemoFixture, node_type: str, task: str, attempt: int, visit: int
) -> FailureClass | None:
    if fixture.scenario == "infrastructure" and node_type == "worker" and visit == 1:
        return FailureClass.INFRASTRUCTURE_WORKER_TRANSPORT
    if fixture.scenario == "provider" and node_type == "organizer" and visit == 1:
        return FailureClass.PROVIDER_TRANSIENT
    if task == "DEV-001" and attempt == 1:
        if fixture.scenario == "canonical" and node_type == "verify":
            return FailureClass.CODE_TEST_FAILURE
        if fixture.scenario == "review" and node_type == "reviewer":
            return FailureClass.CODE_REVIEW_FAILURE
    return None
