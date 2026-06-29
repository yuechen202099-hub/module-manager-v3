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
APP=/opt/module-manager-v2
VERSION=<version>
STAMP=$(date +%Y%m%d_%H%M%S)
REL=$APP/releases/v$VERSION-$STAMP
mkdir -p "$REL"
unzip -q /tmp/module-manager-v2-server-$VERSION.zip -d "$REL"
cp -a "$APP/.env" "$REL/.env"
$APP/venv/bin/python -m pip install -r "$REL/v2-api/requirements.txt"
ln -sfn "$REL" "$APP/current"
systemctl restart module-manager-v2.service
systemctl is-active module-manager-v2.service
systemctl is-active nginx
```

## Post-Deploy Health Check

```bash
APP=/opt/module-manager-v2
"$APP/venv/bin/python" "$APP/current/scripts/production_health_check.py" --base-url http://127.0.0.1 --expected-version <version> --env "$APP/.env"
```

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
