# PM Platform Template Download Guidance

Date: 2026-07-03

## Baseline

- Production branch: `production/V3/3.0.77`
- Baseline commit: `4c05cc92a71e08a7eb5da6a25cef654271b4cfc5`
- Feature branch: `pm-platform/production-3.0.77-sync`

## Scope

The field graph template preview now explains the downloaded workbook before the user clicks download.

The new guidance covers:

- Workbook sheets: `template / fields / instructions`.
- `Excel说明页` purpose: field hierarchy, parent field, conditional collection, and platform-fill rules.
- Module replacement mode: `任务对象下更换附属设备`.
- Terminal replacement mode: `主设备更换后确认附属设备`.

## Modified Files

- `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
- `scripts/verify_vue_template_download_guidance.js`
- `docs/superpowers/plans/2026-07-03-template-download-guidance.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- `docs/reports/pm-platform-template-download-guidance-2026-07-03.md`

## Verification

- `node scripts/verify_vue_template_download_guidance.js`
  - Result: passed.
- `node scripts/verify_vue_template_impact_preview.js`
  - Result: passed.
- `node scripts/verify_vue_project_field_graph_template_actions.js`
  - Result: passed.
- `pnpm --dir v2-web build`
  - Result: passed. Existing Rollup pure-comment and chunk-size warnings remain.
- In-app browser smoke:
  - URL: `http://127.0.0.1:52131/platform-projects?template_download_guidance_clean=1`
  - Flow: open project list, click `新建项目`, scroll to field graph template preview.
  - Result: the modal shows `Excel说明页`, `template / fields / instructions`, and `任务对象下更换附属设备`; page has no framework error overlay.
  - Note: browser console still reported one stale preload error for an old `ProjectsView-rirLIScw.css` path from an earlier cached entry, while the current DOM script source was `/vue/assets/index-B2cgjMO8.js` and the updated UI rendered.

## Migration Notes

- No database migration.
- No PostgreSQL or OSS production data write.
- No `.env`, upload file, dump, build archive, version number, tag, or deployment change.

## Risk Notes

- This is a frontend explanatory panel. It does not change import parsing, template download endpoints, or validation behavior.
- The visible guidance depends on the current field schema mode inferred by the field graph. If a project has no device replacement fields, the panel shows a pending-configuration hint.

## Rollback

Remove `templateDownloadGuideCards`, `templateDownloadHierarchyGuide`, the `.template-download-guide` markup and styles from `FieldGraphDesigner.vue`, then remove `scripts/verify_vue_template_download_guidance.js` and this report.
