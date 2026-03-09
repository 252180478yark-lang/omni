#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
fi

echo "[infra] checking postgres..."
docker exec omni-postgres pg_isready -U "${POSTGRES_USER:-omni_user}" -d "${POSTGRES_DB:-omni_vibe_db}"

echo "[infra] checking redis..."
docker exec omni-redis redis-cli -a "${REDIS_PASSWORD:-changeme_redis}" ping

echo "[infra] checking pgvector..."
docker exec omni-postgres psql -U "${POSTGRES_USER:-omni_user}" -d "${POSTGRES_DB:-omni_vibe_db}" -c "SELECT extname FROM pg_extension WHERE extname='vector';"

echo "[infra] checking schemas..."
docker exec omni-postgres psql -U "${POSTGRES_USER:-omni_user}" -d "${POSTGRES_DB:-omni_vibe_db}" -c "SELECT schema_name FROM information_schema.schemata WHERE schema_name IN ('identity','ai_hub','knowledge');"

echo "[infra] all checks passed"
