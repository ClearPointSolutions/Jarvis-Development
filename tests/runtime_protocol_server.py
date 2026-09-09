"""Loopback native Ollama protocol fixture; never evidence of real model quality."""

import json
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler
from typing import Any


class ProtocolHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass

    def reply(self, value: dict[str, Any]) -> None:
        content = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        self.reply({"models": [{"name": "protocol-fixture:1"}]})

    def do_POST(self) -> None:
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        title = request["format"]["title"]
        content: dict[str, Any]
        if title == "OrganizerOutput":
            content = {"summary": "Create answer 42 and verify with pytest."}
        elif title == "TaskPlan":
            content = {
                "architecture": "A Python constant with an independent assertion.",
                "tasks": [
                    {
                        "key": "DEV-001",
                        "title": "Answer",
                        "description": "Create answer.py with ANSWER = 42 and a test.",
                        "acceptance_criteria": ["ANSWER equals 42"],
                        "verification": [
                            {
                                "argv": ["python", "-m", "pytest", "-q"],
                                "parser": "pytest",
                                "timeout_seconds": 30,
                            }
                        ],
                    }
                ],
            }
        else:
            assert title == "ReviewDecision", title
            evidence = json.loads(request["messages"][-1]["content"].split("\n", 1)[1])
            value = evidence["evidence"]
            snapshot = value["snapshot"]
            content = {
                "id": evidence["required_review_id"],
                "task_id": value["task_id"],
                "task_attempt_id": value["task_attempt_id"],
                "reviewed_snapshot_id": snapshot["id"],
                "reviewed_head_sha": snapshot["head_sha"],
                "snapshot_digest": snapshot["content_digest"],
                "verdict": "PASS",
                "summary": "Protocol fixture decision, not model quality evidence.",
                "findings": [],
                "reviewer_revision": evidence["required_reviewer_revision"],
                "started_at": evidence["review_started_at"],
                "finished_at": datetime.now(UTC).isoformat(),
            }
        self.reply(
            {
                "model": request["model"],
                "message": {"role": "assistant", "content": json.dumps(content)},
                "done": True,
                "prompt_eval_count": 100,
                "eval_count": 100,
            }
        )
