"""Trusted Windows bootstrap: start repository code only after job assignment."""

import base64
import json
import subprocess
import sys

if __name__ == "__main__":
    line = sys.stdin.buffer.readline(36 * 1024 * 1024 + 1)
    if not line.endswith(b"\n") or len(line) > 36 * 1024 * 1024:
        raise SystemExit(125)
    value = json.loads(line)
    argv = value.get("argv") if isinstance(value, dict) else value
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
        raise SystemExit(125)
    data = (
        base64.b64decode(value["stdin_base64"], validate=True) if isinstance(value, dict) else b""
    )
    if len(data) > 26 * 1024 * 1024:
        raise SystemExit(125)
    raise SystemExit(subprocess.run(argv, input=data).returncode)
