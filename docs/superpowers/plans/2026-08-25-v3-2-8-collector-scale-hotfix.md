# V3.2.8 Collector Scale Hotfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make collector inventory scanning and run creation safe for the 22,358-group/17,453-photo production project, then release and attest V3.2.8.

**Architecture:** Inventory scan/register use a database-side single-candidate membership query that preserves the existing photo-first collector rule. Run creation uses ordered selected-column streaming into lightweight projection rows instead of materializing source ORM entities. V3.2.8 retains Alembic head `20260824_0016` and is packaged and deployed as a new immutable release.

**Tech Stack:** FastAPI, SQLAlchemy 2, PostgreSQL, SQLite test fixtures, pytest, Vue 3, TypeScript, PowerShell release tooling, systemd/Nginx production deployment.

**Spec:** `docs/superpowers/specs/2026-08-25-v3-2-8-collector-scale-hotfix-design.md`; production evidence is in `.superpowers/sdd/2026-08-24-project-scoped-collector-inventory/task-9-report.md`.

## Global Constraints

- Preserve V3.2.7 inventory decisions, persistence behavior, project/team isolation, and all HTTP request/response contracts.
- Effective collector precedence is the first nonblank active-photo `collector` ordered by `(Photo.sort_order, Photo.id)`; raw-data aliases are considered only if no active-photo collector exists.
- Collector values are trimmed text; leading zeroes and arbitrary text are preserved.
- Inventory scan/register may not construct a whole-project `MeterSourceProjection`, ORM entity list, Python collector set, or group-ID `IN (...)` list.
- Run projection may retain compact selected values required by the run, but no `MaterialGroup` or `Photo` ORM entity may be materialized.
- The production-scale regression contains at least 22,358 groups and 17,453 active photos.
- A disconnected/499 scan must leave no unbounded project-wide work or business-data write behind.
- V3.2.8 uses the V3.2.7 schema unchanged at Alembic head `20260824_0016`.
- Do not overwrite the deployed V3.2.7 directory or original V3.2.7 ZIP.
- Keep maintenance worker/timer stopped until V3.2.8 smoke and browser acceptance pass.
- Do not delete production releases or backups while the server disk remains constrained.
- Never edit, stage, delete, or commit the unrelated untracked `v2-api/uv.lock`.

---

## File Structure

- `v2-api/app/services/collector_transfer.py`: bounded project collector lookup and compact streamed source projection.
- `v2-api/tests/test_collector_transfer_service.py`: precedence, isolation, persistence, and projection parity tests.
- `v2-api/tests/test_collector_transfer_scale.py`: production-cardinality query-shape, ORM-materialization, memory, and disconnect regressions.
- V3.2.8 version/release files: new release verifier, package gates, release notes, V3.2.7 incident record, and V3.2.8 attestation.

### Task 1: Replace inventory full projection with a bounded collector lookup

**Files:**
- Modify: `v2-api/app/services/collector_transfer.py:261-295,523-745`
- Modify: `v2-api/tests/test_collector_transfer_service.py`
- Create: `v2-api/tests/test_collector_transfer_scale.py`

**Interfaces:**
- Consumes: `normalize_identifier`, `MaterialGroup.raw_data`, ordered active `Photo.collector` values, and the existing inventory decision state machine.
- Produces: `PostgresCollectorTransferService._project_has_collector_number(project_id: UUID, collector_no: str) -> bool`.

- [ ] **Step 1: Add failing precedence and isolation tests**

Add a table-driven test whose literal cases cover:

```python
cases = [
    ({"collector": "RAW-1"}, [(0, " PHOTO-1 ", True)], "PHOTO-1", True),
    ({"collector": "RAW-1"}, [(0, "   ", True)], "RAW-1", True),
    ({"采集器": "0000123"}, [], "0000123", True),
    ({"采集器号": "中文-采集器"}, [], "中文-采集器", True),
    ({"construction_collector": "ALIAS-4"}, [], "ALIAS-4", True),
    ({"collector": "RAW-1"}, [(0, "INACTIVE", False)], "RAW-1", True),
    ({"collector": "RAW-1"}, [(0, "FIRST", True), (1, "SECOND", True)], "SECOND", False),
]
```

For each case, create a project group and the listed photos, call `_project_has_collector_number`, and assert the literal expected result. Add separate rows proving the same value in another project or another team does not match. The production mutation each test catches is a change in source precedence, normalization, active filtering, or tenancy scope.

- [ ] **Step 2: Run the new lookup tests and verify RED**

Run:

```powershell
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_service.py -q -k "project_has_collector_number"
```

Expected: fail because `_project_has_collector_number` does not exist.

