"""Trusted, dedicated executor-host broker. Never mount its socket into a workload."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from jarvis_orchestrator.verification.isolation_contract import IsolationReceipt, IsolationRequest


class IsolationBroker:
    def __init__(self, docker: Path, image_id: str, receipts: Path) -> None:
        import re

        if not docker.is_absolute() or not docker.is_file():
            raise ValueError("broker requires a configured absolute Docker executable")
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id):
            raise ValueError("broker requires an immutable local image ID")
        self.docker, self.image_id, self.receipts = docker, image_id, receipts
        receipts.mkdir(parents=True, exist_ok=True, mode=0o700)

    def docker_command(self, *argv: str) -> bytes:
        return subprocess.run(
            (str(self.docker), *argv),
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout

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
        name = "jarvis-verify-" + request.execution_id.hex
        timeout_path = self.receipts / (request.execution_id.hex + ".timeout")
        while True:
            state = json.loads(self.docker_command("inspect", name))[0]
            if (
                state["Image"] != self.image_id
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
            image_id=self.image_id,
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
        return receipt

    def _execute(self, request: IsolationRequest) -> IsolationReceipt:
        # Revalidate callers that bypassed Pydantic construction.
        request = IsolationRequest.model_validate(request.model_dump())
        tools = {
            "python": ("/usr/local/bin/python",),
            "pytest": ("/usr/local/bin/python", "-m", "pytest"),
        }
        prefix = tools.get(request.command.argv[0])
        if prefix is None:
            raise ValueError("tool unavailable in the configured isolated Python profile")
        key = request.execution_id.hex
        receipt_path = self.receipts / (key + ".receipt.json")
        if receipt_path.exists():
            receipt = IsolationReceipt.model_validate_json(receipt_path.read_bytes())
            receipt.require(request, self.image_id)
            return receipt
        intent = json.dumps(
            {
                "request_digest": request.digest,
                "image_id": self.image_id,
                "timeout_seconds": request.command.timeout_seconds,
            },
            sort_keys=True,
        ).encode()
        intent_path = self.receipts / (key + ".intent.json")
        if intent_path.exists():
            if intent_path.read_bytes() != intent:
                raise ValueError("verification intent identity mismatch")
            return self.reconcile(request)
        self.immutable(intent_path, intent)
        bootstrap = Path(__file__).with_name("isolation_bootstrap.py").read_text(encoding="utf-8")
        name = "jarvis-verify-" + key
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
            "64",
            "--memory",
            "256m",
            "--memory-swap",
            "256m",
            "--cpus",
            "1",
            "--user",
            "10001:10001",
            "--workdir",
            "/work",
            "--tmpfs",
            "/work:rw,nosuid,nodev,size=64m,mode=1777",
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
            self.image_id,
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
            or state["Image"] != self.image_id
            or state["Config"]["Labels"].get("jarvis.verification") != request.digest
        ):
            raise ValueError("verification container identity mismatch")
        receipt = IsolationReceipt(
            request_digest=request.digest,
            run_id=request.run_id,
            execution_id=request.execution_id,
            candidate_sha=request.candidate_sha,
            image_id=self.image_id,
            exit_code=state["State"]["ExitCode"],
            timed_out=timed_out or (self.receipts / (key + ".timeout")).exists(),
            stdout=output[0].decode(errors="replace"),
            stderr=output[1].decode(errors="replace"),
            stdout_truncated=truncated[0],
            stderr_truncated=truncated[1],
        )
        self.immutable(receipt_path, receipt.model_dump_json().encode())
        self.docker_command("rm", name)
        return receipt
