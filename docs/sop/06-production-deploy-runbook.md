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
RETIRED_UNITS=(
  module-manager-v2-photo-barcode-maintenance.service
  module-manager-v2-photo-barcode-maintenance-enqueue.service
  module-manager-v2-photo-barcode-maintenance.timer
)

validate_release_directory() {
  local target=$1
  if [ -z "$target" ] || [ ! -d "$target" ]; then
    echo "Release target is missing or is not a directory: $target" >&2
    return 1
  fi
  case "$target" in
    "$APP"/releases/v*) ;;
    *)
      echo "Release target is outside $APP/releases: $target" >&2
      return 1
      ;;
  esac
  if [ ! -f "$target/RELEASE_MANIFEST.md" ]; then
    echo "Release target has no RELEASE_MANIFEST.md: $target" >&2
    return 1
  fi
}

if [ -L "$APP/current" ]; then
  :
else
  echo "$APP/current must be an existing symlink before deployment" >&2
  exit 1
fi
if ! PREVIOUS=$(readlink -f -- "$APP/current"); then
  echo "Unable to resolve the current release symlink" >&2
  exit 1
fi
validate_release_directory "$PREVIOUS"
PREVIOUS_NAME=$(basename "$PREVIOUS")
if [[ "$PREVIOUS_NAME" =~ ^v([0-9]+\.[0-9]+\.[0-9]+)- ]]; then
  PREVIOUS_VERSION=${BASH_REMATCH[1]}
else
  echo "Unable to derive the previous semantic version from: $PREVIOUS" >&2
  exit 1
fi

assert_retired_unit() {
  local unit=$1
  local load_state
  local active_state
  local unit_file_state
  if ! LOAD_STATE=$(systemctl show "$unit" --property=LoadState --value); then
    echo "Unable to query retired unit load state: $unit" >&2
    return 1
  fi
  load_state=$LOAD_STATE
  if [ "$load_state" = "not-found" ]; then
    return 0
  fi
  if ! ACTIVE_STATE=$(systemctl show "$unit" --property=ActiveState --value); then
    echo "Unable to query retired unit active state: $unit" >&2
    return 1
  fi
  active_state=$ACTIVE_STATE
  case "$active_state" in
    inactive|failed) ;;
    *)
      echo "Retired background barcode unit is not inactive: $unit ($active_state)" >&2
      return 1
      ;;
  esac
  if ! UNIT_FILE_STATE=$(systemctl show "$unit" --property=UnitFileState --value); then
    echo "Unable to query retired unit file state: $unit" >&2
    return 1
  fi
  unit_file_state=$UNIT_FILE_STATE
  case "$unit_file_state" in
    disabled|static|indirect|masked) ;;
    *)
      echo "Retired background barcode unit is not disabled: $unit ($unit_file_state)" >&2
      return 1
      ;;
  esac
}

retire_unit() {
  local unit=$1
  local load_state
  if ! LOAD_STATE=$(systemctl show "$unit" --property=LoadState --value); then
    echo "Unable to query retired unit before disabling it: $unit" >&2
    return 1
  fi
  load_state=$LOAD_STATE
  if [ "$load_state" != "not-found" ]; then
    systemctl disable --now "$unit"
  fi
  assert_retired_unit "$unit"
}

wait_for_uvicorn() {
  "$APP/venv/bin/python" - <<'PY'
import socket
import time

deadline = time.monotonic() + 60
while time.monotonic() < deadline:
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=1):
            raise SystemExit(0)
    except OSError:
        time.sleep(1)
raise SystemExit("Uvicorn did not listen on 127.0.0.1:8000 within 60 seconds")
PY
}

