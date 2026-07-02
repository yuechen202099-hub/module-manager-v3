# PM Platform Project Readiness Check

Date: 2026-07-02

## Feature Scope

This package adds a read-only readiness check for project onboarding and launch preparation.

New API:

```text
GET /projects/{project_id}/readiness
```

The route inspects the current project definition and returns:

- whether the project is ready,
- summary counts,
- grouped checks,
- next actions,
- production-safety flags.

The first pass checks:

- primary field,
- aggregate field,
- site collection fields,
- photo evidence fields,
- required KPI fields,
- core modules,
- template import workflow,
- construction collection workflow,
- review workflow,
- delivery archive workflow.

## Product Fit

This moves project configuration from "the user can configure fields" toward "the system can tell whether the project is actually ready to take over or run."

It directly supports the product direction:

- project progress,
- delivery capability,
- synchronized field construction collection,
- review/archive readiness,
- configurable project-specific process differences.

## Changed Files

- `v2-api/app/services/platform/readiness.py`
- `v2-api/app/api/routes/projects.py`
- `v2-api/tests/test_platform_project_readiness.py`
- `scripts/verify_platform_project_readiness.py`
- `docs/superpowers/plans/2026-07-02-platform-project-readiness-check.md`

## Verification

TDD evidence:

- Before implementation, `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_project_readiness.py -q` failed with `404` for `/projects/{project_id}/readiness`.
- After implementation, the same focused test passed.

Fresh verification:

- `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_project_readiness.py -q`
  - Result: `2 passed, 1 warning in 1.50s`
- `.\.venv\Scripts\python.exe scripts\verify_platform_project_readiness.py`
  - Result: `[OK] platform project readiness is consistent`
- `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_project_readiness.py v2-api\tests\test_platform_project_config_persistence_contract.py v2-api\tests\test_platform_contracts.py -q`
  - Result: `4 passed, 1 warning in 1.47s`
- Final guards:
  - `verify_platform_project_readiness.py`, `verify_platform_project_config_persistence_contract.py`, `verify_platform_backend_contract_snapshot.py`, `verify_pm_platform_handoff_package.py`, and `verify_production_baseline.py` exited 0.

## Migration Notes

- No database migration is included.
- No project status is changed.
- No local JSON project store is written by the readiness route.
- No PostgreSQL connection is opened.

## Rollback Notes

Rollback is code-only:

1. Remove `v2-api/app/services/platform/readiness.py`.
2. Remove the readiness route and import from `v2-api/app/api/routes/projects.py`.
3. Remove `v2-api/tests/test_platform_project_readiness.py`.
4. Remove `scripts/verify_platform_project_readiness.py`.
5. Remove this report and the plan if the package is discarded before PR.

No data rollback is required because this package performs no writes.

## Production Safety

- Read-only API.
- No `.env`, `data`, `uploads`, OSS object, PostgreSQL production data, version number, tag, release, or deployment change.
- The route returns `read_only_no_write`, `no_database_connection`, `no_postgres_schema_change`, and `no_production_data_edit` safety flags.
