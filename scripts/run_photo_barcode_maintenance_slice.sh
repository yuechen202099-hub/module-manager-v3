#!/usr/bin/env bash
set -euo pipefail
umask 077

APP_ROOT="${1:-/opt/module-manager-v2}"
MODE="${2:---serve}"
CURRENT="${APP_ROOT}/current"
ENV_FILE="${APP_ROOT}/.env"
PYTHON="${APP_ROOT}/venv/bin/python"

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
exec "$PYTHON" -m app.services.barcode_maintenance_worker \
  "$MODE" \
  --batch-size "${BARCODE_MAINTENANCE_BATCH_SIZE:-20}" \
  --batch-pause-seconds "${BARCODE_MAINTENANCE_BATCH_PAUSE_SECONDS:-5}"
