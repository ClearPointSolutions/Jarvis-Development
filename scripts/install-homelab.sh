#!/usr/bin/env bash
# First-install / bootstrap for a Jarvis V1 / Mission Control Core machine.
#
#   scripts/install-homelab.sh [--mode homelab|production] [options]
#
# It provisions everything a clean Ubuntu 24.04 Jarvis-Core needs to serve
# Mission Control from this checkout: directories, secrets, a deployment env
# file, local images (unless immutable refs are supplied), PostgreSQL, database
# roles, migrations, checkpoint storage, the API and the web app, then verifies
# readiness and prints the URL. Owner creation is a deliberate separate step
# (scripts/owner-bootstrap.sh), printed at the end.
#
# It NEVER: touches /opt/jarvis, deletes data, runs `docker compose down -v`,
# prints secret values, weakens SSH host-key verification, or turns the
# production API into development mode. `--mode production` keeps JARVIS_ENV
# production, an HTTPS origin, Secure cookies and loopback-only ports, and does
# not configure TLS -- front it with the reviewed proxy in
# deploy/reverse-proxy.nginx.conf.example.
set -euo pipefail

MODE=homelab
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
JARVIS_V1_ROOT=${JARVIS_V1_ROOT:-/opt/jarvis-v1}
LAN_ORIGIN=${JARVIS_PUBLIC_ORIGIN:-}
WEB_PORT=${JARVIS_WEB_PORT:-13000}
WEB_BIND=${JARVIS_WEB_BIND:-0.0.0.0}
PYTHON_IMAGE=${JARVIS_PYTHON_IMAGE:-}
WEB_IMAGE=${JARVIS_WEB_IMAGE:-}
ENV_FILE=""
SKIP_BUILD=0
FORCE_ENV=0
ASSUME_YES=0
PROVIDER_ENDPOINTS=${JARVIS_PROVIDER_ALLOWED_ENDPOINTS:-[]}

log()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[33m    ! %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31mInstall aborted: %s\033[0m\n' "$*" >&2; exit 1; }

usage() {
  sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
  cat <<'OPTS'

Options:
  --mode homelab|production   Deployment profile (default: homelab).
  --root DIR                  V1 root (default: /opt/jarvis-v1 or $JARVIS_V1_ROOT).
  --lan-origin URL           Exact browser origin, e.g. http://192.168.40.105:13000.
                             Required for production (must be https://).
  --web-port PORT            Published Mission Control port (default: 13000).
  --web-bind ADDR            Host interface for the web port (homelab default: 0.0.0.0).
  --python-image REF         Immutable Python image ref; skips the local build.
  --web-image REF            Immutable web image ref; skips the local build.
  --env-file PATH            Deployment env file (default: <root>/shared/<mode>.env).
  --skip-build               Do not build images even if no refs are supplied.
  --force-env                Rewrite the deployment env file if it already exists.
  --yes                      Do not pause for confirmation.
OPTS
}

while [ $# -gt 0 ]; do
  case "$1" in
    --mode) MODE=${2:?}; shift 2;;
    --root) JARVIS_V1_ROOT=${2:?}; shift 2;;
    --lan-origin) LAN_ORIGIN=${2:?}; shift 2;;
    --web-port) WEB_PORT=${2:?}; shift 2;;
    --web-bind) WEB_BIND=${2:?}; shift 2;;
    --python-image) PYTHON_IMAGE=${2:?}; shift 2;;
    --web-image) WEB_IMAGE=${2:?}; shift 2;;
    --env-file) ENV_FILE=${2:?}; shift 2;;
    --skip-build) SKIP_BUILD=1; shift;;
    --force-env) FORCE_ENV=1; shift;;
    --yes|-y) ASSUME_YES=1; shift;;
    -h|--help) usage; exit 0;;
    *) die "unknown argument: $1";;
  esac
done

case "$MODE" in
  homelab|production) ;;
  *) die "--mode must be homelab or production";;
esac
cd "$ROOT_DIR"

COMPOSE_FILES=(-f deploy/compose.production.yml)
[ "$MODE" = homelab ] && COMPOSE_FILES+=(-f deploy/compose.homelab.yml)
SECRET_DIR="$JARVIS_V1_ROOT/secrets"
CONFIG_DIR="$JARVIS_V1_ROOT/config"
[ -n "$ENV_FILE" ] || ENV_FILE="$JARVIS_V1_ROOT/shared/$MODE.env"

compose() {
  docker compose --project-name jarvis-v1 --env-file "$ENV_FILE" "${COMPOSE_FILES[@]}" "$@"
}

