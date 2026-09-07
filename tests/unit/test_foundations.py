import asyncio
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from jarvis_api.config import get_settings
from jarvis_api.main import create_app
from jarvis_contracts import __version__ as contracts_version
from jarvis_orchestrator import __version__ as orchestrator_version
from jarvis_orchestrator.main import run, serve


def test_api_health_is_stable_and_minimal() -> None:
    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "service": "jarvis-api",
        "status": "ok",
        "version": "0.1.0",
    }


def test_orchestrator_package_is_importable() -> None:
    assert orchestrator_version == "0.1.0"
    assert contracts_version == "1.0.0"


def test_settings_have_loopback_defaults() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 8000


def test_orchestrator_serve_waits_for_shutdown() -> None:
    event = AsyncMock()
    with patch("jarvis_orchestrator.main.asyncio.Event", return_value=event):
        asyncio.run(serve())
    event.wait.assert_awaited_once()


def test_orchestrator_entrypoint_uses_asyncio_runner() -> None:
    with patch("jarvis_orchestrator.main.asyncio.run") as asyncio_run:
        run()
    asyncio_run.assert_called_once()
    asyncio_run.call_args.args[0].close()


def test_windows_api_uses_psycopg_compatible_uvicorn_loop_factory() -> None:
    from jarvis_api.main import run as run_api

    with (
        patch("jarvis_api.main.sys.platform", "win32"),
        patch("jarvis_api.main.uvicorn.run") as server,
    ):
        run_api()
    assert server.call_args.kwargs["loop"] == "asyncio:SelectorEventLoop"
