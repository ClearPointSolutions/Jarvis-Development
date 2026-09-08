#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"
if [ -n "${PYTHON:-}" ]; then
  PYTHON_BIN=$PYTHON
elif [ -x .venv/bin/python ]; then
  PYTHON_BIN=.venv/bin/python
elif [ -x .venv/Scripts/python.exe ]; then
  PYTHON_BIN=.venv/Scripts/python.exe
else
  PYTHON_BIN=python
fi
exec "$PYTHON_BIN" -m scripts.demo "$@"
