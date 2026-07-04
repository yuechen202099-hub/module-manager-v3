# Project List Config Preflight Fallback Plan

## Baseline

- Branch: `pm-platform/production-3.0.77-sync`
- Production baseline branch: `production/V3/3.0.77`
- Baseline commit: `4c05cc92a71e08a7eb5da6a25cef654271b4cfc5`

## Requirement

`/platform-projects` must remain usable when legacy or mid-project local draft configuration is invalid.

If `/projects` cannot load local drafts because of field-schema, workflow, module, or store blockers, the endpoint should return built-in project entries plus read-only `config_preflight` evidence instead of returning a generic failure.

## Implementation Steps

1. Add a backend verification script that writes a bad temporary draft store and proves `GET /projects` returns `200` with `config_preflight`.
2. Add a frontend verification script requiring project-list preflight mapping, workspace storage, and visible `项目列表预检`.
3. Add `list_builtin_project_overviews()` as a static fallback that does not read drafts or connect to the database.
4. Update the `/projects` route to catch configuration/validation errors, return fallback built-in projects, `config_preflight`, `fix_config_preflight_blockers`, and safety evidence.
5. Cache the project-list preflight metadata in frontend services/workspace store.
6. Show `项目列表预检` in the top readiness band.

## Migration And Rollback

- Database migration: not required.
- Data migration: not required.
- Rollback: revert `catalog.py`, `projects.py`, the frontend service/store/view changes, and the two verification scripts.

## Safety

- No production `.env`, `data`, `uploads`, OSS, PostgreSQL data, tags, version numbers, or deployment paths are touched.
- The fallback intentionally avoids database access and only reports read-only preflight evidence.
