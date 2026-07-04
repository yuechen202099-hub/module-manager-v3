# PM Platform Delivery Archive Hierarchy Evidence Summary

Date: 2026-07-03

## Scope

This package extends the project board delivery archive preview with a visible evidence coverage summary. The summary uses the same hierarchy semantics as construction and review:

- Terminal replacement is a main-device replacement and must confirm accessory replacement.
- Module replacement is an accessory-device replacement under the task object.
- Conditional accessory evidence remains grouped as conditional follow-up.
- Platform KPI evidence is preserved in the delivery archive manifest.

## Changed Files

- `v2-api/app/services/platform/templates.py`
- `v2-web/src/views/ProjectBoardView.vue`
- `scripts/verify_platform_delivery_archive_manifest.py`
- `scripts/verify_vue_delivery_archive_hierarchy_evidence_summary.js`
- `docs/superpowers/plans/2026-07-03-delivery-archive-hierarchy-evidence-summary.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- `docs/reports/pm-platform-delivery-archive-hierarchy-evidence-summary-2026-07-03.md`

Frontend build regenerated files under `v2-api/app/static/vue/`.

## Implementation Notes

- Added `platformArchiveEvidenceHierarchySummary` to group delivery archive required evidence into `主设备本体`, `任务对象下的附属设备`, `附属设备确认`, `条件补采`, `照片证据`, `KPI资料`, `任务核心`, and `补充资料`.
- Added visible business copy for the two replacement modes:
  - `换模块：任务对象下换附属设备`
  - `换终端：主设备更换并确认附属设备`
- Added platform KPI evidence into the backend delivery archive manifest, including `installer`, `started_at`, `completed_at`, `uploaded_at`, `online_duration_minutes`, `photo_count`, and computed `old_device_recovered`.
- No production data, OSS data, PostgreSQL data, tags, deployment, or official version number was changed.

## Verification

Red checks observed:

- `node scripts\verify_vue_delivery_archive_hierarchy_evidence_summary.js`
  - `[FAIL] board must render archive evidence summary`
- `python scripts\verify_platform_delivery_archive_manifest.py`
  - `[FAIL] required evidence must include platform KPI archive fields`

Passing checks:

- `node scripts\verify_vue_delivery_archive_hierarchy_evidence_summary.js`
  - `[OK] Vue delivery archive hierarchy evidence summary is visible.`
- `node scripts\verify_vue_delivery_archive_manifest_evidence_details.js`
  - `[OK] Vue delivery archive manifest evidence details are visible.`
- `node scripts\verify_vue_delivery_archive_manifest.js`
  - `[OK] Vue delivery archive manifest is wired.`
- `python scripts\verify_platform_delivery_archive_manifest.py`
  - `[OK] platform delivery archive manifest is summarized`
- `python scripts\verify_pm_platform_team_operating_model.py`
  - `[OK] PM platform team operating model is locked`
- `pnpm --dir v2-web build`
  - Passed. Existing warnings remained for VueUse Rollup pure annotations and large chunks.
- Browser smoke at `http://127.0.0.1:52147/project-board?project_id=draft-project`
  - Visible summary cards included `主设备本体`, `任务对象下的附属设备`, `附属设备确认`, `条件补采`, `照片证据`, and `KPI资料`.
  - KPI summary showed `7项证据`.
- `git diff --check`
  - Passed with no output.
- `git status --short -- .env data uploads v2-api/data v2-api/app/static/uploads`
  - Passed with no output.

## Migration Notes

No database migration is required. This is a read-only manifest and frontend presentation change.

The backend manifest contract now includes platform KPI evidence rows. Consumers of the delivery archive manifest should tolerate the additional required evidence items before archive export is implemented.

## Rollback

Revert this package's changes in `v2-api/app/services/platform/templates.py`, `v2-web/src/views/ProjectBoardView.vue`, the two verification scripts, and the documentation updates, then rerun `pnpm --dir v2-web build` to regenerate static Vue assets.

## Risk

Risk is low-to-medium. The only backend behavior change is that delivery archive manifest previews now expose additional required evidence rows for KPI preservation. It does not write archive files or production data.
