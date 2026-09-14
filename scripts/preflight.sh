#!/usr/bin/env bash
# Configuration and readiness preflight for a Jarvis V1 Compose deployment.
#
#   scripts/preflight.sh [--mode homelab|production] [--env-file PATH] [--runtime]
#
# Each check prints PASS, FAIL or SKIP with a specific, actionable reason. The
# script exits non-zero if any check FAILs (SKIP does not fail it). It never
# prints secret values and never starts or stops services.
set -uo pipefail

MODE=homelab
ENV_FILE=""
RUNTIME=auto
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

while [ $# -gt 0 ]; do
  case "$1" in
    --mode) MODE=${2:?}; shift 2;;
    --env-file) ENV_FILE=${2:?}; shift 2;;
    --runtime) RUNTIME=force; shift;;
    --no-runtime) RUNTIME=off; shift;;
    -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) printf 'preflight: unknown argument: %s\n' "$1" >&2; exit 2;;
  esac
done
case "$MODE" in homelab|production) ;; *) echo "preflight: --mode must be homelab or production" >&2; exit 2;; esac
[ -n "$ENV_FILE" ] || ENV_FILE="/opt/jarvis-v1/shared/$MODE.env"

FAILS=0
pass() { printf '  \033[32mPASS\033[0m  %s\n' "$*"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; FAILS=$((FAILS + 1)); }
skip() { printf '  \033[33mSKIP\033[0m  %s\n' "$*"; }
hdr()  { printf '\n\033[1m%s\033[0m\n' "$*"; }

COMPOSE_FILES=(-f deploy/compose.production.yml)
[ "$MODE" = homelab ] && COMPOSE_FILES+=(-f deploy/compose.homelab.yml)
compose() { docker compose --project-name jarvis-v1 --env-file "$ENV_FILE" "${COMPOSE_FILES[@]}" "$@"; }

CONFIG_JSON=""
load_config() {
  [ -n "$CONFIG_JSON" ] && return 0
  CONFIG_JSON=$(compose config --format json 2>/dev/null) || CONFIG_JSON=""
  [ -n "$CONFIG_JSON" ]
}
cfg() { # cfg <python-expression over `c` (the parsed config dict)>
  printf '%s' "$CONFIG_JSON" | python3 -c "import json,sys; c=json.load(sys.stdin); print($1)" 2>/dev/null
}

hdr "Host tooling"
if command -v docker >/dev/null; then pass "docker present ($(docker --version | awk '{print $3}' | tr -d ,))"; else fail "docker not installed"; fi
if docker compose version >/dev/null 2>&1; then
  cv=$(docker compose version --short 2>/dev/null | sed 's/^v//')
  case "$cv" in
    ''|0.*|1.*|2.[0-9].*|2.1[0-9].*|2.2[0-3].*) fail "Docker Compose $cv < 2.24 (needed for the homelab '!override' merge)";;
    *) pass "Docker Compose v$cv";;
  esac
else
  fail "Docker Compose v2 plugin missing"
fi
command -v python3 >/dev/null && pass "python3 present" || fail "python3 not installed"
if docker info >/dev/null 2>&1; then pass "Docker daemon reachable"; else fail "Docker daemon not reachable"; fi

hdr "Deployment env and directories"
if [ -f "$ENV_FILE" ]; then
  pass "env file $ENV_FILE exists"
  if grep -qvE '^[[:space:]]*(#|$|[A-Za-z_][A-Za-z0-9_]*=)' "$ENV_FILE"; then
    fail "env file has lines that are not KEY=value or comments"
  else
    pass "env file syntax is KEY=value"
  fi
  # shellcheck disable=SC1090
  set -a; . "$ENV_FILE"; set +a
else
  fail "env file $ENV_FILE not found (run scripts/install-homelab.sh --mode $MODE)"
