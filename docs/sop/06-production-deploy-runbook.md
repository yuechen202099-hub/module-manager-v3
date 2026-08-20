# Production Deploy Runbook

## Purpose

Standardize the production deployment path for `/opt/module-manager-v2`.

## Preflight

- [ ] User approved production deployment.
- [ ] Current release path recorded.
- [ ] Services checked: `module-manager-v2.service`, `nginx`.
- [ ] Release package verified locally.
- [ ] Local SHA256 recorded.
- [ ] Rollback target identified.

## Backup

Run on server before deployment:

```bash
set -euo pipefail
APP=/opt/module-manager-v2
bash "$APP/current/scripts/production_backup.sh" "$APP" V<version>
```

Backup must include:

- `.env`
- current release archive
- `data`
- `uploads`
- PostgreSQL dump when `DATABASE_URL` is configured
- `SHA256SUMS`

## Upload And Hash

```powershell
scp -i <key.pem> .\build\server-release\module-manager-v2-server-<version>.zip root@<server>:/tmp/
ssh -i <key.pem> root@<server> "sha256sum /tmp/module-manager-v2-server-<version>.zip"
```

The server hash must equal the local hash.

## Deploy

```bash
set -euo pipefail
APP=/opt/module-manager-v2
VERSION=<version>
STAMP=$(date +%Y%m%d_%H%M%S)
REL=$APP/releases/v$VERSION-$STAMP
if ! id -u modulemgr >/dev/null 2>&1; then
  useradd --system --home-dir "$APP" --no-create-home --shell /usr/sbin/nologin modulemgr
fi
install -d -o modulemgr -g modulemgr -m 0750 "$APP/data" "$APP/uploads" "$APP/data/delivery_cache"
install -d -o modulemgr -g modulemgr -m 0750 "$APP/shared"
chown -R modulemgr:modulemgr "$APP/data" "$APP/uploads" "$APP/shared"
chown root:modulemgr "$APP/.env"
chmod 0640 "$APP/.env"
mkdir -p "$REL"
unzip -q /tmp/module-manager-v2-server-$VERSION.zip -d "$REL"
UPLOAD_LINK="$REL/v2-api/app/static/uploads"
if [ -L "$UPLOAD_LINK" ]; then
  rm "$UPLOAD_LINK"
elif [ -d "$UPLOAD_LINK" ]; then
  rmdir "$REL/v2-api/app/static/uploads" || {
    echo "Release package unexpectedly contains files under static/uploads" >&2
    exit 1
  }
elif [ -e "$UPLOAD_LINK" ]; then
  echo "Release package contains a non-directory static/uploads entry" >&2
  exit 1
fi
ln -s "$APP/uploads" "$REL/v2-api/app/static/uploads"
cp -a "$APP/.env" "$REL/.env"
$APP/venv/bin/python -m pip install -r "$REL/v2-api/requirements.txt"
chmod -R g-w,g+rX "$APP/venv"
chgrp -R modulemgr "$APP/venv"
if find "$APP/venv" \( -type f -o -type d \) -perm -g+w -print -quit | grep -q .; then
  echo "Python runtime must not be group-writable" >&2
  exit 1
fi
runuser -u modulemgr -- "$APP/venv/bin/python" -c "from PIL import Image"

# Keep background maintenance stopped until the new API and schema pass health checks.
systemctl stop module-manager-v2-photo-barcode-maintenance.service 2>/dev/null || true
systemctl stop module-manager-v2-photo-barcode-maintenance.timer 2>/dev/null || true
systemctl stop module-manager-v2-photo-barcode-maintenance-enqueue.service 2>/dev/null || true

# The current candidate requires the complete 20260721_0005 -> 20260724_0014 upgrade chain.
set -a
. "$APP/.env"
set +a
cd "$REL/v2-api"
$APP/venv/bin/python -m alembic upgrade head
$APP/venv/bin/python -m alembic current | grep -q "20260724_0014"

install -m 0644 "$REL/infra/module-manager-v2-photo-barcode-maintenance.service" \
  /etc/systemd/system/module-manager-v2-photo-barcode-maintenance.service
install -m 0644 "$REL/infra/module-manager-v2-photo-barcode-maintenance-enqueue.service" \
  /etc/systemd/system/module-manager-v2-photo-barcode-maintenance-enqueue.service
install -m 0644 "$REL/infra/module-manager-v2-photo-barcode-maintenance.timer" \
  /etc/systemd/system/module-manager-v2-photo-barcode-maintenance.timer
install -m 0644 "$REL/infra/module-manager-v2.service" \
  /etc/systemd/system/module-manager-v2.service

ln -sfn "$REL" "$APP/current"
systemctl daemon-reload
systemctl enable module-manager-v2.service
systemctl enable module-manager-v2-photo-barcode-maintenance.service
systemctl enable module-manager-v2-photo-barcode-maintenance.timer
systemctl restart module-manager-v2.service
systemctl is-active module-manager-v2.service
systemctl is-active nginx
systemctl show module-manager-v2.service -p User -p Group -p WorkingDirectory -p ExecStart
```

