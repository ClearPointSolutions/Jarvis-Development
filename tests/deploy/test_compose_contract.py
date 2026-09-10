"""Deployment-contract regressions for the production and homelab Compose files.

These guard the M12A deployment defects so they cannot silently regress:

* the production web service must supply ``JARVIS_API_URL=http://api:8000`` so a
  normal deployment's ``/api/...`` proxy works with no undocumented override;
* the production file must stay strict (production env, Secure cookies, an HTTPS
  origin requirement, loopback-only application ports);
* the homelab overlay must only relax those two things on purpose and must
  replace -- not append to -- the web port mapping;
* the ``owner-bootstrap`` one-shot must use the database-owning migrator login,
  not the least-privilege API login.

Text-level checks always run. The merged-model checks shell out to
``docker compose config`` and are skipped where Docker is unavailable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION = ROOT / "deploy" / "compose.production.yml"
HOMELAB = ROOT / "deploy" / "compose.homelab.yml"
PRODUCTION_TEXT = PRODUCTION.read_text(encoding="utf-8")
HOMELAB_TEXT = HOMELAB.read_text(encoding="utf-8")

REQUIRED_SECRETS = {
    "bootstrap_password",
    "migrator_password",
    "api_password",
    "orchestrator_password",
    "csrf_key",
}

FAKE_ENV = {
    "JARVIS_PYTHON_IMAGE": "jarvis-v1-python:test",
    "JARVIS_WEB_IMAGE": "jarvis-v1-web:test",
    "JARVIS_PUBLIC_ORIGIN": "http://192.168.40.105:13000",
    "JARVIS_SECRET_DIR": "/tmp/jarvis-secrets",
    "JARVIS_PRIVATE_CONFIG_DIR": "/tmp/jarvis-config",
}


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "compose", "version"], capture_output=True).returncode == 0
    except OSError:
        return False


requires_docker = pytest.mark.skipif(not _docker_available(), reason="docker compose not available")


def _merged_config(*files: Path, profile: str | None = None) -> dict[str, Any]:
    argv = ["docker", "compose", "--project-name", "jarvis-v1"]
    for path in files:
        argv += ["-f", str(path)]
    if profile is not None:
        argv += ["--profile", profile]
    argv += ["config", "--format", "json"]
    result = subprocess.run(argv, capture_output=True, text=True, env={**os.environ, **FAKE_ENV})
    assert result.returncode == 0, result.stderr
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


# --------------------------------------------------------------------------- #
# Text-level regressions (always run)
# --------------------------------------------------------------------------- #


def test_production_web_declares_the_internal_api_url() -> None:
    assert "JARVIS_API_URL: http://api:8000" in PRODUCTION_TEXT


def test_production_keeps_strict_security_literals() -> None:
    assert "JARVIS_ENV: production" in PRODUCTION_TEXT
    assert 'JARVIS_COOKIE_SECURE: "true"' in PRODUCTION_TEXT
    assert "${JARVIS_PUBLIC_ORIGIN:?" in PRODUCTION_TEXT
    assert 'ports: ["127.0.0.1:${JARVIS_WEB_PORT:-13000}:3000"]' in PRODUCTION_TEXT
    assert 'ports: ["127.0.0.1:${JARVIS_API_PORT:-18000}:8000"]' in PRODUCTION_TEXT


def test_owner_bootstrap_service_uses_the_migrator_login() -> None:
    block = PRODUCTION_TEXT.split("\n  owner-bootstrap:", 1)[1].split("\n  orchestrator:", 1)[0]
    directives = [
        line.strip()
        for line in block.splitlines()
        if line.strip().startswith(("JARVIS_", "secrets:", "profiles:", "restart:", "command:"))
    ]
    assert "profiles: [owner-bootstrap]" in directives
    assert 'restart: "no"' in directives
    assert "JARVIS_DATABASE_USER: jarvis_v1_migrator_login" in directives
    assert "JARVIS_DATABASE_PASSWORD_FILE: /run/secrets/migrator_password" in directives
    assert "secrets: [migrator_password]" in directives
    assert "jarvis_api.auth.bootstrap" in block
    # The identity directives must never reference the least-privilege API login.
    assert not any("jarvis_v1_api_login" in directive for directive in directives)
    assert not any("api_password" in directive for directive in directives)


def test_homelab_overlay_is_a_minimal_targeted_override() -> None:
    assert "name: jarvis-v1" in HOMELAB_TEXT
    assert "JARVIS_ENV: development" in HOMELAB_TEXT
    assert 'JARVIS_COOKIE_SECURE: "false"' in HOMELAB_TEXT
    # It must replace, not append to, the base web port list.
    assert "ports: !override" in HOMELAB_TEXT
    # Nothing in the overlay may re-assert production mode or touch secrets/db.
    assert "JARVIS_ENV: production" not in HOMELAB_TEXT
    assert "secrets:" not in HOMELAB_TEXT
    assert "postgres:" not in HOMELAB_TEXT


# --------------------------------------------------------------------------- #
# Merged-model regressions (need docker compose)
# --------------------------------------------------------------------------- #


@requires_docker
def test_production_only_model_stays_loopback_and_strict() -> None:
    services = _merged_config(PRODUCTION)["services"]
    web, api = services["web"], services["api"]
    assert web["environment"]["JARVIS_API_URL"] == "http://api:8000"
    assert [p["host_ip"] for p in web["ports"]] == ["127.0.0.1"]
    assert [p["host_ip"] for p in api["ports"]] == ["127.0.0.1"]
    assert api["environment"]["JARVIS_ENV"] == "production"
    assert api["environment"]["JARVIS_COOKIE_SECURE"] == "true"
    assert "owner-bootstrap" not in services  # profile-gated


@requires_docker
def test_homelab_merged_model_exposes_one_lan_web_port_and_dev_api() -> None:
    services = _merged_config(PRODUCTION, HOMELAB)["services"]
    web, api = services["web"], services["api"]
    assert len(web["ports"]) == 1, web["ports"]
    assert web["ports"][0]["host_ip"] == "0.0.0.0"
    assert str(web["ports"][0]["published"]) == "13000"
    assert web["environment"]["JARVIS_API_URL"] == "http://api:8000"
    assert api["environment"]["JARVIS_ENV"] == "development"
    assert api["environment"]["JARVIS_COOKIE_SECURE"] == "false"
    # API maintenance port stays on loopback even in homelab mode.
    assert [p["host_ip"] for p in api["ports"]] == ["127.0.0.1"]


@requires_docker
def test_owner_bootstrap_appears_only_under_its_profile_with_migrator_creds() -> None:
    services = _merged_config(PRODUCTION, HOMELAB, profile="owner-bootstrap")["services"]
    assert "owner-bootstrap" in services
    service = services["owner-bootstrap"]
    assert service["environment"]["JARVIS_DATABASE_USER"] == "jarvis_v1_migrator_login"
    assert {s["source"] for s in service["secrets"]} == {"migrator_password"}
    top_secrets = _merged_config(PRODUCTION)["secrets"]
    assert set(top_secrets) == REQUIRED_SECRETS
