# PM Platform Project Config Preflight

## Baseline

- Branch: `pm-platform/production-3.0.77-sync`
- Production baseline branch: `production/V3/3.0.77`
- Baseline commit: `4c05cc92a71e08a7eb5da6a25cef654271b4cfc5`

## Summary

Added a read-only project configuration preflight for legacy drafts and mid-project takeover work. The preflight checks the raw local project draft store before normal project loading, so invalid historical field schemas can be reported without crashing project list loading or silently mutating configuration.

The preflight currently catches:

- unreadable or invalid draft store format;
- invalid project records or module selections;
- field schema validation blockers, including extra aggregate fields and terminal accessory hierarchy errors;
- workflow validation blockers.

The `/platform-projects` field configuration dialog now shows a `配置预检` panel with history draft status, blocked project count, first blocker details, and safety tags.

## Modified Files

- `v2-api/app/services/platform/config_preflight.py`
- `v2-api/app/api/routes/projects.py`
- `v2-web/src/api/types.ts`
- `v2-web/src/api/services.ts`
- `v2-web/src/views/ProjectsView.vue`
- `scripts/verify_platform_project_config_preflight.py`
- `scripts/verify_vue_project_config_preflight.js`
- `docs/superpowers/plans/2026-07-03-project-config-preflight.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

The frontend build also regenerated static Vue assets under `v2-api/app/static/vue`.

## Verification

- `python scripts/verify_platform_project_config_preflight.py` -> passed.
- `pytest v2-api/tests/test_platform_persistence_status.py v2-api/tests/test_platform_project_config_persistence_contract.py -q` -> passed, `2 passed`.
- `node scripts/verify_vue_project_config_preflight.js` -> passed.
- `node scripts/verify_vue_project_persistence_readiness.js` -> passed.
- `python scripts/verify_platform_persistence_status.py` -> passed.
- `python scripts/verify_platform_project_config_persistence_contract.py` -> passed.
- `pnpm --dir v2-web build` -> passed with existing Rollup PURE-comment and chunk-size warnings.
- Browser smoke on `http://127.0.0.1:52131/platform-projects?...` -> passed; the field configuration dialog shows `配置预检`, `历史草稿`, and `只读预检`.

## Safety

- No production `.env`, `data`, `uploads`, OSS, PostgreSQL data, official version number, tag, or deployment was touched.
- The preflight uses `read_only_no_write`, `no_project_draft_load`, `no_database_connection`, `no_oss_mutation`, `no_migration_execution`, and `no_production_data_edit`.
- Rollback is a frontend/backend revert of this package's route, service, API mapping, view panel, verification scripts, docs, and generated static Vue assets.
