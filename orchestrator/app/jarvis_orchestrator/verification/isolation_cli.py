"""Fixed-command stdin broker entrypoint for a dedicated executor account."""

import argparse
import json
import sys
from pathlib import Path

from jarvis_orchestrator.verification.isolation_broker import IsolationBroker
from jarvis_orchestrator.verification.isolation_contract import IsolationRequest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--reap", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    broker = IsolationBroker(
        Path(config["docker_executable"]), config["image_id"], Path(config["receipt_root"])
    )
    if args.reap:
        print(json.dumps({"terminated_expired_containers": broker.reap()}))
        return
    data = sys.stdin.buffer.read(26 * 1024 * 1024 + 1)
    if len(data) > 26 * 1024 * 1024:
        raise ValueError("verification request too large")
    request = IsolationRequest.model_validate_json(data)
    result = broker.execute(request)
    sys.stdout.write(result.model_dump_json())


if __name__ == "__main__":
    main()
