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
git -C "$release" rev-parse HEAD > "$backup/application-sha.txt"
compose config --images | sort -u > "$backup/images.txt"
compose exec -T postgres psql -U jarvis_v1_bootstrap -d jarvis_v1 -Atc \
  "SELECT version_num FROM alembic_version" > "$backup/schema-revision.txt"
compose exec -T postgres psql -U jarvis_v1_bootstrap -d jarvis_v1 -Atc \
  "SELECT generation || '|' || automatic_dispatch_enabled FROM control.recovery_generations WHERE id=1" \
  > "$backup/recovery-generation.txt"
# This is an inventory, not an assertion that a remote process stopped with Core.
compose exec -T postgres psql -U jarvis_v1_bootstrap -d jarvis_v1 -AtF $'\t' -c \
  "SELECT id, run_id, status, COALESCE(external_id, ''), fence_generation FROM control.effects WHERE status IN ('dispatched','running','cancel_requested','unknown') ORDER BY id" \
  > "$backup/external-effects.tsv"
compose exec -T postgres psql -U jarvis_v1_bootstrap -d jarvis_v1 -Atc \
  "SELECT COALESCE(runtime_manifest_sha256, 'unavailable') FROM control.orchestrator_instances ORDER BY heartbeat_at DESC LIMIT 1" \
  > "$backup/runtime-manifest-sha256.txt"
(cd "$backup" && sha256sum database.dump artifacts.tar source.tar release.txt application-sha.txt images.txt schema-revision.txt recovery-generation.txt external-effects.tsv runtime-manifest-sha256.txt > SHA256SUMS)
python3 - "$backup" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
checksums = {}
for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
    digest, name = line.split(maxsplit=1)
    checksums[name] = digest
effects = []
for line in (root / "external-effects.tsv").read_text(encoding="utf-8").splitlines():
    if line:
        effect, run, status, external, generation = line.split("\t")
        effects.append({"effect_id": effect, "run_id": run, "status": status,
                        "external_id": external or None, "fence_generation": int(generation)})
manifest = {
    "schema_version": "1.0",
    "consistency_protocol": "api-and-orchestrator-quiesced-before-dump-and-volume-capture",
    "application_sha": (root / "application-sha.txt").read_text().strip(),
    "schema_revision": (root / "schema-revision.txt").read_text().strip(),
    "recovery_generation": (root / "recovery-generation.txt").read_text().strip(),
    "runtime_manifest_sha256": (root / "runtime-manifest-sha256.txt").read_text().strip(),
    "image_identities": (root / "images.txt").read_text().splitlines(),
    "files": checksums,
    "surviving_external_effects": effects,
    "secrets_included": False,
    "admission_after_restore": "disabled_until-reconciliation",
}
payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
(root / "manifest.json").write_text(payload, encoding="utf-8")
(root / "manifest.sha256").write_text(hashlib.sha256(payload.encode()).hexdigest() + "  manifest.json\n")
PY
printf 'Consistent quiesced backup: %s\n' "$backup"
