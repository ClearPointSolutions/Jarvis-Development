#!/usr/bin/env bash
# Quiesced database/checkpoint/artifact/source backup on an explicitly configured host.
set -euo pipefail
umask 077
root=${JARVIS_V1_ROOT:-/opt/jarvis-v1}
test "$root" = /opt/jarvis-v1 && test "$(readlink -f "$root")" = "$root" || { echo 'Expected the dedicated /opt/jarvis-v1 root' >&2; exit 2; }
release=$(readlink -f "$root/current")
[[ "$release" == "$root/releases/"* ]] || { echo 'Current V1 release is unavailable' >&2; exit 2; }
exec 9>"$root/deployment.lock"
flock -n 9 || { echo 'Deployment/backup already running' >&2; exit 2; }
compose() { docker compose --project-name jarvis-v1 --env-file "$root/shared/deployment.env" -f "$release/deploy/compose.production.yml" "$@"; }
backup="$root/shared/backups/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup"
compose stop api orchestrator
trap 'compose start api orchestrator' EXIT
compose exec -T postgres pg_dump -U jarvis_v1_bootstrap -d jarvis_v1 --format=custom --no-owner > "$backup/database.dump"
for volume in artifacts source; do
  compose run --rm --no-deps --entrypoint tar orchestrator -C "/var/lib/jarvis-v1/$volume" -cf - . > "$backup/$volume.tar"
done
printf '%s\n' "$release" > "$backup/release.txt"
(cd "$backup" && sha256sum database.dump artifacts.tar source.tar release.txt > SHA256SUMS)
printf 'Consistent quiesced backup: %s\n' "$backup"
