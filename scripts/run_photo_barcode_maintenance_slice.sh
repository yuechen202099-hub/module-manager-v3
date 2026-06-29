#!/usr/bin/env bash
set -euo pipefail
umask 077

APP_ROOT="${1:-/opt/module-manager-v2}"
CURRENT="${APP_ROOT}/current"
ENV_FILE="${APP_ROOT}/.env"
PYTHON="${APP_ROOT}/venv/bin/python"
LOG_DIR="${APP_ROOT}/logs"
LOCK_FILE="${APP_ROOT}/photo-barcode-maintenance.lock"
BATCH_SIZE="${BARCODE_MAINTENANCE_BATCH_SIZE:-20}"
UNREADABLE_RECHECK_ID="${BARCODE_UNREADABLE_RECHECK_ID:-slow-slice-$(date +%Y%m%d)}"
MODE_FILE="${LOG_DIR}/photo-barcode-maintenance-slice-mode"
ARCHIVE_OFFSET_FILE="${LOG_DIR}/photo-barcode-maintenance-archive-offset"

mkdir -p "$LOG_DIR"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "$(date -Is) photo barcode maintenance is already running"
  exit 0
fi

modes=(scan unreadable archive)
mode_index=0
if [ -s "$MODE_FILE" ]; then
  read -r saved_index <"$MODE_FILE" || true
  case "${saved_index:-}" in
    ''|*[!0-9]*) mode_index=0 ;;
    *) mode_index=$((saved_index % ${#modes[@]})) ;;
  esac
fi
mode="${modes[$mode_index]}"
next_index=$(((mode_index + 1) % ${#modes[@]}))

archive_offset=0
if [ -s "$ARCHIVE_OFFSET_FILE" ]; then
  read -r saved_offset <"$ARCHIVE_OFFSET_FILE" || true
  case "${saved_offset:-}" in
    ''|*[!0-9]*) archive_offset=0 ;;
    *) archive_offset="$saved_offset" ;;
  esac
fi

args=(--env-file "$ENV_FILE" --apply --group-limit "$BATCH_SIZE" --auto-archive-passed --auto-archive-actor barcode-maintenance)
case "$mode" in
  scan)
    args+=(--unprocessed-only)
    ;;
  unreadable)
    args+=(--unreadable-only --unreadable-recheck-id "$UNREADABLE_RECHECK_ID")
    ;;
  archive)
    args+=(--archive-ready-only --group-offset "$archive_offset")
    ;;
  *)
    echo "unexpected mode: $mode" >&2
    exit 2
    ;;
esac

command_status=0
if report="$("$PYTHON" "$CURRENT/v2-api/scripts/recompute_photo_barcode_checks.py" "${args[@]}")"; then
  command_status=0
else
  command_status=$?
fi

printf '%s mode=%s_slice\n%s\n' "$(date -Is)" "$mode" "$report" >>"$LOG_DIR/photo-barcode-maintenance.log"
metrics="$(printf '%s' "$report" | "$PYTHON" -c 'import json,sys; data=json.load(sys.stdin); print(int(data.get("groups_selected") or 0)); print(int(data.get("groups_seen") or 0)); print(int(data.get("errors") or 0))')"
selected="$(printf '%s\n' "$metrics" | sed -n '1p')"
seen="$(printf '%s\n' "$metrics" | sed -n '2p')"
errors="$(printf '%s\n' "$metrics" | sed -n '3p')"
if [ "$errors" -gt 0 ] || [ "$command_status" -ne 0 ]; then
  printf '%s mode=%s_slice stopping_after_errors=%s status=%s\n' "$(date -Is)" "$mode" "$errors" "$command_status" >>"$LOG_DIR/photo-barcode-maintenance.log"
  exit 1
fi

printf '%s\n' "$next_index" >"$MODE_FILE"
if [ "$mode" = archive ]; then
  if [ "$seen" -le 0 ]; then
    printf '0\n' >"$ARCHIVE_OFFSET_FILE"
  else
    printf '%s\n' $((archive_offset + BATCH_SIZE)) >"$ARCHIVE_OFFSET_FILE"
  fi
fi
printf '%s mode=%s_slice selected=%s seen=%s errors=%s next_mode=%s\n' "$(date -Is)" "$mode" "$selected" "$seen" "$errors" "${modes[$next_index]}" >>"$LOG_DIR/photo-barcode-maintenance.log"
