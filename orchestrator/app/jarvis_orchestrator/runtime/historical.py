"""Historical workspace preparation inside the LangGraph worker effect boundary."""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
from pathlib import Path
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import select

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.workers import WorkerProject
from jarvis_orchestrator.providers.worker_configuration import OpenHandsDeployment
from jarvis_orchestrator.runtime.errors import RuntimeDependencyError
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership
from jarvis_orchestrator.workers.historical import HistoricalWorkspace
from jarvis_orchestrator.workers.safety import remote_stream_command
from jarvis_orchestrator.workers.source_transfer import MAX_BUNDLE_BYTES
from jarvis_orchestrator.workers.transport import OpenSSHTransport
from jarvis_orchestrator.workers.workspace import WorktreeManager
from jarvis_orchestrator.workers.wrapper import atomic_write
from jarvis_persistence.models import EventModel


class HistoricalPreparation:
    def __init__(
        self,
        owner: RunOwnership,
        fence: RunFence,
        deployment: OpenHandsDeployment,
        transport: OpenSSHTransport,
        source_root: Path,
        source: WorkerProject,
        target: WorkerProject,
        worker_revision_id: UUID,
        lifecycle: dict[str, JsonValue],
        *,
        git_executable: str,
        author_name: str,
        author_email: str,
    ) -> None:
        self.owner, self.fence, self.deployment, self.transport = (
            owner,
            fence,
            deployment,
            transport,
        )
        self.source_root, self.source, self.target = source_root, source, target
        self.worker_revision_id, self.lifecycle = worker_revision_id, lifecycle
        self.git_executable, self.author_name, self.author_email = (
            git_executable,
            author_name,
            author_email,
        )

    async def ensure(self) -> None:
        root = self.source_root / self.fence.run_id.hex
        root.mkdir(parents=True, exist_ok=True)
        path = root / "historical-seed.json"
        if path.exists():
            if path.stat().st_size > 26 * 1024 * 1024:
                raise RuntimeDependencyError("historical seed receipt exceeds bound")
            request = HistoricalWorkspace.model_validate_json(path.read_bytes())
            if (
                request.run_id != self.fence.run_id
                or request.target != self.target
                or request.source != self.source
            ):
                raise RuntimeDependencyError("historical seed identity changed")
        else:
            encoded, digest = None, None
            seed_store = self.lifecycle.get("seed_store_id")
            if seed_store is not None:
                manager = WorktreeManager(self.source_root, git_executable=self.git_executable)
                repository = self.source_root / UUID(str(seed_store)).hex / "repository"
                await manager.scalar(repository, "rev-parse", self.target.base_sha + "^{commit}")
                with tempfile.TemporaryDirectory(dir=root) as temporary:
                    bundle = Path(temporary) / "seed.bundle"
                    await manager.git(repository, "bundle", "create", str(bundle), "--all")
                    with bundle.open("rb") as stream:
                        content = stream.read(MAX_BUNDLE_BYTES + 1)
                    if len(content) > MAX_BUNDLE_BYTES:
                        raise RuntimeDependencyError(
                            "historical source history exceeds transfer limit"
                        )
                    encoded = base64.b64encode(content).decode("ascii")
                    digest = hashlib.sha256(content).hexdigest()
            request = HistoricalWorkspace(
                run_id=self.fence.run_id,
                worker_revision_id=self.worker_revision_id,
                source=self.source,
                target=self.target,
                bundle_base64=encoded,
                bundle_sha256=digest,
                author_name=self.author_name,
                author_email=self.author_email,
            )
            atomic_write(path, request.model_dump_json().encode())
        request_digest = sha256_digest(request)
        async with self.owner.fenced(self.fence) as (session, run):
            previous = await session.scalar(
                select(EventModel)
                .where(EventModel.run_id == run.id, EventModel.type == "worker.workspace_prepared")
                .limit(1)
            )
            if previous is not None:
                if previous.data_json.get("request_digest") != request_digest:
                    raise RuntimeDependencyError("historical workspace authority changed")
                return
        deployment = self.deployment
        if deployment.python_path is None or deployment.wrapper_path is None:
            raise RuntimeDependencyError("historical wrapper is unavailable")
        response = await self.transport.execute_input(
            remote_stream_command(deployment.python_path, deployment.wrapper_path),
            json.dumps(
                {
                    "operation": "prepare_historical",
                    "request": request.model_dump(mode="json"),
                    "workspace_root": deployment.workspace_root,
                    "invocation_root": deployment.invocation_root,
                }
            ).encode(),
            timeout=deployment.timeouts.connect_seconds + 60,
            limit=65536,
        )
        if response.exit_code or response.truncated:
            raise RuntimeDependencyError("historical workspace preparation requires reconciliation")
        result = json.loads(response.stdout)
        if result != {
            "request_digest": request_digest,
            "base_sha": self.target.base_sha,
            "workspace": self.target.workspace_root,
        }:
            raise RuntimeDependencyError("historical workspace receipt mismatch")
        async with self.owner.fenced(self.fence) as (session, run):
            await self.owner.event(session, run, "worker.workspace_prepared", result)
