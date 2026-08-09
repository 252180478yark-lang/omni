#!/usr/bin/env bash
# Omni local Docker development launcher for macOS.
#
# Starts an isolated, disposable RuntimeAllocation; it never reuses the
# canonical ports, volumes, database, or secret files.  The full application
# stack stays in Docker, which avoids requiring host Python packages.

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

command -v docker >/dev/null || {
  printf 'Docker Desktop is required. Start it, then rerun this script.\n' >&2
  exit 1
}
docker info >/dev/null 2>&1 || {
  printf 'Docker Desktop is not ready. Start it and wait for the engine, then rerun this script.\n' >&2
  exit 1
}
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

python3 -B scripts/runtime_guard.py allocation-preflight \
  --allocation-file "$OMNI_RUNTIME_ALLOCATION_SOURCE" --json >/dev/null

docker compose -f docker-compose.yml up -d --build
docker compose -f docker-compose.yml ps

printf '\nOmni is starting in isolated Docker runtime %s.\n' "$OMNI_RUNTIME_ID"
printf 'Frontend: http://127.0.0.1:%s\n' "$FRONTEND_PORT"
printf 'Nginx:    http://127.0.0.1:%s\n' "$NGINX_HTTP_PORT"
printf 'Logs:     docker compose -f docker-compose.yml logs -f\n'
