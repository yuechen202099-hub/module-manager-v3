# PM Platform Review Return Reason Suggestions

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Production baseline: `production/V3/3.0.77`
Baseline commit: `4c05cc9`

## Summary

Review now turns imported hierarchy gaps into an operator-facing return reason suggestion.

When an external-completed takeover import says an accessory device was replaced but misses triggered child evidence, the review work order now exposes a `suggested_review_return_reason` such as:

`导入层级缺口：缺少旧通讯模块号、新通讯模块号、新旧模块照片，请补齐对应现场证据后重新提交。`

## Changed Files

- `v2-api/app/services/platform/templates.py`
- `v2-web/src/api/types.ts`
- `v2-web/src/api/services.ts`
- `v2-web/src/views/ReviewView.vue`
- `v2-web/src/views/TaskHallView.vue`
- `scripts/verify_platform_review_return_reason_suggestions.py`
- `scripts/verify_vue_review_return_reason_suggestions.js`
- `docs/superpowers/plans/2026-07-03-review-return-reason-suggestions.md`
- `docs/reports/pm-platform-review-return-reason-suggestions-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Generated Vue static assets under `v2-api/app/static/vue/`

## Behavior

- Backend review payloads include `suggested_review_return_reason`.
- Returned review actions with a blank reason fall back to the suggestion, so API callers do not lose the reason.
- `ReviewView.vue` shows `建议退回原因` and provides `采用缺口原因` to fill the note box.
- `TaskHallView.vue` shows the same suggestion and pre-fills the return prompt with it.

## Verification

- `python scripts\verify_platform_review_return_reason_suggestions.py` passed.
- `node scripts\verify_vue_review_return_reason_suggestions.js` passed.
- `python scripts\verify_platform_review_hierarchy_gap_followup.py` passed.
- `node scripts\verify_vue_review_hierarchy_gap_followup.js` passed.
- `python scripts\verify_platform_review_required_evidence.py` passed.
- `node scripts\verify_vue_review_required_evidence_gate.js` passed.
- `node scripts\verify_vue_review_hierarchy_sections.js` passed.
- `node scripts\verify_vue_review_hierarchy_intent_labels.js` passed.
- `pnpm --dir v2-web build` passed after prepending bundled Node to PATH. Existing VueUse pure-annotation and large chunk warnings remain.
- Browser smoke on `http://127.0.0.1:52147/task-hall?project_id=draft-project` passed: `审阅工作台`, `平台接入审阅`, and `退回` rendered; local `52147` error logs were empty.

## Risk

Low. This package adds a suggestion and blank-reason fallback for returned platform review actions. It does not change official version numbers, tags, production deployment, PostgreSQL, OSS, production data, permissions, migrations, or archive writes.

The suggestion is derived only from existing `review_hierarchy_gap_items`, so unrelated validation warnings do not become return reasons.

## Rollback

Revert the files listed above and rebuild Vue static assets from the reverted frontend source. No database, OSS, upload, production data, tag, or server rollback is required because this was local feature-branch work only.
