"""Normal process startup and authenticated enqueue against local protocol transports."""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import suppress
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from alembic import command as migration
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from uuid6 import uuid7

from jarvis_api.registry.service import RegistryService
from jarvis_api.workflows.service import WorkflowService
from jarvis_contracts.registry import RegistryWrite
from jarvis_contracts.workflow import WorkflowSpec
from jarvis_contracts.workflow_api import WorkflowCommand, WorkflowCreateRequest, WorkflowDraftWrite
from jarvis_orchestrator.demo.bootstrap import canonical_workflow
from jarvis_persistence.checkpoints import bootstrap as bootstrap_checkpoints
from jarvis_persistence.models import (
    EventModel,
    IntegrationHeadModel,
    RunConfigSnapshotModel,
    RunModel,
)
from tests.integration.test_m2_integrated_api import IntegratedApi, login
from tests.integration.test_m2_integrated_api import integrated_api as integrated_api
from tests.runtime_protocol_server import ProtocolHandler

pytestmark = pytest.mark.integration


@pytest.fixture
def database_url(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Normal startup must not claim unfinished runs left by crash tests."""
    parsed = make_url(database_url)
    name = "jarvis_entrypoint_" + uuid7().hex
    admin = create_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    url = parsed.set(database=name).render_as_string(hide_password=False)
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        monkeypatch.setenv("DATABASE_URL", url)
        migration.upgrade(Config("alembic.ini"), "head")
        asyncio.run(bootstrap_checkpoints())
        yield url
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.mark.parametrize("launch", ["process", "service"])
async def test_normal_real_entrypoint(
    integrated_api: IntegratedApi,
    session_factory: Any,
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    launch: str,
) -> None:
    fixture = os.environ.get("JARVIS_TEST_SSH_DIRECTORY")
    if not fixture:
        if os.environ.get("JARVIS_REQUIRE_REAL_ENTRYPOINT") == "1":
            pytest.fail("Mandatory real-entrypoint job requires provisioned SSH fixture")
        pytest.skip(
            "requires explicitly started disposable SSH fixture and JARVIS_TEST_SSH_DIRECTORY"
        )
    keys = Path(fixture).resolve()
    api = integrated_api
    server = ThreadingHTTPServer(("127.0.0.1", 0), ProtocolHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    namespace = "real-" + uuid7().hex
    # A fresh private checkout makes this acceptance repeatable without resetting
    # an earlier candidate or its durable invocation evidence.
    worker_root = "/workspaces/" + namespace
    base = (keys / "base-sha.txt").read_text().strip()
    for args in (
        ["git", "clone", "--no-checkout", "/workspaces/fixture", worker_root],
        ["git", "-C", worker_root, "checkout", "-B", "main", base],
        ["git", "-C", worker_root, "config", "user.name", "Fixture"],
        ["git", "-C", worker_root, "config", "user.email", "fixture@localhost"],
    ):
        await asyncio.to_thread(
            subprocess.run,
            [
                "docker",
                "exec",
                "--user",
                "10001:10001",
                os.environ.get("JARVIS_TEST_SSH_CONTAINER", "jarvis-v1-mvp-test-worker"),
                *args,
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
    registry = RegistryService(api.factory, allowed_endpoints=(endpoint,))
    refs: dict[str, str] = {}

    async def record(key: str, spec: dict[str, Any]) -> None:
        body = RegistryWrite.model_validate(
            {
                "key": namespace + "-" + key,
                "display_name": "Protocol fixture " + key,
                "spec": spec,
                "idempotency_key": namespace + key,
            }
        )
        result = await registry.write(
            body.spec.kind, body, actor_id=api.owner_id, correlation_id=namespace
        )
        refs[key] = str(result.revision_id)

    try:
        await record(
            "provider",
            {"kind": "provider_connection", "provider_kind": "ollama", "base_url": endpoint},
        )
        for key, purposes in (
            ("profile", ["organizer", "architect", "reviewer"]),
            ("developer", ["developer"]),
        ):
            await record(
                key,
                {
                    "kind": "model_profile",
                    "provider_revision_id": refs["provider"],
                    "model_identifier": "protocol-fixture:1",
                    "purposes": purposes,
                    "capabilities": ["chat", "structured_json"],
                    "structured_json": True,
                    "context_limit": 65536,
                    "output_limit": 4096,
                },
            )
        await record(
            "worker",
            {
                "kind": "worker",
                "adapter_kind": "openhands_ssh_v1",
                "execution_host_label": "Disposable loopback fixture",
                "capabilities": ["code", "git", "tests"],
                "model_binding": {
                    "mode": "worker_managed",
                    "allowed_profile_revision_ids": [refs["developer"]],
                },
                "deployment_configured": True,
            },
        )
        await record(
            "retry",
            {
                "kind": "retry_policy",
                "rules": [
                    {
                        "failure_class": value,
                        "max_retries": 2,
                        "initial_delay_ms": 0,
                        "max_delay_ms": 0,
                        "jitter": "none",
                        "exhaustion_action": "fail",
                    }
                    for value in [
                        "code.test_failure",
                        "code.review_failure",
                        "infrastructure.worker_transport",
                        "provider.transient",
                    ]
                ],
            },
        )
        await record(
            "permission",
            {
                "kind": "permission_policy",
                "allowed_capabilities": ["code", "git", "tests"],
                "git": "allow",
                "shell": "allow",
            },
        )
        await record(
            "route",
            {
                "kind": "route_policy",
                "purposes": ["organizer", "architect", "reviewer"],
                "allow_unknown_health": True,
                "candidates": [{"profile_revision_id": refs["profile"]}],
            },
        )
        await record(
            "worker_route",
            {
                "kind": "route_policy",
                "purposes": ["developer"],
                "allow_unknown_health": True,
                "candidates": [{"profile_revision_id": refs["developer"]}],
            },
        )
        # The local-only graph ends after the serialized integration gates.
        raw = canonical_workflow(refs).model_dump(mode="json", by_alias=True)
        removed = {"final_verify", "final_review", "decision", "publish", "rejected"}
        raw["nodes"] = [n for n in raw["nodes"] if n["id"] not in removed]
        raw["edges"] = [
            e for e in raw["edges"] if e["from"] not in removed and e["to"] not in removed
        ]
        raw["edges"].append(
            {
                "id": "all-done",
                "from": "dispatch",
                "to": "finish",
                "kind": "on_result",
                "fallback": True,
                "priority": 1,
            }
        )
        raw["defaults"]["timeout_seconds"] = 120
        raw["key"], raw["name"] = namespace, "Real local protocol acceptance"
        for n in raw["nodes"]:
            n["label"] = n["id"]
            if n["id"] == "developer":
                n["policy"]["model_route_ref"] = refs["worker_route"]
        workflow = WorkflowService(api.factory, registry)
        doc = await workflow.create(
            WorkflowCreateRequest(
                key=namespace, name="Real local acceptance", idempotency_key=namespace
            ),
            api.owner_id,
            namespace,
        )
        doc = await workflow.save(
            doc.template.id,
            WorkflowDraftWrite(
                expected_version=doc.template.version,
                idempotency_key=namespace + "-save",
                spec=WorkflowSpec.model_validate(raw),
            ),
            api.owner_id,
            namespace,
        )
        doc = await workflow.publish(
            doc.template.id,
            WorkflowCommand(
                expected_version=doc.template.version, idempotency_key=namespace + "-publish"
            ),
            api.owner_id,
            namespace,
        )
        historical_key = namespace + "-history"
        historical_doc = await workflow.create(
            WorkflowCreateRequest(
                key=historical_key,
                name="Historical local acceptance",
                idempotency_key=historical_key,
            ),
            api.owner_id,
            historical_key,
        )
        historical_doc = await workflow.save(
            historical_doc.template.id,
            WorkflowDraftWrite(
                expected_version=historical_doc.template.version,
                idempotency_key=historical_key + "-save",
                spec=WorkflowSpec.model_validate({**raw, "key": historical_key}),
            ),
            api.owner_id,
            historical_key,
        )
        historical_doc = await workflow.publish(
            historical_doc.template.id,
            WorkflowCommand(
                expected_version=historical_doc.template.version,
                idempotency_key=historical_key + "-publish",
            ),
            api.owner_id,
            historical_key,
        )
        headers = {"x-csrf-token": (await login(api)).json()["csrf_token"]}
        project = await api.client.post(
            "/api/v1/projects",
            headers=headers,
            json={
                "slug": namespace,
                "name": "Real process acceptance",
                "idempotency_key": namespace,
            },
        )
        assert project.status_code == 201, project.text
        image = os.environ.get("JARVIS_TEST_ISOLATION_IMAGE", "jarvis-v1-verification:local")
        image_id = json.loads(subprocess.check_output(["docker", "image", "inspect", image]))[0][
            "Id"
        ]
        broker_config = tmp_path / "broker.json"
        broker_config.write_text(
            json.dumps(
                {
                    "docker_executable": shutil.which("docker"),
                    "image_id": image_id,
                    "receipt_root": str(tmp_path / "verification-receipts"),
                }
            )
        )
        manifest: dict[str, Any] = {
            "verification_isolation": {
                "broker_argv": [
                    sys.executable,
                    "-m",
                    "jarvis_orchestrator.verification.isolation_cli",
                    "--config",
                    str(broker_config),
                ],
                "image_id": image_id,
            },
            "providers": {"allowed_endpoints": [endpoint]},
            "workers": {
                refs["worker"]: {
                    "host_alias": "127.0.0.1",
                    "port": int(os.environ.get("JARVIS_TEST_SSH_PORT", "22239")),
                    "user": "jarvis",
                    "ssh_key_ref": "secret:fixture-key",
                    "host_key_ref": "secret:fixture-pin",
                    "workspace_root": "/workspaces",
                    "invocation_root": "/invocations",
                    "runner_path": "/fixture/runner.py",
                    "venv_activate": "/usr/local/bin/python",
                    "python_path": "/usr/local/bin/python",
                    "runner_python_path": "/usr/local/bin/python",
                    "wrapper_path": "/fixture/wrapper.py",
                }
            },
            "credential_files": {
                "secret:fixture-key": str(keys / "client_key"),
                "secret:fixture-pin": str(keys / "known_hosts"),
            },
            "allowed_worker_hosts": ["127.0.0.1"],
            "workflows": {
                str(doc.version.id): {
                    "worker_revision_id": refs["worker"],
                    "project": {
                        "project_id": project.json()["id"],
                        "repository_id": str(uuid7()),
                        "slug": namespace,
                        "workspace_root": worker_root,
                        "branch": "main",
                        "base_sha": (keys / "base-sha.txt").read_text().strip(),
                    },
                    "combined_commands": [
                        {
                            "argv": ["python", "-m", "pytest", "-q"],
                            "parser": "pytest",
                            "timeout_seconds": 30,
                        }
                    ],
                }
            },
            # Keep Git worktree paths within Windows' legacy path limit.
            "source_root": tempfile.mkdtemp(prefix="jarvis-src-"),
            "executables": {"python": [sys.executable]},
            "executable_path": str(Path(sys.executable).parent),
            "git_executable": shutil.which("git"),
            "ssh_executable": shutil.which("ssh"),
            "git_author_name": "Fixture",
            "git_author_email": "fixture@localhost",
        }
        manifest["workflows"][str(historical_doc.version.id)] = {
            **manifest["workflows"][str(doc.version.id)],
            "base_policy": "historical",
        }
        path = tmp_path / "runtime.json"
        path.write_text(json.dumps(manifest))
        env = {
            **os.environ,
            "DATABASE_URL": database_url,
            "JARVIS_ORCHESTRATOR_RUNTIME_MODE": "real",
            "JARVIS_ORCHESTRATOR_RUNTIME_FILE": str(path),
            "JARVIS_ORCHESTRATOR_MAX_CONCURRENCY": "1",
            "JARVIS_ORCHESTRATOR_GLOBAL_CONCURRENCY": "1",
            "JARVIS_ARTIFACT_ROOT": str(api.settings.artifact_root),
        }
        queued = await api.client.post(
            f"/api/v1/projects/{project.json()['id']}/jobs",
            headers=headers,
            json={
                "workflow_version_id": str(doc.version.id),
                "objective": "Implement answer 42 with passing pytest tests",
                "mode": "real",
                "idempotency_key": namespace,
            },
        )
        assert queued.status_code == 202, queued.text
        run_id = queued.json()["id"]
        with (tmp_path / "orchestrator.log").open("wb") as log:
            process = None
            serving = None
            if launch == "process":
                process = subprocess.Popen(
                    [sys.executable, "-m", "jarvis_orchestrator.main"],
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            else:
                # Exercise the same normal composition entrypoint in-process as
                # well: Windows TerminateProcess cannot flush child coverage.
                from jarvis_orchestrator.main import serve

                for key, value in env.items():
                    monkeypatch.setenv(key, value)
                serving = asyncio.create_task(serve())
            try:
                for _ in range(300):
                    await asyncio.sleep(1)
                    run = (await api.client.get(f"/api/v1/runs/{run_id}")).json()
                    if (
                        run.get("status") in {"completed", "failed", "blocked", "cancelled"}
                        or (process is not None and process.poll() is not None)
                        or (serving is not None and serving.done())
                    ):
                        break
                assert run.get("status") == "completed", (
                    run,
                    (tmp_path / "orchestrator.log").read_text()[-4000:],
                )
                extension = await api.client.post(
                    f"/api/v1/projects/{project.json()['id']}/jobs",
                    headers=headers,
                    json={
                        "workflow_version_id": str(doc.version.id),
                        "objective": "Extend completed project with BONUS equal to 43",
                        "mode": "real",
                        "idempotency_key": namespace + "-extension",
                    },
                )
                assert extension.status_code == 202
                extension_id = extension.json()["id"]
                for _ in range(300):
                    await asyncio.sleep(1)
                    extension_run = (await api.client.get(f"/api/v1/runs/{extension_id}")).json()
                    if extension_run["status"] in {"completed", "failed", "blocked"}:
                        break
                assert extension_run["status"] == "completed", extension_run
                worker_git = [
                    "docker",
                    "exec",
                    "--user",
                    "10001:10001",
                    os.environ.get("JARVIS_TEST_SSH_CONTAINER", "jarvis-v1-mvp-test-worker"),
                    "git",
                    "-C",
                    worker_root,
                    "rev-parse",
                    "HEAD",
                ]
                shared_head = subprocess.check_output(worker_git)
                historical_run = await api.client.post(
                    f"/api/v1/projects/{project.json()['id']}/jobs",
                    headers=headers,
                    json={
                        "workflow_version_id": str(historical_doc.version.id),
                        "objective": "Rebuild answer from the explicit historical base",
                        "mode": "real",
                        "idempotency_key": namespace + "-historical",
                    },
                )
                assert historical_run.status_code == 202
                historical_id = historical_run.json()["id"]
                for _ in range(300):
                    await asyncio.sleep(1)
                    historical_state = (
                        await api.client.get(f"/api/v1/runs/{historical_id}")
                    ).json()
                    if historical_state["status"] in {"completed", "failed", "blocked"}:
                        break
                assert historical_state["status"] == "completed", historical_state
                assert subprocess.check_output(worker_git) == shared_head
                wrong_project = await api.client.post(
                    "/api/v1/projects",
                    headers=headers,
                    json={
                        "slug": namespace + "-other",
                        "name": "Different project",
                        "idempotency_key": namespace + "-other",
                    },
                )
                assert wrong_project.status_code == 201
                rejected = await api.client.post(
                    f"/api/v1/projects/{wrong_project.json()['id']}/jobs",
                    headers=headers,
                    json={
                        "workflow_version_id": str(doc.version.id),
                        "objective": "Must never dispatch",
                        "mode": "real",
                        "idempotency_key": namespace + "-wrong-project",
                    },
                )
                assert rejected.status_code == 202
                rejected_id = rejected.json()["id"]
                for _ in range(30):
                    await asyncio.sleep(1)
                    rejected_run = (await api.client.get(f"/api/v1/runs/{rejected_id}")).json()
                    if rejected_run["status"] == "blocked":
                        break
                assert rejected_run["status"] == "blocked"
                async with session_factory() as session:
                    rejected_events = (
                        await session.scalars(
                            select(EventModel).where(EventModel.run_id == rejected_id)
                        )
                    ).all()
                    assert not {"model.call_started", "worker.invocation_dispatched"}.intersection(
                        event.type for event in rejected_events
                    )
            finally:
                if process is not None:
                    process.terminate()
                    await asyncio.to_thread(process.wait, timeout=15)
                if serving is not None:
                    serving.cancel()
                    with suppress(asyncio.CancelledError):
                        await serving
        async with session_factory() as session:
            events = (
                await session.scalars(select(EventModel).where(EventModel.run_id == run_id))
            ).all()
            types = [e.type for e in events]
            assert "test.failed" in types
            passing_reviews = [
                event
                for event in events
                if event.type == "review.completed"
                and event.data_json.get("verdict") == "PASS"
                and event.data_json.get("valid") is True
            ]
            assert len(passing_reviews) == 1
            assert "git.integration_completed" in types
            failures = [event for event in events if event.type == "failure.classified"]
            assert [event.data_json["class"] for event in failures] == ["code.test_failure"]
            attempts = [event for event in events if event.type == "task.attempt_started"]
            assert sorted(event.data_json["attempt"] for event in attempts) == [1, 2]
            model_calls = [event for event in events if event.type == "model.call_completed"]
            assert len(model_calls) == 3
            assert all(
                event.data_json["profile_revision_id"] == refs["profile"] for event in model_calls
            )
            assert refs["profile"] != refs["developer"]
            assert "run.completed" in types
            assert types.count("run.configuration_bound") == 1
            original_run = await session.get(RunModel, UUID(run_id))
            extended_run = await session.get(RunModel, UUID(extension_id))
            assert original_run is not None and extended_run is not None
            original_config = await session.get(
                RunConfigSnapshotModel, original_run.config_snapshot_id
            )
            extended_config = await session.get(
                RunConfigSnapshotModel, extended_run.config_snapshot_id
            )
            assert original_config is not None and extended_config is not None
            first_source = original_config.effective_spec_json["repository_binding"]["lifecycle"]
            second_source = extended_config.effective_spec_json["repository_binding"]["lifecycle"]
            assert second_source["previous_run_id"] == run_id
            assert second_source["source_store_id"] == first_source["source_store_id"]
            original_head = await session.scalar(
                select(IntegrationHeadModel).where(IntegrationHeadModel.run_id == run_id)
            )
            extended_head = await session.scalar(
                select(IntegrationHeadModel).where(IntegrationHeadModel.run_id == extension_id)
            )
            assert original_head is not None and extended_head is not None
            assert second_source["integration_base_sha"] == original_head.head_sha
            repository = (
                Path(manifest["source_root"])
                / UUID(first_source["source_store_id"]).hex
                / "repository"
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository),
                    "merge-base",
                    "--is-ancestor",
                    original_head.head_sha,
                    extended_head.head_sha,
                ],
                check=True,
            )
            answer = subprocess.check_output(
                ["git", "-C", str(repository), "show", extended_head.head_sha + ":answer.py"]
            )
            bonus = subprocess.check_output(
                ["git", "-C", str(repository), "show", extended_head.head_sha + ":bonus.py"]
            )
            assert answer == b"ANSWER = 42\n" and b"ANSWER + 1" in bonus
            historical_record = await session.get(RunModel, UUID(historical_id))
            assert historical_record is not None
            historical_config = await session.get(
                RunConfigSnapshotModel, historical_record.config_snapshot_id
            )
            assert historical_config is not None
            historical_source = historical_config.effective_spec_json["repository_binding"][
                "lifecycle"
            ]
            assert historical_source["policy"] == "historical"
            assert historical_source["worker_base_sha"] == base
            assert historical_source["source_store_id"] != first_source["source_store_id"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
