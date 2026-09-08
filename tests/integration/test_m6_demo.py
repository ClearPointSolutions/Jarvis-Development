"""M6 real PostgreSQL/API/compiler/effect/retry/decision vertical acceptance."""

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_orchestrator.demo.bootstrap import bootstrap_demo
from jarvis_orchestrator.runtime.service import OrchestratorService
from jarvis_persistence.checkpoints import postgres_saver
from jarvis_persistence.models import EventModel, ModelCallModel, RunLeaseModel, RunModel
from tests.integration.test_m2_integrated_api import IntegratedApi, login
from tests.integration.test_m2_integrated_api import integrated_api as integrated_api
from tests.integration.test_m5_effects import InjectedCrash
from tests.integration.test_m5_runtime import acquire

pytestmark = pytest.mark.integration


async def execute_fixture(
    integrated_api: IntegratedApi,
    session_factory: async_sessionmaker[AsyncSession],
    database_url: str,
    tmp_path: Path,
    scenario: str,
    decision: str,
    failure_class: str,
    crash: bool = False,
) -> tuple[object, ...]:
    api = integrated_api
    namespace = "demo-" + uuid7().hex
    from jarvis_api.errors import ApiProblemError

    try:
        doc = await bootstrap_demo(api.factory, api.owner_id, namespace=namespace)
    except ApiProblemError as error:
        raise AssertionError(error.details) from error
    duplicate = await bootstrap_demo(api.factory, api.owner_id, namespace=namespace)
    assert duplicate.version.id == doc.version.id
    headers = {"x-csrf-token": (await login(api)).json()["csrf_token"]}
    project = await api.client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "slug": f"demo-{uuid7().hex}",
            "name": "DEMO objective",
            "idempotency_key": str(uuid7()),
        },
    )
    assert project.status_code == 201, project.text
    queued = await api.client.post(
        f"/api/v1/projects/{project.json()['id']}/jobs",
        headers=headers,
        json={
            "workflow_version_id": str(doc.version.id),
            "objective": "Build a greeting fixture",
            "mode": "demo",
            "idempotency_key": str(uuid7()),
            "demo_fixture": {"delay_seconds": 0, "scenario": scenario},
        },
    )
    assert queued.status_code == 202, queued.text
    assert queued.json()["status"] == "queued"
    from uuid import UUID

    run_id = UUID(queued.json()["id"])
    async with postgres_saver(database_url, setup=True):
        pass
    owner, fence = await acquire(session_factory, run_id)
    if crash:

        def inject(point: str) -> None:
            if point == "after_dispatch_before_result":
                raise InjectedCrash()

        owner.fault = inject
        with pytest.raises(InjectedCrash):
            await OrchestratorService(
                database_url, owner, demo=True, artifact_root=tmp_path
            )._execute(fence)
        async with session_factory.begin() as session:
            lease = await session.scalar(
                select(RunLeaseModel).where(
                    RunLeaseModel.run_id == run_id, RunLeaseModel.generation == fence.generation
                )
            )
            assert lease is not None
            lease.expires_at = owner.clock.now() - timedelta(seconds=1)
        owner, fence = await acquire(session_factory, run_id)
    await OrchestratorService(database_url, owner, demo=True, artifact_root=tmp_path)._execute(
        fence
    )
    view = (await api.client.get(f"/api/v1/runs/{run_id}")).json()
    assert view["status"] == "approval_required", view
    tasks = (await api.client.get(f"/api/v1/runs/{run_id}/tasks")).json()["items"]
    assert [t["status"] for t in tasks] == ["succeeded", "succeeded"]
    expected_attempts = (
        ["failed", "succeeded"] if scenario in {"canonical", "review"} else ["succeeded"]
    )
    assert [a["status"] for a in tasks[0]["attempts"]] == expected_attempts
    wait = (await api.client.get(f"/api/v1/runs/{run_id}/demo-decision")).json()
    invalid = await api.client.post(
        f"/api/v1/runs/{run_id}/demo-decision",
        headers=headers,
        json={
            "decision_id": wait["id"],
            "decision": decision,
            "expected_run_version": view["version"] + 100,
            "idempotency_key": str(uuid7()),
        },
    )
    assert invalid.status_code == 409
    decided = await api.client.post(
        f"/api/v1/runs/{run_id}/demo-decision",
        headers=headers,
        json={
            "decision_id": wait["id"],
            "decision": decision,
            "expected_run_version": view["version"],
            "idempotency_key": str(uuid7()),
        },
    )
    assert decided.status_code == 202, decided.text
    replacement, resumed_fence = await acquire(session_factory, run_id)
    await OrchestratorService(
        database_url, replacement, demo=True, artifact_root=tmp_path
    )._execute(resumed_fence)
    async with session_factory() as session:
        run = await session.get(RunModel, run_id)
        assert run is not None and run.status == (
            "completed" if decision == "approved" else "cancelled"
        )
        assert run.langgraph_thread_id == view["thread_id"]
        events = (
            await session.scalars(
                select(EventModel)
                .where(EventModel.run_id == run_id)
                .order_by(EventModel.run_sequence)
            )
        ).all()
        assert all(e.mode == "demo" for e in events)
        assert sum(e.type == "task.created" for e in events) == 2
        calls = (
            await session.scalars(select(ModelCallModel).where(ModelCallModel.run_id == run_id))
        ).all()
        assert len(calls) == sum(e.type == "model.usage_recorded" for e in events)
        assert all(c.record_json["demo"] for c in calls) and len(calls) >= 5
        assert sum(e.type == "git.pr_created" for e in events) == (
            1 if decision == "approved" else 0
        )
        budgets = [e.data_json for e in events if e.type == "retry.budget_consumed"]
        assert len(budgets) == 1 and budgets[0]["failure_class"] == failure_class

        return (
            tuple(e.type for e in events),
            tuple(
                (t["key"], t["status"], tuple(a["status"] for a in t["attempts"])) for t in tasks
            ),
            tuple(b["failure_class"] for b in budgets),
            run.status,
            run.result_summary,
        )


