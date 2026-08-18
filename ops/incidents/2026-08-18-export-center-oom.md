# Export Center OOM and Emergency Retirement Gate

## Incident

- Title: Export center readiness query repeatedly exhausted production memory
- Detected: 2026-08-17 11:41:57 CST
- Emergency Nginx gate installed: 2026-08-18 15:19:09 CST
- Production application version during mitigation: V3.2.2
- Maintenance branch: `production/V3/3.2.3`
- Severity: P0

## Confirmed Evidence and Impact

- Persistent kernel logs from boot `a9a1d4e1297640f4bddd32360504e359` confirm Uvicorn OOM kills on 2026-07-26, 2026-07-27, 2026-07-28, 2026-07-29, 2026-07-31, 2026-08-04, 2026-08-08, and 2026-08-16.
- On 2026-08-17, `/exports` was opened at 11:41:57 CST, `/exports/terminal-readiness?page=1&page_size=20&query=` returned `499` at 11:42:01, the application start then terminated, and the server restarted at 12:16 CST.
- The confirmed readiness path assembled all matching material groups and active-photo `raw_data` before pagination. The production scope was 22,358 material groups, 16,361 active photos, and a 34,617-row joined result.
- The emergency change blocks the retired HTTP surface before requests reach Uvicorn. It does not change PostgreSQL, OSS, application releases, `.env`, data, uploads, backups, or service definitions.

## Root Cause

`PostgresStateRepository._export_center_lightweight_groups()` loaded the full matching group/photo result into Python and only then paginated the assembled objects. Merely opening the export center could trigger this allocation; no export job needed to be created. Production `export_jobs` and `delivery_package_jobs` contained zero rows during the confirmed incident investigation.

## Emergency Nginx Change

- Enabled config: `/etc/nginx/sites-enabled/module-manager-v2.conf`
- Resolved target: `/etc/nginx/sites-available/module-manager-v2.conf`
- Original SHA256: `06e521f5b52ed67b4cde518a23e9eca7c7cc141078dd7eb69f1cf28e59344a4f`
- Patched SHA256: `e03796608b50f0c622a1bfac7acf5ff2a93704ca43bba28bbc6ae1ad363da3c2`
- Exact backup: `/etc/nginx/sites-available/module-manager-v2.conf.pre-export-retirement-20260818_151744`
- Backup SHA256: `06e521f5b52ed67b4cde518a23e9eca7c7cc141078dd7eb69f1cf28e59344a4f`
- Backup metadata: `root:root`, mode `0644`, 2,842 bytes, original mtime preserved.
- Candidate validation: `nginx -t` reported syntax OK and test successful before reload.
- Reload: `systemctl reload nginx` completed successfully; `systemctl is-active nginx` returned `active`.
- Post-change config: `root:root`, mode `0644`, 4,784 bytes.
- The temporary upload `/tmp/module-manager-v2.conf.patched` was removed after successful reload.

The remote install command was guarded by hashes for the live file, backup, and uploaded candidate. If candidate `nginx -t` had failed, it would have copied the exact timestamped backup over the live config, validated the restored config, exited nonzero, and skipped reload.

## HTTP Verification

Production verification was performed against `www.sgcc.online` with Host/SNI preserved and the approved production IP pinned per curl command. The workstation's Clash fake-DNS address `198.18.1.167` accepted TCP but failed the TLS handshake, so `--resolve www.sgcc.online:443:106.14.122.43` was used without changing system network settings.

### Public HTTPS retired paths

| Path | Status |
| --- | ---: |
| `/exports` | 410 |
| `/exports/terminal-readiness` | 410 |
| `/exports/jobs` | 410 |
| `/exports/final-delivery` | 410 |
| `/local-test/export-manifest/final-delivery` | 410 |
| `/local-test/unmatched/export` | 410 |
| `/local-test/photo-barcode/review-groups/export` | 410 |

The `/exports` response body was exactly:

```json
{"detail":"导出中心已下线，请联系管理员由 OSS 导出到本机。"}
```

### Public HTTPS retained paths

| Path | Status |
| --- | ---: |
| `/health` | 200 |
| `/project-board` | 200 |
| `/construction` | 200 |

### Direct public HTTP layer checks

| Path | Status |
| --- | ---: |
| `/exports` | 410 |
| `/exports/jobs` | 410 |
| `/local-test/unmatched/export` | 410 |

## Post-Change Service and Log Evidence

- `nginx.service`: `active`; active since 2026-08-17 12:16:24 CST.
- `module-manager-v2.service`: `active`; active since 2026-08-17 12:16:23 CST.
- `module-manager-v2-photo-barcode-maintenance.service`: `active`; active since 2026-08-17 12:16:29 CST.
- Uvicorn remained listening on `127.0.0.1:8000` with PID 899.
- The Uvicorn `/exports/terminal-readiness` log count on 2026-08-18 was zero before and after the public retired-path probes.
- Current-boot OOM count after the change was zero.
- Nginx and API error-priority journals contained no entries from 2026-08-18 15:19 CST through the 15:21 CST post-check.
- Final `nginx -t` again reported syntax OK and test successful.
- The live config contained exactly two copies of every retired location and exactly two original `location /` markers.

## Rollback

Keep this gate in place during an application rollback to V3.2.2. If the Nginx gate itself must be rolled back, run:

```bash
cp -a /etc/nginx/sites-available/module-manager-v2.conf.pre-export-retirement-20260818_151744 /etc/nginx/sites-available/module-manager-v2.conf && nginx -t && systemctl reload nginx && systemctl is-active nginx
```

After rollback, verify the restored SHA256 is `06e521f5b52ed67b4cde518a23e9eca7c7cc141078dd7eb69f1cf28e59344a4f` and repeat retained-path and service probes.

## Follow-Up

- V3.2.3 must add the FastAPI retirement gate so Nginx is not the only protection.
- V3.2.3 must remove export-center UI/client entry points and disable retired export producers and workers while preserving barcode verification and auto-archive.
- The emergency Nginx block remains in place until an explicitly approved rollback.
