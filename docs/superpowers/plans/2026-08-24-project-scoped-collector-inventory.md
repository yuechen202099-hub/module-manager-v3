# Project-Scoped Collector Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the batch prerequisite from mobile collector scanning, persist collector inventory per current project, and release the verified change as V3.2.7 to production.

**Architecture:** Introduce project-scoped inventory commands beside the existing run-scoped allocation lifecycle. A scan creates business data only for a direct same-number confirmation; a non-direct collector is created atomically with its one photo. Existing runs consume same-project `direct` or `available` inventory but no longer create inventory.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy 2, PostgreSQL, Alembic, Pillow-backed image storage validation, Vue 3, TypeScript, Pinia, Element Plus, Vitest, pytest, PowerShell release tooling, systemd/Nginx production deployment.

**Spec:** `docs/superpowers/specs/2026-08-24-project-scoped-collector-inventory-design.md`

## Global Constraints

- Inventory is isolated by current project; it is never shared across projects in the same team.
- Mobile inventory has no run selector or run creation control.
- Non-direct scan alone persists no collector, photo, draft, audit event, or business scan event.
- A non-direct inventory row exists only after barcode text and one valid photo commit together.
- Direct same-number inventory never enters the random pool; if its active photo is missing, it may be photographed individually.
- Collector numbers are trimmed text, preserve leading zeroes, and are not meter-short-code normalized.
- The same collector or photo cannot be consumed twice inside one project; identical values are legal in different projects.
- Batch import remains absent, and no collector endpoint may call or accept credentials for the client platform.
- Original `material_groups` and `photos` rows are read-only inputs.
- New installation remains exactly `module_meter` plus `after_box`; removal remains one collector photo.
- Protect the unrelated untracked `v2-api/uv.lock`; never edit, stage, delete, or commit it.
- Production release version is V3.2.7 with Alembic head `20260824_0016`.

---

## File Structure

- `v2-api/app/domain/collector_transfer.py`: pure project-inventory decision enum and state machine.
- `v2-api/app/models.py`: project ownership and project-scoped uniqueness for inventory rows.
- `v2-api/alembic/versions/0016_project_scoped_collector_inventory.py`: guarded backfill and constraint migration.
- `v2-api/app/services/collector_transfer.py`: project projection, inventory scan/register/list, and same-project allocation.
- `v2-api/app/api/routes/collector_transfer.py`: no-run inventory HTTP contracts and safe image lifecycle.
- `v2-web/src/api/types.ts`: inventory request/response types.
- `v2-web/src/api/services.ts`: no-run inventory client functions.
- `v2-web/src/views/CollectorInventoryView.vue`: current-project scan/capture page with no batch UI.
- Existing collector transfer tests: domain, models, migrations, service, API, real PostgreSQL, and Vue behavior.
- V3.2.7 release files: version markers, release verifier/tests, manifest, release record, package gates, and production evidence.

### Task 1: Define the project-inventory decision contract

**Files:**
- Modify: `v2-api/app/domain/collector_transfer.py:27-92`
- Modify: `v2-api/tests/test_collector_transfer_domain.py`

**Interfaces:**
- Consumes: `normalize_identifier(value: object) -> str`.
- Produces: `ProjectInventoryDecisionKind`, `ProjectInventoryDecision`, and `decide_project_inventory_scan(...)` for the service layer.

- [ ] **Step 1: Write failing state-machine tests**

```python
def test_project_scan_non_direct_needs_photo_without_persistence_intent() -> None:
    result = decide_project_inventory_scan(
        collector_no=" 000123 ",
        is_project_requirement=False,
        existing_pool_status=None,
        has_active_photo=False,
    )
    assert result.kind is ProjectInventoryDecisionKind.POOL_NEEDS_PHOTO
    assert result.persist_confirmation is False
    assert result.requires_photo is True
    assert result.add_to_pool is True


def test_project_scan_direct_with_photo_is_confirmed_without_pool_admission() -> None:
    result = decide_project_inventory_scan(
        collector_no="000123",
        is_project_requirement=True,
        existing_pool_status="direct",
        has_active_photo=True,
    )
    assert result.kind is ProjectInventoryDecisionKind.DIRECT_REUSE
    assert result.persist_confirmation is True
    assert result.requires_photo is False
    assert result.add_to_pool is False


@pytest.mark.parametrize("status", ["reserved", "used"])
def test_project_scan_never_demotes_consumed_inventory(status: str) -> None:
    result = decide_project_inventory_scan(
        collector_no="C-1",
        is_project_requirement=True,
        existing_pool_status=status,
        has_active_photo=True,
    )
    assert result.kind.value == f"existing_{status}"
    assert result.persist_confirmation is False
```

