# Server Deployment Prep

This is the lightweight deployment path for the first client-facing build. It is designed for a low-cost 2C2G Linux server.

## Target Topology

- Nginx listens on port `80` for the first HTTP rollout and certificate validation.
- After SSL is issued, Nginx redirects `80` to `443` and forwards HTTPS traffic to FastAPI.
- FastAPI runs on `127.0.0.1:8000`.
- PostgreSQL can run on the same server for the first version.
- Spreadsheet-imported photos remain remote URL data. The app stores URL metadata and does not download spreadsheet photos to local disk.
- Manual补图 accepts image uploads. For production, store these files in OSS/S3-compatible storage or a backed-up upload directory, then persist the served URL/object key as the photo reference.
- The Nginx sample includes baseline hardening headers: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and `Permissions-Policy`.

## Files

- Nginx HTTP sample: `infra/nginx/module-manager-v2.conf`
- Nginx HTTPS sample: `infra/nginx/module-manager-v2.https.conf.example`
- systemd sample: `infra/module-manager-v2.service`
- Environment sample: `.env.example`
- Client demo checklist: `docs/CLIENT_DEMO_READINESS.md`

## Suggested Server Layout

```text
/opt/module-manager-v2/
  .env
  .venv/
  v2-api/
  infra/
  docs/
```

## Environment Values To Change

Before deploying outside local demo, change these values:

```text
APP_ENV=production
APP_SECRET=<strong random value>
JWT_SECRET=<strong random value>
DEMO_AUTH_ENABLED=false
ADMIN_USERNAME=<real admin username>
ADMIN_PASSWORD=<strong password>
DATABASE_URL=<production database url>
```

Demo accounts are acceptable for local client walkthroughs only. When `APP_ENV=production`, demo accounts are disabled by default unless `DEMO_AUTH_ENABLED=true` is explicitly set. A public server must use real account storage or at least strong environment-controlled admin credentials before any production data is imported.

When `APP_ENV=production`, FastAPI API documentation endpoints are disabled: `/docs`, `/redoc`, and `/openapi.json` must return 404. Keep them available only in local/demo mode.

生产安全配置建议同步写入服务器 `.env`：`SECURITY_ALLOWED_ORIGINS` 控制允许携带凭据访问的前端域名，`SECURITY_TRUSTED_HOSTS` 控制可信 Host，`SECURITY_FRAME_ANCESTORS` 控制页面可被哪些站点嵌入，`SECURITY_LOGIN_RATE_LIMIT_PER_MINUTE` 和 `SECURITY_UPLOAD_RATE_LIMIT_PER_MINUTE` 控制登录和上传限流，`MAX_UPLOAD_MB` 与 `MAX_UPLOAD_FILES_PER_REQUEST` 控制单次上传大小和文件数量，`PHOTO_PROXY_ALLOWED_HOSTS` 用于限制照片代理可访问的外部主机。

## Production Preflight

Before exposing real project data, run the production readiness check against the server `.env`:

```bash
./.venv/bin/python scripts/verify-production-readiness.py --env .env
```

On Windows local release verification, the same checker can validate that the sample files are complete:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify-production-readiness.py --example
```

The production check fails if demo authentication is enabled, default secrets remain, the admin password is weak, or the Nginx/systemd deployment samples are missing required settings.
It also checks that the Nginx sample keeps upload limits, reverse proxy forwarding headers, and the baseline security headers.

## Nginx Install Sketch

```bash
sudo cp infra/nginx/module-manager-v2.conf /etc/nginx/sites-available/module-manager-v2.conf
sudo ln -s /etc/nginx/sites-available/module-manager-v2.conf /etc/nginx/sites-enabled/module-manager-v2.conf
sudo nginx -t
sudo systemctl reload nginx
```

Before exposing real project data, add HTTPS with a cloud provider certificate or Certbot.

## Certbot SSL Sketch

Prerequisites:

- Point the domain DNS `A` record to the server public IP.
- Open inbound ports `80` and `443` in the cloud firewall/security group.
- Replace `module.example.com` below with the real domain.

Install Certbot for the server operating system, then issue the certificate. Set the Nginx `server_name` first so Certbot can match the correct site:

```bash
export DOMAIN=your-real-domain.example
sudo sed -i "s/server_name _;/server_name $DOMAIN;/g" /etc/nginx/sites-available/module-manager-v2.conf
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d "$DOMAIN"
sudo certbot renew --dry-run
```

If you prefer to manage the HTTPS Nginx file yourself, issue the certificate first, then install the provided HTTPS sample:

```bash
export DOMAIN=your-real-domain.example
sudo certbot certonly --nginx -d "$DOMAIN"
sudo cp infra/nginx/module-manager-v2.https.conf.example /etc/nginx/sites-available/module-manager-v2.conf
sudo sed -i "s/module.example.com/$DOMAIN/g" /etc/nginx/sites-available/module-manager-v2.conf
sudo nginx -t
sudo systemctl reload nginx
```

Do not enable `module-manager-v2.https.conf.example` before the certificate exists under `/etc/letsencrypt/live/<domain>/`, because `nginx -t` will fail if the certificate files are missing.

## systemd Install Sketch

```bash
sudo cp infra/module-manager-v2.service /etc/systemd/system/module-manager-v2.service
sudo systemctl daemon-reload
sudo systemctl enable module-manager-v2
sudo systemctl start module-manager-v2
sudo systemctl status module-manager-v2
```

## Smoke Checks

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1/login
```

Expected public pages:

- `/login`
- `/project-board`
- `/task-hall`
- `/claim-tasks`
- `/unmatched`

Expected production-hidden endpoints:

- `/docs`
- `/redoc`
- `/openapi.json`

## Backup Notes

- Back up PostgreSQL daily before importing production data.
- Keep imported source spreadsheets with timestamped names.
- Keep export files and import logs for traceability.
- Configure OSS/S3 lifecycle and backup policy before using manual补图 uploads with real production data.
