# PM Platform Review Hierarchy Intent Labels Report

Date: 2026-07-03

Baseline branch: `production/V3/3.0.77`

Feature branch: `pm-platform/production-3.0.77-sync`

## Scope

- Added review evidence intent labels to the platform review workbench and the underlying review detail component.
- Kept existing review hierarchy sections and review approval blocking behavior unchanged.
- Added a KPI evidence section that displays existing `kpiValues` such as installer, install/completion time, upload time, online duration, photo count, and old-device recovery.

## Product Meaning

- `主设备本体`: the main device being replaced, such as the new terminal.
- `任务对象下的附属设备`: old devices and accessory new devices under the task object.
- `附属设备确认`: confirmation fields that decide whether accessory devices are replaced.
- `条件补采`: fields or photos required only after an accessory replacement confirmation is triggered.
- `照片证据`: photo evidence slots.
- `KPI资料`: evidence used for efficiency, quality, and delivery metrics.

## Modified Files

- `v2-web/src/views/ReviewView.vue`
- `v2-web/src/views/TaskHallView.vue`
- `scripts/verify_vue_review_hierarchy_intent_labels.js`
- `docs/superpowers/plans/2026-07-03-review-hierarchy-intent-labels.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

## Verification

Results:

- `node scripts\verify_vue_review_hierarchy_intent_labels.js`: passed.
- `node scripts\verify_vue_review_hierarchy_sections.js`: passed.
- `node scripts\verify_vue_review_required_evidence_gate.js`: passed.
- `python scripts\verify_pm_platform_team_operating_model.py`: passed.
- `pnpm --dir v2-web build`: passed, with existing VueUse Rollup annotation warnings and large chunk warnings.
- Browser smoke on `/task-hall?project_id=draft-project`: passed; visible tags include `主设备本体`, `任务对象下的附属设备`, `附属设备确认`, `条件补采`, `照片证据`, and `KPI资料`; `上传时间` is also tagged as `KPI资料`.
- `git diff --check`: passed.
- `git status --short -- .env data uploads v2-api/data v2-api/app/static/uploads`: no sensitive-path changes.

## Risk And Rollback

- Risk: visual-only labels could crowd narrow review rows; rows already wrap and the new tag is non-growing.
- Rollback: revert the modified `ReviewView.vue` label helpers/templates plus the new guard/report/plan files.
- Data safety: no production `.env`, `data`, `uploads`, OSS, PostgreSQL data, tags, version numbers, or release deployment touched.