- [ ] **Step 2: Run the focused test and confirm red**

Run: `v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_domain.py -q`

Expected: import or attribute failures for the new project-inventory contract.

- [ ] **Step 3: Implement the pure decision types and function**

```python
class ProjectInventoryDecisionKind(str, Enum):
    DIRECT_REUSE = "direct_reuse"
    DIRECT_NEEDS_PHOTO = "direct_needs_photo"
    POOL_NEEDS_PHOTO = "pool_needs_photo"
    EXISTING_AVAILABLE = "existing_available"
    EXISTING_RESERVED = "existing_reserved"
    EXISTING_USED = "existing_used"


@dataclass(frozen=True, slots=True)
class ProjectInventoryDecision:
    kind: ProjectInventoryDecisionKind
    persist_confirmation: bool
    requires_photo: bool
    add_to_pool: bool
```

`decide_project_inventory_scan` must give `reserved` and `used` precedence, return `existing_available` for an existing pool item, return direct reuse/photo decisions for project requirements, and return `pool_needs_photo` for a new non-direct number.

- [ ] **Step 4: Run the focused test and confirm green**

Run: `v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_domain.py -q`

Expected: all collector-transfer domain tests pass.

- [ ] **Step 5: Commit the domain contract**

```powershell
git add -- v2-api/app/domain/collector_transfer.py v2-api/tests/test_collector_transfer_domain.py
git commit -m "feat: define project collector inventory decisions"
```

### Task 2: Add guarded project ownership and uniqueness migration

**Files:**
- Modify: `v2-api/app/models.py:796-868`
- Create: `v2-api/alembic/versions/0016_project_scoped_collector_inventory.py`
- Modify: `v2-api/tests/test_models.py:117-148`
- Modify: `v2-api/tests/test_migrations.py:183-206`
- Modify: collector fixtures in `v2-api/tests/test_collector_transfer_service.py`, `v2-api/tests/test_collector_transfer_api.py`, and `v2-api/tests/test_collector_transfer_postgres_integration.py`

**Interfaces:**
- Consumes: existing revision `20260823_0015` and `Project.id`.
- Produces: `PhysicalCollector.project_id`, `CollectorPhoto.project_id`, nullable `CollectorScanEvent.run_id`, and non-null `CollectorScanEvent.project_id`.

- [ ] **Step 1: Write failing model and DDL assertions**

```python
def test_physical_collector_is_unique_per_project() -> None:
    constraints = {
        tuple(column.name for column in item.columns)
        for item in PhysicalCollector.__table__.constraints
        if isinstance(item, UniqueConstraint)
    }
    assert ("team_id", "project_id", "collector_no") in constraints
    assert ("team_id", "collector_no") not in constraints


def test_project_inventory_migration_is_guarded_and_chained() -> None:
    migration = load_migration_module("0016_project_scoped_collector_inventory.py")
    upgrade = render_postgresql_ddl("upgrade", "0016_project_scoped_collector_inventory.py")
    assert migration.down_revision == "20260823_0015"
    assert "project_id" in upgrade
    assert "ambiguous" in upgrade.lower()
    assert "uq_physical_collectors_team_project_no" in upgrade
    assert "uq_collector_photos_team_project_sha256" in upgrade
    assert "uq_collector_photos_one_active" in upgrade
```

- [ ] **Step 2: Run the focused schema tests and confirm red**

Run: `v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_models.py v2-api/tests/test_migrations.py -q`

Expected: old team-wide constraints and missing migration fail the new assertions.

- [ ] **Step 3: Update SQLAlchemy models**

Add `project_id` foreign keys and these model-level constraints/indexes:

```python
UniqueConstraint("team_id", "project_id", "collector_no", name="uq_physical_collectors_team_project_no")
Index("ix_physical_collectors_team_project_status", "team_id", "project_id", "pool_status")
UniqueConstraint("team_id", "project_id", "sha256", name="uq_collector_photos_team_project_sha256")
Index(
    "uq_collector_photos_one_active",
    "physical_collector_id",
    unique=True,
    postgresql_where=text("is_active"),
)
```

