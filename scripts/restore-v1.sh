#!/usr/bin/env bash
# Validate and restore a V1 backup into a new Compose namespace. Never starts dispatch.
set -euo pipefail
umask 077

root=${JARVIS_V1_ROOT:-/opt/jarvis-v1}
backup=
namespace=
execute=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --backup) backup=$2; shift 2 ;;
    --namespace) namespace=$2; shift 2 ;;
    --execute) execute=1; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
test "$root" = /opt/jarvis-v1 && test "$(readlink -f "$root")" = "$root" || {
  echo 'Expected the dedicated /opt/jarvis-v1 root' >&2; exit 2;
}
test -n "$backup" && test -n "$namespace" || {
  echo 'Usage: restore-v1.sh --backup PATH --namespace jarvis-v1-restore-NAME [--execute]' >&2
  exit 2
}
case "$namespace" in jarvis-v1-restore-[a-zA-Z0-9_-]*) ;; *)
  echo 'Namespace must begin jarvis-v1-restore-' >&2; exit 2;; esac
backup=$(readlink -f "$backup")
case "$backup" in "$root/shared/backups/"*) ;; *)
  echo 'Backup must be below /opt/jarvis-v1/shared/backups' >&2; exit 2;; esac
for file in database.dump artifacts.tar source.tar SHA256SUMS manifest.json manifest.sha256; do
  test -f "$backup/$file" || { echo "Missing backup component: $file" >&2; exit 2; }
done
(cd "$backup" && sha256sum -c SHA256SUMS && sha256sum -c manifest.sha256)
python3 - "$backup/manifest.json" <<'PY'
import json, pathlib, sys
data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
required = {"schema_version", "consistency_protocol", "application_sha", "schema_revision",
            "recovery_generation", "runtime_manifest_sha256", "image_identities", "files",
            "surviving_external_effects", "admission_after_restore"}
missing = sorted(required - data.keys())
if missing:
    raise SystemExit("Manifest missing: " + ", ".join(missing))
if data["secrets_included"] is not False:
    raise SystemExit("Manifest does not assert secret separation")
if data["admission_after_restore"] != "disabled_until-reconciliation":
    raise SystemExit("Manifest does not require disabled dispatch after restore")
print("Manifest valid; surviving external effects:", len(data["surviving_external_effects"]))
PY
if [ "$execute" -ne 1 ]; then
  echo 'Restore validation passed. Re-run with --execute to create the isolated namespace.'
  exit 0
fi

release=$(readlink -f "$root/current")
[[ "$release" == "$root/releases/"* ]] || { echo 'Current V1 release is unavailable' >&2; exit 2; }
env_file="$root/shared/deployment.env"
compose() { docker compose --project-name "$namespace" --env-file "$env_file" -f "$release/deploy/compose.production.yml" "$@"; }
for volume in postgres artifacts source; do
  if docker volume inspect "${namespace}_${volume}" >/dev/null 2>&1; then
    echo "Refusing existing restore volume: ${namespace}_${volume}" >&2
    exit 2
  fi
done
compose up -d --wait postgres
compose run --rm bootstrap
compose exec -T postgres pg_restore -U jarvis_v1_bootstrap -d jarvis_v1 --no-owner \
  < "$backup/database.dump"
# Incrementing the generation fences every authority captured in the backup.
compose exec -T postgres psql -U jarvis_v1_bootstrap -d jarvis_v1 -v ON_ERROR_STOP=1 -c \
  "UPDATE control.recovery_generations SET generation=generation+1, automatic_dispatch_enabled=false, reason='isolated restore pending reconciliation', updated_at=clock_timestamp() WHERE id=1"
for volume in artifacts source; do
  compose run --rm --no-deps --entrypoint tar orchestrator \
    -C "/var/lib/jarvis-v1/$volume" -xf - < "$backup/$volume.tar"
done
actual_schema=$(compose exec -T postgres psql -U jarvis_v1_bootstrap -d jarvis_v1 -Atc \
  "SELECT version_num FROM alembic_version")
expected_schema=$(tr -d '\r\n' < "$backup/schema-revision.txt")
test "$actual_schema" = "$expected_schema" || {
  echo "Restored schema $actual_schema does not match manifest $expected_schema" >&2; exit 2;
}
compose exec -T postgres psql -U jarvis_v1_bootstrap -d jarvis_v1 -Atc \
  "SELECT id, run_id, status, COALESCE(external_id, '') FROM control.effects WHERE status IN ('dispatched','running','cancel_requested','unknown') ORDER BY id" \
  > "$backup/restored-effects-${namespace}.tsv"
echo "Restore created isolated namespace $namespace. API/orchestrator were not started."
echo "Dispatch is fenced and disabled. Reconcile restored-effects-${namespace}.tsv before resume."
