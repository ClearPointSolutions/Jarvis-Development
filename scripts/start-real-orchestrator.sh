#!/usr/bin/env bash
# Validate and explicitly start the configured real orchestrator.
set -euo pipefail

MODE=homelab
ENV_FILE=""
VALIDATE_ONLY=0
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

while [ $# -gt 0 ]; do
  case "$1" in
    --mode) MODE=${2:?}; shift 2;;
    --env-file) ENV_FILE=${2:?}; shift 2;;
    --validate-only) VALIDATE_ONLY=1; shift;;
    -h|--help)
      sed -n '2,3p' "$0" | sed 's/^# \{0,1\}//'
      printf '%s\n' 'Options: --mode homelab|production --env-file PATH --validate-only'
      exit 0;;
    *) printf 'start-real-orchestrator: unknown argument: %s\n' "$1" >&2; exit 2;;
  esac
done
case "$MODE" in homelab|production) ;; *) echo "invalid --mode" >&2; exit 2;; esac
[ -n "$ENV_FILE" ] || ENV_FILE="/opt/jarvis-v1/shared/$MODE.env"
[ -f "$ENV_FILE" ] || { echo "env file missing: $ENV_FILE" >&2; exit 1; }
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

COMPOSE_FILES=(-f deploy/compose.production.yml)
[ "$MODE" = homelab ] && COMPOSE_FILES+=(-f deploy/compose.homelab.yml)
compose() {
  docker compose --project-name jarvis-v1 --env-file "$ENV_FILE" "${COMPOSE_FILES[@]}" "$@"
}

CONFIG_DIR=${JARVIS_PRIVATE_CONFIG_DIR:-/opt/jarvis-v1/config}
MANIFEST="$CONFIG_DIR/runtime.json"
[ -f "$MANIFEST" ] || {
  echo "real execution is unconfigured: missing $MANIFEST" >&2
  exit 1
}
compose config --quiet
compose run --rm --no-deps orchestrator python -m jarvis_orchestrator.admin \
  runtime inspect --manifest /etc/jarvis-v1/runtime.json

if [ "$VALIDATE_ONLY" = 1 ]; then
  echo "Local runtime configuration is valid but worker/provider capability is unverified."
  exit 0
fi

cat <<'NOTICE'
Starting the real orchestrator may claim already queued REAL runs and invoke the
configured model/worker. This command does not create a job itself.
NOTICE
compose up -d orchestrator
"$ROOT_DIR/scripts/preflight.sh" --mode "$MODE" --env-file "$ENV_FILE" --runtime