Change `CollectorScanEvent.run_id` to nullable with `ondelete="SET NULL"`; add `project_id` and index `(team_id, project_id, created_at)`.

- [ ] **Step 4: Implement the `20260824_0016` migration**

The upgrade must:

1. Add nullable project columns.
2. Backfill physical rows from `first_seen_run_id` and cross-check every run, scan event, and assignment points to one project.
3. Raise a PostgreSQL exception containing `ambiguous collector project ownership` before constraint changes when the cross-check finds more than one project or no project.
4. Backfill photos from physical rows and events from run/physical rows.
5. Set all three project columns non-null.
6. Replace team-wide unique constraints and indexes with project-scoped forms.
7. Preserve `awaiting_photo` as non-allocatable legacy state.

The downgrade must fail before DDL with `RuntimeError("project-scoped collector inventory is forward-only")`; after cross-project duplicate numbers exist, restoring the team-wide constraint is unsafe.

- [ ] **Step 5: Update every test fixture constructor with an explicit project**

Use the fixture run's `project_id`; do not introduce a global default or nullable test shortcut:

```python
PhysicalCollector(team_id=run.team_id, project_id=run.project_id, collector_no="C-1", pool_status="available")
CollectorPhoto(team_id=run.team_id, project_id=run.project_id, physical_collector_id=physical.id, ...)
CollectorScanEvent(run_id=run.id, project_id=run.project_id, team_id=run.team_id, ...)
```

- [ ] **Step 6: Run schema and collector tests**

Run: `v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_models.py v2-api/tests/test_migrations.py v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_api.py -q`

Expected: all tests pass with project-explicit fixtures.

- [ ] **Step 7: Commit the migration slice**

```powershell
git add -- v2-api/app/models.py v2-api/alembic/versions/0016_project_scoped_collector_inventory.py v2-api/tests/test_models.py v2-api/tests/test_migrations.py v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_api.py v2-api/tests/test_collector_transfer_postgres_integration.py
git commit -m "feat: scope collector inventory to projects"
```

### Task 3: Implement no-run project inventory service commands

**Files:**
- Modify: `v2-api/app/services/collector_transfer.py:216-885`
- Modify: `v2-api/tests/test_collector_transfer_service.py`

**Interfaces:**
- Consumes: `decide_project_inventory_scan`, project-scoped model columns, `meter_sources_from_groups`.
- Produces:
  - `scan_inventory(*, project_id: str, collector_no: str) -> dict[str, object]`
  - `register_inventory(*, project_id: str, collector_no: str, original_filename: str, stored: Mapping[str, object], byte_size: int) -> dict[str, object]`
  - `list_inventory(*, project_id: str, status: str | None = None) -> dict[str, object]`

- [ ] **Step 1: Write failing service tests for the three persistence boundaries**

```python
def test_non_direct_scan_leaves_no_business_rows(db_session: Session) -> None:
    project = project_row(db_session)
    result = service(db_session).scan_inventory(project_id=str(project.id), collector_no="POOL-001")
    assert result["decision"] == "pool_needs_photo"
    assert db_session.scalar(select(func.count(PhysicalCollector.id))) == 0
    assert db_session.scalar(select(func.count(CollectorScanEvent.id))) == 0


def test_direct_scan_without_photo_persists_only_direct_confirmation(db_session: Session) -> None:
    project, _group = project_with_collector_requirement(db_session, collector_no="DIRECT-001")
    result = service(db_session).scan_inventory(project_id=str(project.id), collector_no="DIRECT-001")
    assert result["decision"] == "direct_needs_photo"
    physical = db_session.scalar(select(PhysicalCollector))
    assert physical.project_id == project.id
    assert physical.pool_status == "direct"
    assert db_session.scalar(select(func.count(CollectorPhoto.id))) == 0


def test_non_direct_photo_atomically_creates_available_inventory(db_session: Session) -> None:
    project = project_row(db_session)
    result = service(db_session).register_inventory(
        project_id=str(project.id), collector_no="POOL-001", original_filename="POOL-001.jpg",
        stored=stored_photo("a" * 64), byte_size=128,
    )
    assert result["pool_status"] == "available"
    assert db_session.scalar(select(func.count(PhysicalCollector.id))) == 1
    assert db_session.scalar(select(func.count(CollectorPhoto.id))) == 1
```

