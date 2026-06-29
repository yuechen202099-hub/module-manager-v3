#!/usr/bin/env bash
set -euo pipefail
umask 077

APP_ROOT="${1:-/opt/module-manager-v2}"
CURRENT="${APP_ROOT}/current"
ENV_FILE="${APP_ROOT}/.env"
PYTHON="${APP_ROOT}/venv/bin/python"
LOG_DIR="${APP_ROOT}/logs"
LOCK_FILE="${APP_ROOT}/photo-barcode-maintenance.lock"

BATCH_SIZE="${BARCODE_NOT_MATCHED_BATCH_SIZE:-20}"
MAX_BATCHES="${BARCODE_NOT_MATCHED_MAX_BATCHES:-10000}"
GROUP_SLEEP_SECONDS="${BARCODE_NOT_MATCHED_GROUP_SLEEP_SECONDS:-5}"
BATCH_SLEEP_SECONDS="${BARCODE_NOT_MATCHED_BATCH_SLEEP_SECONDS:-0}"
SCAN_MAX_CANDIDATES="${BARCODE_NOT_MATCHED_SCAN_MAX_CANDIDATES:-12}"
USE_OCR="${BARCODE_NOT_MATCHED_USE_OCR:-1}"
RECHECK_ID="${BARCODE_NOT_MATCHED_RECHECK_ID:-not-matched-$(date +%Y%m%d_%H%M%S)}"

mkdir -p "$LOG_DIR"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "$(date -Is) photo barcode maintenance is already running"
  exit 0
fi

for ((batch = 1; batch <= MAX_BATCHES; batch += 1)); do
  command_status=0
  ocr_args=()
  if [ "$USE_OCR" = "1" ] || [ "$USE_OCR" = "true" ] || [ "$USE_OCR" = "yes" ]; then
    ocr_args=(--use-ocr)
  fi
  if report="$("$PYTHON" "$CURRENT/v2-api/scripts/recompute_photo_barcode_checks.py" \
    --env-file "$ENV_FILE" \
    --apply \
    --not-matched-only \
    --not-matched-recheck-id "$RECHECK_ID" \
    --group-limit "$BATCH_SIZE" \
    --group-sleep-seconds "$GROUP_SLEEP_SECONDS" \
    --scan-max-candidates "$SCAN_MAX_CANDIDATES" \
    "${ocr_args[@]}" \
    --auto-archive-passed \
    --auto-archive-actor barcode-maintenance)"; then
    command_status=0
  else
    command_status=$?
  fi

  printf '%s mode=not_matched_rescan batch=%s recheck_id=%s\n%s\n' \
    "$(date -Is)" "$batch" "$RECHECK_ID" "$report" >>"$LOG_DIR/photo-barcode-not-matched-rescan.log"

  if ! metrics="$(printf '%s' "$report" | "$PYTHON" -c 'import json,sys; data=json.load(sys.stdin); print(int(data.get("groups_selected") or 0)); print(int(data.get("groups_seen") or 0)); print(int(data.get("errors") or 0))')"; then
    printf '%s mode=not_matched_rescan stopping_after_invalid_report=1 status=%s\n' \
      "$(date -Is)" "$command_status" >>"$LOG_DIR/photo-barcode-not-matched-rescan.log"
    exit 1
  fi

  selected="$(printf '%s\n' "$metrics" | sed -n '1p')"
  seen="$(printf '%s\n' "$metrics" | sed -n '2p')"
  errors="$(printf '%s\n' "$metrics" | sed -n '3p')"
  printf '%s mode=not_matched_rescan batch=%s selected=%s seen=%s errors=%s\n' \
    "$(date -Is)" "$batch" "$selected" "$seen" "$errors" >>"$LOG_DIR/photo-barcode-not-matched-rescan.log"

  if [ "$errors" -gt 0 ] || [ "$command_status" -ne 0 ]; then
    printf '%s mode=not_matched_rescan stopping_after_errors=%s status=%s\n' \
      "$(date -Is)" "$errors" "$command_status" >>"$LOG_DIR/photo-barcode-not-matched-rescan.log"
    exit 1
  fi

  if [ "$selected" -le 0 ]; then
    printf '%s mode=not_matched_rescan completed=1 recheck_id=%s\n' \
      "$(date -Is)" "$RECHECK_ID" >>"$LOG_DIR/photo-barcode-not-matched-rescan.log"
    break
  fi

  if [ "$BATCH_SLEEP_SECONDS" != "0" ]; then
    sleep "$BATCH_SLEEP_SECONDS"
  fi
done
