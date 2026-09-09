"""Actual disposable containers; no mock is evidence of filesystem isolation."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

from jarvis_contracts.verification import VerificationCommand
from jarvis_orchestrator.verification.isolation_broker import IsolationBroker
from jarvis_orchestrator.verification.isolation_contract import CandidateFile, IsolationRequest


def test_real_container_denies_authority_and_runs_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = os.environ.get("JARVIS_TEST_ISOLATION_IMAGE")
    if not image:
        if os.environ.get("JARVIS_REQUIRE_REAL_ENTRYPOINT") == "1":
            pytest.fail("mandatory job requires the isolated verification image")
        pytest.skip("requires explicitly provisioned disposable isolation image")
    executable = shutil.which("docker")
    assert executable is not None
    image_id = json.loads(subprocess.check_output([executable, "image", "inspect", image]))[0]["Id"]
    broker = IsolationBroker(Path(executable), image_id, tmp_path / "receipts")
    monkeypatch.setenv("DATABASE_URL", "synthetic-control-database-canary")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-control-provider-canary")
    canary = tmp_path / "core-credential-canary"
    canary.write_text("synthetic-core-authority")
    source = """import os, pathlib, socket
def test_isolation():
    assert os.getuid() == 10001
    assert not pathlib.Path("/var/run/docker.sock").exists()
    assert not pathlib.Path("/run/secrets").exists()
    assert not pathlib.Path("/app").exists()
    assert {entry.name for entry in pathlib.Path("/sys/class/net").iterdir()} == {"lo"}
    assert not pathlib.Path(CANARY).exists()
    assert not any(key in os.environ for key in ("DATABASE_URL", "OPENAI_API_KEY", "SSH_AUTH_SOCK"))
    status = pathlib.Path("/proc/self/status").read_text()
    assert "CapEff:\\t0000000000000000" in status
    assert "NoNewPrivs:\\t1" in status
    assert "Seccomp:\\t2" in status
    try:
        pathlib.Path("/authority-canary").write_text("mutation")
    except OSError:
        pass
    else:
        raise AssertionError("root filesystem is writable")
    connection = socket.socket()
    connection.settimeout(0.5)
    try:
        connection.connect(("192.0.2.1", 80))
    except OSError:
        pass
    else:
        raise AssertionError("network is available")
    finally:
        connection.close()
def test_project():
    from project import add
    assert add(2, 3) == 5
""".replace("CANARY", repr(str(canary)))
    request = IsolationRequest(
        run_id=uuid4(),
        execution_id=uuid4(),
        candidate_sha="a" * 40,
        tree_sha="b" * 40,
        files=(
            CandidateFile(path="test_project.py", content=source),
            CandidateFile(path="project.py", content="def add(a, b): return a + b\n"),
        ),
        command=VerificationCommand(argv=("pytest", "-q"), timeout_seconds=30),
    )
    result = broker.execute(request)
    assert result.exit_code == 0, result.stderr + result.stdout
    assert "2 passed" in result.stdout
    assert canary.read_text() == "synthetic-core-authority"
    assert broker.execute(request) == result
    with pytest.raises(ValueError, match="identity mismatch"):
        broker.execute(request.model_copy(update={"candidate_sha": "c" * 40}))
    crash_request = request.model_copy(
        update={
            "execution_id": uuid4(),
            "command": VerificationCommand(
                argv=("python", "-c", "import uuid; print(uuid.uuid4())")
            ),
        }
    )
    publish = broker.immutable

    def crash_before_receipt(path: Path, data: bytes) -> None:
        if path.name.endswith(".receipt.json"):
            raise RuntimeError("injected receipt publication crash")
        publish(path, data)

    monkeypatch.setattr(broker, "immutable", crash_before_receipt)
    with pytest.raises(RuntimeError, match="injected"):
        broker.execute(crash_request)
    output = broker.docker_command("logs", "jarvis-verify-" + crash_request.execution_id.hex)
    monkeypatch.setattr(broker, "immutable", publish)
    recovered = broker.execute(crash_request)
    assert recovered.stdout == output.decode()
    assert recovered.exit_code == 0
    assert recovered.stdout_truncated  # Recovery never invents stream completeness.
    timeout_request = request.model_copy(
        update={
            "execution_id": uuid4(),
            "command": VerificationCommand(
                argv=("python", "-c", "import time; time.sleep(60)"), timeout_seconds=1
            ),
        }
    )
    timed = broker.execute(timeout_request)
    assert timed.timed_out and timed.exit_code != 0
    assert broker.execute(timeout_request) == timed
    abandoned = request.model_copy(
        update={
            "execution_id": uuid4(),
            "command": VerificationCommand(
                argv=("python", "-c", "import time; time.sleep(60)"), timeout_seconds=3
            ),
        }
    )
    configuration = tmp_path / "broker.json"
    configuration.write_text(
        json.dumps(
            {
                "docker_executable": executable,
                "image_id": image_id,
                "receipt_root": str(broker.receipts),
            }
        )
    )
    child = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "jarvis_orchestrator.verification.isolation_cli",
            "--config",
            str(configuration),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert child.stdin is not None
    child.stdin.write(abandoned.model_dump_json().encode())
    child.stdin.close()
    name = "jarvis-verify-" + abandoned.execution_id.hex
    try:
        for _ in range(100):
            if broker.docker_command("ps", "--filter", "name=^/" + name + "$", "-q").strip():
                break
            time.sleep(0.1)
        else:
            pytest.fail("abandoned verification container did not start")
    finally:
        child.terminate()
        child.wait(timeout=10)
    time.sleep(3.1)
    assert broker.reap() == 1
    recovered_timeout = broker.execute(abandoned)
    assert recovered_timeout.timed_out and recovered_timeout.exit_code != 0
    assert broker.reap() == 0
