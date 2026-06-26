#!/usr/bin/env bash
set -euo pipefail
umask 077

APP_ROOT="${1:-/opt/module-manager-v2}"
VERSION="${2:-manual}"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="$APP_ROOT/backups/${VERSION}-pre-$STAMP"

mkdir -p "$BACKUP_DIR"

cp -a "$APP_ROOT/.env" "$BACKUP_DIR/.env"

CURRENT="$(readlink -f "$APP_ROOT/current")"
printf '%s\n' "$CURRENT" > "$BACKUP_DIR/current_release.txt"
tar -C "$(dirname "$CURRENT")" -czf "$BACKUP_DIR/current_release.tar.gz" "$(basename "$CURRENT")"

tar -C "$APP_ROOT" -czf "$BACKUP_DIR/data.tar.gz" data
tar -C "$APP_ROOT" -czf "$BACKUP_DIR/uploads.tar.gz" uploads

DB_URL="$(grep -E '^DATABASE_URL=' "$APP_ROOT/.env" | head -1 | cut -d= -f2- | tr -d '\"' || true)"
DB_URL="${DB_URL/postgresql+psycopg:\/\//postgresql:\/\/}"
DB_URL="${DB_URL/postgresql+psycopg2:\/\//postgresql:\/\/}"
DB_SERVICE="$BACKUP_DIR/pg_service.conf"

write_pg_service() {
  python3 - "$DB_URL" "$DB_SERVICE" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

url = sys.argv[1]
path = Path(sys.argv[2])
parsed = urlparse(url)
if not parsed.scheme or not parsed.hostname:
    raise SystemExit(2)
fields = {
    "host": parsed.hostname,
    "port": str(parsed.port or 5432),
    "dbname": parsed.path.lstrip("/"),
}
if parsed.username:
    fields["user"] = unquote(parsed.username)
if parsed.password:
    fields["password"] = unquote(parsed.password)
path.write_text("[module_manager_backup]\n" + "\n".join(f"{key}={value}" for key, value in fields.items() if value) + "\n")
PY
  chmod 600 "$DB_SERVICE"
}

if command -v pg_dump >/dev/null 2>&1 && [ -n "$DB_URL" ]; then
  write_pg_service
  PGSERVICEFILE="$DB_SERVICE" pg_dump service=module_manager_backup -Fc -f "$BACKUP_DIR/database.dump"
  PGSERVICEFILE="$DB_SERVICE" pg_dump service=module_manager_backup --schema-only -f "$BACKUP_DIR/database-schema.sql"
  rm -f "$DB_SERVICE"
else
  printf 'pg_dump or DATABASE_URL unavailable\n' > "$BACKUP_DIR/database_backup_skipped.txt"
fi

sha256sum "$BACKUP_DIR"/* | sort -k2 > "$BACKUP_DIR/SHA256SUMS"
chmod -R go-rwx "$BACKUP_DIR"

echo "BACKUP_DIR=$BACKUP_DIR"
ls -lh "$BACKUP_DIR"
