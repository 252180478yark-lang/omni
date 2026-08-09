#!/usr/bin/env bash
# Verify the isolated macOS runtime. Set OMNI_REQUIRE_RECOVERED_DATA=1 to also
# enforce the historical recovered-Windows-data thresholds.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHANGE_ID="${OMNI_CHANGE_ID:-mac-local-dev}"
OWNER="${OMNI_OWNER:-${USER:-mac-developer}}"
RUNTIME_PROFILE="${OMNI_RUNTIME_PROFILE:-content}"
REQUIRE_RECOVERED_DATA="${OMNI_REQUIRE_RECOVERED_DATA:-0}"
VERIFY_TIMEOUT_SECONDS="${OMNI_VERIFY_TIMEOUT_SECONDS:-120}"

case "$RUNTIME_PROFILE" in
  core|content|full) ;;
  *)
    printf 'OMNI_RUNTIME_PROFILE must be core, content, or full (got %s).\n' "$RUNTIME_PROFILE" >&2
    exit 2
    ;;
esac

case "$REQUIRE_RECOVERED_DATA" in
  0|1) ;;
  *)
    printf 'OMNI_REQUIRE_RECOVERED_DATA must be 0 or 1 (got %s).\n' "$REQUIRE_RECOVERED_DATA" >&2
    exit 2
    ;;
esac