- [ ] **Step 2: Run the focused service tests and confirm red**

Run: `v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_service.py -q`

Expected: missing method failures.

- [ ] **Step 3: Extract a shared project collector-number projection**

Add `_project_collector_numbers(project_id: UUID) -> frozenset[str]` using the same source precedence as `meter_sources_from_groups`: current project groups, active photos first, then compatible group fields. Both `create_run` and `scan_inventory` must use the same helper.

- [ ] **Step 4: Implement scan without a run**

`scan_inventory` must lock an existing same-project physical row when present. For a new direct number it creates `PhysicalCollector(pool_status="direct", project_id=...)` plus one `CollectorScanEvent(run_id=None, project_id=...)`. For a new non-direct number it returns `pool_needs_photo` before creating any ORM object.

- [ ] **Step 5: Implement atomic inventory registration and project SHA rules**

`register_inventory` must re-evaluate direct/non-direct state inside the transaction, recover from project-number uniqueness races, enforce project SHA uniqueness, and never change `reserved` or `used` back to another state. Create `direct` for a project requirement and `available` otherwise.

- [ ] **Step 6: Implement list inventory**

Return `items`, `total`, and stats for `direct`, `available`, `reserved`, `used`, and legacy `awaiting_photo`. Every query includes both `team_id` and `project_id`.

- [ ] **Step 7: Add duplicate and cross-project tests**

Cover same-number idempotency, same-photo same-collector idempotency, same-photo different-collector conflict, same values in two projects, and direct rows never appearing in the `available` candidate query.

- [ ] **Step 8: Run focused tests and commit**

Run: `v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_domain.py v2-api/tests/test_collector_transfer_service.py -q`

```powershell
git add -- v2-api/app/domain/collector_transfer.py v2-api/app/services/collector_transfer.py v2-api/tests/test_collector_transfer_domain.py v2-api/tests/test_collector_transfer_service.py
git commit -m "feat: add no-run collector inventory service"
```

### Task 4: Expose atomic project inventory API and retire run-scanning mutations

**Files:**
- Modify: `v2-api/app/api/routes/collector_transfer.py:29-301`
- Modify: `v2-api/tests/test_collector_transfer_api.py`

**Interfaces:**
- Consumes: Task 3 service methods and `save_image_bytes`/`delete_saved_image` cleanup behavior.
- Produces: `POST /collector-transfer/inventory/scan`, `POST /collector-transfer/inventory`, and `GET /collector-transfer/inventory`.

- [ ] **Step 1: Write failing API contract tests**

```python
def test_inventory_scan_requires_no_run_and_non_direct_has_zero_rows(client, db_session) -> None:
    response = client.post(
        "/collector-transfer/inventory/scan",
        headers=auth_headers(),
        json={"project_id": str(PROJECT_ID), "collector_no": "POOL-001"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["decision"] == "pool_needs_photo"
    assert db_session.scalar(select(func.count(PhysicalCollector.id))) == 0


def test_inventory_photo_rejects_cross_collector_sha_and_cleans_new_object(client, monkeypatch) -> None:
    response = client.post(
        "/collector-transfer/inventory",
        headers=auth_headers(),
        data={"project_id": str(PROJECT_ID), "collector_no": "C-2"},
        files={"file": ("C-2.jpg", b"duplicate", "image/jpeg")},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "photo_conflict"
    assert deleted_storage_keys == [new_storage_key]
```

- [ ] **Step 2: Run API tests and confirm red**

Run: `v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_api.py -q`

- [ ] **Step 3: Add strict Pydantic scan request and GET filters**

`InventoryScanRequest` uses `extra="forbid"`, project ID length 1-64, and collector text length 1-255. GET accepts `project_id` and optional known status only.

- [ ] **Step 4: Add the multipart atomic endpoint**

Save under `scope="collector-inventory"`, `group_id=project_id`, and a key hint derived from collector/project IDs. Always call `cleanup_unregistered_saved_images` after success and on caught domain failures so deduplicated or rejected new objects do not leak.

- [ ] **Step 5: Retire old mutating routes**

