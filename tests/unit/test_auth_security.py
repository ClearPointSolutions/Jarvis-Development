from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jarvis_api.auth.crypto import (
    PasswordManager,
    client_network,
    derive_csrf_token,
    new_session_token,
    normalize_username,
    sha256_text,
)
from jarvis_api.auth.service import AuthService
from jarvis_api.config import Settings
from jarvis_api.main import create_app
from jarvis_contracts.event_registry import SecurityDeniedData


@pytest.fixture(autouse=True)
def isolate_audit_database(monkeypatch: pytest.MonkeyPatch) -> None:
    async def discard_audit(
        self: AuthService, payload: SecurityDeniedData, *, correlation_id: str
    ) -> None:
        pass

    monkeypatch.setattr(AuthService, "security_denied", discard_audit)


def test_argon2id_and_opaque_token_primitives() -> None:
    credential = "test-only-long-credential"
    passwords = PasswordManager()
    password_hash = passwords.hash(credential)

    assert password_hash.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
    assert passwords.verify(password_hash, credential)
    assert not passwords.verify(password_hash, "incorrect-test-value")
    assert not passwords.needs_rehash(password_hash)

    first = new_session_token()
    second = new_session_token()
    assert first != second
    assert len(first) >= 43
    assert sha256_text(first) != first


def test_csrf_username_and_network_derivations_are_stable_and_bounded() -> None:
    token = "opaque-session-token-with-enough-entropy-material"
    key = b"k" * 32
    csrf = derive_csrf_token(token, key)

    assert csrf == derive_csrf_token(token, key)
    assert csrf != derive_csrf_token(token + "x", key)
    assert normalize_username("  Mission.Owner  ") == "mission.owner"
    assert client_network("192.0.2.42") == "192.0.2.0/24"
    assert client_network("2001:db8::1234") == "2001:db8::/64"
    assert client_network("not-an-address") == "unknown"


def test_anonymous_surface_errors_headers_and_route_inventory_are_safe() -> None:
    settings = Settings(_env_file=None, env="test")
    app = create_app(settings=settings)
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"service": "jarvis-api", "status": "ok", "version": "0.1.0"}
    assert health.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in health.headers["content-security-policy"]
    assert "access-control-allow-origin" not in health.headers

    assert client.get("/api/v1/session").status_code == 401
    assert client.get("/api/v1/system/readiness").status_code == 401
    assert client.get("/docs").status_code == 404
    route_paths = {getattr(route, "path", "") for route in app.routes}
    assert not any("shell" in path or "exec" in path for path in route_paths)


def test_origin_host_json_and_validation_errors_do_not_echo_credentials() -> None:
    settings = Settings(
        _env_file=None,
        env="test",
        public_origin="https://jarvis.test",
        cookie_secure=True,
    )
    client = TestClient(create_app(settings=settings), base_url="https://jarvis.test")
    credential = "sensitive-test-input-not-for-output"

    missing_origin = client.post(
        "/api/v1/auth/login", json={"username": "owner", "password": credential}
    )
    assert missing_origin.status_code == 403

    wrong_host = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "https://jarvis.test", "Host": "attacker.test"},
        json={"username": "owner", "password": credential},
    )
    assert wrong_host.status_code == 400

    non_json = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "https://jarvis.test", "Content-Type": "text/plain"},
        content=credential,
    )
    assert non_json.status_code == 415

    invalid = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "https://jarvis.test"},
        json={"username": "owner", "password": credential * 100},
    )
    assert invalid.status_code == 422
    assert credential not in invalid.text
    assert "input" not in invalid.json()["error"]["details"]


def test_unexpected_exception_is_redacted_in_body_logs_and_has_security_headers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(settings=Settings(_env_file=None, env="test"))
    canary = "synthetic-private-exception-value"

    @app.get("/failure-fixture")
    async def fail() -> None:
        raise RuntimeError(canary)

    response = TestClient(app).get("/failure-fixture")
    assert response.status_code == 500
    assert canary not in response.text
    assert canary not in caplog.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-request-id"] == response.json()["error"]["request_id"]
