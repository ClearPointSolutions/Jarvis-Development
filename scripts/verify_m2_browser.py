"""Run Chromium against the actual API and a fresh disposable PostgreSQL database."""

from __future__ import annotations

import asyncio
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text, update
from sqlalchemy.engine import make_url
from tests.integration.support import seed_run

from jarvis_api.auth.bootstrap import bootstrap_owner
from jarvis_persistence.checkpoints import postgres_saver
from jarvis_persistence.database import create_async_database_engine, create_async_session_factory
from jarvis_persistence.models import ProjectModel

ROOT = Path(__file__).resolve().parents[1]


async def seed(url: str, password: str) -> str:
    async with postgres_saver(url, setup=True):
        pass
    engine = create_async_database_engine(url)
    factory = create_async_session_factory(engine)
    try:
        owner, _ = await bootstrap_owner(factory, username="browser-owner", password=password)
        run = await seed_run(factory)
        async with factory.begin() as session:
            await session.execute(
                update(ProjectModel)
                .where(ProjectModel.id == run.project_id)
                .values(owner_user_id=owner)
            )
        return str(run.run_id)
    finally:
        await engine.dispose()


def main() -> int:
    parsed = make_url(os.environ["TEST_DATABASE_URL"])
    if parsed.host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("M2 browser verification refuses non-loopback databases")
    name = "jarvis_m2_browser_" + uuid4().hex
    admin = create_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    url = parsed.set(database=name).render_as_string(hide_password=False)
    api: subprocess.Popen[bytes] | None = None
    orchestrator: subprocess.Popen[bytes] | None = None
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        # Environment and config agree because env.py supports DATABASE_URL.
        os.environ["DATABASE_URL"] = url
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        command.upgrade(config, "head")
        password = secrets.token_urlsafe(32)
        run_id = asyncio.run(seed(url, password))
        with tempfile.TemporaryDirectory(prefix="jarvis-m2-browser-") as directory:
            key = Path(directory) / "csrf.key"
            key.write_bytes(secrets.token_urlsafe(48).encode())
            env = {
                **os.environ,
                "DATABASE_URL": parsed.set(database=name)
                .update_query_dict({"options": "-c role=jarvis_v1_api"})
                .render_as_string(hide_password=False),
                "JARVIS_PROVIDER_ALLOWED_ENDPOINTS": '["http://127.0.0.1:11499"]',
                "JARVIS_BROWSER_PROVIDER_ENDPOINT": "http://127.0.0.1:11499",
                "JARVIS_ENV": "test",
                "JARVIS_PUBLIC_ORIGIN": "http://127.0.0.1:3000",
                "JARVIS_COOKIE_SECURE": "true",
                "JARVIS_CSRF_HMAC_KEY_FILE": str(key),
                "JARVIS_API_PORT": "8000",
                "JARVIS_API_URL": "http://127.0.0.1:8000",
                "JARVIS_BROWSER_DATABASE_URL": url,
                "JARVIS_BROWSER_PASSWORD": password,
                "JARVIS_BROWSER_RUN_ID": run_id,
                "JARVIS_BROWSER_PYTHON": sys.executable,
                "JARVIS_ARTIFACT_ROOT": str(Path(directory) / "artifacts"),
                "JARVIS_SSE_POLL_SECONDS": "0.1",
            }
            with (Path(directory) / "api.log").open("wb") as log:
                orchestrator = subprocess.Popen(
                    [sys.executable, "-m", "scripts.m5_browser_runtime"],
                    cwd=ROOT,
                    env={
                        **env,
                        "DATABASE_URL": parsed.set(database=name)
                        .update_query_dict({"options": "-c role=jarvis_v1_orchestrator"})
                        .render_as_string(hide_password=False),
                    },
                    stdout=log,
                    stderr=log,
                )
                api = subprocess.Popen(
                    [sys.executable, "-m", "jarvis_api.main"],
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=log,
                )
                with httpx.Client(trust_env=False) as client:
                    for _ in range(100):
                        if api.poll() is not None:
                            raise RuntimeError("M2 API failed to start; no raw log exported")
                        try:
                            if (
                                client.get(
                                    "http://127.0.0.1:8000/health",
                                    headers={"Host": "127.0.0.1:3000"},
                                ).status_code
                                == 200
                            ):
                                break
                        except httpx.ConnectError:
                            pass
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("M2 API startup timed out")
                npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
                if npm is None:
                    raise RuntimeError("npm unavailable")
                result = subprocess.run(
                    [npm, "run", "test:e2e"], cwd=ROOT / "web", env=env, check=False
                )
                api.terminate()
                api.wait(timeout=15)
                api = None
                orchestrator.terminate()
                orchestrator.wait(timeout=15)
                orchestrator = None
            content = (Path(directory) / "api.log").read_text(errors="replace")
            if result.returncode:
                for line in content.splitlines():
                    if "exception_type=" in line:
                        print(line)
            if password in content or "synthetic-" + "event-canary" in content:
                raise RuntimeError("secret canary found in API log")
            for asset in (ROOT / "web/.next/static").rglob("*.js"):
                bundle = asset.read_text(errors="replace")
                if password in bundle or "synthetic-" + "event-canary" in bundle:
                    raise RuntimeError("secret canary found in browser bundle")
            print("M2 API log secret canaries: absent")
            print("M2 browser bundle secret canaries: absent")
            return result.returncode
    finally:
        if orchestrator is not None:
            orchestrator.terminate()
            orchestrator.wait(timeout=15)
        if api is not None:
            api.terminate()
            api.wait(timeout=15)
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(cast(Any, asyncio).WindowsSelectorEventLoopPolicy())
    raise SystemExit(main())
