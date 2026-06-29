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

## Completion Evidence

Record in `ops/releases/V<version>.md`:

- backup directory,
- release directory,
- local and server hash,
- service status,
- health/API/page check results.
