# Module Manager V2 Production Server Release

## Package

- Package: `build/server-release/module-manager-v2-server-3.2.1.zip`
- Name: `module-manager-v2-server-3.2.1.zip`
- Version: 3.2.1
- Generated at: 2026-07-24 10:33:21 +08:00
- Size: 1621627 bytes
- SHA256: `9448EDDCA27A36F2DF606EC1BC04A3BED05930B3D4D718E2D10381EE7FAEE6DF`
- Source commit: `fe527eb84064096321e727abf9ccbdc981e10b7e`
- Production release: `/opt/module-manager-v2/releases/v3.2.0-20260724_105649`

## Included

- FastAPI application source under v2-api/app
- Vue production bundle under v2-api/app/static/vue
- v2-web source required by docker-compose.yml
- Alembic migration files
- V3.2.0 data-center and export-center schemas, services, components, migrations `0013`/`0014`, release record, and focused gates
- JSON/PostgreSQL and photo migration scripts under v2-api/scripts
- Requirements and Dockerfile
- Client acceptance gate, demo startup, smoke-check, strict Vue migration verification, PostgreSQL cutover audit, production-readiness verification, and release verification scripts under scripts
- Local static review images and the demo data seed script for pre-production smoke checks
- Nginx and systemd deployment samples under infra
- Client acceptance, final audit, visual QA, signoff, demo, deployment, and production SOP documents under docs
- Production release and incident record templates under ops

## Excluded

- Local virtual environments such as .venv
- Local .env files and secrets
- Runtime data, uploads, local databases, generated test results, and coverage output
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

.\.venv\Scripts\python.exe .\scripts\verify_release_sop.py --version V3.2.1

## Verified During Packaging

- Release smoke check passes unless -SkipSmoke was used
- Demo admin and constructor login are available only for local walkthrough when enabled
- V3.2.0 role, data-center, dashboard-drilldown, export-center, single-export-entry, and release gates pass
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
- V3.1 migrations `0006` through `0012` are production-irreversible; never run Alembic downgrade. Application rollback keeps the forward schema, and data rollback requires a validated pre-upgrade PostgreSQL backup.
- Use `build/server-release/` packages for production deployment
- Record each production release under `ops/releases/`
- V3.2.0 发布前备份：`/opt/module-manager-v2/backups/V3.2.0-pre-20260724_105349`
- V3.2.0 回滚 release：`/opt/module-manager-v2/releases/v3.2.0-20260724_095503`
