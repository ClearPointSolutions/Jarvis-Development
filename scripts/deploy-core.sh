#!/usr/bin/env bash
# Explicit side-by-side deployment. `check` never contacts a target.
set -euo pipefail
mode=${1:-check}
root=$(cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
fail() { printf '%s\n' "$1" >&2; exit 2; }
case "$mode" in check|deploy|rollback) ;; *) fail 'Usage: deploy-core.sh check|deploy|rollback' ;; esac
for tool in git ssh scp tar sha256sum; do command -v "$tool" >/dev/null || fail "Required tool missing: $tool"; done
sha=$(git rev-parse HEAD)
[[ "$sha" =~ ^[a-f0-9]{40}$ ]] || fail 'A committed release SHA is required'
test -z "$(git status --porcelain)" || fail 'Commit and verify the release before deployment'
test -f deploy/compose.production.yml || fail 'Production compose file is missing'
if [[ "$mode" == check ]]; then
  printf 'Release: %s\nTarget root: /opt/jarvis-v1\n' "$sha"
  printf '%s\n' 'Local preflight passed. No target contacted.' \
    'Before deploy: configure JARVIS_DEPLOY_TARGET, JARVIS_DEPLOY_KEY and JARVIS_DEPLOY_KNOWN_HOSTS.' \
    'Target prerequisites: Docker Compose, tar, sha256sum, flock, and /opt/jarvis-v1/shared/deployment.env.'
  exit 0
fi
target=${JARVIS_DEPLOY_TARGET:?Explicit user@host required}
key=${JARVIS_DEPLOY_KEY:?Explicit SSH key file required}
pins=${JARVIS_DEPLOY_KNOWN_HOSTS:?Pinned known_hosts file required}
[[ "$target" =~ ^[a-z_][a-z0-9_-]*@[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]] || fail 'Target must be a literal user@host'
test -f "$key" && test -f "$pins" || fail 'SSH credential files are missing'
options=(-F none -i "$key" -o BatchMode=yes -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$pins" -o GlobalKnownHostsFile=none -o IdentitiesOnly=yes -o IdentityAgent=none -o ClearAllForwardings=yes -o ProxyCommand=none)
if [[ "$mode" == deploy ]]; then
  archive=$(mktemp)
  trap 'rm -f -- "$archive"' EXIT
  git archive --format=tar "$sha" > "$archive"
  digest=$(sha256sum "$archive" | cut -d ' ' -f1)
  ssh "${options[@]}" "$target" 'test "$(readlink -f /opt/jarvis-v1)" = /opt/jarvis-v1 && test -f /opt/jarvis-v1/shared/deployment.env && mkdir -p /opt/jarvis-v1/incoming /opt/jarvis-v1/releases'
  scp "${options[@]}" "$archive" "$target:/opt/jarvis-v1/incoming/$sha.tar"
else
  digest=unused
fi
ssh "${options[@]}" "$target" bash -s -- "$mode" "$sha" "$digest" <<'REMOTE'
set -euo pipefail
mode=$1; sha=$2; digest=$3
root=/opt/jarvis-v1
test "$(readlink -f "$root")" = "$root" || { echo 'V1 root must exist and must not be a symlink' >&2; exit 2; }
exec 9>"$root/deployment.lock"
flock -n 9 || { echo 'Another V1 deployment holds the lock' >&2; exit 2; }
compose() { docker compose --project-name jarvis-v1 --env-file "$root/shared/deployment.env" -f "$1/deploy/compose.production.yml" "${@:2}"; }
old=$(readlink -f "$root/current" || true)
if [[ "$mode" == deploy ]]; then
  printf '%s  %s\n' "$digest" "$root/incoming/$sha.tar" | sha256sum -c -
  release="$root/releases/$sha"
  if [[ ! -d "$release" ]]; then mkdir "$release"; tar -xf "$root/incoming/$sha.tar" -C "$release"; fi
else
  release=$(readlink -f "$root/previous")
  [[ "$release" == "$root/releases/"* ]] && test -d "$release" || { echo 'No previous V1 release available' >&2; exit 2; }
  diff -qr "$old/api/migrations" "$release/api/migrations" >/dev/null || { echo 'Schema changed; a consistent backup restore is required before rollback' >&2; exit 2; }
fi
compose "$release" config --quiet
compose "$release" pull
if ! compose "$release" up -d --wait --wait-timeout 180; then
  echo 'V1 startup failed; volumes and release retained for diagnosis' >&2
  exit 1
fi
if [[ -d "$old" && "$old" != "$release" ]]; then ln -sfn "$old" "$root/previous"; fi
ln -sfn "$release" "$root/current"
printf 'V1 release active: %s\n' "$release"
REMOTE
