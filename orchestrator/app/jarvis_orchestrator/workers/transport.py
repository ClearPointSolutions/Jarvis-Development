"""Injectable SSH transport. Only explicitly configured hosts can be contacted."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from jarvis_contracts.enums import FailureClass
from jarvis_orchestrator.providers.worker_configuration import OpenHandsDeployment
from jarvis_orchestrator.workers.safety import WorkerBoundaryError


@dataclass(frozen=True)
class TransportResult:
    stdout: bytes
    stderr: bytes
    exit_code: int
    truncated: bool = False


class SSHTransport(Protocol):
    async def execute(self, command: str, *, timeout: float, limit: int) -> TransportResult: ...


@dataclass(frozen=True)
class SSHCredentials:
    private_key_file: Path = field(repr=False)
    known_hosts_file: Path = field(repr=False)


async def bounded_read(stream: asyncio.StreamReader, limit: int) -> tuple[bytes, bool]:
    chunks = bytearray()
    truncated = False
    while block := await stream.read(16384):
        remaining = max(0, limit - len(chunks))
        chunks.extend(block[:remaining])
        truncated |= len(block) > remaining
    return bytes(chunks), truncated


class OpenSSHTransport:
    """System OpenSSH validates the exact pinned host and fails without a pin.

    Ambient SSH config, agents, forwarding, proxy commands and interactive auth
    are disabled. Credentials are server-resolved files and never serialized.
    """

    def __init__(
        self,
        deployment: OpenHandsDeployment,
        credentials: SSHCredentials,
        *,
        allowed_hosts: frozenset[str],
        executable: str = "ssh",
    ) -> None:
        if deployment.host_alias not in allowed_hosts:
            raise WorkerBoundaryError("host_not_allowed", FailureClass.SECURITY_POLICY_DENIED)
        if not credentials.private_key_file.is_file() or not credentials.known_hosts_file.is_file():
            raise WorkerBoundaryError("ssh_credentials_unconfigured")
        self.deployment = deployment
        self.credentials = credentials
        self.executable = executable

    def argv(self, command: str) -> tuple[str, ...]:
        return (
            self.executable,
            "-F",
            "none",
            "-T",
            "-i",
            str(self.credentials.private_key_file),
            "-p",
            str(self.deployment.port),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={self.credentials.known_hosts_file}",
            "-o",
            "GlobalKnownHostsFile=none",
            "-o",
            "UpdateHostKeys=no",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "IdentityAgent=none",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "ProxyCommand=none",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "KbdInteractiveAuthentication=no",
            "-o",
            f"ConnectTimeout={self.deployment.timeouts.connect_seconds}",
            f"{self.deployment.user}@{self.deployment.host_alias}",
            command,
        )

    async def execute(self, command: str, *, timeout: float, limit: int) -> TransportResult:
        if not 0 < timeout <= 86400 or not 1024 <= limit <= 104857600:
            raise WorkerBoundaryError("transport_limits_invalid")
        try:
            process = await asyncio.create_subprocess_exec(
                *self.argv(command),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except NotImplementedError:
            # Psycopg requires Windows' SelectorEventLoop, which has no native
            # subprocess transport. Reuse the bounded process-group/Job Object
            # runner so cancellation still terminates our SSH process tree.
            from jarvis_orchestrator.verification.process import run_process

            result = await run_process(
                self.argv(command),
                cwd=self.credentials.private_key_file.parent,
                environment={
                    key: value
                    for key, value in os.environ.items()
                    if key.upper()
                    in {"PATH", "SYSTEMROOT", "TEMP", "TMP", "PROGRAMDATA", "COMSPEC"}
                },
                timeout=timeout,
                limit=limit,
            )
            if result.timed_out:
                raise WorkerBoundaryError(
                    "ssh_timeout", FailureClass.INFRASTRUCTURE_TIMEOUT
                ) from None
            if result.exit_code == 255:
                raise WorkerBoundaryError(
                    self.connection_error(result.stderr),
                    FailureClass.INFRASTRUCTURE_WORKER_TRANSPORT,
                ) from None
            if result.exit_code is None:
                raise WorkerBoundaryError("ssh_unavailable") from None
            return TransportResult(
                result.stdout,
                result.stderr,
                result.exit_code,
                result.stdout_truncated or result.stderr_truncated,
            )
        except OSError:
            raise WorkerBoundaryError(
                "ssh_unavailable", FailureClass.INFRASTRUCTURE_WORKER_TRANSPORT
            ) from None
        assert process.stdout is not None and process.stderr is not None
        readers = asyncio.gather(
            bounded_read(process.stdout, limit), bounded_read(process.stderr, limit)
        )
        try:
            async with asyncio.timeout(timeout):
                output = await asyncio.shield(readers)
                exit_code = await process.wait()
        except (TimeoutError, asyncio.CancelledError) as error:
            # This only ends our SSH client. Remote invocation still needs reconciliation.
            if process.returncode is None:
                process.kill()
            await process.wait()
            await readers
            if isinstance(error, asyncio.CancelledError):
                raise
            raise WorkerBoundaryError("ssh_timeout", FailureClass.INFRASTRUCTURE_TIMEOUT) from None
        stdout, stderr = output
        if exit_code == 255:
            raise WorkerBoundaryError(
                self.connection_error(stderr[0]), FailureClass.INFRASTRUCTURE_WORKER_TRANSPORT
            )
        return TransportResult(stdout[0], stderr[0], exit_code, stdout[1] or stderr[1])

    async def execute_input(
        self, command: str, data: bytes, *, timeout: float, limit: int
    ) -> TransportResult:
        from jarvis_orchestrator.verification.process import run_process

        if not 0 < timeout <= 86400 or not 1024 <= limit <= 104857600:
            raise WorkerBoundaryError("transport_limits_invalid")
        result = await run_process(
            self.argv(command),
            cwd=self.credentials.private_key_file.parent,
            environment={
                key: value
                for key, value in os.environ.items()
                if key.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP", "PROGRAMDATA", "COMSPEC"}
            },
            timeout=timeout,
            limit=limit,
            input_data=data,
        )
        if result.timed_out:
            raise WorkerBoundaryError("ssh_timeout", FailureClass.INFRASTRUCTURE_TIMEOUT)
        if result.exit_code in {None, 255}:
            raise WorkerBoundaryError(
                "ssh_unavailable", FailureClass.INFRASTRUCTURE_WORKER_TRANSPORT
            )
        return TransportResult(
            result.stdout,
            result.stderr,
            result.exit_code,
            result.stdout_truncated or result.stderr_truncated,
        )

    @staticmethod
    def connection_error(stderr: bytes) -> str:
        diagnostic = stderr.lower()
        if (
            b"host key verification failed" in diagnostic
            or b"host identification has changed" in diagnostic
        ):
            return "host_key_mismatch"
        if b"permission denied" in diagnostic:
            return "authentication_failed"
        return "host_unreachable"
