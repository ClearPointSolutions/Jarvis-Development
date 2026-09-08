"""Local-only demo launcher. Run --e2e for disposable browser acceptance."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from jarvis_api.auth.bootstrap import bootstrap_owner
from jarvis_orchestrator.demo.bootstrap import bootstrap_demo
from jarvis_orchestrator.demo.safety import local_database_port
from jarvis_persistence.checkpoints import postgres_saver
from jarvis_persistence.database import create_async_database_engine, create_async_session_factory

ROOT = Path(__file__).resolve().parents[1]


async def seed(url: str, password: str) -> None:
    async with postgres_saver(url, setup=True):
        pass
    engine = create_async_database_engine(url)
    try:
        factory = create_async_session_factory(engine)
        owner, _ = await bootstrap_owner(factory, username="demo-owner", password=password)
        await bootstrap_demo(factory, owner)
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--e2e", action="store_true")
    args = parser.parse_args()
    url = os.environ.get(
        "TEST_DATABASE_URL", "postgresql+psycopg://jarvis_v1_dev@127.0.0.1:55432/jarvis_v1_test"
    )
    local_database_port(url)
    environment_files = [
        p
        for folder in (ROOT, ROOT / "web")
        for p in folder.glob(".env*")
        if p.name != ".env.example"
    ]
    if environment_files or os.environ.get("JARVIS_ORCHESTRATOR_RUNTIME_MODE") == "real":
        raise ValueError("Demo refuses a repository .env or explicitly real runtime configuration")
    npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
    if npm is None or not (ROOT / "web/.next/BUILD_ID").exists():
        raise ValueError("Install local dependencies and run the frontend production build first")
    parsed = make_url(url)
    name = "jarvis_demo_" + (uuid4().hex if args.e2e else "local")
    url = parsed.set(database=name).render_as_string(hide_password=False)
    directory = ROOT / ".tmp" / name
    directory.mkdir(parents=True, exist_ok=True)
    # Prevent libpq's implicit lookup of the developer's personal password file.
    passfile = directory / "unused.pgpass"
    passfile.write_text("")
    os.environ["PGPASSFILE"] = str(passfile)
    admin = create_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    children: dict[str, subprocess.Popen[bytes]] = {}
    password = (
        secrets.token_urlsafe(32) if args.e2e else getpass.getpass("Local demo owner password: ")
    )
    key = directory / "csrf.key"
    if not key.exists():
        key.write_text(secrets.token_urlsafe(48))
    control = directory / "restart.request"
    acknowledged = directory / "restart.done"
    try:
        with admin.connect() as connection:
            exists = connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}
            )
            if not exists:
                connection.execute(text(f'CREATE DATABASE "{name}"'))
        # Only migrations/bootstrap receive the local migration connection.
        os.environ["DATABASE_URL"] = url
        configuration = Config(str(ROOT / "alembic.ini"))
        command.upgrade(configuration, "head")
        asyncio.run(seed(url, password))
        env = {
            k: v
            for k, v in os.environ.items()
            if k.upper()
            in {
                "PATH",
                "SYSTEMROOT",
                "WINDIR",
                "TEMP",
                "TMP",
                "HOME",
                "USERPROFILE",
                "COMSPEC",
                "PATHEXT",
                "LOCALAPPDATA",
                "APPDATA",
                "CI",
                "PLAYWRIGHT_BROWSERS_PATH",
            }
        }
        env.update(
            {
                "PGPASSFILE": str(passfile),
                "DATABASE_URL": parsed.set(database=name)
                .update_query_dict({"options": "-c role=jarvis_v1_api"})
                .render_as_string(hide_password=False),
                "JARVIS_ENV": "test",
                "JARVIS_PUBLIC_ORIGIN": "http://127.0.0.1:3000",
                "JARVIS_CSRF_HMAC_KEY_FILE": str(key),
                "JARVIS_ARTIFACT_ROOT": str(directory / "artifacts"),
                "JARVIS_API_URL": "http://127.0.0.1:8000",
                "JARVIS_API_PORT": "8000",
                "JARVIS_SSE_POLL_SECONDS": "0.1",
                "JARVIS_ORCHESTRATOR_RUNTIME_MODE": "demo",
                "JARVIS_DEMO_NETWORK_GUARD": "1",
                "JARVIS_ORCHESTRATOR_LEASE_SECONDS": "5",
                "JARVIS_M6_E2E": "1" if args.e2e else "",
                "JARVIS_BROWSER_PASSWORD": password,
                "JARVIS_M6_CONTROL": str(control),
                "JARVIS_M6_ACK": str(acknowledged),
            }
        )
        with (directory / "services.log").open("wb") as log:

            def start_services() -> None:
                children["api"] = subprocess.Popen(
                    [sys.executable, "-m", "jarvis_api.main"],
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=log,
                )
                children["orchestrator"] = subprocess.Popen(
                    [sys.executable, "-m", "jarvis_orchestrator.main"],
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

            def stop_services() -> None:
                for service in ("api", "orchestrator"):
                    child = children.pop(service, None)
                    if child is not None:
                        child.terminate()
                        child.wait(timeout=15)

            start_services()
            print("DEMO Mission Control: http://127.0.0.1:3000 · username demo-owner", flush=True)
            print(
                "Create a project, select DEMO deterministic development, and enter an objective.",
                flush=True,
            )
            command_line = (
                [npm, "run", "test:e2e", "--", "m6-demo.spec.ts"]
                if args.e2e
                else [npm, "run", "start", "--", "--hostname", "127.0.0.1", "--port", "3000"]
            )
            children["web"] = subprocess.Popen(command_line, cwd=ROOT / "web", env=env)
            while children["web"].poll() is None:
                if control.exists():
                    control.unlink()
                    stop_services()
                    start_services()
                    acknowledged.write_text("restarted")
                if any(children[s].poll() is not None for s in ("api", "orchestrator")):
                    raise RuntimeError("Demo service stopped; inspect local service log")
                time.sleep(0.1)
            return int(children["web"].returncode or 0)
    finally:
        for child in children.values():
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=15)
        if args.e2e:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    raise SystemExit(main())
