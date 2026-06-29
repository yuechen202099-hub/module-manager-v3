#!/usr/bin/env bash
set -euo pipefail
umask 077

APP_ROOT="${1:-/opt/module-manager-v2}"
CURRENT="${APP_ROOT}/current"
ENV_FILE="${APP_ROOT}/.env"
PYTHON="${APP_ROOT}/venv/bin/python"
LOG_DIR="${APP_ROOT}/logs"
LOCK_FILE="${APP_ROOT}/photo-barcode-maintenance.lock"

BATCH_SIZE="${BARCODE_MAINTENANCE_BATCH_SIZE:-50}"
MAX_BATCHES="${BARCODE_MAINTENANCE_MAX_BATCHES:-200}"
SLEEP_SECONDS="${BARCODE_MAINTENANCE_SLEEP_SECONDS:-20}"
UNREADABLE_RECHECK_ID="${BARCODE_UNREADABLE_RECHECK_ID:-$(date +%Y%m%d_%H%M%S)}"

mkdir -p "$LOG_DIR"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "$(date -Is) photo barcode maintenance is already running"
  exit 0
fi

run_batch() {
  local mode="$1"
  shift
  local report
  local metrics
  local selected
  local seen
  local errors
  local command_status
  if report="$("$PYTHON" "$CURRENT/v2-api/scripts/recompute_photo_barcode_checks.py" \
    --env-file "$ENV_FILE" \
    --apply \
    --group-limit "$BATCH_SIZE" \
    "$@")"; then
    command_status=0
  else
    command_status=$?
  fi
  printf '%s mode=%s\n%s\n' "$(date -Is)" "$mode" "$report" >> "$LOG_DIR/photo-barcode-maintenance.log"
  if ! metrics="$(printf '%s' "$report" | "$PYTHON" -c 'import json,sys; data=json.load(sys.stdin); print(int(data.get("groups_selected") or 0)); print(int(data.get("groups_seen") or 0)); print(int(data.get("errors") or 0))')"; then
    printf '%s mode=%s stopping_after_invalid_report=1 status=%s\n' "$(date -Is)" "$mode" "$command_status" >> "$LOG_DIR/photo-barcode-maintenance.log"
    return 1
  fi
  selected="$(printf '%s\n' "$metrics" | sed -n '1p')"
  seen="$(printf '%s\n' "$metrics" | sed -n '2p')"
  errors="$(printf '%s\n' "$metrics" | sed -n '3p')"
  if [ "$errors" -gt 0 ] || [ "$command_status" -ne 0 ]; then
    printf '%s mode=%s stopping_after_errors=%s status=%s\n' "$(date -Is)" "$mode" "$errors" "$command_status" >> "$LOG_DIR/photo-barcode-maintenance.log"
    return 1
  fi
  printf '%s %s' "$selected" "$seen"
}

for mode in scan unreadable archive; do
  offset=0
  for ((batch = 1; batch <= MAX_BATCHES; batch += 1)); do
    if [ "$mode" = "scan" ]; then
      result="$(run_batch "$mode" --unprocessed-only --auto-archive-passed --auto-archive-actor barcode-maintenance)"
    elif [ "$mode" = "unreadable" ]; then
      result="$(run_batch "$mode" --unreadable-only --unreadable-recheck-id "$UNREADABLE_RECHECK_ID" --auto-archive-passed --auto-archive-actor barcode-maintenance)"
    else
      result="$(run_batch "$mode" --archive-ready-only --auto-archive-passed --auto-archive-actor barcode-maintenance --group-offset "$offset")"
    fi
    selected="$(printf '%s\n' "$result" | awk '{print $1}')"
    seen="$(printf '%s\n' "$result" | awk '{print $2}')"
    if [ "$selected" -le 0 ]; then
      if [ "$mode" = "scan" ] || [ "$mode" = "unreadable" ] || [ "$seen" -le 0 ]; then
        break
      fi
    fi
    if [ "$mode" = "archive" ]; then
      offset=$((offset + BATCH_SIZE))
    fi
    sleep "$SLEEP_SECONDS"
  done
done
