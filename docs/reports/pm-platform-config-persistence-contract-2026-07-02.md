# PM Platform Project Config Persistence Contract

Date: 2026-07-02

## Feature Scope

This package adds a read-only API contract preview for future platform project configuration persistence.

New API:

```text
GET /projects/{project_id}/persistence/contract
```

The route returns how an existing platform project definition would map into the future PostgreSQL persistence slice:

- target tables,
- config record preview,
- normalized field schema,
- normalized workflow definition,
- round-trip preservation result,
- migration gates,
- safety flags.

This package uses the current local JSON project draft store as the source of truth. It does not create an Alembic migration and does not connect to PostgreSQL.

## Product Fit

The test data uses the "更换终端" project shape:

- main field: `terminal`,
- aggregate field: `station_area`,
- child/site fields: old terminal, communication module, new SIM card,
- site photo fields: before photo and after photo,
- workflow nodes: project setup, field schema, construction collection, review, delivery archive.

This keeps the persistence readiness work tied to real operator configuration instead of an abstract database exercise.

## Changed Files

- `v2-api/app/services/platform/config_persistence_contract.py`
- `v2-api/app/api/routes/projects.py`
- `v2-api/tests/test_platform_project_config_persistence_contract.py`
- `scripts/verify_platform_project_config_persistence_contract.py`
- `docs/superpowers/plans/2026-07-02-platform-project-config-persistence-contract.md`

## Verification

Fresh verification run:

- `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_project_config_persistence_contract.py -q`
  - Result: `1 passed, 1 warning in 1.34s`
- `.\.venv\Scripts\python.exe scripts\verify_platform_project_config_persistence_contract.py`
  - Result: `[OK] platform project config persistence contract is consistent`
- Final related suite:
  - `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_project_config_persistence_contract.py v2-api\tests\test_platform_postgres_design.py v2-api\tests\test_platform_persistence_status.py v2-api\tests\test_platform_contracts.py -q`
  - Result: `4 passed, 1 warning in 1.58s`
- Final handoff and baseline guards:
  - `verify_platform_project_config_persistence_contract.py`, `verify_platform_postgres_design.py`, `verify_platform_persistence_status.py`, `verify_platform_backend_contract_snapshot.py`, `verify_pm_platform_handoff_package.py`, and `verify_production_baseline.py` exited 0.

TDD red-green evidence:

- Before implementation, the API test failed with `404` for `/projects/{project_id}/persistence/contract`.
- After implementing the read-only service and route, the focused test and guard passed.

## Migration Notes

- No database migration is included.
- No table, index, permission, trigger, or production data was changed.
- The route reports `requires_user_approval_before_migration` and keeps PostgreSQL as a future approved step.
- The current source remains `local_json_project_draft_store`.

## Rollback Notes

Rollback is code-only:

1. Remove `v2-api/app/services/platform/config_persistence_contract.py`.
2. Remove the route and import from `v2-api/app/api/routes/projects.py`.
3. Remove the focused test and verification script.
4. Remove this report and the plan if the package is discarded before PR.

No database rollback is required because the package performs no database writes or migrations.

## Production Safety

- Read-only API preview.
- No database connection.
- No PostgreSQL schema change.
- No production data edit.
- No `.env`, `data`, `uploads`, OSS object, or production workbook change.
- No version bump, tag, release, or deployment.
