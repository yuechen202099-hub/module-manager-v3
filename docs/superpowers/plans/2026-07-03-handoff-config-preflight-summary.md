# Handoff Config Preflight Summary Plan

## Baseline

- Branch: `pm-platform/production-3.0.77-sync`
- Production baseline branch: `production/V3/3.0.77`
- Baseline commit: `4c05cc92a71e08a7eb5da6a25cef654271b4cfc5`

## Requirement

Operators should see project configuration preflight blockers from the project-list handoff readiness layer, not only after opening the field configuration dialog.

The handoff readiness endpoint must remain read-only and must not load broken project drafts when the preflight already shows blockers.

## Implementation Steps

1. Add a backend verification script that writes a temporary bad local draft and proves `build_platform_handoff_readiness()` returns `config_preflight` instead of crashing.
2. Add a frontend verification script that requires handoff config preflight mapping and a top-level `/platform-projects` display.
3. Call `build_project_config_preflight()` first in `build_platform_handoff_readiness()`.
4. If preflight is blocked, return a synthetic project readiness summary with `fix_config_preflight_blockers`.
5. Map `config_preflight` through frontend API types/services.
6. Show the top-level `配置预检` status in the handoff readiness band.

## Migration And Rollback

- Database migration: not required.
- Data migration: not required.
- Rollback: revert `handoff_readiness.py`, the frontend handoff mapping/display changes, and the two verification scripts.

## Safety

- No production `.env`, `data`, `uploads`, OSS, PostgreSQL data, tags, version numbers, or deployment paths are touched.
- The preflight path is read-only and does not save, repair, migrate, or connect to production databases.