- [ ] **Step 3: Add a failing no-materialization and production-cardinality regression**

In `test_collector_transfer_scale.py`, bulk-insert exactly 22,358 `MaterialGroup` rows and 17,453 active `Photo` rows with SQLAlchemy Core inserts. Attach a `Session.loaded_as_persistent` listener that records loaded `MaterialGroup` and `Photo` instances, and a `before_cursor_execute` listener that records SQL statements. Call the lookup for a guaranteed nonmatch and assert:

```python
assert result is False
assert loaded_source_entities == []
assert len(recorded_selects) <= 2
assert not any(" IN (" in statement.upper() and "MATERIAL_GROUPS" in statement.upper() for statement in recorded_selects)
```

Use `tracemalloc` around the lookup and require peak additional Python allocations below 64 MiB. Add a route-level test that cancels or disconnects the caller after dispatch and proves the database connection becomes idle and physical/photo/scan-event counts remain unchanged.

- [ ] **Step 4: Run the scale test and verify RED for the V3.2.7 query shape**

Run:

```powershell
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_scale.py -q
```

Expected: fail because V3.2.7 materializes source ORM entities, emits the generated group-ID filter, or exceeds the bounded-memory gate.

- [ ] **Step 5: Implement the bounded database-side membership query**

Create `_project_has_collector_number`. Use a correlated ordered subquery for the first nonblank active photo collector and ordered raw-data alias fallbacks, then an `EXISTS`/`LIMIT 1` membership query scoped by `MaterialGroup.team_id` and `MaterialGroup.project_id`. The query returns only a boolean/scalar and never selects a `MaterialGroup` or `Photo` entity.

Replace these two expressions:

```python
normalized_no in self._project_collector_numbers(project.id)
```

with:

```python
self._project_has_collector_number(project.id, normalized_no)
```

in both `scan_inventory` and `register_inventory`. Remove `_project_collector_numbers` when it has no caller.

- [ ] **Step 6: Verify GREEN and unchanged persistence behavior**

Run:

```powershell
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_api.py v2-api/tests/test_collector_transfer_scale.py -q
```

Expected: all tests pass; direct scans still persist only direct confirmation, non-direct scans remain zero-write, and photo registration remains atomic/idempotent.

- [ ] **Step 7: Commit the bounded inventory slice**

```powershell
git add -- v2-api/app/services/collector_transfer.py v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_scale.py
git commit -m "fix: bound project collector inventory lookup"
```

### Task 2: Make run source projection selected-column and streamed

**Files:**
- Modify: `v2-api/app/services/collector_transfer.py:88-186,261-291,385-521`
- Modify: `v2-api/tests/test_collector_transfer_service.py`
- Modify: `v2-api/tests/test_collector_transfer_scale.py`

**Interfaces:**
- Consumes: `meter_sources_from_groups(groups, photos)`, `_photo_snapshot(photo)`, and ordered project source rows.
- Produces: `_ProjectGroupRow` and `_ProjectPhotoRow` lightweight immutable values and a scale-safe `_project_meter_projection(project_id)`.

- [ ] **Step 1: Add failing projection parity and source-read tests**

Build the same small project once through full ORM reference objects and once through `_project_meter_projection`; assert literal equality for `projection.sources`, `projection.diagnostics`, and each `_photo_snapshot` used by `create_run`. Cover blank terminal, missing meter/module/collector, first-photo collector precedence, `module_meter`, `after_box`, inactive photos, and raw-data aliases.

Record ORM load events and executed SQL while calling `_project_meter_projection`, then assert zero `MaterialGroup`/`Photo` entity loads, exactly one ordered group select, one ordered project-photo select, and no group-ID `IN (...)` filter.

- [ ] **Step 2: Run focused projection tests and verify RED**

Run:

```powershell
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_scale.py -q -k "projection or create_run_scale"
```

Expected: V3.2.7 loads both source ORM classes and uses a generated ID list.

- [ ] **Step 3: Introduce exact lightweight source values**

Define frozen slotted dataclasses containing only the consumed fields:

```python
@dataclass(frozen=True, slots=True)
class _ProjectGroupRow:
    id: UUID
    terminal: str | None
    display_meter_no: str
    installation_address: str
    raw_data: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _ProjectPhotoRow:
    id: UUID
    group_id: UUID
    collector: str | None
    asset_no: str | None
    category: str | None
    sort_order: int
    is_active: bool
    image_url: str | None
    object_key: str
    storage_type: str | None
    storage_key: str | None
    storage_bucket: str | None
    sha256: str
    content_type: str | None
```

Do not add source-only lifecycle methods or copy unused ORM fields.

- [ ] **Step 4: Replace ORM entity queries with selected-column streams**

