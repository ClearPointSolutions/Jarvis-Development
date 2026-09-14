#!/usr/bin/env bash
# Supported one-shot owner bootstrap / recovery for a Compose deployment.
#
#   scripts/owner-bootstrap.sh [--env-file PATH] [--homelab] [--username NAME]
#                              [--password-file HOSTFILE] [--reset-password]
#
# Wraps the `owner-bootstrap` Compose service. That service runs
# `python -m jarvis_api.auth.bootstrap` through the container entrypoint as the
# database-owning `jarvis_v1_migrator_login`, so:
#   * DATABASE_URL is resolved from the mounted migrator password file
#     (`docker compose exec api ...` would skip that and fail);
#   * the identity has INSERT on control.users, which the least-privilege
#     jarvis_v1_api_login deliberately does not;
#   * no broad grant is added to the API role.
#
# With no --password-file the container prompts twice for the password without
# echo. --reset-password changes the existing owner's password and revokes every
# session; it never creates a second owner. The command refuses a duplicate
# bootstrap and records the audit events the security model requires.
set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

ENV_FILE=""
HOMELAB=0
USERNAME="${JARVIS_OWNER_USERNAME:-owner}"
PASSWORD_FILE=""
RESET=0

die() { printf 'owner-bootstrap: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --env-file) ENV_FILE=${2:?}; shift 2;;
    --homelab) HOMELAB=1; shift;;
    --username) USERNAME=${2:?}; shift 2;;
    --password-file) PASSWORD_FILE=${2:?}; shift 2;;
    --reset-password) RESET=1; shift;;
    -h|--help) sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) die "unknown argument: $1";;
  esac
done

[ -n "$ENV_FILE" ] || die "--env-file is required (the deployment env file used at install)"
[ -f "$ENV_FILE" ] || die "env file not found: $ENV_FILE"

COMPOSE_FILES=(-f deploy/compose.production.yml)
[ "$HOMELAB" = 1 ] && COMPOSE_FILES+=(-f deploy/compose.homelab.yml)

run_args=(--rm)
cmd=(python -m jarvis_api.auth.bootstrap --username "$USERNAME")
[ "$RESET" = 1 ] && cmd+=(--reset-password)

if [ -n "$PASSWORD_FILE" ]; then
  [ -f "$PASSWORD_FILE" ] || die "password file not found: $PASSWORD_FILE"
  [ -L "$PASSWORD_FILE" ] && die "password file must not be a symlink"
  abs=$(readlink -f -- "$PASSWORD_FILE")
  run_args+=(-T -v "$abs:/run/owner_password:ro")
  cmd+=(--password-file /run/owner_password)
fi

exec docker compose --project-name jarvis-v1 --env-file "$ENV_FILE" \
  "${COMPOSE_FILES[@]}" --profile owner-bootstrap \
  run "${run_args[@]}" owner-bootstrap "${cmd[@]}"