rollback_cutover() {
  local original_code=$?
  local restored
  trap - ERR
  set +e
  ROLLBACK_FAILED=0
  if [ "${CUTOVER_PENDING:-0}" -ne 1 ]; then
    ROLLBACK_FAILED=1
  elif ! validate_release_directory "$PREVIOUS"; then
    ROLLBACK_FAILED=1
  elif ! ln -sfn "$PREVIOUS" "$APP/current"; then
    ROLLBACK_FAILED=1
  elif ! RESTORED=$(readlink -f -- "$APP/current"); then
    ROLLBACK_FAILED=1
  else
    restored=$RESTORED
    if [ "$restored" != "$PREVIOUS" ]; then
      ROLLBACK_FAILED=1
    elif ! systemctl daemon-reload; then
      ROLLBACK_FAILED=1
    elif ! systemctl restart module-manager-v2.service; then
      ROLLBACK_FAILED=1
    elif ! wait_for_uvicorn; then
      ROLLBACK_FAILED=1
    elif ! "$APP/venv/bin/python" "$APP/current/scripts/production_health_check.py" \
      --base-url http://127.0.0.1 \
      --expected-version "$PREVIOUS_VERSION" \
      --env "$APP/.env"; then
      ROLLBACK_FAILED=1
    fi
  fi
  if [ "$ROLLBACK_FAILED" -ne 0 ]; then
    echo "Automatic rollback failed; current release state requires manual recovery." >&2
    exit 70
  fi
  exit "$original_code"
}

if ! id -u modulemgr >/dev/null 2>&1; then
  useradd --system --home-dir "$APP" --no-create-home --shell /usr/sbin/nologin modulemgr
fi
install -d -o modulemgr -g modulemgr -m 0750 "$APP/data" "$APP/uploads" "$APP/data/delivery_cache"
install -d -o modulemgr -g modulemgr -m 0750 "$APP/shared"
chown -R modulemgr:modulemgr "$APP/data" "$APP/uploads" "$APP/shared"
chown root:modulemgr "$APP/.env"
chmod 0640 "$APP/.env"
mkdir -p "$REL"
# Nginx serves /static directly as www-data and must be able to traverse the
# immutable release root even when the server umask is 0027.
chmod 0751 "$REL"
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

# V3.2.26 permanently retires background barcode recognition. Disable old
# services before cutover and remove their unit files so a later daemon reload
# cannot bring them back.
for UNIT in "${RETIRED_UNITS[@]}"; do
  retire_unit "$UNIT"
done
for UNIT in "${RETIRED_UNITS[@]}"; do
  assert_retired_unit "$UNIT"
done
rm -f \
  /etc/systemd/system/module-manager-v2-photo-barcode-maintenance.service \
  /etc/systemd/system/module-manager-v2-photo-barcode-maintenance-enqueue.service \
  /etc/systemd/system/module-manager-v2-photo-barcode-maintenance.timer
systemctl daemon-reload
for UNIT in "${RETIRED_UNITS[@]}"; do
  assert_retired_unit "$UNIT"
done

# The current candidate requires the complete 20260721_0005 -> 20260824_0016 upgrade chain.
set -a
. "$APP/.env"
set +a
cd "$REL/v2-api"
$APP/venv/bin/python -m alembic upgrade head
$APP/venv/bin/python -m alembic current | grep -q "20260824_0016"

install -m 0644 "$REL/infra/module-manager-v2.service" \
  /etc/systemd/system/module-manager-v2.service

CUTOVER_PENDING=1
trap rollback_cutover ERR
ln -sfn "$REL" "$APP/current"
systemctl daemon-reload
systemctl enable module-manager-v2.service
systemctl restart module-manager-v2.service
systemctl is-active module-manager-v2.service
systemctl is-active nginx
systemctl show module-manager-v2.service -p User -p Group -p WorkingDirectory -p ExecStart
wait_for_uvicorn
"$APP/venv/bin/python" "$APP/current/scripts/production_health_check.py" \
  --base-url http://127.0.0.1 \
  --expected-version "$VERSION" \
  --env "$APP/.env"
CUTOVER_PENDING=0
trap - ERR
```

The `0006` through `0016` migrations are forward-only in this release. A code rollback must keep the database at `20260824_0016`; do not run `alembic downgrade` in production. The API service must report `modulemgr` as its configured user.

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

Confirm again that all retired background barcode services remain disabled and inactive:

```bash
for UNIT in "${RETIRED_UNITS[@]}"; do
  assert_retired_unit "$UNIT"
done
```

This retirement does not remove construction live scanning, collector-inventory scanning, review-region scanning, or historical recognition results.

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
