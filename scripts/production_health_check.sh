#!/usr/bin/env bash
set -euo pipefail

APP_BASE="${APP_BASE:-/opt/module-manager-v2}"
CURRENT_DIR="${CURRENT_DIR:-$APP_BASE/current}"
DATA_DIR="${DATA_DIR:-$APP_BASE/data}"
BACKUP_DIR="${BACKUP_DIR:-$APP_BASE/backups/runtime}"
UPLOAD_DIR="${UPLOAD_DIR:-$CURRENT_DIR/v2-api/app/static/uploads}"
DISK_WARN_PERCENT="${DISK_WARN_PERCENT:-70}"
BACKUP_WARN_SECONDS="${BACKUP_WARN_SECONDS:-86400}"

status=0
now="$(date +%s)"
disk_percent="$(df -P "$APP_BASE" | awk 'NR==2 {gsub("%","",$5); print $5}')"
state_file="$DATA_DIR/local_state.json"
state_size=0
upload_size="0"
upload_files=0

if [ -f "$state_file" ]; then
  state_size="$(stat -c%s "$state_file")"
fi

if [ -d "$UPLOAD_DIR" ]; then
  upload_size="$(du -shL "$UPLOAD_DIR" | awk '{print $1}')"
  upload_files="$(find -L "$UPLOAD_DIR" -type f | wc -l | awk '{print $1}')"
fi

latest_backup_epoch=""
latest_backup_path=""
if [ -d "$BACKUP_DIR" ]; then
  latest_line="$(find "$BACKUP_DIR" -mindepth 1 -maxdepth 3 -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 || true)"
  if [ -n "$latest_line" ]; then
    latest_backup_epoch="${latest_line%% *}"
    latest_backup_path="${latest_line#* }"
  fi
fi

echo "module-manager-v2 health"
echo "disk_percent=$disk_percent"
echo "state_file=$state_file"
echo "state_size_bytes=$state_size"
echo "upload_dir=$UPLOAD_DIR"
echo "upload_size=$upload_size"
echo "upload_files=$upload_files"
echo "latest_backup=$latest_backup_path"

if [ "${disk_percent:-0}" -ge "$DISK_WARN_PERCENT" ]; then
  echo "WARN disk usage is above ${DISK_WARN_PERCENT}%"
  status=2
fi

if [ -z "$latest_backup_epoch" ]; then
  echo "WARN no backup found"
  status=2
else
  latest_backup_seconds="${latest_backup_epoch%.*}"
  backup_age="$((now - latest_backup_seconds))"
  echo "backup_age_seconds=$backup_age"
  if [ "$backup_age" -gt "$BACKUP_WARN_SECONDS" ]; then
    echo "WARN latest backup is older than ${BACKUP_WARN_SECONDS}s"
    status=2
  fi
fi

if systemctl is-active --quiet module-manager-v2.service; then
  echo "service=active"
else
  echo "WARN service=inactive"
  status=2
fi

if systemctl is-active --quiet nginx; then
  echo "nginx=active"
else
  echo "WARN nginx=inactive"
  status=2
fi

exit "$status"
