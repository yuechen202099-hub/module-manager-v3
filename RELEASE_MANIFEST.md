# Module Manager V2 Production Server Release

## Package

- Package: `build/server-release/module-manager-v2-server-3.2.4.zip`
- Name: `module-manager-v2-server-3.2.4.zip`
- Version: 3.2.4
- Generated at: pending
- Size: pending
- SHA256: pending
- Source commit: pending
- Production release: pending

## Included

- FastAPI application source under v2-api/app
- Vue production bundle under v2-api/app/static/vue
- v2-web source required by docker-compose.yml
- Alembic migration files
- V3.2.0 historical boundaries, V3.2.1/V3.2.2 KPI history, the immutable V3.2.3 export-retirement candidate, and the V3.2.4 HTTPS-compatibility, migration, signer, and OSS-local-export gates
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

.\.venv\Scripts\python.exe .\scripts\verify_release_sop.py --version V3.2.4

## Pending Package Gates

- Release smoke check must pass unless -SkipSmoke is used
- Demo admin and constructor login are available only for local walkthrough when enabled
- The three inverted historical export/UI gates, the retained V3.2.3 contract, and the V3.2.4 HTTPS, route, worker, migration, package, lifecycle, and local-export contract must pass
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
- V3.2.0 的历史生产证据仅保留在 `ops/releases/V3.2.0.md`。
