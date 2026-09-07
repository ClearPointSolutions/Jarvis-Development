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

echo "== secret scan =="
"$PYTHON_BIN" scripts/secret_scan.py --self-test
"$PYTHON_BIN" scripts/secret_scan.py

echo "== Python format, lint, and types =="
"$PYTHON_BIN" -m ruff format --check .
"$PYTHON_BIN" -m ruff check .
"$PYTHON_BIN" -m mypy

echo "== Python unit and compatibility tests =="
"$PYTHON_BIN" -m pytest -m "not integration" --cov --cov-report=term-missing

if [ -n "${TEST_DATABASE_URL:-}" ] && [ -f alembic.ini ]; then
  echo "== PostgreSQL migration and integration tests =="
  DATABASE_URL="$TEST_DATABASE_URL" "$PYTHON_BIN" -m alembic upgrade head
  "$PYTHON_BIN" -m pytest -m integration
else
  echo "== PostgreSQL tests skipped (set TEST_DATABASE_URL to enable) =="
fi

if [ -f packages/contracts/generated/jarvis-contracts.schema.json ]; then
  echo "== generated shared contract drift =="
  "$PYTHON_BIN" -m jarvis_contracts.generate --check
  (cd web && npm run contracts:check)
fi

echo "== frontend format, lint, types, unit tests, and build =="
(cd web && npm run format:check)
(cd web && npm run lint)
(cd web && npm run typecheck)
(cd web && npm run test)
(cd web && npm run build)

if [ "${JARVIS_SKIP_E2E:-0}" = "1" ]; then
  echo "== Playwright skipped by explicit JARVIS_SKIP_E2E=1 =="
else
  echo "== Playwright =="
  (cd web && npm run test:e2e)
fi

echo "All enabled verification gates passed."
