# Task 2 Report

## Result

- Status: DONE
- Branch: `production/V3/3.2.0`
- Baseline HEAD before work: `418d51c fix: address task1 review findings`
- Commit: produced after this report is staged; final hash is in the task response.
- Commit message: `feat: add paginated data center query`

## Requirement

Add the server-paginated data-center query contract for V3.2.0 Task 2 without touching frontend or Task 3+ scope:

- `GET /groups/data-center`
- `GET /groups/data-center/{kind}/{item_id}`
- Shared JSON/PostgreSQL/DualWrite repository interface.
- Lightweight list rows, lazy detail loading.
- Page sizes limited to `20`, `50`, `100`.
- Stable server-side sorting and pagination.
- PostgreSQL indexes through migration `0013`.

## Changed Files

- `v2-api/app/schemas/data_center.py`
- `v2-api/app/services/data_center.py`
- `v2-api/app/api/routes/groups.py`
- `v2-api/app/services/state_repository.py`
- `v2-api/app/services/local_simulation.py`
- `v2-api/app/models.py`
- `v2-api/alembic/versions/0013_data_center_query_indexes.py`
- `v2-api/tests/test_data_center.py`
- `v2-api/tests/test_state_repository.py`
- `v2-api/tests/test_migrations.py`

## RED

Command:

```powershell
cd v2-api
..\.venv\Scripts\python.exe -m pytest tests/test_data_center.py tests/test_state_repository.py -k "data_center" -q
```

Result: failed as expected before implementation:

- `/groups/data-center` was routed to the legacy `/{group_id}` path and returned 422 instead of serving the contract.
- `app.schemas.data_center` did not exist.
- repository classes did not expose `list_data_center_rows` / `get_data_center_detail`.

Command:

```powershell
cd v2-api
..\.venv\Scripts\python.exe -m pytest tests/test_migrations.py -k "data_center" -q
```

Result: failed as expected because `0013_data_center_query_indexes.py` did not exist.

## Implementation

- Added explicit Pydantic request/response schemas with literal enums and `page_size` validator for `20`, `50`, `100`.
- Added shared pure mapping helpers for data-center group/unmatched rows, classification/barcode/archive/construction states, stable sorting, filtering, and pagination.
- Added JSON repository path through `local_simulation.list_data_center_rows` and `get_data_center_detail`.
- Added PostgreSQL repository path using one count statement and one bounded row statement, with stable `updated_at, legacy_id` ordering and active photo-count aggregation.
- DualWrite inherits the same read interface from the JSON-authoritative path.
- Added admin-only routes before the legacy dynamic `/{group_id}` route.
- Added lazy detail loading for photos/audit while keeping list rows free of `photos`, signed URLs, OCR candidates, and binary content.
- Added SQLAlchemy model indexes and Alembic migration `0013` without creating any database enum.

## GREEN

Focused API/repository tests:

```powershell
cd v2-api
..\.venv\Scripts\python.exe -m pytest tests/test_data_center.py tests/test_state_repository.py -k "data_center" -q
```

Result: `14 passed, 245 deselected, 1 warning`.

Migration tests:

```powershell
cd v2-api
..\.venv\Scripts\python.exe -m pytest tests/test_migrations.py -q
```

Result: `15 passed`.

Syntax check:

```powershell
cd v2-api
..\.venv\Scripts\python.exe -m py_compile app\schemas\data_center.py app\services\data_center.py app\api\routes\groups.py app\services\state_repository.py app\services\local_simulation.py app\models.py tests\test_data_center.py tests\test_state_repository.py tests\test_migrations.py
```

Result: exit `0`.

Whitespace check:

```powershell
git diff --check
```

Result: exit `0`; only Git's existing CRLF conversion warnings were printed for modified text files.

## Self-review

- Re-read the Task 2 brief and repository `AGENTS.md` before edits.
- Verified the worktree started clean and HEAD contained Task 1 at `418d51c`.
- Used codebase-memory MCP first to find repository classes, admin route patterns, migration tests, and model relationships; then used direct file reads for precise edits.
- Reviewed route order so `/groups/data-center` cannot be captured by `/{group_id}`.
- Checked list/detail split: list rows are lightweight; details fetch photos/audit only for one requested item.
- Checked PostgreSQL list shape: one count query, one bounded row query, stable order by `updated_at` plus `legacy_id`.
- Confirmed no frontend files or Task 3+ files were changed.
- Confirmed no production `.env`, data, uploads, OSS object, or real database mutation was touched.

## Concerns

- The PostgreSQL data-center path is covered by SQL-shape tests rather than a live PostgreSQL integration dataset in this task run.
- Test output includes an existing `StarletteDeprecationWarning` from FastAPI's `TestClient` importing deprecated `httpx` usage.

## Blocking Review Fix - 2026-07-23

### Findings Addressed

- C1: `0013_data_center_query_indexes.py` downgrade now drops only the three indexes created by this migration, by explicit name.
- I1: PostgreSQL list/archive filtering now derives `archive_status` from active `Photo.archive_status` aggregates, matching JSON photo-derived semantics instead of `MaterialGroup.raw_data`.
- I2: PostgreSQL classification complete now requires all four required category slots, not `photo_count >= 4`.
- I3: PostgreSQL detail now loads active photos first, then derives classification/archive statuses from those photos.
- I4: PostgreSQL `updated_at` ordering now uses explicit `NULLS LAST`; JSON updated sort also keeps empty times at the tail for both asc and desc.
- I5: JSON/DualWrite listing now uses `select_bounded_page` over iterators and retains at most `offset + page_size` mapped candidates while still counting all matches.

