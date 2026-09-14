"""Behavioral shell regressions for installer/preflight HTTP readiness probes."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "scripts" / "lib" / "http-probe.sh"


def _bash_available() -> bool:
    executable = shutil.which("bash")
    if executable is None:
        return False
    try:
        return (
            subprocess.run([executable, "--version"], capture_output=True, timeout=5).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(not _bash_available(), reason="functional bash is unavailable")


def _fake_curl(tmp_path: Path) -> Path:
    executable = tmp_path / "curl"
    executable.write_text(
        """#!/usr/bin/env bash
set -eu
body=""
headers=""
while [ $# -gt 0 ]; do
  case "$1" in
    --output) body=$2; shift 2;;
    --dump-header) headers=$2; shift 2;;
    --header) printf '%s\\n' "$2" >> "$PROBE_ARGUMENTS"; shift 2;;
    --connect-timeout|--max-time|--max-redirs|--write-out) shift 2;;
    --silent|--show-error) shift;;
    *) printf '%s\\n' "$1" >> "$PROBE_ARGUMENTS"; shift;;
  esac
done
printf 'Content-Type: %s\\r\\n' "${PROBE_CONTENT_TYPE:-application/json}" > "$headers"
if [ -n "${PROBE_LOCATION:-}" ]; then
  printf 'Location: %s\\r\\n' "$PROBE_LOCATION" >> "$headers"
fi
printf '%s' "${PROBE_BODY:-}" > "$body"
printf '%s' "${PROBE_CODE:-200}"
exit "${PROBE_EXIT:-0}"
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def _run(
    tmp_path: Path,
    *,
    code: str,
    exit_code: int,
    body: str = "",
    expected_codes: str = "401",
    contract: str = "auth_required",
    location: str = "",
) -> tuple[subprocess.CompletedProcess[str], str]:
    _fake_curl(tmp_path)
    arguments = tmp_path / "arguments"
    env = {
        **os.environ,
        "PATH": f"{tmp_path.as_posix()}:{os.environ.get('PATH', '')}",
        "PROBE_ARGUMENTS": str(arguments),
        "PROBE_CODE": code,
        "PROBE_EXIT": str(exit_code),
        "PROBE_BODY": body,
        "PROBE_LOCATION": location,
        "JARVIS_PUBLIC_ORIGIN": "https://jarvis.example:13000",
    }
    command = (
        f"source '{PROBE.as_posix()}'; "
        "jarvis_http_probe 'http://127.0.0.1:13000/api/v1/session' "
        f"'jarvis.example:13000' '{expected_codes}' '{contract}'"
    )
    result = subprocess.run(["bash", "-c", command], text=True, capture_output=True, env=env)
    recorded = arguments.read_text(encoding="utf-8") if arguments.exists() else ""
    return result, recorded


def test_http_000_with_curl_failure_is_not_accepted_as_nonempty_success(tmp_path: Path) -> None:
    result, _arguments = _run(tmp_path, code="000", exit_code=7)

    assert result.returncode != 0
    assert "curl exit 7, HTTP 000" in result.stderr


@pytest.mark.parametrize("code", ["200", "302", "400", "500", "502", "503"])
def test_unexpected_statuses_fail_the_required_session_probe(tmp_path: Path, code: str) -> None:
    result, _arguments = _run(tmp_path, code=code, exit_code=0)

    assert result.returncode != 0
    assert "unexpected status" in result.stderr


def test_arbitrary_401_is_rejected_and_public_host_is_sent(tmp_path: Path) -> None:
    result, arguments = _run(
        tmp_path,
        code="401",
        exit_code=0,
        body='{"error":{"code":"some.other.server"}}',
    )

    assert result.returncode != 0
    assert "did not match" in result.stderr
    assert "Host: jarvis.example:13000" in arguments


def test_jarvis_auth_required_contract_succeeds(tmp_path: Path) -> None:
    result, _arguments = _run(
        tmp_path,
        code="401",
        exit_code=0,
        body=(
            '{"error":{"code":"auth.required","message":"Authentication is required",'
            '"request_id":"request-123","details":{}}}'
        ),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "401"


@pytest.mark.parametrize(
    ("location", "accepted"),
    [
        ("/login?returnTo=%2F", True),
        ("https://jarvis.example:13000/login", True),
        ("https://evil.example/login", False),
        ("//evil.example/login", False),
    ],
)
def test_redirect_contract_allows_only_documented_same_origin_login(
    tmp_path: Path, location: str, accepted: bool
) -> None:
    result, _arguments = _run(
        tmp_path,
        code="307",
        exit_code=0,
        expected_codes="200,307,308",
        contract="same_origin_login_redirect",
        location=location,
    )

    assert (result.returncode == 0) is accepted
