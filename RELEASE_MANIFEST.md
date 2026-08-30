# Module Manager V2 Production Server Release

## Package

- Package: `build/server-release/module-manager-v2-server-3.2.21.zip`
- Name: `module-manager-v2-server-3.2.21.zip`
- Version: 3.2.21
- Generated at: 2026-08-30 20:38:00 +08:00
- Size: 2367192 bytes
- SHA256: c421b326817e4bc0ecd957b8748d49e7decbf2d2a5be3266ef12ceca55566837
- Source commit: 983c911d2e5184fcc64c471c0bb98799eea62c23
- Production release: `/opt/module-manager-v2/releases/v3.2.21-20260830T124356Z`

## Included

- FastAPI application source under v2-api/app
- Vue production bundle under v2-api/app/static/vue
- v2-web source required by docker-compose.yml
- Alembic migration files
- V3.2.0 historical boundaries, immutable V3.2.3 through V3.2.20 records, V3.2.9 Quagga-first scanner regressions, V3.2.13 classification-independent rephoto gates, V3.2.14 archive/manual-demand/source-photo gates, V3.2.15 exception-count/deferred-image gates, V3.2.16 reviewer-claim removal gates, V3.2.17 anomaly-confirmation/meter-module-export gates, V3.2.18 approved-exception closure gates, V3.2.19 terminal meter-number deduplication gates, V3.2.20 effective collector/module display gates, and V3.2.21 audited bulk anomaly approval gates
- Nginx retirement patcher, server migration and manifest signer, Windows-local downloader, verifier tests, operator SOP, and release record
- JSON/PostgreSQL and photo migration scripts under v2-api/scripts
- Requirements and Dockerfile
- Client acceptance gate, demo startup, smoke-check, strict Vue migration verification, PostgreSQL cutover audit, production-readiness verification, and release verification scripts under scripts
- Local static review images and the demo data seed script for pre-production smoke checks
- Nginx and systemd deployment samples under infra
- Client acceptance, final audit, visual QA, signoff, demo, deployment, and production SOP documents under docs
- Production release and incident record templates under ops

## Excluded

- Local virtual environments such as .venv
- Local `.env` files, PEM/key material, credentials, and allowlists
- Runtime data, uploads, delivery caches, local databases, database dumps, migration reports, generated local exports, test results, and coverage output
- Python caches such as __pycache__, .pyc, and .pytest_cache
- Generated build/runtime folders outside this release package

## Demo Commands

.\scripts\run-client-demo.ps1

.\scripts\run-client-acceptance-gate.ps1

.\.venv\Scripts\python.exe .\scripts\smoke-client-demo.py

.\.venv\Scripts\python.exe .\scripts\verify_vue_migration_gate.py --strict-native

.\.venv\Scripts\python.exe .\scripts\verify_postgres_cutover_gate.py

.\.venv\Scripts\python.exe .\scripts\verify-production-readiness.py --example

.\.venv\Scripts\python.exe .\scripts\verify-client-release.py

.\.venv\Scripts\python.exe .\scripts\verify_release_sop.py --version V3.2.21 --phase source

## Verified Package Gates

- Release smoke check must pass unless -SkipSmoke is used
- Demo admin and constructor login are available only for local walkthrough when enabled
- Historical release contracts plus the active V3.2.21 bulk-anomaly-approval, package, and lifecycle contracts must pass
- Vue strict-native production pages are required
- PostgreSQL cutover audit must be reviewed before production deployment
- Production mode disables demo accounts by default
- Production mode disables /docs, /redoc, and /openapi.json by default
- Required client documents and deployment samples are present
- Client signoff checklist is included for payment acceptance
- Production SOP files and release record templates are present

## Production Notes

- Set APP_ENV=production
- Set DEMO_AUTH_ENABLED=false
- Replace APP_SECRET, JWT_SECRET, ADMIN_USERNAME, and ADMIN_PASSWORD
- Confirm /docs, /redoc, and /openapi.json return 404 in production
- Enable HTTPS before real project data is exposed
- Configure PostgreSQL backup before production import
- V3.1-V3.2 migrations `0006` through `0016` are production-irreversible; never run Alembic downgrade. Application rollback keeps the forward schema, and data rollback requires a validated pre-upgrade PostgreSQL backup.
- Use `build/server-release/` packages for production deployment
- Record each production release under `ops/releases/`
- V3.2.0 的历史生产证据仅保留在 `ops/releases/V3.2.0.md`。
