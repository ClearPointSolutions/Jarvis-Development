"""Deterministic child process for local SSH acceptance, never an OpenHands claim."""

import base64
import json
import subprocess
import sys
from pathlib import Path

payload = json.loads(base64.b64decode(sys.argv[1]))
root = Path("/workspaces") / payload["project_slug"]


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


base = git("rev-parse", "HEAD")
counter = Path("/invocations") / (payload["project_slug"] + ".attempts")
number = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(number))
(root / "answer.py").write_text(f"ANSWER = {0 if number == 1 else 42}\n")
(root / "test_answer.py").write_text(
    "from answer import ANSWER\n\ndef test_answer():\n    assert ANSWER == 42\n"
)
git("add", "answer.py", "test_answer.py")
git("commit", "-m", "protocol fixture attempt " + str(number))
print(
    "JARVIS_RESULT_JSON="
    + json.dumps(
        {
            "task_id": payload["task"]["id"],
            "workspace": str(root),
            "start_head": base,
            "end_head": git("rev-parse", "HEAD"),
            "diff_stat": git("diff", "--stat", base, "HEAD"),
            "error": None,
            "execution_status": "finished",
        }
    )
)