Remove the two route handlers that accept `run_id` for scanning/upload and assert both old paths return `404`. Do not leave wrappers that can create `awaiting_photo` rows.

- [ ] **Step 6: Verify permissions and no client-platform integration**

Add tests for cross-team project access, inactive project, unknown project, and request bodies containing unknown platform credential fields.

- [ ] **Step 7: Run API/service tests and commit**

Run: `v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_api.py v2-api/tests/test_collector_transfer_service.py -q`

```powershell
git add -- v2-api/app/api/routes/collector_transfer.py v2-api/tests/test_collector_transfer_api.py
git commit -m "feat: expose project collector inventory API"
```

### Task 5: Make runs consume same-project long-lived inventory

**Files:**
- Modify: `v2-api/app/services/collector_transfer.py:333-497, 886-1130`
- Modify: `v2-api/tests/test_collector_transfer_service.py`
- Modify: `v2-api/tests/test_collector_transfer_postgres_integration.py`

**Interfaces:**
- Consumes: project-scoped physical/photo inventory.
- Produces: `_bind_direct_inventory(run)` and allocation queries filtered by `run.project_id`.

- [ ] **Step 1: Write failing direct-bind and isolation tests**

```python
def test_create_run_binds_photographed_same_project_direct_inventory(db_session: Session) -> None:
    project, group = project_with_collector_requirement(db_session, collector_no="DIRECT-1")
    physical, photo = photographed_inventory(db_session, project, "DIRECT-1", status="direct")
    created = service(db_session).create_run(project_id=str(project.id), name="run")
    assignment = db_session.scalar(select(CollectorAssignment))
    assert assignment.physical_collector_id == physical.id
    assert assignment.collector_photo_id == photo.id
    assert assignment.assignment_mode == "direct"


def test_allocate_never_reads_available_inventory_from_another_project(db_session: Session) -> None:
    run = run_with_requirement(db_session, project=project_a)
    photographed_inventory(db_session, project_b, "POOL-B", status="available")
    with pytest.raises(PoolInsufficientError) as error:
        service(db_session).allocate(run_id=str(run.id))
    assert error.value.available == 0
```

- [ ] **Step 2: Run focused tests and confirm red**

Run: `v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_postgres_integration.py -q`

- [ ] **Step 3: Bind direct inventory when a run snapshot is created**

After all requirements are flushed, lock matching `direct`/`available` physical rows with active photos in the same team and project, create `direct` assignments, set requirements to `direct_ready`, and create removal workbench items. A same-number direct row without a photo sets `direct_pending_photo` and cannot be bypassed by random allocation.

- [ ] **Step 4: Filter allocation and rollback by project invariant**

Add `PhysicalCollector.project_id == run.project_id` and `CollectorPhoto.project_id == run.project_id` to candidate/validation queries. Before creating or completing an assignment, reject any team/project mismatch with a stable conflict error.

- [ ] **Step 5: Verify real PostgreSQL locking behavior**

Run the repository's disposable PostgreSQL fixture tests for concurrent registration and concurrent allocation. Assert one active assignment per physical and requirement and legal same-number inventory across two projects.

- [ ] **Step 6: Run focused tests and commit**

Run: `v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_postgres_integration.py -q`

```powershell
git add -- v2-api/app/services/collector_transfer.py v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_postgres_integration.py
git commit -m "feat: consume project inventory in collector runs"
```

### Task 6: Replace the mobile batch UI with current-project scan and capture

**Files:**
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts:2890-2957`
- Rewrite: `v2-web/src/views/CollectorInventoryView.vue`
- Modify: `v2-web/src/views/__tests__/CollectorInventoryView.spec.ts`
- Modify: `v2-web/src/views/__tests__/CollectorInventoryRouting.spec.ts`

**Interfaces:**
- Consumes: Task 4 HTTP responses.
- Produces:
  - `scanProjectCollector(projectId: string, collectorNo: string): Promise<CollectorInventoryDecision>`
  - `registerProjectCollector(projectId: string, collectorNo: string, file: File): Promise<CollectorPhotoRegistration>`
  - `fetchProjectCollectorInventory(projectId: string): Promise<CollectorInventoryPage>`

- [ ] **Step 1: Rewrite tests around current-project behavior**

```ts
it('opens ready to scan without loading or selecting a run', async () => {
  mountView({ activeProjectId: 'project-1' })
  expect(fetchCollectorTransferRuns).not.toHaveBeenCalled()
  expect(wrapper.find('[data-testid="collector-run-select"]').exists()).toBe(false)
  expect(wrapper.get('[data-testid="project-identity"]').text()).toContain('项目一')
  expect(wrapper.get('[data-testid="start-camera"]').attributes('disabled')).toBeUndefined()
})

