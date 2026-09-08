"""Fail-closed demo construction and local-only process networking."""

from __future__ import annotations

import ipaddress
import sys
from typing import Any

from sqlalchemy.engine import make_url

from jarvis_contracts.registry import ProviderSpec, WorkerSpec
from jarvis_contracts.workflow_api import WorkflowResolvedSnapshot


def validate_demo_snapshot(snapshot: WorkflowResolvedSnapshot) -> None:
    for revision in snapshot.revisions:
        spec = revision.spec
        if isinstance(spec, ProviderSpec) and (
            spec.provider_kind != "demo" or spec.base_url is not None
        ):
            raise ValueError("DEMO refuses production provider revisions")
        if isinstance(spec, WorkerSpec) and (
            spec.adapter_kind != "demo" or spec.deployment_configured
        ):
            raise ValueError("DEMO refuses production worker revisions")


def local_database_port(url: str) -> int:
    parsed = make_url(url)
    if set(parsed.query) - {"options"} or parsed.query.get("options") not in {
        None,
        "-c role=jarvis_v1_api",
        "-c role=jarvis_v1_orchestrator",
    }:
        raise ValueError("DEMO refuses database transport overrides")
    if parsed.host not in {"127.0.0.1", "::1", "localhost"} or not (
        parsed.database or ""
    ).startswith(("jarvis_demo_", "jarvis_m2_browser_", "jarvis_v1_test")):
        raise ValueError("DEMO requires an explicitly named disposable loopback database")
    return parsed.port or 5432


def install_network_guard(url: str) -> None:
    """Irreversible process guard: only the configured local PostgreSQL port.

    Applies to Python socket clients, including provider clients. Demo startup
    also disables native transports by construction; no shell or SSH is bound.
    This is an application audit guard, not an OS sandbox for arbitrary code.
    """
    port = local_database_port(url)

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event in {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"}:
            raise PermissionError("DEMO cannot launch external programs")
        if event == "socket.getaddrinfo" and args[0] not in {"localhost", "127.0.0.1", "::1"}:
            raise PermissionError("DEMO denies external name resolution")
        if event == "socket.sendto":
            raise PermissionError("DEMO denies outbound datagrams")
        if event == "socket.connect":
            address = args[1]
            if not isinstance(address, tuple) or len(address) < 2:
                raise PermissionError("DEMO denies non-IP outbound connections")
            host, destination = address[:2]
            try:
                local = ipaddress.ip_address(host).is_loopback
            except ValueError:
                local = host == "localhost"
            if not local or destination != port:
                raise PermissionError("DEMO permits only the configured local database")

    sys.addaudithook(audit)