fi
SECRET_DIR=${JARVIS_SECRET_DIR:-/opt/jarvis-v1/secrets}
CONFIG_DIR=${JARVIS_PRIVATE_CONFIG_DIR:-/opt/jarvis-v1/config}
[ -d "$SECRET_DIR" ] && pass "secret dir $SECRET_DIR exists" || fail "secret dir $SECRET_DIR missing"
[ -d "$CONFIG_DIR" ] && pass "config dir $CONFIG_DIR exists" || fail "config dir $CONFIG_DIR missing"
if [ -d "$SECRET_DIR" ]; then
  if python3 scripts/provision_secrets.py --secret-dir "$SECRET_DIR" --check >/dev/null 2>&1; then
    pass "secret files present, in-range, mode denies group/other"
  else
    fail "secret files failed provision_secrets.py --check (run: python3 scripts/provision_secrets.py --secret-dir $SECRET_DIR --check)"
  fi
fi

hdr "Compose model"
if load_config; then
  pass "compose config is valid for mode=$MODE"
  api_url=$(cfg "c['services']['web']['environment'].get('JARVIS_API_URL','')")
  [ "$api_url" = "http://api:8000" ] && pass "web JARVIS_API_URL=$api_url" || fail "web JARVIS_API_URL is '$api_url', expected http://api:8000"
  web_ports=$(cfg "len(c['services']['web'].get('ports',[]))")
  [ "$web_ports" = 1 ] && pass "web publishes exactly one port" || fail "web publishes $web_ports port mappings (expected 1; check the homelab override)"
  env_mode=$(cfg "c['services']['api']['environment'].get('JARVIS_ENV','')")
  cookie=$(cfg "c['services']['api']['environment'].get('JARVIS_COOKIE_SECURE','')")
  origin=$(cfg "c['services']['api']['environment'].get('JARVIS_PUBLIC_ORIGIN','')")
  web_ip=$(cfg "c['services']['web']['ports'][0].get('host_ip','')")
  api_ip=$(cfg "c['services']['api']['ports'][0].get('host_ip','')")
  [ -n "$origin" ] && pass "public origin $origin" || fail "JARVIS_PUBLIC_ORIGIN is empty"
  if [ "$MODE" = production ]; then
    [ "$env_mode" = production ] && pass "API JARVIS_ENV=production" || fail "API JARVIS_ENV=$env_mode (production expected)"
    case "$origin" in https://*) pass "origin is HTTPS";; *) fail "production origin must be https:// (got $origin)";; esac
    [ "$cookie" = true ] && pass "Secure cookies on" || fail "JARVIS_COOKIE_SECURE=$cookie (must be true in production)"
    [ "$api_ip" = 127.0.0.1 ] && pass "API port bound to loopback" || fail "API port host_ip=$api_ip (production must stay loopback)"
    [ "$web_ip" = 127.0.0.1 ] && pass "web port bound to loopback (front with the TLS proxy)" || fail "web port host_ip=$web_ip (production must stay loopback)"
  else
    [ "$env_mode" = development ] && pass "API JARVIS_ENV=development (homelab)" || fail "homelab overlay not applied: JARVIS_ENV=$env_mode"
    [ "$cookie" = false ] && pass "Secure cookies off (homelab HTTP)" || fail "homelab expects JARVIS_COOKIE_SECURE=false, got $cookie"
    case "$origin" in http://*|https://*) pass "origin scheme ok";; *) fail "JARVIS_PUBLIC_ORIGIN must be an absolute origin";; esac
    [ "$web_ip" != 127.0.0.1 ] && pass "web port exposed on $web_ip for the LAN" || fail "homelab web port is loopback-only; set JARVIS_WEB_BIND"
  fi
  for var in JARVIS_PYTHON_IMAGE JARVIS_WEB_IMAGE; do
    ref=$(eval "printf '%s' \"\${$var:-}\"")
    if [ -z "$ref" ]; then fail "$var is not set in $ENV_FILE"
    elif docker image inspect "$ref" >/dev/null 2>&1; then pass "$var=$ref present locally"
    else skip "$var=$ref not present locally (pull or build before deploy)"
    fi
  done
else
  fail "docker compose config failed (run: compose ${COMPOSE_FILES[*]} --env-file $ENV_FILE config)"
