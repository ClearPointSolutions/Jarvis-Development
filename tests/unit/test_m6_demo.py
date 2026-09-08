from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import create_autospec
from uuid import UUID

import pytest
from pydantic import ValidationError
from tests.unit.test_m4_workflows_compiler import node, resolved_revision, snapshot_for, spec_for

from jarvis_contracts.demo import DemoFixture
from jarvis_contracts.enums import FailureClass
from jarvis_contracts.registry import ProviderSpec, WorkerSpec
from jarvis_orchestrator.demo.boundaries import DemoPublicationAdapter, DemoWorkerAdapter
from jarvis_orchestrator.demo.fixtures import injected_failure, repository_fixture, task_plan
from jarvis_orchestrator.demo.safety import local_database_port, validate_demo_snapshot
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership


def test_demo_task_topology_and_cumulative_repository_are_deterministic() -> None:
    first, second = task_plan()
    assert first.dependencies == () and second.dependencies == (first.key,)
    fixture = DemoFixture()
    assert repository_fixture(first.key, 1, fixture) != repository_fixture(first.key, 2, fixture)
    assert (
        repository_fixture(first.key, 2, fixture).items()
        <= repository_fixture(second.key, 1, fixture).items()
    )
    assert task_plan() == task_plan()


@pytest.mark.parametrize(
    "scenario,kind,task,attempt,expected",
    [
        ("canonical", "verify", "DEV-001", 1, FailureClass.CODE_TEST_FAILURE),
        ("infrastructure", "worker", "DEV-001", 0, FailureClass.INFRASTRUCTURE_WORKER_TRANSPORT),
        ("review", "reviewer", "DEV-001", 1, FailureClass.CODE_REVIEW_FAILURE),
        ("provider", "organizer", "", 0, FailureClass.PROVIDER_TRANSIENT),
    ],
)
def test_fixture_failures_have_distinct_budgets(
    scenario: str,
    kind: str,
    task: str,
    attempt: int,
    expected: FailureClass,
) -> None:
    fixture = DemoFixture.model_validate({"scenario": scenario})
    assert injected_failure(fixture, kind, task, attempt, 1) == expected
    assert injected_failure(fixture, kind, task, 2, 2) is None


@pytest.mark.parametrize("endpoint", ["https://api.openai.com", "http://127.0.0.1:11434"])
def test_demo_snapshot_rejects_network_providers_before_construction(endpoint: str) -> None:
    provider = ProviderSpec(
        provider_kind="openai" if endpoint.startswith("https") else "ollama", base_url=endpoint
    )
    spec = spec_for((node("finish", "finalize"),))
    with pytest.raises(ValueError, match="production provider"):
        validate_demo_snapshot(snapshot_for(spec, resolved_revision(provider)))
    validate_demo_snapshot(
        snapshot_for(
            spec,
            resolved_revision(ProviderSpec(provider_kind="demo")),
            resolved_revision(WorkerSpec()),
        )
    )


@pytest.mark.parametrize(
    "url", ["postgresql://example.com/jarvis_demo_local", "postgresql://localhost/production"]
)
def test_demo_refuses_nonlocal_or_nondisposable_database(url: str) -> None:
    with pytest.raises(ValueError, match="disposable"):
        local_database_port(url)


def test_demo_control_bounds() -> None:
    with pytest.raises(ValidationError):
        DemoFixture(delay_seconds=31)
    with pytest.raises(ValueError, match="transport overrides"):
        local_database_port("postgresql://localhost/jarvis_demo_test?host=example.com")


@pytest.mark.parametrize("status", ["healthy", "degraded", "unavailable", "unknown"])
async def test_normalized_demo_worker_and_publication_health(status: str, tmp_path: Path) -> None:
    owner = create_autospec(RunOwnership, instance=True)
    fence = RunFence(UUID(int=1), "unit-demo", 1)
    fixture = DemoFixture.model_validate({"health": status})
    worker = DemoWorkerAdapter(owner, fence, tmp_path, fixture)
    publication = DemoPublicationAdapter(owner, fence, tmp_path, fixture)
    assert worker.validate(WorkerSpec()).valid
    for adapter in (worker, publication):
        report = await adapter.health()
        assert report.demo and report.health == status
        assert report.valid == (status in {"healthy", "degraded"})


def test_demo_process_blocks_external_and_wrong_local_port_without_network_request() -> None:
    script = """
import socket
from jarvis_orchestrator.demo.safety import install_network_guard
install_network_guard("postgresql://localhost:55432/jarvis_demo_test")
for address in [("203.0.113.1", 443), ("127.0.0.1", 11434), ("127.0.0.1", 22)]:
    try:
        socket.create_connection(address, timeout=0.1)
    except PermissionError:
        pass
    else:
        raise AssertionError("DEMO egress guard did not deny connection")
print("denied")
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "denied"
