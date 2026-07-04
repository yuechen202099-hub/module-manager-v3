# Project Config Preflight

## Goal

Add a read-only preflight for legacy or mid-project draft configuration before the platform loads, saves, migrates, or repairs any project data.

This protects the next platform stage: old project draft JSON can be checked against the current field hierarchy rules, including one active aggregate field and terminal accessory confirmation hierarchy, without mutating production or local project data.

## Scope

- Backend route: `GET /projects/persistence/config-preflight`.
- Backend service reads `platform-project-drafts.json` directly and reports store/project/schema/workflow blockers.
- Frontend field-configuration dialog shows `配置预检`, history draft status, blocked project count, first blocker details, and read-only safety boundaries.
- No database connection, migration execution, OSS mutation, production data edit, version bump, tag, or deployment.

## Verification Commands

```powershell
python scripts/verify_platform_project_config_preflight.py
pytest v2-api/tests/test_platform_persistence_status.py v2-api/tests/test_platform_project_config_persistence_contract.py -q
node scripts/verify_vue_project_config_preflight.js
node scripts/verify_vue_project_persistence_readiness.js
pnpm --dir v2-web build
git diff --check
```
