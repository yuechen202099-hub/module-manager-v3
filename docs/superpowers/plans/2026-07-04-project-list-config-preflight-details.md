# Project List Config Preflight Details

## Goal

Make project-list config preflight blockers actionable at the top of `/platform-projects`.

When local draft config blocks normal list loading, operators should see:

- Store-level draft file issues.
- Blocked project names.
- The first actionable issue for each blocked project.
- The project id and issue count for follow-up.

## Scope

- Reuse the existing read-only `projectListConfigPreflight` state from the workspace store.
- Add a visible top-level detail block below the readiness summary band.
- Keep the detail block hidden when there are no project-list preflight blockers.
- Add a Vue static verification script for the visible block.
- Do not change backend persistence, migrations, production data, OSS, PostgreSQL, version numbers, tags, or deployment.

## Implementation Steps

1. Add a failing Vue verification script for project-list preflight detail visibility.
2. Add computed lists for store issues and blocked projects.
3. Render `项目列表预检阻断` above the table with issue text and project identifiers.
4. Add responsive styling for desktop and tablet/mobile.
5. Run focused Vue guards, backend fallback guard, frontend build, browser smoke, diff check, and sensitive path scan.

## Verification Commands

```powershell
node scripts/verify_vue_project_list_config_preflight_details.js
node scripts/verify_vue_project_list_config_preflight.js
python scripts/verify_platform_project_list_config_preflight.py
pnpm --dir v2-web build
```