it('cancelling a non-direct photo never calls registration', async () => {
  scanProjectCollector.mockResolvedValue({ decision: 'pool_needs_photo', requires_photo: true })
  await submitBarcode('POOL-1')
  await cancelCapture()
  expect(registerProjectCollector).not.toHaveBeenCalled()
})
```

- [ ] **Step 2: Run the component test and confirm red**

Run from `v2-web`: `npm test -- --run src/views/__tests__/CollectorInventoryView.spec.ts`

- [ ] **Step 3: Replace API types and service functions**

Remove `runId` from the mobile scan/register signatures. Preserve batch API types used by `CollectorBatchManagementView` and `CollectorWorkbenchView`.

- [ ] **Step 4: Remove batch state and controls from the Vue page**

Delete run list loading, selected run, setup dialog, run progress, run generation guards, and batch selectors. Read `workspace.activeProject?.id`; if absent, show only the safe project-selection empty state.

- [ ] **Step 5: Implement decision-driven scan/capture**

Keep `BarcodeDetector`, manual input, external scanner, local preview, and URL cleanup. `direct_reuse` shows the existing photo and continues; `direct_needs_photo` and `pool_needs_photo` open capture; `existing_available` reports already in pool; reserved/used are blocking notices.

- [ ] **Step 6: Keep retry local and discard it on refresh/unmount**

Upload failure retains `collectorNo` and the local object URL only in component state. Cancel/unmount revokes the URL and makes no registration request.

- [ ] **Step 7: Run frontend tests, type-check, and build**

```powershell
Push-Location v2-web
npm test -- --run src/views/__tests__/CollectorInventoryView.spec.ts src/views/__tests__/CollectorInventoryRouting.spec.ts src/views/__tests__/CollectorBatchManagementView.spec.ts src/views/__tests__/CollectorWorkbenchView.spec.ts
npm run type-check
npm run build
Pop-Location
```

Expected: tests/type-check/build pass; built collector inventory chunk contains no run scan URL, inventory import text, or client-platform upload call.

- [ ] **Step 8: Commit the mobile slice**

```powershell
git add -- v2-web/src/api/types.ts v2-web/src/api/services.ts v2-web/src/views/CollectorInventoryView.vue v2-web/src/views/__tests__/CollectorInventoryView.spec.ts v2-web/src/views/__tests__/CollectorInventoryRouting.spec.ts
git commit -m "feat: scan project collectors without batches"
```

### Task 7: Complete migrations, regression, and browser acceptance locally

**Files:**
- Verify: `v2-api/app/domain/collector_transfer.py`
- Verify: `v2-api/app/models.py`
- Verify: `v2-api/alembic/versions/0016_project_scoped_collector_inventory.py`
- Verify: `v2-api/app/services/collector_transfer.py`
- Verify: `v2-api/app/api/routes/collector_transfer.py`
- Verify: `v2-web/src/api/types.ts`
- Verify: `v2-web/src/api/services.ts`
- Verify: `v2-web/src/views/CollectorInventoryView.vue`
- Do not modify: `v2-api/uv.lock`

**Interfaces:**
- Consumes: completed backend/frontend slices.
- Produces: evidence that every spec invariant passes before version packaging.

- [ ] **Step 1: Run migration upgrade on disposable PostgreSQL**

Start from `20260823_0015`, seed one unambiguous run/physical/photo/event, upgrade to `20260824_0016`, and assert project IDs and constraints. Then seed an ambiguous cross-project reference on a separate database and assert the migration stops before constraint mutation.

- [ ] **Step 2: Run all collector and migration tests**

```powershell
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_domain.py v2-api/tests/test_models.py v2-api/tests/test_migrations.py v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_api.py v2-api/tests/test_collector_transfer_postgres_integration.py -q
```

- [ ] **Step 3: Run the complete backend suite**

Run: `v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests -q`

Expected: command exits 0; timeout or missing final summary is not a pass.

- [ ] **Step 4: Run complete frontend validation**

```powershell
Push-Location v2-web
npm test -- --run
npm run type-check
npm run build
Pop-Location
```

- [ ] **Step 5: Exercise local browser flows**

Use a disposable local PostgreSQL project to verify at 390x844: page opens without run, direct confirmation, non-direct cancel zero rows, non-direct photo success, duplicate scan feedback, manual fallback, retry, and project switch isolation. Verify batch creation then consumes direct and random project inventory and workbench still shows the three confirmed photo slots.

- [ ] **Step 6: Run source hygiene**

```powershell
git diff --check
git status --short
rg -n "inventory/import|runs/.*/scan|当前批次|选择盘点批次" v2-web/src/views/CollectorInventoryView.vue v2-web/src/api/services.ts
```

Expected: no forbidden mobile batch/import references; only `v2-api/uv.lock` remains unrelated/untracked.

- [ ] **Step 7: Commit any focused verification fixes**

Use explicit paths and a message describing the actual corrected invariant. Do not create an empty verification commit.

### Task 8: Prepare and verify the V3.2.7 production candidate

**Files:**
- Modify: `AGENTS.md`
- Modify: `RELEASE_MANIFEST.md`
- Modify: `v2-api/app/main.py`
- Modify: `v2-api/app/services/ops_status.py`
- Modify: `v2-api/pyproject.toml`
- Modify: `v2-api/scripts/verify_v3_1_release.py`
- Modify: `v2-api/tests/test_v3_1_release.py`
- Modify: `v2-web/index.html`
- Modify: `v2-web/src/components/AppLayout.vue`
- Modify: `v2-web/src/constants/releaseNotes.ts`
- Create: `scripts/verify_v3_2_7_release.py`
- Create: `scripts/test_verify_v3_2_7_release.py`
- Modify: `scripts/verify-client-release.py`
- Modify: `scripts/test_verify_client_release.py`
- Modify: `scripts/build-client-release.ps1`
- Modify: `scripts/verify_release_sop.py`
- Modify: `scripts/test_verify_release_sop.py`
- Create: `ops/releases/V3.2.7.md`

**Interfaces:**
- Consumes: source/tests/build from Tasks 1-7.
- Produces: `build/server-release/module-manager-v2-server-3.2.7.zip`, SHA256, source commit, and pending release record.

- [ ] **Step 1: Write V3.2.7 release gate tests first**

Copy the V3.2.6 verifier contract, update version/head/branch/file names, and add required assertions for the new migration, no-run inventory endpoints, and absence of old mutating run-scan routes from the frontend.

- [ ] **Step 2: Run release tests and confirm red before version edits**

Run: `v2-api\.venv\Scripts\python.exe -m pytest scripts/test_verify_v3_2_7_release.py scripts/test_verify_client_release.py scripts/test_verify_release_sop.py -q`

- [ ] **Step 3: Advance all source markers to V3.2.7**

Use candidate branch `production/V3/3.2.7`, database head `20260824_0016`, and deployed baseline `V3.2.6`. Release notes describe current-project no-batch scanning, atomic photo admission, project isolation, and unchanged client-platform boundary.

- [ ] **Step 4: Run source release gates**

```powershell
v2-api\.venv\Scripts\python.exe scripts/verify_v3_2_7_release.py --phase source
v2-api\.venv\Scripts\python.exe scripts/verify_release_sop.py --version V3.2.7 --phase source
```

- [ ] **Step 5: Commit candidate metadata with explicit paths**

Stage only the listed V3.2.7 files and commit `release: prepare V3.2.7 project collector inventory`.

- [ ] **Step 6: Build and verify the release package**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-client-release.ps1 -Version 3.2.7
v2-api\.venv\Scripts\python.exe scripts/verify-client-release.py build/server-release/module-manager-v2-server-3.2.7.zip
Get-FileHash -Algorithm SHA256 -LiteralPath build/server-release/module-manager-v2-server-3.2.7.zip
```

