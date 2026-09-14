#!/usr/bin/env bash
# Create a fresh committed disposable project; refuses an existing destination.
set -euo pipefail

[ $# -eq 1 ] || { echo "usage: $0 ABSOLUTE_EMPTY_DESTINATION" >&2; exit 2; }
destination=$1
case "$destination" in /*) ;; *) echo "destination must be absolute" >&2; exit 2;; esac
[ ! -e "$destination" ] || { echo "destination already exists: $destination" >&2; exit 1; }
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p "$destination"
cp -R "$root/tests/fixtures/phase-00-project/." "$destination/"
git -C "$destination" init -b main
git -C "$destination" config user.name "Jarvis Phase 0 Acceptance"
git -C "$destination" config user.email "jarvis-phase-00@localhost"
git -C "$destination" add -A
git -C "$destination" commit -m "chore: phase 0 acceptance baseline"
printf 'project=%s\nbase_sha=%s\n' "$destination" "$(git -C "$destination" rev-parse HEAD)"