fi

pin=$(grep -oE 'EXPECTED_SCHEMA_REVISION = "[0-9]+"' api/app/jarvis_api/auth/routes.py | grep -oE '[0-9]+' || true)

hdr "Secret readability from the container UID"
py_ref=${JARVIS_PYTHON_IMAGE:-}
if [ -z "$py_ref" ] || ! docker image inspect "$py_ref" >/dev/null 2>&1; then
  skip "Python image not available locally; cannot test in-container reads"
else
  out=$(compose run --rm --no-deps --entrypoint sh api -c \
    'id -u; for f in /run/secrets/*; do [ -r "$f" ] || echo "UNREADABLE $f"; done' 2>/dev/null)
  uid=$(printf '%s\n' "$out" | head -n1)
  if printf '%s\n' "$out" | grep -q UNREADABLE; then
    fail "the container UID ($uid) cannot read: $(printf '%s\n' "$out" | grep UNREADABLE | tr '\n' ' ')"
  elif [ "$uid" = 10001 ]; then
    pass "container UID 10001 can read every mounted secret"
  else
    fail "python image runs as UID '$uid', expected 10001"
  fi
fi

RUN_LIVE=0
if [ "$RUNTIME" = force ]; then RUN_LIVE=1
elif [ "$RUNTIME" = auto ] && docker compose --project-name jarvis-v1 ps --status running -q 2>/dev/null | grep -q .; then RUN_LIVE=1
fi

hdr "Runtime readiness"
if [ "$RUN_LIVE" != 1 ]; then
  skip "stack not running (pass --runtime to force these checks)"
else
  if compose exec -T postgres pg_isready -U jarvis_v1_bootstrap -d jarvis_v1 >/dev/null 2>&1; then
    pass "PostgreSQL accepts connections"
    rev=$(compose exec -T postgres psql -U jarvis_v1_bootstrap -d jarvis_v1 -tAc 'select version_num from alembic_version' 2>/dev/null | tr -d '[:space:]')
    if [ -z "$rev" ]; then fail "alembic_version has no row (migrations not applied)"
    elif [ -n "$pin" ] && [ "$rev" != "$pin" ]; then fail "schema revision $rev != code pin $pin (run the migrate step)"
    else pass "schema revision $rev matches the code pin"
    fi
  else
    fail "PostgreSQL not reachable inside the project"
  fi
  authority=${JARVIS_PUBLIC_ORIGIN#*://}
  if compose exec -T api python -c "import urllib.request,sys; r=urllib.request.Request('http://127.0.0.1:8000/health',headers={'Host':'$authority'}); sys.exit(0 if urllib.request.urlopen(r,timeout=3).status==200 else 1)" 2>/dev/null; then
    pass "API /health ready"
  else
    fail "API /health not ready (docker compose logs api)"
  fi
  wp=${JARVIS_WEB_PORT:-13000}
  code=$(curl -fsS -o /dev/null -w '%{http_code}' "http://127.0.0.1:$wp/" 2>/dev/null || true)
  [ -n "$code" ] && pass "web app answers HTTP $code on 127.0.0.1:$wp" || fail "web app not answering on 127.0.0.1:$wp"
  sc=$(curl -fsS -o /dev/null -w '%{http_code}' "http://127.0.0.1:$wp/api/v1/session" 2>/dev/null || true)
  case "$sc" in
    401) pass "/api/v1/session -> 401 (proxy reaches the API)";;
    503) fail "/api/v1/session -> 503 (web app missing JARVIS_API_URL)";;
    502) fail "/api/v1/session -> 502 (web app cannot reach the API)";;
    *)   fail "/api/v1/session -> ${sc:-no response} (expected 401)";;
  esac
fi

hdr "Result"
if [ "$FAILS" -eq 0 ]; then
  printf '\033[32mpreflight passed\033[0m\n'; exit 0
else
  printf '\033[31mpreflight failed: %d check(s)\033[0m\n' "$FAILS"; exit 1
fi