Expected: package members, source commit, static assets, migration head, CRC, duplicate/case/path checks, and V3.2.7 release contract all pass.

### Task 9: Back up, deploy, and attest V3.2.7 production

**Files:**
- Modify after verified deployment: `ops/releases/V3.2.7.md`

**Interfaces:**
- Consumes: verified V3.2.7 ZIP and `C:\Users\Administrator\Downloads\XXXXXX.pem`.
- Produces: production current symlink on V3.2.7, migration head `20260824_0016`, public/authenticated acceptance, restore-ready backup evidence, and attestation commit.

- [ ] **Step 1: Read-only production preflight**

Using `root@www.sgcc.online`, verify SSH identity, `readlink -f /opt/module-manager-v2/current`, `systemctl status`, `ss -ltnp` for `127.0.0.1:8000`, `df -h`, current Alembic head, and available releases/backups. Do not delete releases or backups.

- [ ] **Step 2: Run migration ambiguity preflight before backup or cutover**

Execute read-only SQL that reports every physical collector whose historical runs/scans/assignments resolve to zero or multiple project IDs. Stop deployment if any row is reported.

- [ ] **Step 3: Create a fresh restore-ready backup without consuming scarce server disk**

Because the server was previously at 97% usage, stream `pg_dump -Fc`, `database-schema.sql`, `.env`, current release metadata, `data.tar.gz`, and `uploads.tar.gz` over SSH into a timestamped local directory under `C:\Users\Administrator\Documents\module-manager-production-backups`. Verify SHA256, `pg_restore -l`, and archive listing locally before continuing. Never delete the existing V3.2.6 backup.

