"""Explicit server-only bindings; building the registry never contacts a worker."""

from collections.abc import Callable, Mapping
from pathlib import Path
from uuid import UUID

from jarvis_contracts.registry import WorkerSpec
from jarvis_orchestrator.providers.worker_configuration import OpenHandsDeployment
from jarvis_orchestrator.runtime.ownership import RunFence, RunOwnership
from jarvis_orchestrator.workers.artifacts import WorkerContextReader, WorkerLogPublisher
from jarvis_orchestrator.workers.openhands import OpenHandsSSHAdapter
from jarvis_orchestrator.workers.registry import WorkerRuntimeRegistry
from jarvis_orchestrator.workers.runtime import RequestSource, WorkerEffectAdapter
from jarvis_orchestrator.workers.safety import WorkerBoundaryError
from jarvis_orchestrator.workers.transport import SSHTransport


def configured_worker_registry(
    deployments: Mapping[UUID, OpenHandsDeployment],
    transport_factory: Callable[[OpenHandsDeployment], SSHTransport],
    request_source: RequestSource,
    artifact_root: Path,
) -> WorkerRuntimeRegistry:
    """Bind immutable revisions to server-resolved transports and durable task input.

    The deployment catalog is not a browser contract. A production transport factory
    resolves key references to protected files and supplies an explicit host allowlist.
    Tests inject a local fake transport through exactly the same registration path.
    """
    catalog = dict(deployments)

    def build(
        owner: RunOwnership, fence: RunFence, revision_id: UUID, worker: WorkerSpec
    ) -> WorkerEffectAdapter:
        deployment = catalog.get(revision_id)
        if deployment is None or not worker.deployment_configured:
            raise WorkerBoundaryError("worker_deployment_unconfigured")
        return WorkerEffectAdapter(
            owner,
            fence,
            worker,
            OpenHandsSSHAdapter(
                worker,
                deployment,
                transport_factory(deployment),
                publish_log=WorkerLogPublisher(owner, fence, artifact_root),
                artifact_reader=WorkerContextReader(owner, fence, artifact_root),
            ),
            request_source,
        )

    return WorkerRuntimeRegistry({"openhands_ssh_v1": build})
