# PM Platform Project List Config Preflight Details

## Baseline

- Branch: `pm-platform/production-3.0.77-sync`
- Production baseline branch: `production/V3/3.0.77`
- Baseline commit: `4c05cc92a71e08a7eb5da6a25cef654271b4cfc5`

## Summary

`/platform-projects` now shows actionable project-list config preflight details when legacy local drafts block normal list loading.

The top of the project list can now show:

- Store-level draft file issues.
- Blocked project names.
- The first mapped fix message for each blocked project.
- Project id and issue count for follow-up.

This keeps the list resilient while also telling operators which historical project needs cleanup before full config loading resumes.

## Modified Files

- `v2-web/src/views/ProjectsView.vue`
- `scripts/verify_vue_project_list_config_preflight_details.js`
- `docs/superpowers/plans/2026-07-04-project-list-config-preflight-details.md`
- `docs/reports/pm-platform-project-list-config-preflight-details-2026-07-04.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Generated Vue static assets under `v2-api/app/static/vue/`

## Verification

- `node scripts/verify_vue_project_list_config_preflight_details.js` -> passed.
- `node scripts/verify_vue_project_list_config_preflight.js` -> passed.
- `python scripts/verify_platform_project_list_config_preflight.py` -> passed.
- `python scripts/verify_platform_project_config_preflight.py` -> passed.
- `pnpm --dir v2-web build` -> passed with existing Rollup PURE-comment and chunk-size warnings.

## Risk

Low. This is a frontend visibility improvement over existing read-only `config_preflight` data. It does not create, repair, migrate, delete, or publish project drafts.

No production `.env`, real `data`, `uploads`, OSS, PostgreSQL data, official version number, tag, release, or deployment is touched.

## Rollback

Remove the new computed properties and top-level detail block from `ProjectsView.vue`, remove the verification script and docs, then rebuild Vue static assets. No database, OSS, or production-data rollback is required.