- [ ] **Step 4: Upload and verify the package**

```powershell
scp -i "C:\Users\Administrator\Downloads\XXXXXX.pem" build/server-release/module-manager-v2-server-3.2.7.zip root@www.sgcc.online:/tmp/
ssh -i "C:\Users\Administrator\Downloads\XXXXXX.pem" root@www.sgcc.online "sha256sum /tmp/module-manager-v2-server-3.2.7.zip"
```

Server SHA256 must exactly match the verified local hash.

- [ ] **Step 5: Deploy with the production runbook safety gates**

Create `/opt/module-manager-v2/releases/v3.2.7-<UTC timestamp>`, unpack, restore production `.env`, install dependencies, normalize permissions with `chmod -R g-w,g+rX` and correct group ownership, verify `runuser -u modulemgr -- ... "from PIL import Image"`, run Alembic to `20260824_0016`, atomically switch `current`, and restart `module-manager-v2.service`.

If migration, permission, service start, or port readiness fails, stop and restore the V3.2.6 current symlink. If the migration committed, application-only rollback is forbidden; restore the just-created database/uploads backup as documented in the spec.

- [ ] **Step 6: Wait for real application readiness**

Do not trust systemd `active` alone. Wait until Uvicorn listens on `127.0.0.1:8000`, then require local `/health` 200 and version 3.2.7 before public checks.

- [ ] **Step 7: Run public, security, and authenticated acceptance**

Run `production_health_check.py --expected-version 3.2.7` and `audit_production_security.py`. Verify `/collector-inventory`, `/collector-batches`, `/collector-workbench`, and `/project-board` return 200. After authenticated login, confirm inventory opens at 390x844 without a batch selector/import action, current project is visible, camera/manual controls are enabled, and console/network logs contain no client-platform request.

Use a guaranteed non-matching smoke barcode against the active project to verify `pool_needs_photo`; compare database counts before/after to prove the scan creates no physical, photo, or business event. Do not upload a real or synthetic photo into the live project during smoke acceptance.

- [ ] **Step 8: Record deployment evidence and attest**

Update `ops/releases/V3.2.7.md` with source commit, local/server SHA256, local streamed-backup path and verification, release directory, rollback release, migration head, readiness, health/security, authenticated browser evidence, and the intentionally non-mutating smoke result.

Run:

```powershell
v2-api\.venv\Scripts\python.exe scripts/verify_v3_2_7_release.py --phase attestation
git add -- ops/releases/V3.2.7.md
git commit -m "release: record V3.2.7 production deployment"
```

- [ ] **Step 9: Final completion audit**

Re-read every requirement in the spec and point it to a passing test, current production endpoint, migration evidence, browser evidence, package hash, or release-record field. Confirm `git status --short` contains only protected `v2-api/uv.lock`; confirm production `current`, `/health`, migration head, and authenticated UI remain healthy after the attestation commit.