The group select must list only `_ProjectGroupRow` columns and preserve `(terminal, display_meter_no, id)` ordering. The photo select must join `Photo.group_id == MaterialGroup.id`, scope both source tables by team/project, select only `_ProjectPhotoRow` columns, filter active photos, preserve `(group_id, sort_order, id)` ordering, and iterate with `yield_per`/streaming execution options. It must not call `.scalars(select(MaterialGroup|Photo)).all()` and must not construct a list of every group ID.

Feed the lightweight rows into the unchanged reference projection rules. Update `_photo_snapshot`'s accepted type without changing its output keys.

- [ ] **Step 5: Extend the 22,358/17,453 regression to projection and create-run entry**

On the production-cardinality fixture, call `_project_meter_projection`, assert exact source count 22,358, zero source ORM loads, at most two source SELECTs, no giant `IN`, and peak additional Python allocations below 256 MiB. Exercise `create_run` on a representative multi-terminal fixture and prove it invokes only the compact projection and produces the same run stats, requirement de-duplication, workbench photo snapshots, and direct binding as before.

- [ ] **Step 6: Verify GREEN and all collector regressions**

Run:

```powershell
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_domain.py v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_api.py v2-api/tests/test_collector_transfer_postgres_integration.py v2-api/tests/test_collector_transfer_scale.py -q
```

Expected: all pass with no source ORM materialization.

- [ ] **Step 7: Commit the compact run-projection slice**

```powershell
git add -- v2-api/app/services/collector_transfer.py v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_scale.py
git commit -m "fix: stream collector run source projection"
```

### Task 3: Prepare and independently review the V3.2.8 candidate

**Files:**
- Modify: all current V3.2.7 source version markers and release-note consumers identified by `scripts/verify_v3_2_7_release.py`
- Create: `scripts/verify_v3_2_8_release.py`
- Create: `scripts/test_verify_v3_2_8_release.py`
- Modify: `scripts/verify-client-release.py`
- Modify: `scripts/test_verify_client_release.py`
- Modify: `scripts/build-client-release.ps1`
- Modify: `scripts/verify_release_sop.py`
- Modify: `scripts/test_verify_release_sop.py`
- Modify: `ops/releases/V3.2.7.md`
- Create: `ops/releases/V3.2.8.md`

**Interfaces:**
- Consumes: Tasks 1-2, V3.2.7 release verifier/package contract, and production incident evidence.
- Produces: immutable `build/server-release/module-manager-v2-server-3.2.8.zip`, exact SHA256, source commit, clean independent review, and pending V3.2.8 release record.

- [ ] **Step 1: Rename the candidate branch before version commits**

Run:

```powershell
git branch -m production/V3/3.2.8
```

Confirm `git status --short` still contains only the protected untracked `v2-api/uv.lock` plus intentional hotfix files.

- [ ] **Step 2: Write V3.2.8 release-gate tests and verify RED**

Copy the V3.2.7 behavioral verifier contract, update the version/branch/archive names to V3.2.8, retain Alembic `20260824_0016`, and require the two scale regression files and their successful execution. Add package tests proving the V3.2.7 archive name cannot satisfy V3.2.8 verification.

Run:

```powershell
v2-api\.venv\Scripts\python.exe -m pytest scripts/test_verify_v3_2_8_release.py scripts/test_verify_client_release.py scripts/test_verify_release_sop.py -q
```

Expected: fail before V3.2.8 version markers/verifier integration exist.

- [ ] **Step 3: Advance source/package markers and release records**

Set application/package/UI/release-note versions to `3.2.8`/`V3.2.8`, candidate branch to `production/V3/3.2.8`, and database head to unchanged `20260824_0016`. Record the V3.2.7 deployment and OOM incident as incomplete/failed acceptance without claiming attestation. Create V3.2.8 notes describing bounded inventory lookup, compact streamed run projection, unchanged business contracts, and pending production acceptance.

- [ ] **Step 4: Run focused, full, and source release gates**

```powershell
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_domain.py v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_api.py v2-api/tests/test_collector_transfer_postgres_integration.py v2-api/tests/test_collector_transfer_scale.py -q
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests scripts -q
v2-api\.venv\Scripts\python.exe scripts/verify_v3_2_8_release.py --phase source
v2-api\.venv\Scripts\python.exe scripts/verify_release_sop.py --version V3.2.8 --phase source
```

A timeout, interrupted run, or missing final pytest summary is a failure.

