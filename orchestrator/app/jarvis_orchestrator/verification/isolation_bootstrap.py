"""Executed inside the disposable container before replacing itself with project code.

The broker validates this input. No broker credentials, receipts or host mounts
exist in this namespace. The bootstrap has no continuing supervisory authority.
"""

import json
import os
import sys
from pathlib import Path


def main() -> None:
    request = json.loads(sys.stdin.buffer.read(26 * 1024 * 1024))
    root = Path("/work/project")
    root.mkdir()
    for entry in request["files"]:
        destination = root / entry["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(entry["content"], encoding="utf-8")
        destination.chmod(0o755 if entry["executable"] else 0o644)
    os.chdir(root)
    environment = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/work",
        "TMPDIR": "/work",
        "CI": "1",
        "NO_COLOR": "1",
        "TZ": "UTC",
        **request["environment"],
    }
    os.execve(request["argv"][0], request["argv"], environment)


if __name__ == "__main__":
    main()
