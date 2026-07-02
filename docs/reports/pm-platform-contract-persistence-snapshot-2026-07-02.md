# PM Platform Contract Persistence Snapshot

Date: 2026-07-02

## Feature Scope

This package extends the backend shared contract snapshot with the project configuration persistence contract.

The snapshot now records:

- route: `GET /projects/{project_id}/persistence/contract`,
- source backend: `local_json_project_draft_store`,
- target backend: `postgres_after_approved_migration`,
- target tables: `platform_project_configs` and `platform_project_config_events`,
- future config record keys,
- round-trip result keys,
- migration approval gates,
- read-only safety flags.

This is a contract snapshot only. It does not create a migration, connect to PostgreSQL, or change runtime persistence.

## Changed Files

- `v2-api/app/services/platform/contracts.py`
- `v2-api/tests/test_platform_contracts.py`
- `scripts/verify_platform_backend_contract_snapshot.py`
- `docs/superpowers/plans/2026-07-02-platform-contract-persistence-snapshot.md`

## Verification

TDD evidence:

- Before implementation, `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_contracts.py -q` failed with `KeyError: 'persistence'`.
- After implementation, the same focused test passed.

Fresh verification:

- `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_contracts.py -q`
  - Result: `1 passed in 0.82s`
- `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_contracts.py v2-api\tests\test_platform_project_config_persistence_contract.py -q`
  - Result: `2 passed, 1 warning in 1.48s`
- `.\.venv\Scripts\python.exe scripts\verify_platform_backend_contract_snapshot.py`
  - Result: `[OK] platform backend contract snapshot is consistent`
- `.\.venv\Scripts\python.exe scripts\verify_platform_project_config_persistence_contract.py`
  - Result: `[OK] platform project config persistence contract is consistent`
- `.\.venv\Scripts\python.exe scripts\verify_pm_platform_handoff_package.py`
  - Result: `[OK] PM platform PR/patch handoff package is consistent`

## Migration Notes

- No Alembic migration is included.
- No database connection is opened.
- No table, index, permission, import/export rule, or production data is changed.
- The snapshot explicitly keeps `requires_user_approval_before_migration` as a migration gate.

## Rollback Notes

Rollback is code-only:

1. Remove the `persistence.project_config` section and related constants from `v2-api/app/services/platform/contracts.py`.
2. Remove the persistence assertions from `v2-api/tests/test_platform_contracts.py`.
3. Remove persistence checks from `scripts/verify_platform_backend_contract_snapshot.py`.
4. Remove this report and the plan file if the package is discarded before PR.

No database rollback is required.

## Production Safety

- No `.env`, `data`, `uploads`, OSS object, PostgreSQL production data, version number, tag, release, or deployment change.
- The package only expands a read-only contract snapshot and guard.
