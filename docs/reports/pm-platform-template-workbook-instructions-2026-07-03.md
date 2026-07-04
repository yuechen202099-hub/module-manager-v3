# PM Platform Template Workbook Instructions

Date: 2026-07-03

## Baseline

- Production branch: `production/V3/3.0.77`
- Baseline commit: `4c05cc92a71e08a7eb5da6a25cef654271b4cfc5`
- Feature branch: `pm-platform/production-3.0.77-sync`

## Scope

Downloaded project import templates now include an `instructions` worksheet in addition to `template` and `fields`.

The instruction sheet explains:

- Field hierarchy and parent field.
- Conditional collection rules.
- Upload-time platform-generated fields.
- Device replacement hierarchy mode:
  - Module replacement: `任务对象下更换附属设备`.
  - Terminal replacement: `主设备更换后确认附属设备`.

## Modified Files

- `v2-api/app/services/platform/templates.py`
- `v2-api/tests/test_platform_overview.py`
- `scripts/verify_platform_template_workbook_instructions.py`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- `docs/reports/pm-platform-template-workbook-instructions-2026-07-03.md`

## Verification

- `python scripts/verify_platform_template_workbook_instructions.py`
  - Result: passed, workbook instructions include hierarchy, parent, condition, platform-fill, module-replacement, and terminal-replacement guidance.
- `python -m pytest v2-api/tests/test_platform_overview.py -k project_templates_download_schema_driven_workbooks -q`
  - Result: `2 passed, 38 deselected`.
- `python scripts/verify_platform_device_replacement_hierarchy_mode.py`
  - Result: passed.
- `node scripts/verify_vue_device_replacement_hierarchy_mode.js`
  - Result: passed.
- `node scripts/verify_vue_replacement_hierarchy_template_apply.js`
  - Result: passed.
- `git diff --check`
  - Result: passed.
- Sensitive path scan over `git status --short`
  - Result: passed, no `.env`, data, uploads, dump, archive, or secret path included.

## Migration Notes

- No database migration.
- No PostgreSQL or OSS production data write.
- No `.env`, upload file, dump, build archive, version number, tag, or deployment change.

## Risk Notes

- The downloaded workbook shape changes from two worksheets to three worksheets. Existing upload parsing still reads the active `template` worksheet, so import behavior is not changed.
- Consumers that assert exact workbook sheet names must be updated to allow `instructions`.

## Rollback

Remove the `instructions` worksheet creation and helper functions from `v2-api/app/services/platform/templates.py`, restore the workbook sheet-name expectation in `v2-api/tests/test_platform_overview.py`, and remove `scripts/verify_platform_template_workbook_instructions.py`.
