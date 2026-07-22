#!/usr/bin/env bash
set -euo pipefail
umask 077

APP_ROOT="${1:-/opt/module-manager-v2}"
MODE="${2:---serve}"
CURRENT="${APP_ROOT}/current"
ENV_FILE="${APP_ROOT}/.env"
PYTHON="${APP_ROOT}/venv/bin/python"
LOCK_FILE="${APP_ROOT}/shared/photo-barcode-maintenance.lock"

case "$MODE" in
  --serve|--enqueue) ;;
  *)
    echo "unsupported barcode maintenance mode: $MODE" >&2
    exit 2
    ;;
esac

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

cd "$CURRENT/v2-api"
WORKER_ARGS=(
  -m app.services.barcode_maintenance_worker
  "$MODE"
  --batch-size 20
  --batch-pause-seconds 5
)

if [ "$MODE" = "--serve" ]; then
  mkdir -p "$(dirname "$LOCK_FILE")"
  exec flock -n "$LOCK_FILE" -- "$PYTHON" "${WORKER_ARGS[@]}"
fi

exec "$PYTHON" "${WORKER_ARGS[@]}"
