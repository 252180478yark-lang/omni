#!/usr/bin/env bash
# Verify the isolated macOS runtime and prove recovered Windows data is visible.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHANGE_ID="${OMNI_CHANGE_ID:-mac-local-dev}"
OWNER="${OMNI_OWNER:-${USER:-mac-developer}}"

for tool in docker jq curl python3; do
  command -v "$tool" >/dev/null || {
    printf '%s is required for recovery verification.\n' "$tool" >&2
    exit 1
  }
done

cd "$ROOT"
ALLOCATION_JSON="$(python3 scripts/runtime_allocation.py --root "$ROOT" acquire \
  --change-id "$CHANGE_ID" \
  --owner "$OWNER" \
  --mode write \
  --risk-level R1 \
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

required_services=(
  postgres redis identity-service ai-provider-hub knowledge-engine news-aggregator
  video-analysis livestream-analysis ad-review-service scout-agent frontend nginx
)

for service in "${required_services[@]}"; do
  container_id="$(docker compose -f docker-compose.yml ps -q "$service")"
  if [[ -z "$container_id" ]]; then
    printf 'Missing service container: %s\n' "$service" >&2
    exit 1
  fi
  state="$(docker inspect --format '{{.State.Status}}' "$container_id")"
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}not-configured{{end}}' "$container_id")"
  if [[ "$state" != "running" ]]; then
    printf 'Service %s is %s, expected running.\n' "$service" "$state" >&2
    exit 1
  fi
  if [[ "$health" != "not-configured" && "$health" != "healthy" ]]; then
    printf 'Service %s health is %s, expected healthy.\n' "$service" "$health" >&2
    exit 1
  fi
  printf 'SERVICE %s state=%s health=%s\n' "$service" "$state" "$health"
done

postgres_id="$(docker compose -f docker-compose.yml ps -q postgres)"
database_evidence="$(docker exec "$postgres_id" sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F "|" -v ON_ERROR_STOP=1 -c "select pg_database_size(current_database()), (select count(*) from pg_catalog.pg_tables where schemaname not in ('"'"'pg_catalog'"'"','"'"'information_schema'"'"')), (select count(*) from knowledge.documents), (select count(*) from knowledge.knowledge_chunks), (select count(*) from public.mvp_daily_metric)"')"
IFS='|' read -r database_bytes table_count document_count chunk_count daily_metric_count <<<"$database_evidence"

if (( database_bytes < 1000000000 )); then
  printf 'Recovered database is unexpectedly small: %s bytes.\n' "$database_bytes" >&2
  exit 1
fi
if (( table_count < 100 || document_count < 1 || chunk_count < 1 || daily_metric_count < 1 )); then
  printf 'Recovered data thresholds failed: tables=%s documents=%s chunks=%s daily_metrics=%s\n' \
    "$table_count" "$document_count" "$chunk_count" "$daily_metric_count" >&2
  exit 1
fi

curl -fsS --max-time 20 -o /dev/null "http://127.0.0.1:${FRONTEND_PORT}/"
curl -fsS --max-time 20 -o /dev/null "http://127.0.0.1:${NGINX_HTTP_PORT}/"
stats_json="$(curl -fsS --max-time 20 "http://127.0.0.1:${KNOWLEDGE_ENGINE_PORT}/api/v1/knowledge/stats")"
visible_documents="$(printf '%s' "$stats_json" | jq -r '.data.documents // 0')"
visible_chunks="$(printf '%s' "$stats_json" | jq -r '.data.chunks // 0')"
if (( visible_documents < 1 || visible_chunks < 1 )); then
  printf 'Product read path did not expose recovered knowledge data: documents=%s chunks=%s\n' \
    "$visible_documents" "$visible_chunks" >&2
  exit 1
fi

printf 'DATABASE bytes=%s tables=%s documents=%s chunks=%s daily_metrics=%s\n' \
  "$database_bytes" "$table_count" "$document_count" "$chunk_count" "$daily_metric_count"
printf 'PRODUCT_VISIBLE documents=%s chunks=%s\n' "$visible_documents" "$visible_chunks"
printf 'FRONTEND http://127.0.0.1:%s/\n' "$FRONTEND_PORT"
printf 'NGINX http://127.0.0.1:%s/\n' "$NGINX_HTTP_PORT"