- [ ] **Step 5: Build and verify the immutable candidate**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-client-release.ps1 -Version 3.2.8
v2-api\.venv\Scripts\python.exe scripts/verify-client-release.py build/server-release/module-manager-v2-server-3.2.8.zip
Get-FileHash -Algorithm SHA256 -LiteralPath build/server-release/module-manager-v2-server-3.2.8.zip
```

Verify `SOURCE_COMMIT`, CRC/path/case/duplicate gates, static assets, unchanged migration head, exclusion of runtime uploads and `.env`, and exact hash. Do not modify or delete the V3.2.7 ZIP.

- [ ] **Step 6: Commit explicit candidate paths and obtain independent review**

Commit source/test/version/release inputs with explicit paths; never stage `v2-api/uv.lock` or generated runtime uploads. Generate a full review package from the V3.2.7 candidate base `8db0c64` through the V3.2.8 candidate and require a clean spec-and-quality review before deployment.

### Task 4: Back up, deploy, smoke, and attest V3.2.8

**Files:**
- Modify after successful acceptance: `ops/releases/V3.2.8.md`
- Modify after successful acceptance: `ops/releases/V3.2.7.md`

**Interfaces:**
- Consumes: independently verified V3.2.8 ZIP and `C:\Users\Administrator\Downloads\XXXXXX.pem`.
- Produces: production current on V3.2.8, restored maintenance services, exact smoke/browser evidence, and attested release records.

- [ ] **Step 1: Reconfirm production recovery and safety boundaries**

Read current release, database head, service PID/listener, health, memory/swap, PostgreSQL activity, disk usage, maintenance worker/timer state, and retained releases/backups. Stop if the host is not stable. Do not delete any release or backup and do not run retention cleanup.

- [ ] **Step 2: Create and verify a fresh streamed local backup**

Stream `.env`, current release metadata, `pg_dump -Fc`, schema SQL, `data.tar.gz`, and `uploads.tar.gz` directly to a new timestamped local directory under `C:\Users\Administrator\Documents\module-manager-production-backups`. Verify every SHA256, `pg_restore -l`, complete tar listings, nonempty schema, and source release metadata before cutover.

- [ ] **Step 3: Upload, hash, prepare, and cut over a new release directory**

Upload only `module-manager-v2-server-3.2.8.zip`, compare local/server SHA256, create `/opt/module-manager-v2/releases/v3.2.8-<UTC timestamp>`, restore `.env` without printing it, install dependencies, enforce group ownership and `chmod -R g-w,g+rX`, verify Pillow and `app.main` imports as `modulemgr`, and confirm Alembic remains `20260824_0016`. Atomically switch `current`, restart the main service, wait for the real Uvicorn listener on `127.0.0.1:8000`, then require local and public health/version 3.2.8.

- [ ] **Step 4: Execute exactly one guarded non-photo smoke**

Before POST, generate a guaranteed nonmatching barcode and immediately print/flush it, the selected project ID, physical/photo/scan-event counts, Uvicorn RSS, and host memory. POST once to `/collector-transfer/inventory/scan`; require HTTP 200, decision `pool_needs_photo`, bounded latency, unchanged counts, no barcode row, healthy listener, no OOM/restart increment, idle PostgreSQL sessions, and stable memory. Do not precompute a full project projection, upload a photo, create/allocate a run, or call the client platform.

- [ ] **Step 5: Perform authenticated 390x844 browser acceptance**

Confirm `/collector-inventory` opens on the active project with camera/manual controls, no run selector, no import control, no batch prerequisite, and no client-platform request in console/network logs. Verify `/collector-batches`, `/collector-workbench`, and `/project-board` remain available without creating production business data.

- [ ] **Step 6: Restore maintenance services and run soak checks**

Only after Steps 3-5 pass, restore the maintenance worker/timer to the pre-V3.2.7 active/enabled state. Run bounded repeated `/health` and PostgreSQL/resource checks long enough to cover service restart/readiness and one maintenance cycle; any restart, rising unreleased session count, or health failure stops attestation.

- [ ] **Step 7: Record evidence, attest, and perform the final audit**

Update V3.2.7 with its deployed hash/release/backup and failed OOM acceptance. Update V3.2.8 with source commit, local/server hash, backup path and verification, release/rollback directories, head, readiness, smoke latency/count/resource evidence, 390x844 browser evidence, maintenance restoration, and soak checks.

Run:

```powershell
v2-api\.venv\Scripts\python.exe scripts/verify_v3_2_8_release.py --phase attestation
git add -- ops/releases/V3.2.7.md ops/releases/V3.2.8.md
git commit -m "release: attest V3.2.8 collector scale hotfix"
```

Confirm production `current`, `/health`, version, database head, pages, worker/timer, and resource state once more. Confirm local `git status --short` contains only protected `v2-api/uv.lock` before declaring the goal complete.

