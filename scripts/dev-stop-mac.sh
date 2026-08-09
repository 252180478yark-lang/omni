#!/usr/bin/env bash
# Stop the isolated macOS Docker development stack without deleting its data.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHANGE_ID="${OMNI_CHANGE_ID:-mac-local-dev}"
OWNER="${OMNI_OWNER:-${USER:-mac-developer}}"
RUNTIME_PROFILE="${OMNI_RUNTIME_PROFILE:-content}"

case "$RUNTIME_PROFILE" in
  core|content|full) ;;
  *)
    printf 'OMNI_RUNTIME_PROFILE must be core, content, or full (got %s).\n' "$RUNTIME_PROFILE" >&2
    exit 2
    ;;
esac

command -v jq >/dev/null || {
  printf 'jq is required to load the isolated runtime environment (brew install jq).\n' >&2
  exit 1
}

cd "$ROOT"
ALLOCATION_JSON="$(python3 scripts/runtime_allocation.py --root "$ROOT" acquire \
  --change-id "$CHANGE_ID" \
  --owner "$OWNER" \
  --mode write \
  --risk-level R1 \
  --runtime-profile "$RUNTIME_PROFILE" \
  --path 'docker-compose.yml' \
  --path 'docker-compose.dev.yml' \
  --path 'scripts/dev-start-mac.sh' \
  --path 'migrations/**' \
  --path 'scripts/apply_migrations.py' \
  --path 'services/**' \
  --path 'frontend/**' \
  --json)"

while IFS= read -r setting; do
  export "$setting"
done < <(printf '%s' "$ALLOCATION_JSON" | jq -r '.environment | to_entries[] | "\(.key)=\(.value)"')

docker compose -f docker-compose.yml stop
docker compose -f docker-compose.yml ps