The `0006` through `0014` migrations are forward-only in this release. A code rollback must keep the database at `20260724_0014`; do not run `alembic downgrade` in production. The API, worker, and enqueue service must all report `modulemgr` as their configured user before the worker is resumed.

## Post-Deploy Health Check

```bash
APP=/opt/module-manager-v2
"$APP/venv/bin/python" "$APP/current/scripts/production_health_check.py" --base-url http://127.0.0.1 --expected-version <version> --env "$APP/.env"
```

Run the production security audit against the real server `.env`:

```bash
APP=/opt/module-manager-v2
SECURITY_ENV_PATH="$APP/.env" "$APP/venv/bin/python" "$APP/current/scripts/audit_production_security.py"
```

Only after the main service, pages, and security audit pass, resume and start the low-load serial worker and the midnight enqueue timer:

```bash
APP=/opt/module-manager-v2
cd "$APP/current/v2-api"
"$APP/venv/bin/python" - <<'PY'
from app.services.barcode_maintenance_worker import set_maintenance_paused

print(set_maintenance_paused(False, "production-deploy"))
PY
systemctl start module-manager-v2-photo-barcode-maintenance.service
systemctl start module-manager-v2-photo-barcode-maintenance.timer
systemctl is-active module-manager-v2-photo-barcode-maintenance.service
systemctl is-active module-manager-v2-photo-barcode-maintenance.timer
systemctl status module-manager-v2-photo-barcode-maintenance-enqueue.service --no-pager || true
```

The worker must remain one process, use batches of at most 20 groups, process serially, and pause 5 seconds after every full batch.

`PHOTO_PROXY_ALLOWED_HOSTS` must list the real external photo source domains. If it is empty, the production image proxy will reject external photo fallback requests under the explicit allowlist policy.

Also verify the public entry:

```powershell
curl.exe -k -s -o NUL -w "%{http_code}" https://<server>/health
curl.exe -k -s -o NUL -w "%{http_code}" https://<server>/project-board
```

## Production Release Retention

After the new release passes health checks, keep 5 recent release directories on the server and rely on GitHub branches/tags plus `ops/releases/` for older history.

Always dry-run first:

```bash
APP=/opt/module-manager-v2
bash "$APP/current/scripts/cleanup_old_releases.sh" "$APP" 5 --dry-run
```

If the dry-run only lists old release directories under `$APP/releases`, run the cleanup:

```bash
APP=/opt/module-manager-v2
bash "$APP/current/scripts/cleanup_old_releases.sh" "$APP" 5
```

Rules:

- Keep the latest 5 release directories by modification time.
- Never delete the directory pointed to by `$APP/current`; if it is outside the latest 5, keep it as an extra safety copy.
- Remove loose `module-manager-v2-server-*.zip` package archives from `$APP/releases`; release packages are retained by GitHub tags/branches and release records instead.
- Do not delete `.env`, `data`, `uploads`, backups, database dumps, or anything outside `$APP/releases`.
- Record the cleanup summary in the release record.

## Completion Evidence

Record in `ops/releases/V<version>.md`:

- backup directory,
- release directory,
- release retention dry-run and cleanup summary,
- local and server hash,
- service status,
- health/API/page check results.
