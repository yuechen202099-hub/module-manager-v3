# Single Aggregate Device Hierarchy Guard Plan

Date: 2026-07-03

## Context

Project fields already support a primary field, one aggregate field, custom child fields, parent links, relation roles, and conditional collection. The operator-facing UI says a terminal project may aggregate by station area, region, or manufacturer, but only one aggregation mode can be active at a time.

The user clarified that equipment replacement also needs strict hierarchy:

- Module replacement: accessory equipment is replaced under one task object.
- Terminal replacement: the main terminal is replaced, then accessory equipment such as communication module and SIM card must be confirmed as replaced or not replaced.

## Scope

- Add backend validation to reject project schemas with custom fields marked as extra aggregate fields.
- Add backend validation to reject main-device replacement schemas that do not include accessory confirmation.
- Keep module replacement valid: direct accessory replacement under the task object remains allowed.
- Keep this package local and data-safe: no PostgreSQL connection, no Alembic migration, no production data writes, no tags, no deployment.

## Implementation

1. Add a red verification script for an extra custom aggregate field and a terminal replacement schema missing accessory confirmation.
2. Add focused backend pytest coverage for the same two cases.
3. Implement schema-level guards in `v2-api/app/services/platform/catalog.py` after field normalization.
4. Run new and existing device hierarchy/template verification.
5. Record report and team ledger entry.

## Rollback

Revert:

- `v2-api/app/services/platform/catalog.py` guard helpers and guard calls.
- `v2-api/tests/test_platform_overview.py` two new validation tests.
- `scripts/verify_platform_single_aggregate_device_hierarchy_guard.py`.

No database rollback is required because this package does not create tables, migrations, persistent production records, tags, or deployments.
