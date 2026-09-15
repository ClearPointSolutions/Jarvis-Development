"""Trusted, dedicated executor-host broker. Never mount its socket into a workload."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from jarvis_contracts.verification import ResolvedExecutionProfile
from jarvis_orchestrator.verification.isolation_contract import IsolationReceipt, IsolationRequest


class IsolationBroker:
    def __init__(
        self,
        docker: Path,
        image_id: str,
        receipts: Path,
        profiles: Mapping[str, ResolvedExecutionProfile] | None = None,
        *,
        preparation_network: str | None = None,
        registry_url: str | None = None,
    ) -> None:
        import re

        if not docker.is_absolute() or not docker.is_file():
            raise ValueError("broker requires a configured absolute Docker executable")
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id):
            raise ValueError("broker requires an immutable local image ID")
        self.docker, self.image_id, self.receipts = docker, image_id, receipts
        self.profiles = dict(profiles or {})
        self.preparation_network = preparation_network
        self.registry_url = registry_url
        receipts.mkdir(parents=True, exist_ok=True, mode=0o700)

    def prepare_dependencies(
        self, request: IsolationRequest, image_id: str
    ) -> tuple[str | None, str, str, bool]:
        profile = request.profile
        if profile is None or profile.spec.dependencies.manager == "none":
            return None, "", "", False
        policy = profile.spec.dependencies
        if policy.manager != "npm":
            raise ValueError("dependency manager is not available in this broker revision")
        if (
            profile.spec.network.preparation != "registry_allowlist"
            or not self.preparation_network
            or not self.registry_url
        ):
            raise ValueError("restricted dependency preparation is not configured")
        parsed = urlsplit(self.registry_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.hostname not in policy.registry_allowlist
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("dependency registry is outside the approved allowlist")
        key = request.execution_id.hex
        volume = "jarvis-deps-" + key
        label = "jarvis.dependency=" + str(request.dependency_digest)
        self.docker_command("volume", "create", "--label", label, volume)
        # Initialize only the broker-owned volume. No source or credential enters
        # this root helper and no Docker socket is mounted into either workload.
        self.docker_command(
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--cap-add",
            "CHOWN",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "16",
            "--memory",
            "128m",
            "--memory-swap",
            "128m",
            "--cpus",
            "1",
            "--mount",
            f"type=volume,source={volume},target=/dependencies",
            "--entrypoint",
            "/bin/sh",
            image_id,
            "-c",
            "chown 10001:10001 /dependencies",
        )
        bootstrap = Path(__file__).with_name("isolation_bootstrap.py").read_text(encoding="utf-8")
        payload = json.dumps(
            {
                "files": [file.model_dump() for file in request.files],
                "argv": (
                    "/usr/local/bin/npm",
                    "ci",
                    "--ignore-scripts",
                    "--no-audit",
                    "--no-fund",
                    "--cache",
                    "/work/npm-cache",
                ),
                "environment": {"NPM_CONFIG_REGISTRY": self.registry_url},
            }
        ).encode()
        resources = profile.spec.resources
        prepared = subprocess.run(
            (
                str(self.docker),
                "run",
                "--rm",
                "--name",
                "jarvis-prepare-" + key,
                "--label",
                label,
                "--network",
                self.preparation_network,
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                str(resources.pids),
                "--memory",
                f"{resources.memory_mb}m",
                "--memory-swap",
                f"{resources.memory_mb}m",
                "--cpus",
                str(resources.cpu_count),
                "--user",
                "10001:10001",
                "--workdir",
                "/work",
                "--tmpfs",
                f"/work:rw,nosuid,nodev,size={resources.workspace_mb}m,mode=1777",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,size=64m,mode=1777",
                "--mount",
                f"type=volume,source={volume},target=/work/project/node_modules",
                "--interactive",
                "--entrypoint",
                "/usr/local/bin/python",
                image_id,
                "-I",
                "-c",
                bootstrap,
            ),
            input=payload,
            capture_output=True,
            timeout=resources.timeout_seconds,
        )
        limit = resources.output_bytes
        truncated = len(prepared.stdout) > limit or len(prepared.stderr) > limit
        stdout = prepared.stdout[:limit].decode(errors="replace")
        stderr = prepared.stderr[:limit].decode(errors="replace")
        if prepared.returncode != 0 or truncated:
            self.docker_command("volume", "rm", "-f", volume)
            raise ValueError("dependency preparation failed or produced incomplete evidence")
        measured = self.docker_command(
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--mount",
            f"type=volume,source={volume},target=/dependencies,readonly",
            "--entrypoint",
            "/usr/bin/du",
            image_id,
            "-sm",
            "/dependencies",
        )
        try:
            dependency_mb = int(measured.split(maxsplit=1)[0])
        except (ValueError, IndexError):
            self.docker_command("volume", "rm", "-f", volume)
            raise ValueError("dependency cache size could not be verified") from None
        if dependency_mb > policy.cache_max_mb:
            self.docker_command("volume", "rm", "-f", volume)
            raise ValueError("dependency cache exceeds the approved bound")
        return volume, stdout, stderr, truncated

    def runtime(self, request: IsolationRequest) -> tuple[str, dict[str, tuple[str, ...]]]:
        if request.profile is None:
            return self.image_id, {
                "python": ("/usr/local/bin/python",),
                "pytest": ("/usr/local/bin/python", "-m", "pytest"),
            }
        configured = self.profiles.get(str(request.profile.revision_id))
        if configured is None or configured != request.profile:
            raise ValueError("execution profile is not approved by the broker")
        tools = {
            "python": ("/usr/local/bin/python",),
            "pytest": ("/usr/local/bin/python", "-m", "pytest"),
            "npm": ("/usr/local/bin/npm",),
            "node": ("/usr/local/bin/node",),
            "npx": ("/usr/local/bin/npx",),
            "vitest": ("/usr/local/bin/npx", "vitest"),
            "tsc": ("/usr/local/bin/npx", "tsc"),
            "next": ("/usr/local/bin/npx", "next"),
            "eslint": ("/usr/local/bin/npx", "eslint"),
            "playwright": ("/usr/local/bin/npx", "playwright"),
        }
        return configured.image_id, {
            key: value for key, value in tools.items() if key in configured.spec.supported_commands
        }

    def docker_command(self, *argv: str) -> bytes:
        return subprocess.run(
            (str(self.docker), *argv),
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout

    def cleanup_dependencies(self, request: IsolationRequest) -> None:
        if request.profile is None or request.profile.spec.dependencies.manager == "none":
            return
        volume = "jarvis-deps-" + request.execution_id.hex
        inspected = subprocess.run(
            (str(self.docker), "volume", "inspect", volume), capture_output=True, timeout=30
        )
        if inspected.returncode != 0:
            return
        state = json.loads(inspected.stdout)[0]
        expected = str(request.dependency_digest)
        if state.get("Labels", {}).get("jarvis.dependency") != expected:
            raise ValueError("dependency volume identity mismatch")
        self.docker_command("volume", "rm", "-f", volume)

    def cleanup_preparation(self, request: IsolationRequest) -> None:
        """Remove only the preparation container bound to this exact request."""
        if request.profile is None or request.profile.spec.dependencies.manager == "none":
            return
        name = "jarvis-prepare-" + request.execution_id.hex
        inspected = subprocess.run(
            (str(self.docker), "inspect", name), capture_output=True, timeout=30
        )
        if inspected.returncode != 0:
            return
        state = json.loads(inspected.stdout)[0]
        if state.get("Config", {}).get("Labels", {}).get("jarvis.dependency") != str(
            request.dependency_digest
        ):
            raise ValueError("dependency preparation identity mismatch")
        self.docker_command("rm", "-f", name)

    @staticmethod
    def immutable(path: Path, data: bytes) -> None:
        # Publish only complete bytes. A competing request cannot replace history.
        from uuid import uuid4

        temporary = path.with_name(path.name + "." + uuid4().hex)
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
                if sys.platform != "win32":
                    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
            except FileExistsError:
                if path.read_bytes() != data:
                    raise ValueError("immutable broker identity changed") from None
        finally:
            temporary.unlink(missing_ok=True)

    def execute(self, request: IsolationRequest) -> IsolationReceipt:
        with self.lock(request.execution_id.hex):
            return self._execute(request)

    def reap(self) -> int:
        """Enforce abandoned workload deadlines independently of Core liveness."""
        from uuid import UUID

        killed = 0
        for path in self.receipts.glob("*.intent.json"):
            key = path.name.removesuffix(".intent.json")
            if UUID(hex=key).hex != key or (self.receipts / (key + ".receipt.json")).exists():
                continue
            intent = json.loads(path.read_bytes())
            name = "jarvis-verify-" + key
            preparation_name = "jarvis-prepare-" + key
            preparation = self.docker_command(
                "ps", "-a", "--filter", "name=^/" + preparation_name + "$", "-q"
            )
            if preparation.strip():
                prep_state = json.loads(self.docker_command("inspect", preparation_name))[0]
                if prep_state["Config"]["Labels"].get("jarvis.dependency") != str(
                    intent.get("dependency_digest")
                ):
                    raise ValueError("dependency watchdog identity mismatch")
                started = datetime.fromisoformat(
                    prep_state["State"]["StartedAt"].replace("Z", "+00:00")
                )
                if (datetime.now(UTC) - started).total_seconds() > intent["timeout_seconds"]:
                    if prep_state["State"]["Running"]:
                        self.docker_command("kill", preparation_name)
                        killed += 1
                    self.docker_command("rm", preparation_name)
                    volume = "jarvis-deps-" + key
                    inspected = subprocess.run(
                        (str(self.docker), "volume", "inspect", volume),
                        capture_output=True,
                        timeout=30,
                    )
                    if inspected.returncode == 0:
                        volume_state = json.loads(inspected.stdout)[0]
                        if volume_state.get("Labels", {}).get("jarvis.dependency") != str(
                            intent.get("dependency_digest")
                        ):
                            raise ValueError("dependency volume watchdog identity mismatch")
                        self.docker_command("volume", "rm", "-f", volume)
            # List only the exact identity; never enumerate unrelated containers.
            exists = self.docker_command("ps", "-a", "--filter", "name=^/" + name + "$", "-q")
            if not exists.strip():
                continue
            state = json.loads(self.docker_command("inspect", name))[0]
            if (
                state["Image"] != intent["image_id"]
                or state["Config"]["Labels"].get("jarvis.verification") != intent["request_digest"]
            ):
                raise ValueError("executor watchdog identity mismatch")
            if not state["State"]["Running"]:
                continue
            started = datetime.fromisoformat(state["State"]["StartedAt"].replace("Z", "+00:00"))
            if (datetime.now(UTC) - started).total_seconds() > intent["timeout_seconds"]:
                self.immutable(
                    self.receipts / (key + ".timeout"), intent["request_digest"].encode()
                )
                self.docker_command("kill", name)
                killed += 1
        return killed

    @contextmanager
    def lock(self, key: str) -> Iterator[None]:
        with (self.receipts / (key + ".lock")).open("a+b") as stream:
            stream.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                stream.seek(0)
                if sys.platform == "win32":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def reconcile(self, request: IsolationRequest) -> IsolationReceipt:
        image_id, _tools = self.runtime(request)
        name = "jarvis-verify-" + request.execution_id.hex
        timeout_path = self.receipts / (request.execution_id.hex + ".timeout")
        while True:
            state = json.loads(self.docker_command("inspect", name))[0]
            if (
                state["Image"] != image_id
                or state["Config"]["Labels"].get("jarvis.verification") != request.digest
            ):
                raise ValueError("verification reconciliation identity mismatch")
            if state["State"]["Status"] == "exited":
                break
            if not state["State"]["Running"]:
                raise ValueError("verification launch requires explicit reconciliation")
            started = datetime.fromisoformat(state["State"]["StartedAt"].replace("Z", "+00:00"))
            if (datetime.now(UTC) - started).total_seconds() > request.command.timeout_seconds:
                self.immutable(timeout_path, request.digest.encode())
                self.docker_command("kill", name)
            else:
                time.sleep(0.1)
        # Daemon logs are bounded by the broker's fixed logging policy. When
        # recovering, conservatively mark output incomplete: rotation may have
        # removed earlier content. Never claim a complete stream after a crash.
        logs = subprocess.run(
            (str(self.docker), "logs", name), capture_output=True, check=True, timeout=30
        )
        limit = request.command.max_output_bytes
        receipt = IsolationReceipt(
            request_digest=request.digest,
            run_id=request.run_id,
            execution_id=request.execution_id,
            candidate_sha=request.candidate_sha,
            image_id=image_id,
            profile_digest=request.profile.profile_digest if request.profile else None,
            dependency_digest=request.dependency_digest,
            exit_code=state["State"]["ExitCode"],
            timed_out=timeout_path.exists(),
            stdout=logs.stdout[:limit].decode(errors="replace"),
            stderr=logs.stderr[:limit].decode(errors="replace"),
            stdout_truncated=True,
            stderr_truncated=True,
        )
        self.immutable(
            self.receipts / (request.execution_id.hex + ".receipt.json"),
            receipt.model_dump_json().encode(),
        )
        self.docker_command("rm", name)
        self.cleanup_dependencies(request)
        return receipt

    def _execute(self, request: IsolationRequest) -> IsolationReceipt:
        # Revalidate callers that bypassed Pydantic construction.
        request = IsolationRequest.model_validate(request.model_dump())
        image_id, tools = self.runtime(request)
        prefix = tools.get(request.command.argv[0])
        if prefix is None:
            raise ValueError("tool unavailable in the configured isolated Python profile")
        key = request.execution_id.hex
        receipt_path = self.receipts / (key + ".receipt.json")
        if receipt_path.exists():
            receipt = IsolationReceipt.model_validate_json(receipt_path.read_bytes())
            receipt.require(request, image_id)
            return receipt
        intent = json.dumps(
            {
                "request_digest": request.digest,
                "image_id": image_id,
                "timeout_seconds": request.command.timeout_seconds,
                "dependency_digest": request.dependency_digest,
            },
            sort_keys=True,
        ).encode()
        intent_path = self.receipts / (key + ".intent.json")
        if intent_path.exists():
            if intent_path.read_bytes() != intent:
                raise ValueError("verification intent identity mismatch")
            name = "jarvis-verify-" + key
            inspected = subprocess.run(
                (str(self.docker), "inspect", name), capture_output=True, timeout=30
            )
            if inspected.returncode == 0:
                state = json.loads(inspected.stdout)[0]
                if (
                    state["Image"] != image_id
                    or state["Config"]["Labels"].get("jarvis.verification") != request.digest
                ):
                    raise ValueError("verification reconciliation identity mismatch")
                if state["State"]["Status"] in {"running", "exited"}:
                    return self.reconcile(request)
                # A crash between create and start has no execution evidence. Remove
                # the exact never-started container and safely repeat preparation.
                if state["State"]["Status"] == "created":
                    self.docker_command("rm", name)
                else:
                    raise ValueError("verification launch requires explicit reconciliation")
            self.cleanup_preparation(request)
            self.cleanup_dependencies(request)
        else:
            self.immutable(intent_path, intent)
        try:
            dependency_volume, preparation_stdout, preparation_stderr, preparation_truncated = (
                self.prepare_dependencies(request, image_id)
            )
        except BaseException:
            self.cleanup_preparation(request)
            self.cleanup_dependencies(request)
            raise
        dependency_mount = (
            (
                "--mount",
                "type=volume,source="
                + dependency_volume
                + ",target=/work/project/node_modules,readonly",
            )
            if dependency_volume
            else ()
        )
        bootstrap = Path(__file__).with_name("isolation_bootstrap.py").read_text(encoding="utf-8")
        name = "jarvis-verify-" + key
        resources = request.profile.spec.resources if request.profile else None
        self.docker_command(
            "create",
            "--name",
            name,
            "--label",
            "jarvis.verification=" + request.digest,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(resources.pids if resources else 64),
            "--memory",
            f"{resources.memory_mb if resources else 256}m",
            "--memory-swap",
            f"{resources.memory_mb if resources else 256}m",
            "--cpus",
            str(resources.cpu_count if resources else 1),
            "--user",
            "10001:10001",
            "--workdir",
            "/work",
            "--tmpfs",
            f"/work:rw,nosuid,nodev,size={resources.workspace_mb if resources else 64}m,mode=1777",
            *dependency_mount,
            "--log-driver",
            "local",
            "--log-opt",
            "max-size=4m",
            "--log-opt",
            "max-file=1",
            "--log-opt",
            "compress=false",
            "--interactive",
            "--entrypoint",
            "/usr/local/bin/python",
            image_id,
            "-I",
            "-c",
            bootstrap,
        )
        payload = json.dumps(
            {
                "files": [file.model_dump() for file in request.files],
                "argv": (*prefix, *request.command.argv[1:]),
                "environment": request.command.environment,
            }
        ).encode()
        process = subprocess.Popen(
            (str(self.docker), "start", "--attach", "--interactive", name),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        output = [bytearray(), bytearray()]
        truncated = [False, False]
        limit = request.command.max_output_bytes

        def drain(index: int) -> None:
            stream = process.stdout if index == 0 else process.stderr
            assert stream is not None
            with stream:
                while chunk := stream.read(8192):
                    remaining = limit - len(output[index])
                    output[index].extend(chunk[:remaining])
                    truncated[index] |= len(chunk) > remaining

        def feed() -> None:
            assert process.stdin is not None
            try:
                with process.stdin:
                    process.stdin.write(payload)
            except BrokenPipeError:
                pass

        threads = [threading.Thread(target=drain, args=(i,), daemon=True) for i in range(2)]
        threads.append(threading.Thread(target=feed, daemon=True))
        for thread in threads:
            thread.start()
        timed_out = False
        try:
            process.wait(timeout=request.command.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            self.immutable(self.receipts / (key + ".timeout"), request.digest.encode())
            self.docker_command("kill", name)
            process.wait(timeout=15)
        finally:
            for thread in threads:
                thread.join(timeout=15)
        if any(thread.is_alive() for thread in threads):
            raise ValueError("verification transport outcome requires reconciliation")
        state = json.loads(self.docker_command("inspect", name))[0]
        if (
            state["State"]["Running"]
            or state["State"]["Status"] != "exited"
            or state["State"]["StartedAt"].startswith("0001-")
            or state["Image"] != image_id
            or state["Config"]["Labels"].get("jarvis.verification") != request.digest
        ):
            raise ValueError("verification container identity mismatch")
        receipt = IsolationReceipt(
            request_digest=request.digest,
            run_id=request.run_id,
            execution_id=request.execution_id,
            candidate_sha=request.candidate_sha,
            image_id=image_id,
            profile_digest=request.profile.profile_digest if request.profile else None,
            dependency_digest=request.dependency_digest,
            dependency_prepared=dependency_volume is not None,
            preparation_stdout=preparation_stdout,
            preparation_stderr=preparation_stderr,
            preparation_output_truncated=preparation_truncated,
            exit_code=state["State"]["ExitCode"],
            timed_out=timed_out or (self.receipts / (key + ".timeout")).exists(),
            stdout=output[0].decode(errors="replace"),
            stderr=output[1].decode(errors="replace"),
            stdout_truncated=truncated[0],
            stderr_truncated=truncated[1],
        )
        self.immutable(receipt_path, receipt.model_dump_json().encode())
        self.docker_command("rm", name)
        self.cleanup_dependencies(request)
        return receipt
