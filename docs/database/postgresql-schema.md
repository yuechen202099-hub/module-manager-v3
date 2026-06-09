# PostgreSQL Schema V2.0

This document records the first V2.0 database baseline. The implementation lives in:

- `v2-api/app/database.py`
- `v2-api/app/models.py`
- `v2-api/alembic/versions/0001_initial_schema.py`

## Migration

From the V2.0 project root:

```powershell
$env:DATABASE_URL="postgresql+psycopg://module_manager:module_manager_password@localhost:5432/module_manager_v2"
cd v2-api
alembic upgrade head
```

The Docker Compose API container should use the service network URL from `.env`:

```text
postgresql+psycopg://module_manager:module_manager_password@postgres:5432/module_manager_v2
```

The first migration enables PostgreSQL `pgcrypto` so UUID primary keys can use `gen_random_uuid()`.

## Core Tables

- `users`, `roles`, `user_roles`: account identity and role assignment.
- `projects`: project workspace and lifecycle status.
- `total_catalog_rows`: imported total catalog rows. Installation address is stored per row and is not deduplicated.
- `stage_catalog_rows`: imported stage catalog rows for stage, terminal, and task slicing data.
- `material_groups`: reviewable meter/material group. It persists the backend-generated `meter_match_key`, display meter number from total catalog, and installation address snapshot.
- `photos`: object-storage photo metadata. Duplicates are prevented per group by `sha256`.
- `tasks`, `task_groups`: published review task and its assigned groups. Claim/release must be handled in a transaction by the service layer.
- `review_records`: immutable review action history for a group.
- `exceptions`: exception tickets raised from review/import workflows.
- `import_jobs`, `export_jobs`: async job state for imports and exports.
- `audit_logs`: append-only operational audit trail.

## Required Indexes

- `ix_total_catalog_rows_project_meter_key` on `total_catalog_rows(project_id, meter_match_key)`
- `ix_stage_catalog_rows_project_meter_key` on `stage_catalog_rows(project_id, meter_match_key)`
- `ix_material_groups_project_meter_key` on `material_groups(project_id, meter_match_key)`
- `ix_material_groups_task_status` on `material_groups(task_id, status)`
- `ix_photos_group_sha256` on `photos(group_id, sha256)`
- `ix_tasks_project_status` on `tasks(project_id, status)`
- `ix_task_groups_task_group` on `task_groups(task_id, group_id)`

Additional operational indexes are included for job polling, exception queues, review history, and audit lookup:

- `ix_import_jobs_project_status`
- `ix_export_jobs_project_status`
- `ix_exceptions_project_status`
- `ix_review_records_group_created`
- `ix_audit_logs_project_created`
- `ix_audit_logs_entity`

## Integrity Notes

- `total_catalog_rows` and `stage_catalog_rows` keep raw row payloads in `raw_data` for import traceability.
- `material_groups(project_id, meter_match_key)` is unique because review state is tracked per group.
- `photos(group_id, sha256)` is unique to deduplicate photos inside one group.
- Catalog tables intentionally do not unique-constrain installation address.
- Task ownership fields are nullable with `SET NULL` user references so historical data survives account removal.
- `total_catalog_rows.installation_address` is the only authoritative installation-address source.
- `material_groups.installation_address` must be copied from the selected total catalog row and must not be overwritten by stage catalog, scan data, review comments, or frontend edits.
- A group with fewer than 4 valid uploaded photos remains `incomplete`; supplemental photos append to the same group and then recalculate `photo_count`.
- Local simulation task status `in_review` is a V2.1 local alias for production task status `claimed`.

## V2.1 Data Rules

Detailed V2.1 mapping, status flow, photo-insufficient rules, supplemental-photo rules, and risks are recorded in `docs/database/v2.1-data-rules.md`.
