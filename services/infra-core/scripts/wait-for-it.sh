#!/usr/bin/env sh
set -eu

usage() {
  echo "Usage: $0 host:port [--timeout=30] [--strict] [--] [command ...]"
}

if [ "$#" -lt 1 ]; then
  usage
  exit 1
fi

TARGET="$1"
shift

HOST="${TARGET%:*}"
PORT="${TARGET##*:}"
TIMEOUT=30
STRICT=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --timeout=*)
      TIMEOUT="${1#*=}"
      shift
      ;;
    --strict)
      STRICT=1
      shift
      ;;
    --)
      shift
      break
      ;;
    *)
      break
      ;;
  esac
done

CMD="$*"
START_TS="$(date +%s)"

echo "[wait-for-it] waiting for ${HOST}:${PORT}, timeout=${TIMEOUT}s"
while :; do
  if nc -z "$HOST" "$PORT" >/dev/null 2>&1; then
    echo "[wait-for-it] ${HOST}:${PORT} is available"
    if [ -n "$CMD" ]; then
      exec sh -c "$CMD"
    fi
    exit 0
  fi

  NOW_TS="$(date +%s)"
  ELAPSED="$((NOW_TS - START_TS))"
  if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
    echo "[wait-for-it] timeout after ${TIMEOUT}s for ${HOST}:${PORT}" >&2
    if [ "$STRICT" -eq 1 ]; then
      exit 1
    fi
    if [ -n "$CMD" ]; then
      exec sh -c "$CMD"
    fi
    exit 0
  fi
  sleep 1
done
