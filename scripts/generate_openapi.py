"""Generate deterministic browser paths from the integrated production routes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jarvis_api.config import Settings
from jarvis_api.main import create_app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    schema = create_app(
        settings=Settings(env="test"), server_key=b"schema-generation-key" * 2
    ).openapi()
    content = (json.dumps(schema, indent=2, sort_keys=True) + "\n").encode()
    path = (
        Path(__file__).resolve().parents[1] / "packages/contracts/generated/jarvis-api.openapi.json"
    )
    if args.check:
        if not path.exists() or path.read_bytes() != content:
            raise SystemExit("generated OpenAPI is stale; run python -m scripts.generate_openapi")
        print("Integrated OpenAPI: current")
    else:
        path.write_bytes(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
