"""Bounded local process execution with a private process group and environment.

The Windows gate waits for job assignment before it can launch repository code.
Closing that job kills its descendants. POSIX children use a new session.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int | None
    timed_out: bool
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool
    stderr_truncated: bool


def _run(
    argv: tuple[str, ...],
    cwd: Path,
    environment: Mapping[str, str],
    timeout: float,
    limit: int,
    cancel: threading.Event,
    input_data: bytes | None = None,
) -> ProcessResult:
    from contextlib import suppress

    job = None
    gate = Path(__file__).with_name("process_gate.py")
    launch = (sys.executable, "-I", str(gate)) if sys.platform == "win32" else argv
    process = subprocess.Popen(
        launch,
        cwd=cwd,
        env=dict(environment),
        stdin=subprocess.PIPE
        if sys.platform == "win32" or input_data is not None
        else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=sys.platform != "win32",
    )
    output = [bytearray(), bytearray()]
    truncated = [False, False]

    def drain(stream: BinaryIO, index: int) -> None:
        try:
            while chunk := stream.read(8192):
                remaining = limit - len(output[index])
                output[index].extend(chunk[:remaining])
                truncated[index] |= len(chunk) > remaining
        finally:
            stream.close()

    assert process.stdout is not None and process.stderr is not None
    readers = [
        threading.Thread(target=drain, args=(stream, index), daemon=True)
        for index, stream in enumerate((process.stdout, process.stderr))
    ]

    def feed() -> None:
        assert process.stdin is not None
        payload = input_data or b""
        if sys.platform == "win32":
            payload = (
                json.dumps(
                    {"argv": argv, "stdin_base64": base64.b64encode(payload).decode()}
                ).encode()
                + b"\n"
            )
        try:
            with process.stdin:
                process.stdin.write(payload)
        except BrokenPipeError:
            pass

    writer = threading.Thread(target=feed, daemon=True) if process.stdin is not None else None
    timed_out = False
    try:
        if sys.platform == "win32":
            from jarvis_orchestrator.verification.windows_job import WindowsJob

            job = WindowsJob(process.pid)
        for reader in readers:
            reader.start()
        if writer is not None:
            writer.start()
        deadline = time.monotonic() + timeout
        while process.poll() is None or any(reader.is_alive() for reader in readers):
            if cancel.is_set() or time.monotonic() >= deadline:
                timed_out = not cancel.is_set()
                break
            time.sleep(0.01)
    finally:
        if job is not None:
            job.close()
        elif sys.platform != "win32":
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        elif process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        for reader in readers:
            if reader.ident is not None:
                reader.join(timeout=5)
        if writer is not None and writer.ident is not None:
            writer.join(timeout=5)
        if any(reader.is_alive() for reader in readers):
            raise RuntimeError("verification process output could not be reconciled")
    return ProcessResult(
        process.returncode, timed_out, bytes(output[0]), bytes(output[1]), *truncated
    )


async def run_process(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout: float,
    limit: int,
    input_data: bytes | None = None,
) -> ProcessResult:
    if input_data is not None and len(input_data) > 26 * 1024 * 1024:
        raise ValueError("process input exceeds bound")
    cancel = threading.Event()
    pending = asyncio.create_task(
        asyncio.to_thread(_run, argv, cwd, environment, timeout, limit, cancel, input_data)
    )
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        cancel.set()
        await pending
        raise
