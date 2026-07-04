# PM Platform Single Aggregate Device Hierarchy Guard

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` at `4c05cc92a71e08a7eb5da6a25cef654271b4cfc5`

## Summary

This package turns the latest field-hierarchy product rule into a backend schema guard.

- A project now keeps exactly one active aggregate slot: `aggregate_field`.
- Custom fields can no longer be marked as another `aggregate` relation role.
- Module replacement remains valid as accessory-device replacement under the task object.
- Terminal replacement is treated as main-device replacement and must include accessory confirmation fields.
- Main-device accessory new-value fields must depend on an accessory confirmation through `required_when`.

## Files Changed

- `v2-api/app/services/platform/catalog.py`
- `v2-api/tests/test_platform_overview.py`
- `scripts/verify_platform_single_aggregate_device_hierarchy_guard.py`
- `docs/superpowers/plans/2026-07-03-single-aggregate-device-hierarchy-guard.md`
- `docs/reports/pm-platform-single-aggregate-device-hierarchy-guard-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

## Verification

- Red first:
  - `python scripts/verify_platform_single_aggregate_device_hierarchy_guard.py` failed before implementation because the backend accepted an extra aggregate field.
  - `python -m pytest v2-api/tests/test_platform_overview.py -k "extra_aggregate_field or terminal_replacement_without_accessory_confirmation" -q` failed before implementation with both endpoints returning 200.
- Green:
  - `python scripts/verify_platform_single_aggregate_device_hierarchy_guard.py`
  - `python -m pytest v2-api/tests/test_platform_overview.py -k "extra_aggregate_field or terminal_replacement_without_accessory_confirmation" -q`
  - `python scripts/verify_platform_device_replacement_hierarchy_mode.py`
  - `python scripts/verify_platform_device_relation_roles.py`
  - `python scripts/verify_platform_template_workbook_instructions.py`
  - `python -m pytest v2-api/tests/test_platform_overview.py -k "work_item_schema or project_templates_download_schema_driven_workbooks" -q`

## Migration Notes

No migration is included. The change is a local backend validation rule for project field schema payloads. It does not connect to PostgreSQL, alter OSS, modify production data, generate official version numbers, create tags, or publish a server.

## Rollback Notes

Rollback is code-only:

1. Remove the new schema guard helpers and calls from `v2-api/app/services/platform/catalog.py`.
2. Remove the two new backend tests from `v2-api/tests/test_platform_overview.py`.
3. Remove `scripts/verify_platform_single_aggregate_device_hierarchy_guard.py`.

No database or file-store rollback is required.
