# Project List Config Preflight Fallback Report

## Summary

Made the project list resilient to bad local project drafts.

`GET /projects` now catches project draft configuration/validation failures, returns built-in project rows, and attaches read-only `config_preflight` metadata with `fix_config_preflight_blockers`. The fallback uses static project overview data and does not connect to the database.

`/platform-projects` now stores and displays the project-list preflight state as `项目列表预检`, so operators can see whether list loading is clean, waiting, or blocked.

## Changed Files

- `v2-api/app/api/routes/projects.py`
- `v2-api/app/services/platform/catalog.py`
- `v2-web/src/api/services.ts`
- `v2-web/src/stores/workspace.ts`
- `v2-web/src/views/ProjectsView.vue`
- `scripts/verify_platform_project_list_config_preflight.py`
- `scripts/verify_vue_project_list_config_preflight.js`
- `docs/superpowers/plans/2026-07-03-project-list-config-preflight-fallback.md`
- `docs/reports/pm-platform-project-list-config-preflight-fallback-2026-07-03.md`

## Verification

- `python scripts/verify_platform_project_list_config_preflight.py`
- `python scripts/verify_platform_project_config_preflight.py`
- `python scripts/verify_platform_handoff_config_preflight.py`
- `python scripts/verify_platform_handoff_readiness.py`
- `node scripts/verify_vue_project_list_config_preflight.js`
- `node scripts/verify_vue_project_config_preflight.js`
- `node scripts/verify_vue_handoff_config_preflight.js`
- `node scripts/verify_vue_platform_handoff_readiness.js`
- `python -m pytest v2-api/tests/test_platform_handoff_readiness.py v2-api/tests/test_platform_persistence_status.py v2-api/tests/test_platform_overview.py -q`
- `pnpm --dir v2-web build`
- Browser smoke on `/platform-projects`: top readiness band contains `项目列表预检通过 · 4 个草稿`
- `git diff --check`
- Sensitive-path scan for `.env`, `data`, `uploads`, dumps, archives, and keys

## Migration And Rollback

- Migration: none.
- Rollback: revert the changed route/service/frontend files and remove the new verification scripts.

## Production Safety

- No production data, production uploads, OSS objects, PostgreSQL data, version numbers, tags, or deployment actions were changed.
- Fallback path is read-only and carries `config_preflight_blocks_project_list`, `read_only_no_write`, `no_database_connection`, and `no_production_data_edit` safety evidence.
