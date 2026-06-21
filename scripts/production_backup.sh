#!/usr/bin/env bash
set -euo pipefail

APP_BASE="${APP_BASE:-/opt/module-manager-v2}"
CURRENT_DIR="${CURRENT_DIR:-$APP_BASE/current}"
DATA_DIR="${DATA_DIR:-$APP_BASE/data}"
BACKUP_ROOT="${BACKUP_ROOT:-$APP_BASE/backups/runtime}"
UPLOAD_DIR="${UPLOAD_DIR:-$CURRENT_DIR/v2-api/app/static/uploads}"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
DEST="$BACKUP_ROOT/$STAMP"

mkdir -p "$DEST"
chmod 700 "$DEST"

copy_if_exists() {
  local src="$1"
  local dst="$2"
  if [ -e "$src" ]; then
    cp -a "$src" "$dst"
  fi
}

copy_if_exists "$DATA_DIR/local_state.json" "$DEST/local_state.json"
copy_if_exists "$DATA_DIR/users.json" "$DEST/users.json"
copy_if_exists "$CURRENT_DIR/.env" "$DEST/env.backup"
if [ -f "$DEST/env.backup" ]; then
  chmod 600 "$DEST/env.backup"
fi

if [ -d "$UPLOAD_DIR" ]; then
  tar -C "$UPLOAD_DIR" -czf "$DEST/uploads.tar.gz" .
fi

if [ -f "$CURRENT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$CURRENT_DIR/.env"
  set +a
fi

if command -v pg_dump >/dev/null 2>&1 && [ -n "${DATABASE_URL:-}" ]; then
  if ! pg_dump "$DATABASE_URL" -Fc -f "$DEST/postgres.dump" 2>"$DEST/postgres.dump.err"; then
    echo "pg_dump_failed" > "$DEST/postgres.dump.status"
  else
    rm -f "$DEST/postgres.dump.err"
    echo "ok" > "$DEST/postgres.dump.status"
  fi
fi

cat > "$DEST/manifest.txt" <<EOF
created_at_utc=$STAMP
app_base=$APP_BASE
current_dir=$CURRENT_DIR
data_dir=$DATA_DIR
upload_dir=$UPLOAD_DIR
hostname=$(hostname)
disk=$(df -h "$APP_BASE" | tail -n 1)
EOF

echo "$DEST"
