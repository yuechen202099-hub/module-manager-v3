# PM Platform Field Template Hierarchy Hints Report

Date: 2026-07-03

## Baseline

- Branch: `pm-platform/production-3.0.77-sync`
- Production base: `production/V3/3.0.77`
- Scope: template preview/download guidance and frontend field graph display only.

## What Changed

- Extended backend template preview `field_rows` with:
  - `parent_key`
  - `relation_role`
  - `required_when`
  - `show_in_construction_panel`
  - `template_hierarchy_role`
  - `template_parent_label`
  - `template_condition_hint`
- Extended downloaded template `fields` sheet with `层级角色`, `父字段`, and `条件采集` columns.
- Made backend field cleaning compatible with both snake_case and camelCase schema keys, including `parentKey`, `relationRole`, and `requiredWhen`.
- Extended frontend template preview types and API mapping to keep hierarchy metadata.
- Updated field graph template preview to render field cards with compact hierarchy hints instead of losing everything into a flat label list.

## Requirement Mapping

- Module replacement can now surface as task object plus accessory device fields in the template guidance.
- Terminal replacement can now surface main device, accessory confirmation, and conditional collection fields in downloaded and previewed templates.
- System-external completed templates still keep platform-fill rules for fields the platform can supply at upload time.

## Verification

Passed:

```powershell
node scripts\verify_field_template_hierarchy_hints.js
node scripts\verify_vue_project_field_graph_template_actions.js
node scripts\verify_vue_field_graph_backend_readiness_echo.js
python scripts\verify_platform_line_loss_template_contract.py
pnpm --dir v2-web build
git diff --check
git status --short -- .env data uploads v2-api/data v2-api/app/static/uploads
```

Browser smoke:

- Restarted local platform on `http://127.0.0.1:52147/platform-projects`.
- Opened `字段配置：更换终端`.
- Verified two `.template-preview-field-list` sections, 29 field cards, and visible `任务核心`, `附属设备确认`, `条件采集`, and `父字段` hints.

Build warnings retained from the existing project:

- VueUse pure annotation warning from Rollup.
- Large chunk size warning.

## Data And Migration

- No database schema change.
- No production data change.
- No OSS, PostgreSQL, upload, or `.env` changes.
- No production version, tag, release, or deploy action.

## Risks

- Template hierarchy hints are guidance metadata; they do not yet enforce import row-level parent/condition completeness beyond existing required/recommended header checks.
- Browser smoke used the local demo project `更换终端`; other project templates are covered by guard scripts and the line-loss template contract.

## Rollback

Revert these files:

- `v2-api/app/services/platform/templates.py`
- `v2-web/src/api/types.ts`
- `v2-web/src/api/services.ts`
- `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
- `v2-web/src/views/ProjectsView.vue`
- `scripts/verify_field_template_hierarchy_hints.js`
- `docs/superpowers/plans/2026-07-03-field-template-hierarchy-hints.md`
- `docs/reports/pm-platform-field-template-hierarchy-hints-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

Then rebuild frontend with:

```powershell
pnpm --dir v2-web build
```
