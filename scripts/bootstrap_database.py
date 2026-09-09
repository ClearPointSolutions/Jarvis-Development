"""One-shot privileged role bootstrap. Never run in the web/API service."""

import os
from pathlib import Path

import psycopg
from psycopg import sql

from jarvis_persistence.checkpoints import psycopg_connection_string


def main() -> None:
    database = os.environ.get("JARVIS_DATABASE_NAME", "jarvis_v1")
    with psycopg.connect(psycopg_connection_string(os.environ["DATABASE_URL"])) as connection:
        for role in ("migrator", "api", "orchestrator", "readonly"):
            name = "jarvis_v1_" + role
            if not connection.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)
            ).fetchone():
                connection.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(name)))
        for role in ("migrator", "api", "orchestrator"):
            name = "jarvis_v1_" + role
            login = name + "_login"
            password = Path(f"/run/secrets/{role}_password").read_text().strip()
            if not 24 <= len(password) <= 1024:
                raise ValueError("role password file has an invalid length")
            if not connection.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s", (login,)
            ).fetchone():
                connection.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
                    ).format(sql.Identifier(login))
                )
            connection.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(login), sql.Literal(password)
                )
            )
            connection.execute(
                sql.SQL("GRANT {} TO {}").format(sql.Identifier(name), sql.Identifier(login))
            )
        connection.execute(
            sql.SQL("ALTER DATABASE {} OWNER TO jarvis_v1_migrator_login").format(
                sql.Identifier(database)
            )
        )
        connection.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
        )
        connection.execute(
            sql.SQL(
                "GRANT CONNECT ON DATABASE {} TO jarvis_v1_api_login, jarvis_v1_orchestrator_login"
            ).format(sql.Identifier(database))
        )
        connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        connection.execute("GRANT USAGE, CREATE ON SCHEMA public TO jarvis_v1_migrator_login")
    print("Dedicated V1 database roles ready")


if __name__ == "__main__":
    main()
