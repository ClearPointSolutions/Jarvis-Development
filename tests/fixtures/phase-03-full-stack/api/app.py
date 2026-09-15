from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
DATABASE = Path(os.environ.get("ACCEPTANCE_DATABASE", ROOT / ".tmp" / "items.sqlite3"))


def validate_title(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Title is required")
    title = value.strip()
    if len(title) > 80:
        raise ValueError("Title must be 80 characters or fewer")
    return title


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE IF NOT EXISTS items ("
        "id INTEGER PRIMARY KEY, title TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0)"
    )
    try:
        with connection:
            yield connection
    finally:
        connection.close()


class Handler(SimpleHTTPRequestHandler):
    def guess_type(self, path: str | os.PathLike[str]) -> str:
        return (
            "application/javascript"
            if os.fspath(path).endswith(".mjs")
            else super().guess_type(path)
        )

    def json_response(self, status: HTTPStatus, payload: object) -> None:
        content = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        if urlparse(self.path).path != "/api/items":
            return super().do_GET()
        with connect() as database:
            items = [dict(row) for row in database.execute("SELECT * FROM items ORDER BY id")]
        self.json_response(HTTPStatus.OK, {"items": items})

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/items":
            return self.send_error(HTTPStatus.NOT_FOUND)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024:
                raise ValueError("Invalid request size")
            title = validate_title(json.loads(self.rfile.read(length)).get("title"))
        except (ValueError, json.JSONDecodeError) as error:
            return self.json_response(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": str(error)})
        with connect() as database:
            cursor = database.execute("INSERT INTO items(title) VALUES (?)", (title,))
            item = dict(
                database.execute("SELECT * FROM items WHERE id = ?", (cursor.lastrowid,)).fetchone()
            )
        self.json_response(HTTPStatus.CREATED, item)

    def do_PATCH(self) -> None:
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) != 3 or parts[:2] != ["api", "items"] or not parts[2].isdigit():
            return self.send_error(HTTPStatus.NOT_FOUND)
        with connect() as database:
            database.execute("UPDATE items SET completed = 1 WHERE id = ?", (int(parts[2]),))
            row = database.execute("SELECT * FROM items WHERE id = ?", (int(parts[2]),)).fetchone()
        if row is None:
            return self.send_error(HTTPStatus.NOT_FOUND)
        self.json_response(HTTPStatus.OK, dict(row))


if __name__ == "__main__":
    if os.environ.get("ACCEPTANCE_RESET") == "1":
        DATABASE.unlink(missing_ok=True)
    handler = partial(Handler, directory=str(DIST))
    ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "8765"))), handler).serve_forever()
