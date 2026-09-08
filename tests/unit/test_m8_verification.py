"""Local verification process, parser and input boundary acceptance."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from jarvis_contracts.verification import ParserKind, VerificationCommand
from jarvis_orchestrator.verification.executor import ConfirmedRepository, VerificationExecutor
from jarvis_orchestrator.verification.legacy import normalize_legacy
from jarvis_orchestrator.verification.parsers import parse_output
from jarvis_orchestrator.verification.process import run_process
from jarvis_orchestrator.workers.safety import WorkerBoundaryError
from jarvis_orchestrator.workers.workspace import WorktreeManager


@pytest.mark.parametrize("root", ["/app", "/workspace", "/project", "/repo", "..", "/sibling"])
def test_no_caller_selected_cwd(root: str) -> None:
    with pytest.raises(ValidationError):
        VerificationCommand.model_validate({"argv": ["python", "-m", "pytest"], "cwd": root})


@pytest.mark.parametrize("program", ["bash", "sh", "cmd", "powershell", "cd", "/usr/bin/python"])
def test_shell_and_absolute_executable_denied(program: str) -> None:
    with pytest.raises(ValidationError):
        VerificationCommand(argv=(program, "something"))


@pytest.mark.parametrize("key", ["PATH", "HOME", "OPENAI_API_KEY", "GITHUB_TOKEN", "PYTHONPATH"])
def test_environment_cannot_select_credentials_or_search_paths(key: str) -> None:
    with pytest.raises(ValidationError):
        VerificationCommand.model_validate({"argv": ["pytest"], "environment": {key: "1"}})


@pytest.mark.parametrize("root", ["/app", "/workspace", "/project", "/repo"])
def test_exact_legacy_correction(root: str) -> None:
    correction = normalize_legacy(f"cd {root} && python -m pytest")
    assert correction.removed_prefix == f"cd {root} && "
    assert correction.command.argv == ("python", "-m", "pytest")
    assert len(correction.original_digest) == 64


@pytest.mark.parametrize(
    "command",
    [
        "cd /other && pytest",
        "cd /workspaces && pytest",
        "cd /app && cd ..",
        "cd /app && pytest; id",
        "cd /app && $(id)",
    ],
)
def test_legacy_does_not_accept_path_manipulation(command: str) -> None:
    with pytest.raises(ValueError):
        normalize_legacy(command)


@pytest.mark.parametrize(
    ("kind", "output", "field", "count"),
    [
        ("pytest", "=== 8 passed, 2 failed, 1 skipped in 1.0s ===", "failed", 2),
        ("vitest", "Tests  1 failed | 9 passed (10)", "passed", 9),
        ("typescript", "file.ts(1,1): error TS1000: bad", "errors", 1),
        ("ruff", "Found 3 errors.", "errors", 3),
        ("eslint", "3 problems (2 errors, 1 warning)", "errors", 2),
        ("mypy", "Success: no issues found in 5 source files", "errors", 0),
    ],
)
def test_parser_summaries(kind: ParserKind, output: str, field: str, count: int) -> None:
    parsed = parse_output(kind, output, 1)
    assert getattr(parsed, field) == count
    assert parsed.confidence == "summary"


def test_parser_fallback_and_ansi_remain_data() -> None:
    parsed = parse_output("next", "\x1b[31mFailed to compile.\x1b[0m", 1)
    assert parsed.confidence == "exit_code"
    assert "1" in parsed.summary


def environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key in {"SystemRoot", "SYSTEMROOT"}}


async def test_process_bounds_and_exit(tmp_path: Path) -> None:
    result = await run_process(
        (
            sys.executable,
            "-c",
            "import sys; print('x'*20000); sys.stderr.write('bad'); sys.exit(3)",
        ),
        cwd=tmp_path,
        environment=environment(),
        timeout=10,
        limit=1024,
    )
    assert result.exit_code == 3
    assert result.stdout_truncated and len(result.stdout) == 1024
    assert result.stderr == b"bad"
    assert not result.timed_out


async def test_process_timeout(tmp_path: Path) -> None:
    result = await run_process(
        (sys.executable, "-c", "import time; time.sleep(20)"),
        cwd=tmp_path,
        environment=environment(),
        timeout=0.3,
        limit=1024,
    )
    assert result.timed_out
    assert result.exit_code != 0


async def test_process_cancellation(tmp_path: Path) -> None:
    pending = asyncio.create_task(
        run_process(
            (sys.executable, "-c", "import time; time.sleep(20)"),
            cwd=tmp_path,
            environment=environment(),
            timeout=10,
            limit=1024,
        )
    )
    await asyncio.sleep(0.3)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending


def repository(tmp_path: Path) -> ConfirmedRepository:
    root = tmp_path / "source"
    root.mkdir()
    for args in (
        ("init", "-b", "main"),
        ("config", "user.name", "Fixture"),
        ("config", "user.email", "fixture@localhost"),
        ("commit", "--allow-empty", "-m", "base"),
    ):
        subprocess.run(("git", *args), cwd=root, check=True, capture_output=True)
    head = subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=root, text=True).strip()
    return ConfirmedRepository(root, "main", head)


async def test_actual_root_and_minimal_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    confirmed = repository(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-private-value")
    executor = VerificationExecutor(
        WorktreeManager(tmp_path), {"python": (sys.executable,)}, path=os.defpath
    )
    result = await executor.execute(
        confirmed,
        VerificationCommand(
            argv=(
                "python",
                "-c",
                "import os; print(os.getcwd()); assert 'OPENAI_API_KEY' not in os.environ",
            )
        ),
    )
    assert result.passed
    assert result.cwd == str(confirmed.root)
    assert str(confirmed.root).encode() in result.process.stdout
    assert "OPENAI_API_KEY" not in result.environment_keys


async def test_subdirectory_and_changed_head_rejected(tmp_path: Path) -> None:
    confirmed = repository(tmp_path)
    executor = VerificationExecutor(
        WorktreeManager(tmp_path), {"python": (sys.executable,)}, path=os.defpath
    )
    sub = confirmed.root / "sub"
    sub.mkdir()
    with pytest.raises(WorkerBoundaryError, match="root_mismatch"):
        await executor.execute(
            ConfirmedRepository(sub, "main", confirmed.head_sha),
            VerificationCommand(argv=("python", "--version")),
        )
    with pytest.raises(WorkerBoundaryError, match="identity_mismatch"):
        await executor.execute(
            ConfirmedRepository(confirmed.root, "main", "f" * 40),
            VerificationCommand(argv=("python", "--version")),
        )


async def test_parser_never_overrides_failure_exit(tmp_path: Path) -> None:
    confirmed = repository(tmp_path)
    executor = VerificationExecutor(
        WorktreeManager(tmp_path), {"python": (sys.executable,)}, path=os.defpath
    )
    result = await executor.execute(
        confirmed,
        VerificationCommand(
            argv=("python", "-c", "print('99 passed'); raise SystemExit(1)"),
            parser="pytest",
        ),
    )
    assert result.parsed.passed == 99
    assert not result.passed


async def test_filename_metacharacters_remain_argv_data(tmp_path: Path) -> None:
    confirmed = repository(tmp_path)
    filename = "source; echo injected & data.txt"
    (confirmed.root / filename).write_text("literal file", encoding="utf-8")
    subprocess.run(("git", "add", "--", filename), cwd=confirmed.root, check=True)
    subprocess.run(
        ("git", "commit", "-m", "literal filename"),
        cwd=confirmed.root,
        check=True,
        capture_output=True,
    )
    confirmed = ConfirmedRepository(
        confirmed.root,
        confirmed.branch,
        subprocess.check_output(
            ("git", "rev-parse", "HEAD"), cwd=confirmed.root, text=True
        ).strip(),
    )
    result = await VerificationExecutor(
        WorktreeManager(tmp_path), {"python": (sys.executable,)}, path=os.defpath
    ).execute(
        confirmed,
        VerificationCommand(
            argv=(
                "python",
                "-c",
                "import sys; from pathlib import Path; print(Path(sys.argv[1]).read_text())",
                filename,
            )
        ),
    )
    assert result.passed
    assert result.process.stdout.strip() == b"literal file"


async def test_repository_execution_extensions_fail_before_checkout(tmp_path: Path) -> None:
    confirmed = repository(tmp_path)
    subprocess.run(
        ("git", "config", "filter.attack.smudge", "arbitrary-command"),
        cwd=confirmed.root,
        check=True,
    )
    with pytest.raises(WorkerBoundaryError, match="execution_extension_denied"):
        await VerificationExecutor(
            WorktreeManager(tmp_path), {"python": (sys.executable,)}, path=os.defpath
        ).confirm(confirmed)


async def test_timeout_terminates_descendants_only(tmp_path: Path) -> None:
    unrelated = subprocess.Popen(
        (sys.executable, "-c", "import time; time.sleep(20)"), cwd=tmp_path, env=environment()
    )
    child = (
        "import time; from pathlib import Path; time.sleep(2); "
        "Path('escaped-marker').write_text('unsafe')"
    )
    parent = (
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', sys.argv[1]]); time.sleep(20)"
    )
    try:
        result = await run_process(
            (sys.executable, "-c", parent, child),
            cwd=tmp_path,
            environment=environment(),
            timeout=0.8,
            limit=1024,
        )
        assert result.timed_out
        await asyncio.sleep(2.5)
        assert not (tmp_path / "escaped-marker").exists()
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)
