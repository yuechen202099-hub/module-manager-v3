# V3.2.8 Collector Scale Hotfix Design

## Context

V3.2.7 is live with Alembic head `20260824_0016`, but the first production inventory-scan smoke triggered a host-wide resource incident. The active project contains 22,358 material groups and 17,453 active source photos on a 1.6 GiB server. The scan request returned Nginx 499, PostgreSQL later reported a 7,776-second checkpoint and too many clients, and the kernel OOM killer terminated Uvicorn. No collector inventory, photo, or scan-event business row was created.

The confirmed call chain is:

```text
scan_inventory / register_inventory
  -> _project_collector_numbers
  -> _project_meter_projection
  -> full MaterialGroup ORM load
  -> giant group-id IN list
  -> full Photo ORM load
  -> full MeterSource and diagnostics construction
  -> one collector-number membership check
```

`create_run` also calls `_project_meter_projection`, so the hotfix must cover both inventory scanning and batch creation.

## Approved outcome

Release V3.2.8 from the V3.2.7 source baseline without a new database migration. Preserve every V3.2.7 business rule and HTTP contract while replacing unbounded source-data loading with bounded database work.

## Inventory membership query

Add `_project_has_collector_number(project_id: UUID, collector_no: str) -> bool` and call it from both `scan_inventory` and `register_inventory`.

The query must be scoped by both `team_id` and `project_id`, normalize only by trimming text, and preserve leading zeroes and arbitrary nonnumeric text. For each material group, the effective collector number is:

1. The first nonblank `Photo.collector` among active photos ordered by `(sort_order, id)`.
2. Only when no such active-photo value exists, the first nonblank material-group `raw_data` value from `collector`, `采集器`, `采集器号`, and `construction_collector`, in that order.

The database must decide whether any effective value equals the single normalized candidate. It must not instantiate `MaterialGroup` or `Photo` ORM objects, build a project-wide Python set, or build a project-wide `IN (...)` list.

## Run projection

Keep `meter_sources_from_groups` as the reference business projection. Replace `_project_meter_projection` source loading with ordered selected-column queries. Photo rows must be joined to the project groups instead of filtering with a generated list of every group ID. Use streamed result iteration and lightweight immutable row values containing only fields consumed by `meter_sources_from_groups` and `_photo_snapshot`.

The projection may retain the final `MeterSourceProjection` and the compact source-photo rows needed to create immutable run snapshots; those are proportional to the run being created. It must not retain full SQLAlchemy source entities or unused photo/group JSON payloads.

## Cancellation boundary

A disconnected inventory client may allow the already-issued bounded lookup to finish, but must not leave a project-wide projection, unbounded Python loop, or write transaction running. Non-direct scan remains read-only and produces `pool_needs_photo`. Cancellation handling is defense in depth; bounded query shape is the primary guarantee.

## Compatibility

- Existing inventory decisions and persistence boundaries do not change.
- Existing collector-photo precedence and raw-data aliases do not change.
- Cross-team and cross-project isolation does not change.
- Original `material_groups` and `photos` remain read-only.
- Mobile remains no-batch and has no import or client-platform request.
- V3.2.8 keeps Alembic head `20260824_0016`.
- The unrelated untracked `v2-api/uv.lock` remains untouched.

## Acceptance gates

- Parity tests cover photo precedence, blank photo collectors, raw-data aliases, inactive photos, whitespace, leading zeroes, arbitrary text, and project/team isolation.
- Tests prove inventory lookup materializes zero `MaterialGroup` and zero `Photo` ORM objects.
- A regression dataset contains at least 22,358 groups and 17,453 active photos and completes with bounded query count and bounded Python memory.
- Run projection tests prove selected-column/streamed source reads and unchanged terminal/meter/collector/photo snapshots.
- All backend/frontend/release tests pass and a new source-bound V3.2.8 ZIP is produced; the V3.2.7 ZIP and deployed release are never modified in place.
- Production gets a fresh streamed restore-ready backup before cutover.
- Exactly one non-photo production smoke prints the generated barcode and before counts before POST, returns `pool_needs_photo`, leaves physical/photo/event counts unchanged, and records latency and resource use.
- Browser acceptance is performed at 390x844 before maintenance worker/timer are restored.

