#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

if [ -x .venv/bin/python ]; then
  PYTHON_BIN=.venv/bin/python
elif [ -x .venv/Scripts/python.exe ]; then
  PYTHON_BIN=.venv/Scripts/python.exe
else
  echo "Create .venv and install requirements.lock before starting development." >&2
  exit 2
fi

cleanup() {
  trap - INT TERM EXIT
  kill "$API_PID" "$ORCHESTRATOR_PID" "$WEB_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

"$PYTHON_BIN" -m uvicorn jarvis_api.main:app --host 127.0.0.1 --port "${JARVIS_API_PORT:-8000}" &
API_PID=$!
"$PYTHON_BIN" -m jarvis_orchestrator.main &
ORCHESTRATOR_PID=$!
npm --prefix web run dev -- --hostname 127.0.0.1 --port "${JARVIS_WEB_PORT:-3000}" &
WEB_PID=$!

echo "Jarvis local processes started on loopback only. Press Ctrl+C to stop."
wait
