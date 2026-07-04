# PM Platform Construction Submit Gap Preview

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `4c05cc9`

## Summary

The construction page now shows a single submission gap warning before platform construction metadata is submitted.

The warning groups missing required fields, missing required photos, and missing required KPI inputs. Final submit is disabled while a gap exists, but saving a platform draft remains available.

## Changed Files

- `v2-web/src/views/ConstructionView.vue`
- `scripts/verify_vue_construction_submit_gap_preview.js`
- `docs/superpowers/plans/2026-07-03-construction-submit-gap-preview.md`
- `docs/reports/pm-platform-construction-submit-gap-preview-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Generated Vue static assets under `v2-api/app/static/vue/` after `pnpm --dir v2-web build`

## Verification

Commands:

- `node scripts\verify_vue_construction_submit_gap_preview.js`
  - Red check before implementation: failed because `missingRequiredKpiFieldLabels` was missing.
  - Green check after implementation: `[OK] Vue construction submit gap preview is wired.`
- `node scripts\verify_vue_construction_checklist_consumption.js`
  - Result: `[OK] Vue construction page consumes configured checklist.`
- `node scripts\verify_vue_platform_construction_kpi_fields.js`
  - Result: `[OK] Vue construction page preserves platform KPI collection fields.`
- `node scripts\verify_vue_construction_conditional_visibility.js`
  - Result: `[OK] Vue construction conditional visibility is wired.`
- `pnpm --dir v2-web build`
  - Result: passed after adding bundled Node to `PATH`.
  - Existing VueUse pure-annotation warnings and large chunk warnings remain.

Browser smoke:

- Current-code temporary server: `http://127.0.0.1:52143/construction?project_id=draft-project`
- Result: rendered `Module Manager V3.0.77`, no framework error overlay, seeded platform construction list visible, `施工提交缺口` visible after opening the first platform collection form, and `提交元数据` disabled while the gap remained.
- Temporary server was stopped after smoke validation.
- Note: existing user-open port `52131` was not restarted; it still served older static assets during smoke setup and produced a stale CSS preload error for an older `ProjectsView` asset.

## Risk Notes

- This is a frontend guard. The backend submit validation remains the source of truth.
- The submit gap does not block platform draft saves.
- Required KPI blocking currently applies to required KPI input fields, not derived status values such as photo count or old-device recovery. Those remain represented through configured required photos/fields and backend KPI generation.

## Rollback Notes

- Revert `v2-web/src/views/ConstructionView.vue`.
- Remove `scripts/verify_vue_construction_submit_gap_preview.js`.
- Rebuild Vue static assets from reverted source if generated assets are included.
- Revert the documentation entries listed above.
- No production rollback is needed because no production deployment, migration, tag, version bump, OSS write, PostgreSQL write, or production data edit occurred.
