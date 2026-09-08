"""Trusted Windows bootstrap: start repository code only after job assignment."""

import json
import subprocess
import sys

if __name__ == "__main__":
    line = sys.stdin.buffer.readline(131073)
    if not line.endswith(b"\n") or len(line) > 131072:
        raise SystemExit(125)
    argv = json.loads(line)
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
        raise SystemExit(125)
    raise SystemExit(subprocess.call(argv, stdin=subprocess.DEVNULL))
