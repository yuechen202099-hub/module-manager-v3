# PM Platform Readiness Summary List Report

Date: 2026-07-02

## Scope

This package makes the multi-project list scan-ready for onboarding status. It adds a read-only batch readiness endpoint and a visible `上线状态` column on `/platform-projects`, while keeping detailed check items inside the existing `字段配置` dialog.

## Baseline

- Production branch: `production/V3/3.0.71`
- Feature branch: `pm-platform/project-drafts`
- Safety mode: read-only platform readiness summary, no migration, no PostgreSQL write, no production data edit.

## Backend

- Added `build_project_readiness_summary()` in `v2-api/app/services/platform/readiness.py`.
- Added `GET /projects/readiness/summary`.
- The response contains per-project lightweight rows: project id, name, status, ready flag, pass/fail summary, and next actions.
- The response also contains aggregated `action_counts` for not-ready projects, so operators can see the most common onboarding blockers.
- The response intentionally does not include full `checks` arrays, so the list stays lightweight and detailed diagnostics remain in `GET /projects/{project_id}/readiness`.

## Frontend

- Added `ProjectReadinessSummaryItem` and `ProjectReadinessSummaryList`.
- Added `fetchProjectReadinessSummary()`.
- `/platform-projects` now loads readiness summary with the project list.
- The table shows a `上线状态` column with `可接入` or `需补齐` and `通过 x/y 项`.
- The table header area shows a compact `上线检查` aggregate band and a `接入待办` list such as `启用模板接入流程 151 个`.
- No new row-level operation button was added.

## Verification

- `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_project_readiness.py::test_project_readiness_summary_lists_ready_and_blocked_projects -q`
  - RED before implementation: `404 Not Found`.
  - GREEN after implementation: `1 passed, 1 warning`.
- `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_project_readiness.py -q`
  - Result: `3 passed, 1 warning`.
- `.\.venv\Scripts\python.exe scripts\verify_platform_project_readiness.py`
  - Result: `[OK] platform project readiness is consistent`.
- `node scripts\verify_vue_project_readiness_summary_list.js`
  - RED before frontend wiring: missing `ProjectReadinessSummaryItem`.
  - GREEN after frontend wiring: `[OK] Project readiness summary list is wired to the frontend.`
- `node scripts\verify_vue_project_readiness_panel.js`
  - Result: `[OK] Project readiness panel is wired to the frontend.`
- `pnpm --dir v2-web build`
  - Result: build exited 0, `1894 modules transformed`.
  - Existing warnings: Rollup PURE annotation warnings and large chunk warnings.
- Browser smoke:
  - URL: `http://127.0.0.1:52131/platform-projects`
  - Result: current assets included `/vue/assets/ProjectsView-BXx1sPVJ.css` and `/vue/assets/ProjectsView-C_xHx24g.js`.
  - Visible result: `上线检查可接入 1 个 · 需补齐 192 个`, `接入待办` action counts, `上线状态` column, and row cells such as `需补齐通过 6/10 项`.

## Migration And Rollback

- No database migration.
- No production `.env`, OSS, PostgreSQL, `data`, or `uploads` changes.
- Rollback before merge: discard this branch package or reverse the patch.
- Rollback after merge: revert the merge commit and rebuild Vue static assets from source.

## Risks

- The current local demo has many draft projects, so the aggregate count reflects local development data.
- The endpoint computes readiness for each listed project; it is read-only and suitable for current project counts, but a future production-scale version may add cached/batched persistence after the approved PostgreSQL migration.
