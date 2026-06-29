# Module Manager V2 Production Server Release

## Package

- Name: module-manager-v2-server-3.0.70
- Version: 3.0.70
- Generated at: 2026-06-29 23:58 +08:00

## Included

- FastAPI application source under v2-api/app
- Vue production bundle under v2-api/app/static/vue
- v2-web source required by docker-compose.yml
- Alembic migration files
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

.\.venv\Scripts\python.exe .\scripts\verify_release_sop.py

## Verified During Packaging

- Release smoke check passes unless -SkipSmoke was used
- Demo admin and reviewer login are available only for local walkthrough when enabled
- Reviewer task ownership uses the logged-in reviewer identity, not a local debug reviewer id
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
- Use `build/server-release/` packages for production deployment
- Record each production release under `ops/releases/`