### RED Added

Command:

```powershell
cd v2-api
..\.venv\Scripts\python.exe -m pytest tests/test_data_center.py -q
```

Result before fix: failed with 4 blocking regressions:

- JSON updated-desc placed an empty timestamp before a real timestamp.
- `select_bounded_page` was missing.
- PostgreSQL SQL shape did not reference `photos.archive_status` / `photos.category`.
- PostgreSQL detail returned `archive_status=unarchived` after loading mixed archived/pending photos.

Command:

```powershell
cd v2-api
..\.venv\Scripts\python.exe -m pytest tests/test_migrations.py -q
```

Result before fix: failed because `0013` downgrade still raised an irreversible RuntimeError.

Additional RED during self-review:

```powershell
cd v2-api
..\.venv\Scripts\python.exe -m pytest tests/test_data_center.py -k "row_mapping_preserves" -q
```

Result before fix: failed because SQL-derived `archive_status=archived` was remapped to `unarchived`.

### GREEN

Data-center API/repository tests:

```powershell
cd v2-api
..\.venv\Scripts\python.exe -m pytest tests/test_data_center.py -q
```

Result: `18 passed, 1 warning`.

Data-center state repository contract tests:

```powershell
cd v2-api
..\.venv\Scripts\python.exe -m pytest tests/test_state_repository.py -k "data_center" -q
```

Result: `1 passed, 245 deselected`.

Migration tests:

```powershell
cd v2-api
..\.venv\Scripts\python.exe -m pytest tests/test_migrations.py -q
```

Result: `15 passed`.

Syntax and whitespace:

```powershell
cd v2-api
..\.venv\Scripts\python.exe -m py_compile app\services\data_center.py app\services\local_simulation.py app\services\state_repository.py alembic\versions\0013_data_center_query_indexes.py tests\test_data_center.py tests\test_migrations.py
git diff --check
```

Result: both exited `0`; `git diff --check` printed only CRLF conversion warnings.

### Remaining Concerns

- PostgreSQL behavior remains covered through compiled SQL-shape tests and focused fake-session detail tests, not a live PostgreSQL fixture with persisted sample rows.
- The existing FastAPI `TestClient` deprecation warning remains unrelated to this fix.

## Second Review Fix - 2026-07-23

### Findings Addressed

- I1: PostgreSQL data-center list row mapping now treats the SQL verification-table derived `barcode_status` as authoritative. `raw_data.barcode_verification` and legacy `group_barcode_check_status` no longer override the SQL-derived value in PostgreSQL list responses; JSON fallback order is unchanged.
- I1: Added list-level SQL-shape coverage proving the same `data_center_rows.barcode_status = 'ineligible'` filter is used by both count and row statements, and that a row with raw_data `passed` still returns SQL-derived `ineligible`.
- I2: PostgreSQL detail photo loading now uses the same effective photo collection as the list aggregate: same team/group, `is_active = true`, and `upload_status != invalid`. Detail `photo_count`, classification, archive status, and returned photos are derived from that filtered collection.

### RED

Command:

```powershell
cd v2-api
..\.venv\Scripts\python.exe -m pytest tests/test_data_center.py -k "authoritative_sql_barcode_status or excludes_invalid_upload_photos" -q
```

Result before fix: `2 failed, 18 deselected, 1 warning`.

- SQL row mapping returned `barcode_status=passed` because raw_data overrode authoritative SQL `ineligible`.
- PostgreSQL detail returned `photo_count=5` because active invalid photos were still included.

### GREEN

Focused regression tests:

```powershell
cd v2-api
..\.venv\Scripts\python.exe -m pytest tests/test_data_center.py -q
```

Result: `21 passed, 1 warning`.

State repository data-center tests:

```powershell
cd v2-api
..\.venv\Scripts\python.exe -m pytest tests/test_state_repository.py -k "data_center" -q
```

Result: `1 passed, 245 deselected`.

Migration tests:

```powershell
cd v2-api
..\.venv\Scripts\python.exe -m pytest tests/test_migrations.py -q
```

Result: `15 passed`.

Syntax and whitespace:

```powershell
cd v2-api
..\.venv\Scripts\python.exe -m py_compile app\services\state_repository.py tests\test_data_center.py
cd ..
git diff --check
```

Result: both exited `0`; `git diff --check` printed only the existing CRLF conversion warnings for modified files.

### Self-review

- Confirmed changed files are limited to backend repository logic, backend tests, and this report.
- Confirmed PostgreSQL list filters/count/row mapping now use the same SQL-derived barcode status value.
- Confirmed PostgreSQL detail excludes invalid upload photos before computing `photo_count`, `classification_status`, and `archive_status`.
- No frontend files, production data, `.env`, uploads, OSS objects, or PostgreSQL production data were touched.

### Remaining Concerns

- PostgreSQL list/detail behavior is still covered by SQL-shape and fake-session tests rather than a live PostgreSQL fixture seeded with the exact review data.
- The existing FastAPI `TestClient` deprecation warning remains unrelated to this fix.