if [[ ! "$VERIFY_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  printf 'OMNI_VERIFY_TIMEOUT_SECONDS must be a positive integer (got %s).\n' "$VERIFY_TIMEOUT_SECONDS" >&2
  exit 2
fi

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

required_services=(
  postgres redis ai-provider-hub knowledge-engine frontend
)
if [[ "$RUNTIME_PROFILE" == "content" || "$RUNTIME_PROFILE" == "full" ]]; then
  required_services+=(video-analysis livestream-analysis scout-agent)
fi
if [[ "$RUNTIME_PROFILE" == "full" ]]; then
  required_services+=(news-aggregator ad-review-service nginx)
fi

health_deadline=$((SECONDS + VERIFY_TIMEOUT_SECONDS))
for service in "${required_services[@]}"; do
  state="missing"
  health="unknown"
  while (( SECONDS < health_deadline )); do
    container_id="$(docker compose -f docker-compose.yml ps -q "$service")"
    if [[ -n "$container_id" ]]; then
      state="$(docker inspect --format '{{.State.Status}}' "$container_id")"
      health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}not-configured{{end}}' "$container_id")"
      if [[ "$state" == "running" && ( "$health" == "not-configured" || "$health" == "healthy" ) ]]; then
        break
      fi
      if [[ "$state" == "exited" || "$state" == "dead" ]]; then
        break
      fi
    fi
    sleep 1
  done
  if [[ "$state" != "running" || ( "$health" != "not-configured" && "$health" != "healthy" ) ]]; then
    printf 'Service %s did not become ready within %ss: state=%s health=%s.\n' \
      "$service" "$VERIFY_TIMEOUT_SECONDS" "$state" "$health" >&2
    exit 1
  fi
  printf 'SERVICE %s state=%s health=%s\n' "$service" "$state" "$health"
done

postgres_id="$(docker compose -f docker-compose.yml ps -q postgres)"
database_evidence="$(docker exec "$postgres_id" sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F "|" -v ON_ERROR_STOP=1 -c "select pg_database_size(current_database()), (select count(*) from pg_catalog.pg_tables where schemaname not in ('"'"'pg_catalog'"'"','"'"'information_schema'"'"')), (select count(*) from knowledge.documents), (select count(*) from knowledge.knowledge_chunks), (select count(*) from public.mvp_daily_metric)"')"
IFS='|' read -r database_bytes table_count document_count chunk_count daily_metric_count <<<"$database_evidence"

if [[ "$REQUIRE_RECOVERED_DATA" == "1" ]]; then
  if (( database_bytes < 1000000000 )); then
    printf 'Recovered database is unexpectedly small: %s bytes.\n' "$database_bytes" >&2
    exit 1
  fi
  if (( table_count < 100 || document_count < 1 || chunk_count < 1 || daily_metric_count < 1 )); then
    printf 'Recovered data thresholds failed: tables=%s documents=%s chunks=%s daily_metrics=%s\n' \
      "$table_count" "$document_count" "$chunk_count" "$daily_metric_count" >&2
    exit 1
  fi
fi

curl -fsS --max-time 20 -o /dev/null "http://127.0.0.1:${FRONTEND_PORT}/"
nginx_url="not_started_for_${RUNTIME_PROFILE}_profile"
if [[ "$RUNTIME_PROFILE" == "full" ]]; then
  curl -fsS --max-time 20 -o /dev/null "http://127.0.0.1:${NGINX_HTTP_PORT}/"
  nginx_url="http://127.0.0.1:${NGINX_HTTP_PORT}/"
fi
stats_json="$(curl -fsS --max-time 20 "http://127.0.0.1:${KNOWLEDGE_ENGINE_PORT}/api/v1/knowledge/stats")"
if ! printf '%s' "$stats_json" | jq -e \
  '(.data | type) == "object" and (.data.documents | type) == "number" and (.data.chunks | type) == "number"' \
  >/dev/null; then
  printf 'Product read path returned an invalid knowledge stats payload.\n' >&2
  exit 1
fi
visible_documents="$(printf '%s' "$stats_json" | jq -r '.data.documents')"
visible_chunks="$(printf '%s' "$stats_json" | jq -r '.data.chunks')"
if [[ "$REQUIRE_RECOVERED_DATA" == "1" ]] && (( visible_documents < 1 || visible_chunks < 1 )); then
  printf 'Product read path did not expose recovered knowledge data: documents=%s chunks=%s\n' \
    "$visible_documents" "$visible_chunks" >&2
  exit 1
fi

graph_json="$(curl -fsS --max-time 60 "http://127.0.0.1:${FRONTEND_PORT}/api/omni/system-graph/snapshot")"
if ! printf '%s' "$graph_json" | jq -e \
  '(.snapshot_id | type) == "string" and (.content.commit | type) == "string" and (.content.nodes | type) == "array" and (.content.edges | type) == "array" and (.content.source_results | type) == "array"' \
  >/dev/null; then
  printf 'System graph BFF returned an invalid snapshot payload.\n' >&2
  exit 1
fi
graph_snapshot="$(printf '%s' "$graph_json" | jq -r '.snapshot_id')"
graph_commit="$(printf '%s' "$graph_json" | jq -r '.content.commit')"
graph_nodes="$(printf '%s' "$graph_json" | jq -r '.content.nodes | length')"
graph_edges="$(printf '%s' "$graph_json" | jq -r '.content.edges | length')"
graph_unknowns="$(printf '%s' "$graph_json" | jq -r '[.content.source_results[] | select(.status == "unknown")] | length')"

printf 'DATABASE bytes=%s tables=%s documents=%s chunks=%s daily_metrics=%s\n' \
  "$database_bytes" "$table_count" "$document_count" "$chunk_count" "$daily_metric_count"
printf 'PRODUCT_VISIBLE documents=%s chunks=%s\n' "$visible_documents" "$visible_chunks"
printf 'SYSTEM_GRAPH snapshot=%s commit=%s nodes=%s edges=%s unknown_sources=%s\n' \
  "$graph_snapshot" "$graph_commit" "$graph_nodes" "$graph_edges" "$graph_unknowns"
printf 'RECOVERED_DATA_REQUIRED %s\n' "$REQUIRE_RECOVERED_DATA"
printf 'PROFILE %s\n' "$RUNTIME_PROFILE"
printf 'FRONTEND http://127.0.0.1:%s/\n' "$FRONTEND_PORT"
printf 'NGINX %s\n' "$nginx_url"
