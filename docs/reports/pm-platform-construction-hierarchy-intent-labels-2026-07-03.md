# PM Platform Construction Hierarchy Intent Labels Report

## Summary

The construction collection page now shows a field collection intent label for configured project fields and photo slots.

Operators can distinguish:

- `主设备本体`
- `任务对象下的附属设备`
- `附属设备确认`
- `条件补采`
- `照片证据`
- `KPI资料`

This carries the device hierarchy model from project field configuration into the field construction workflow.

## Baseline

- Production baseline branch: `production/V3/3.0.77`
- Platform branch: `pm-platform/production-3.0.77-sync`
- Baseline commit: `6892205`

## Modified Files

- `v2-web/src/views/ConstructionView.vue`
- `scripts/verify_vue_construction_hierarchy_intent_labels.js`
- `docs/superpowers/plans/2026-07-03-construction-hierarchy-intent-labels.md`
- `docs/reports/pm-platform-construction-hierarchy-intent-labels-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Generated Vue static assets under `v2-api/app/static/vue/`

## Verification

- `node scripts\verify_vue_construction_hierarchy_intent_labels.js`
- `node scripts\verify_vue_construction_hierarchy_collection.js`
- `node scripts\verify_vue_construction_conditional_visibility.js`
- `node scripts\verify_vue_construction_submit_gap_preview.js`
- `python scripts\verify_platform_construction_required_collection.py`
- `pnpm --dir v2-web build`
- Browser smoke on the local construction preview

## Risk

Low. This is a read-only UI clarification using existing schema fields: `relationRole` and `requiredWhen`.

No submission logic, scanner behavior, review status, archive behavior, PostgreSQL, OSS, production data, official version, tag, or deployment was changed.

## Rollback

Remove the construction intent label helpers, checklist fields, template tags, guard script, and report row, then rebuild Vue static assets. No data rollback is required.
