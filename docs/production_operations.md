# V2.3 Production Operations

This document covers the low-risk production hardening layer for the current
FastAPI + static HTML deployment.

## Daily Backup

Run on the server:

```bash
cd /opt/module-manager-v2/current
bash scripts/production_backup.sh
```

The script creates a timestamped directory under:

```text
/opt/module-manager-v2/backups/runtime/
```

It backs up:

- `/opt/module-manager-v2/data/local_state.json`
- `/opt/module-manager-v2/data/users.json`
- `/opt/module-manager-v2/current/.env`
- `/opt/module-manager-v2/current/v2-api/app/static/uploads`
- PostgreSQL dump when `pg_dump` and `DATABASE_URL` are available

Recommended cron:

```cron
15 2 * * * cd /opt/module-manager-v2/current && bash scripts/production_backup.sh >/opt/module-manager-v2/logs/backup.log 2>&1
```

## Health Check

Run:

```bash
cd /opt/module-manager-v2/current
bash scripts/production_health_check.sh
```

The script fails with exit code `2` when:

- disk usage is above 70%
- no backup exists
- the latest backup is older than 24 hours
- `module-manager-v2.service` is inactive
- `nginx` is inactive

## Restore Drill

1. Stop the application:

```bash
systemctl stop module-manager-v2.service
```

2. Copy the selected backup data back:

```bash
cp /opt/module-manager-v2/backups/runtime/<STAMP>/local_state.json /opt/module-manager-v2/data/local_state.json
cp /opt/module-manager-v2/backups/runtime/<STAMP>/users.json /opt/module-manager-v2/data/users.json
```

3. Restore uploads if needed:

```bash
mkdir -p /opt/module-manager-v2/current/v2-api/app/static/uploads
tar -C /opt/module-manager-v2/current/v2-api/app/static/uploads -xzf /opt/module-manager-v2/backups/runtime/<STAMP>/uploads.tar.gz
```

4. Start the application:

```bash
systemctl start module-manager-v2.service
systemctl status module-manager-v2.service --no-pager
```

5. Verify:

```bash
curl -s http://127.0.0.1:8000/health
bash scripts/production_health_check.sh
```

## OSS Trigger

Keep local uploads for now. Start the OSS migration when any of these is true:

- local uploaded photos exceed 10 GB
- local uploaded photo count exceeds 30,000
- more than one team is using the system in production
- the project requires long-term photo retention independent of the server

The V2.3 code now stores `storage_type` and `storage_key` on photo records so a
future OSS backend can be introduced without changing review and export flows.

## Enable OSS For New Uploads

Install dependencies:

```bash
cd /opt/module-manager-v2/current/v2-api
../.venv/bin/python -m pip install -r requirements.txt
```

Edit `/opt/module-manager-v2/current/.env`:

```env
STORAGE_BACKEND=oss
OSS_ENDPOINT=https://oss-cn-shanghai.aliyuncs.com
OSS_INTERNAL_ENDPOINT=https://oss-cn-shanghai-internal.aliyuncs.com
OSS_BUCKET=<bucket-name>
OSS_ACCESS_KEY_ID=<access-key-id>
OSS_ACCESS_KEY_SECRET=<access-key-secret>
OSS_PREFIX=module-manager-v2
OSS_SIGNED_URL_EXPIRE_SECONDS=3600
OSS_PUBLIC_BASE_URL=
OSS_THUMBNAIL_PROCESS=image/resize,m_lfit,w_360,h_360/quality,q_75
OSS_PREVIEW_PROCESS=image/resize,m_lfit,w_1280,h_1280/quality,q_85
```

Recommended bucket policy:

- private bucket
- same region as the ECS server
- no AccessKey in frontend code
- backend signs preview URLs at read time
- keep `OSS_ENDPOINT` as the public HTTPS endpoint for browser/mobile signed URLs
- set `OSS_INTERNAL_ENDPOINT` to the same-region internal endpoint for server-side upload and migration traffic
- use `thumbnail_url` for lists/cards, `preview_url` for the default review canvas, and `image_url` only for full-size viewing/export

Restart:

```bash
systemctl restart module-manager-v2.service
bash scripts/production_health_check.sh
```

Only new manual补图 and施工上传 photos go to OSS after this switch. Existing local
photos remain readable from `/static/uploads` until a separate migration is run.