@pytest.mark.parametrize(
    "scenario,decision,failure_class",
    [
        ("canonical", "approved", "code.test_failure"),
        ("canonical", "rejected", "code.test_failure"),
        ("infrastructure", "approved", "infrastructure.worker_transport"),
        ("review", "approved", "code.review_failure"),
        ("provider", "approved", "provider.transient"),
    ],
)
async def test_demo_uses_compiled_runtime_and_durable_decision(
    integrated_api: IntegratedApi,
    session_factory: async_sessionmaker[AsyncSession],
    database_url: str,
    tmp_path: Path,
    scenario: str,
    decision: str,
    failure_class: str,
) -> None:
    await execute_fixture(
        integrated_api, session_factory, database_url, tmp_path, scenario, decision, failure_class
    )


async def test_fixed_demo_runs_have_identical_normalized_history(
    integrated_api: IntegratedApi,
    session_factory: async_sessionmaker[AsyncSession],
    database_url: str,
    tmp_path: Path,
) -> None:
    first = await execute_fixture(
        integrated_api,
        session_factory,
        database_url,
        tmp_path,
        "canonical",
        "approved",
        "code.test_failure",
    )
    second = await execute_fixture(
        integrated_api,
        session_factory,
        database_url,
        tmp_path,
        "canonical",
        "approved",
        "code.test_failure",
    )
    assert first == second


async def test_demo_crash_after_effect_receipt_reconstructs_without_duplicate_work(
    integrated_api: IntegratedApi,
    session_factory: async_sessionmaker[AsyncSession],
    database_url: str,
    tmp_path: Path,
) -> None:
    await execute_fixture(
        integrated_api,
        session_factory,
        database_url,
        tmp_path,
        "canonical",
        "approved",
        "code.test_failure",
        crash=True,
    )


async def test_demo_artifact_boundary_redacts_synthetic_worker_output(
    integrated_api: IntegratedApi,
    session_factory: async_sessionmaker[AsyncSession],
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis_contracts.demo import DemoFixture
    from jarvis_orchestrator.demo import adapters
    from jarvis_orchestrator.demo.fixtures import repository_fixture as original

    canary = "sk-proj-" + "demo_synthetic_canary_" * 5

    def output(task: str, attempt: int, fixture: DemoFixture) -> dict[str, str]:
        return {**original(task, attempt, fixture), "output.txt": canary}

    monkeypatch.setattr(adapters, "repository_fixture", output)
    await execute_fixture(
        integrated_api,
        session_factory,
        database_url,
        tmp_path,
        "canonical",
        "approved",
        "code.test_failure",
    )
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert files and all(canary.encode() not in p.read_bytes() for p in files)
