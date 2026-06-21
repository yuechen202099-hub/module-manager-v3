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

## V2.3 JSON State Migration Bridge

V2.3 adds a bridge layer for moving the current production JSON state into PostgreSQL without breaking the existing `/local-test/...` API surface.

### New Operational Tables and Columns

- `teams`: team workspace identity.
- `migration_runs`: append-only record of each JSON-to-PostgreSQL migration run.
- `photo_events`: photo category/delete/supplement events migrated from JSON state.
- `unmatched_records`: unmatched scan rows, blank manual records, and pending association records.
- `users.team_id`, `projects.team_id`, `tasks.team_id`, `material_groups.team_id`, `photos.team_id`, and event/job `team_id` columns make team isolation explicit.
- `tasks.legacy_id` preserves the numeric terminal task id used by the current frontend APIs.
- `material_groups.legacy_id` preserves the current group id such as `g-00001`.
- `photos.legacy_id` preserves the current photo id such as `p-...`.
- `raw_data` / `payload` JSONB columns keep the original JSON row for lossless rollback and auditing.

### Status Mapping

The production enum values remain canonical:

- Local task `in_review` migrates to production `claimed`.
- Local group `pending` migrates to production `unreviewed`.
- Local group `exception` and `unmatched` migrate to production `rejected`.
- The exact local status is still kept in `raw_data`.

### Duplicate Meter Keys

The production schema treats `meter_match_key` as the unique business identity for a team/project. During JSON migration:

- The first material group for a non-empty `meter_match_key` keeps that key.
- Later material groups with the same key are still migrated, but their database `meter_match_key` is set to `NULL`.
- The original duplicate key and source group id are preserved in `material_groups.raw_data` as `migration_duplicate_meter_match_key` and `migration_duplicate_of_group_id`.
- Duplicate total catalog rows are upserted by key, so database row counts may be lower than raw input rows when the source file contains duplicate table numbers.

### State Backend Switch

`STATE_BACKEND` controls the cutover:

```text
STATE_BACKEND=postgres  # default mode, PostgreSQL is the source of truth
STATE_BACKEND=dual      # migration mode, reads JSON and mirrors core writes to PostgreSQL
STATE_BACKEND=json      # compatibility and rollback mode only
```

Before claiming full JSON cutover, run the production-route audit:

```powershell
python scripts\verify_postgres_cutover_gate.py --strict
```

This gate fails if production API routes still call `local_simulation` business-state functions directly. A non-strict run is useful during migration because it lists the remaining API surfaces that still need repository-backed PostgreSQL implementations:

```powershell
python scripts\verify_postgres_cutover_gate.py
```

`STATE_BACKEND=postgres` is necessary but not sufficient; the strict cutover gate must also pass before the service can be treated as fully de-JSONized.

### Migration Commands

Dry-run first:

```powershell
cd v2-api
..\.venv\Scripts\python.exe scripts\migrate_json_to_postgres.py `
  --state C:\path\to\local_state.json `
  --users C:\path\to\users.json `
  --dry-run `
  --report C:\path\to\migration-report.json
```

Then apply schema and migrate:

```powershell
cd v2-api
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe scripts\migrate_json_to_postgres.py `
  --state C:\path\to\local_state.json `
  --users C:\path\to\users.json `
  --report C:\path\to\migration-report.json
```

The real migration copies `local_state.json`, `users.json`, and `.env` into a timestamped backup folder before writing to PostgreSQL.

### Full Photo Migration To OSS

After JSON state has been migrated into PostgreSQL, run a separate photo migration. This downloads every external photo URL, reads every local `/static/uploads/...` photo, uploads the bytes to OSS, and updates the `photos` table to use `storage_type='oss'`.

Dry-run first:

```powershell
cd v2-api
..\.venv\Scripts\python.exe scripts\migrate_photos_to_oss.py `
  --database-url postgresql+psycopg://USER:PASSWORD@HOST:5432/DB `
  --uploads-root C:\path\to\v2-api\app\static\uploads `
  --dry-run `
  --report C:\path\to\photo-oss-dry-run-report.json
```

Then upload and update PostgreSQL:

```powershell
cd v2-api
..\.venv\Scripts\python.exe scripts\migrate_photos_to_oss.py `
  --database-url postgresql+psycopg://USER:PASSWORD@HOST:5432/DB `
  --uploads-root C:\path\to\v2-api\app\static\uploads `
  --max-workers 8 `
  --report C:\path\to\photo-oss-report.json
```

Photo migration guarantees:

- Already migrated OSS photos are skipped unless `--force` is passed.
- Every successful row keeps the pre-OSS URL and storage fields in `photos.metadata_json`.
- `photos.image_url` becomes `oss://bucket/key`.
- `photos.storage_bucket` and `photos.storage_key` become the authoritative OSS location.
- The final SQL check should show zero non-OSS photos:

```sql
select storage_type, count(*) from photos group by storage_type order by storage_type;
select count(*) from photos where storage_type <> 'oss' or storage_type is null;
```
