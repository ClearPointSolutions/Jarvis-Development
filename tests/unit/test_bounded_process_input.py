"""Actual bounded stdin delivery, including the Windows job-assignment gate."""

import hashlib
import os
import sys
from pathlib import Path

from jarvis_orchestrator.verification.process import run_process


async def test_bounded_process_preserves_binary_stdin(tmp_path: Path) -> None:
    data = bytes(range(256)) * 256
    result = await run_process(
        (
            sys.executable,
            "-c",
            "import sys,hashlib; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())",
        ),
        cwd=tmp_path,
        environment=os.environ,
        timeout=10,
        limit=1024,
        input_data=data,
    )
    assert result.exit_code == 0 and not result.timed_out
    assert result.stdout.strip().decode() == hashlib.sha256(data).hexdigest()


async def test_unread_stdin_does_not_bypass_timeout(tmp_path: Path) -> None:
    result = await run_process(
        (sys.executable, "-c", "import time; time.sleep(60)"),
        cwd=tmp_path,
        environment=os.environ,
        timeout=1,
        limit=1024,
        input_data=b"x" * 1048576,
    )
    assert result.timed_out and result.exit_code != 0
