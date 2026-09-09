"""Resolve one service's database secret immediately before exec, without logging it."""

import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy.engine import URL


def main() -> None:
    password = Path(os.environ["JARVIS_DATABASE_PASSWORD_FILE"]).read_text().strip()
    if not 24 <= len(password) <= 1024:
        raise ValueError("database password file must contain 24-1024 characters")
    os.environ["DATABASE_URL"] = URL.create(
        "postgresql+psycopg",
        username=os.environ["JARVIS_DATABASE_USER"],
        password=password,
        host=os.environ.get("JARVIS_DATABASE_HOST", "postgres"),
        database=os.environ.get("JARVIS_DATABASE_NAME", "jarvis_v1"),
    ).render_as_string(hide_password=False)
    csrf_source = os.environ.get("JARVIS_CSRF_HMAC_KEY_FILE")
    if csrf_source:
        # Compose file-backed secrets can be mounted 0444. Preserve the API's
        # strict private-file check by materializing a 0600 copy in private tmpfs.
        with Path(csrf_source).open("rb") as source:
            content = source.read(4097)
        if not 32 <= len(content) <= 4096:
            raise ValueError("CSRF secret file length is invalid")
        descriptor, filename = tempfile.mkstemp(prefix="jarvis-csrf-")
        with os.fdopen(descriptor, "wb") as target:
            target.write(content)
        os.chmod(filename, 0o600)
        os.environ["JARVIS_CSRF_HMAC_KEY_FILE"] = filename
    if len(sys.argv) < 2:
        raise ValueError("service command is required")
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