# ---------------------------------------------------------------------------
log "1/13  Validate prerequisites"
command -v docker >/dev/null || die "docker is not installed"
docker compose version >/dev/null 2>&1 || die "the Docker Compose v2 plugin is required"
compose_version=$(docker compose version --short 2>/dev/null | sed 's/^v//')
info "docker $(docker --version | awk '{print $3}' | tr -d ,), compose v${compose_version}"
case "$compose_version" in
  ''|0.*|1.*|2.[0-9].*|2.1[0-9].*|2.2[0-3].*)
    die "Docker Compose >= 2.24 is required for the homelab '!override' merge (found ${compose_version:-unknown})";;
esac
for tool in git python3 openssl; do command -v "$tool" >/dev/null || die "$tool is not installed"; done
docker info >/dev/null 2>&1 || die "the Docker daemon is not reachable"

log "2/13  Validate repository state"
head_sha=$(git rev-parse HEAD)
info "checkout $head_sha"
if [ -n "$(git status --porcelain)" ]; then
  warn "working tree is not clean; the install uses the files on disk, not $head_sha"
fi

log "3/13  Create V1 directories"
real_root=$(readlink -f -- "$JARVIS_V1_ROOT" 2>/dev/null || echo "$JARVIS_V1_ROOT")
case "$real_root" in
  /opt/jarvis|/opt/jarvis/*) die "refusing: $JARVIS_V1_ROOT resolves inside the legacy /opt/jarvis tree";;
esac
[ "$real_root" = / ] && die "refusing to use / as the V1 root"
mkdir -p "$JARVIS_V1_ROOT/shared" "$SECRET_DIR" "$CONFIG_DIR"
for d in "$SECRET_DIR" "$CONFIG_DIR" "$JARVIS_V1_ROOT/shared"; do
  case "$(readlink -f -- "$d")" in
    "$real_root"/*) : ;;
    *) die "$d is not under $JARVIS_V1_ROOT";;
  esac
done
info "root $JARVIS_V1_ROOT  secrets $SECRET_DIR  config $CONFIG_DIR"

log "4/13  Provision secrets"
if [ "$(id -u)" != 0 ]; then
  warn "not running as root: secret files cannot be chowned to the container UID 10001."
  warn "Re-run with sudo, or ensure 'docker compose' runs as a user that can read $SECRET_DIR."
fi
python3 scripts/provision_secrets.py --secret-dir "$SECRET_DIR"
python3 scripts/provision_secrets.py --secret-dir "$SECRET_DIR" --check

log "5/13  Create or validate the deployment env file"
if [ "$MODE" = production ]; then
  [ -n "$LAN_ORIGIN" ] || die "production requires --lan-origin https://your.host"
  case "$LAN_ORIGIN" in https://*) ;; *) die "production origin must be https://";; esac
else
  if [ -z "$LAN_ORIGIN" ]; then
    guess_ip=$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n1 || true)
    [ -n "$guess_ip" ] || die "could not detect a LAN IP; pass --lan-origin http://<ip>:$WEB_PORT"
    LAN_ORIGIN="http://$guess_ip:$WEB_PORT"
    warn "no --lan-origin given; using detected $LAN_ORIGIN"
  fi
fi

write_env() {
  ( umask 077
  {
    echo "# Generated by scripts/install-homelab.sh on $(date -u +%FT%TZ) for mode=$MODE."
    echo "# Non-secret runtime configuration only. Secrets live as files in JARVIS_SECRET_DIR."
    echo "JARVIS_PUBLIC_ORIGIN=$LAN_ORIGIN"
    echo "JARVIS_WEB_PORT=$WEB_PORT"
    [ "$MODE" = homelab ] && echo "JARVIS_WEB_BIND=$WEB_BIND"
    echo "JARVIS_API_PORT=18000"
    echo "JARVIS_PYTHON_IMAGE=$PYTHON_IMAGE"
    echo "JARVIS_WEB_IMAGE=$WEB_IMAGE"
    echo "JARVIS_SECRET_DIR=$SECRET_DIR"
    echo "JARVIS_PRIVATE_CONFIG_DIR=$CONFIG_DIR"
    echo "JARVIS_PROVIDER_ALLOWED_ENDPOINTS=$PROVIDER_ENDPOINTS"
    echo "JARVIS_OWNER_USERNAME=owner"
  } > "$ENV_FILE" )
}

if [ -f "$ENV_FILE" ] && [ "$FORCE_ENV" != 1 ]; then
  info "keeping existing $ENV_FILE (use --force-env to rewrite)"
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  PYTHON_IMAGE=${JARVIS_PYTHON_IMAGE:-$PYTHON_IMAGE}
  WEB_IMAGE=${JARVIS_WEB_IMAGE:-$WEB_IMAGE}
  LAN_ORIGIN=${JARVIS_PUBLIC_ORIGIN:-$LAN_ORIGIN}
  WEB_PORT=${JARVIS_WEB_PORT:-$WEB_PORT}
else
  write_env
  info "wrote $ENV_FILE"
fi

log "6/13  Build local images if immutable refs are not supplied"
if [ -z "$PYTHON_IMAGE" ] || [ -z "$WEB_IMAGE" ]; then
  if [ "$SKIP_BUILD" = 1 ]; then
    die "no image refs and --skip-build set; supply --python-image/--web-image"
  fi
  [ -n "$PYTHON_IMAGE" ] || PYTHON_IMAGE="jarvis-v1-python:local-$head_sha"
  [ -n "$WEB_IMAGE" ] || WEB_IMAGE="jarvis-v1-web:local-$head_sha"
  info "building $PYTHON_IMAGE"
  docker build -f deploy/python.Dockerfile -t "$PYTHON_IMAGE" .
  info "building $WEB_IMAGE"
  docker build -f deploy/web.Dockerfile -t "$WEB_IMAGE" .
  export JARVIS_PYTHON_IMAGE="$PYTHON_IMAGE" JARVIS_WEB_IMAGE="$WEB_IMAGE"
  # Persist the resolved refs so redeploys and rollback use the same images.
  tmp_env=$(mktemp)
  grep -v -E '^JARVIS_(PYTHON|WEB)_IMAGE=' "$ENV_FILE" > "$tmp_env" || true
  {
    echo "JARVIS_PYTHON_IMAGE=$PYTHON_IMAGE"
    echo "JARVIS_WEB_IMAGE=$WEB_IMAGE"
  } >> "$tmp_env"
  cat "$tmp_env" > "$ENV_FILE"
  rm -f "$tmp_env"
else
  export JARVIS_PYTHON_IMAGE="$PYTHON_IMAGE" JARVIS_WEB_IMAGE="$WEB_IMAGE"
  info "using supplied images $PYTHON_IMAGE / $WEB_IMAGE"
fi

log "7/13  Validate the merged Compose model"
compose config --quiet
info "compose config is valid for mode=$MODE"

if [ "$ASSUME_YES" != 1 ]; then
  printf '\nProceed to start PostgreSQL, bootstrap roles, migrate and start API+web? [y/N] '
  read -r reply
  case "$reply" in y|Y|yes|YES) ;; *) die "cancelled by operator";; esac
fi

log "8/13  Start PostgreSQL"
compose up -d --wait postgres

log "9/13  Bootstrap database roles"
compose run --rm bootstrap

log "10/13  Apply Alembic migrations and initialize checkpoint storage"
compose run --rm migrate

log "11/13  Start the API"
compose up -d --wait api

log "12/13  Start the web app"
compose up -d --wait web

log "13/13  Verify readiness"
# The API's Host guard rejects a mismatched Host even on /health, so the probe
# must present the configured public authority.
authority=${LAN_ORIGIN#*://}
api_ok=0
for _ in $(seq 1 30); do
  if compose exec -T api python -c "import urllib.request,sys; r=urllib.request.Request('http://127.0.0.1:8000/health',headers={'Host':'$authority'}); sys.exit(0 if urllib.request.urlopen(r,timeout=3).status==200 else 1)" 2>/dev/null; then
    api_ok=1; break
  fi
  sleep 2
done
[ "$api_ok" = 1 ] || die "API /health did not become ready; check 'docker compose logs api'"
info "API liveness OK"

probe_host=127.0.0.1
code=$(curl -fsS -o /dev/null -w '%{http_code}' "http://$probe_host:$WEB_PORT/" 2>/dev/null || true)
[ -n "$code" ] || die "web app not answering on $probe_host:$WEB_PORT; check 'docker compose logs web'"
info "web app HTTP $code on $probe_host:$WEB_PORT"

session_code=$(curl -fsS -o /dev/null -w '%{http_code}' "http://$probe_host:$WEB_PORT/api/v1/session" 2>/dev/null || true)
case "$session_code" in
  401) info "/api/v1/session -> 401 (proxy reached the API; no session yet)";;
  503) die "/api/v1/session -> 503: the web app has no JARVIS_API_URL (proxy misconfigured)";;
  502) die "/api/v1/session -> 502: the web app cannot reach the API service";;
  *)   warn "/api/v1/session -> ${session_code:-no response}; expected 401";;
esac

cat <<DONE

$(printf '\033[32mMission Control is up.\033[0m')

  URL:            $LAN_ORIGIN
  Mode:           $MODE
  Compose files:  ${COMPOSE_FILES[*]}
  Env file:       $ENV_FILE
  Project:        jarvis-v1

Create the initial owner (interactive password prompt):

  scripts/owner-bootstrap.sh --env-file "$ENV_FILE"$([ "$MODE" = homelab ] && echo ' --homelab')

Then sign in at $LAN_ORIGIN.

Non-destructive teardown of V1 services only (data volumes are kept):

  docker compose --project-name jarvis-v1 --env-file "$ENV_FILE" ${COMPOSE_FILES[*]} down
DONE
