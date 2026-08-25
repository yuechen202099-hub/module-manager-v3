# Global Terminal Collector Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the project/run-driven collector workbench with a global terminal selector, allow scanned same-number physical collectors to be re-photographed without a website photo, atomically replace every missing collector in one terminal, and deploy the verified V3.2.8 result to production.

**Architecture:** The UI searches team-wide terminal candidates but never chooses a project or run. The API revalidates the candidate's internal project, creates or reuses an immutable single-terminal hidden run in the existing collector-transfer tables, and projects each collector as `present`, `missing`, or `replaced`. Direct physical collectors use a `CollectorWorkbenchItem` whose `requirement_id` is non-null and `assignment_id` is null, with no fake photo; random replacements keep existing one-to-one `CollectorAssignment` rows and active pool photos.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy 2, PostgreSQL, pytest, Vue 3, TypeScript, Vitest, Vue Router, PowerShell release tooling, SSH/systemd/Nginx production deployment.

**Spec:** `docs/superpowers/specs/2026-08-25-global-terminal-collector-workbench-design.md`

## Global Constraints

- New-install work items contain exactly `module_meter` (“电表和模块”) and `after_box` (“改造完成”); collector removal contains one collector position.
- Same-number inventory scan returns no-photo direct readiness, never enters the random pool, and never creates a fake `CollectorPhoto`.
- Random replacement is scoped by authenticated `team_id` and hidden-run `project_id`; no cross-project or cross-team inventory use is permitted.
- One terminal click allocates every current missing requirement or allocates none; pool shortage produces zero assignment/requirement/physical/workbench mutations.
- Effective collector precedence, module/photo selection, text trimming, leading zeroes, and arbitrary text remain identical across inventory scan, candidate listing, and hidden snapshot creation.
- Original `material_groups`, `photos`, total-catalog data, collector photos, and historical assignments remain immutable/auditable.
- Only an authenticated administrator may replace missing collectors, roll back random replacement, refresh a progressed snapshot, or call the legacy allocate endpoint.
- `/collector-batches` redirects to `/collector-workbench`; no batch page remains in navigation.
- V3.2.8 retains Alembic head `20260824_0016`; do not add a migration unless implementation proves the approved no-migration representation unsafe and the design is explicitly reopened.
- Never edit, stage, delete, package, or commit the unrelated untracked `v2-api/uv.lock`.
- Do not reuse the stale V3.2.8 ZIP whose `SOURCE_COMMIT` is `253ff06`; rebuild the final ZIP from the final source commit.
- Do not overwrite the deployed V3.2.7 release or V3.2.7 ZIP, and do not delete production releases/backups.
- Keep production maintenance worker/timer stopped until listener, smoke, workbench, and real-phone camera acceptance pass.

---

## File Structure

- `v2-api/app/domain/collector_transfer.py`: no-photo inventory decision and pure terminal-key/revision/state helpers.
- `v2-api/app/services/collector_transfer.py`: terminal candidate queries, hidden snapshot lifecycle, direct binding, terminal detail, canonical mutation locks, replacement, rollback, completion, audit.
- `v2-api/app/api/routes/collector_transfer.py`: typed global-terminal DTOs, role-aware identity, stable errors, and new endpoints.
- `v2-api/tests/test_collector_transfer_domain.py`: direct decision and deterministic key/revision/state tests.
- `v2-api/tests/test_collector_transfer_service.py`: hidden snapshot, direct binding, source-change, detail, replacement, rollback, and completion tests.
- `v2-api/tests/test_collector_transfer_api.py`: HTTP shapes, tenancy, role matrix, redirect-independent API behavior, and stable error tests.
- `v2-api/tests/test_collector_transfer_postgres_integration.py`: advisory-lock, allocation race, direct-claim race, and lock-order integration tests.
- `v2-api/tests/test_collector_transfer_scale.py`: bounded page/index and selected-terminal projection query-shape regressions.
- `v2-web/src/api/types.ts`: global terminal, physical-state, pool summary, and workbench DTOs.
- `v2-web/src/api/services.ts`: global terminal list/open/detail/replace/refresh/rollback clients.
- `v2-web/src/features/collectorTransfer/state.ts`: pure candidate labels, completion blockers, replacement permission, and stale-response guards.
- `v2-web/src/views/CollectorInventoryView.vue`: remove the same-number photo branch while preserving mobile scanner lifecycle.
- `v2-web/src/views/CollectorWorkbenchView.vue`: global terminal search and integrated replacement/re-photo workflow.
- `v2-web/src/views/__tests__/CollectorInventoryView.spec.ts`: same-number no-photo UI regression.
- `v2-web/src/views/__tests__/CollectorWorkbenchView.spec.ts`: terminal search, state cards, role controls, replacement, completion, and stale-response regressions.
- `v2-web/src/router/index.ts`, `v2-web/src/router/staticPages.ts`, `v2-web/src/layouts/AppLayout.vue`: batch-route redirect and navigation retirement.
- Delete `v2-web/src/views/CollectorBatchManagementView.vue` and `v2-web/src/views/__tests__/CollectorBatchManagementView.spec.ts` after the redirect no longer imports them.
- `v2-api/app/static/vue/**`: rebuilt tracked Vue production assets.
- `ops/releases/V3.2.8.md`: source/package/production evidence for the integrated feature.

### Task 1: Make same-number inventory and direct binding photo-free

**Files:**
- Modify: `v2-api/app/domain/collector_transfer.py:159-200`
- Modify: `v2-api/app/services/collector_transfer.py:615-745,1000-1091,1093-1221`
- Modify: `v2-api/tests/test_collector_transfer_domain.py`
- Modify: `v2-api/tests/test_collector_transfer_service.py`
- Modify: `v2-web/src/views/CollectorInventoryView.vue`
- Modify: `v2-web/src/views/__tests__/CollectorInventoryView.spec.ts`

**Interfaces:**
- Consumes: `decide_project_inventory_scan`, `_project_has_collector_number`, `PhysicalCollector.pool_status`, successful `CollectorScanEvent` provenance.
- Produces: same-number decision `direct_reuse` with `requires_photo=False`; `_ensure_direct_removal_workbench_item(run, requirement)` with `assignment_id=None`; direct requirement state `direct_ready` without `CollectorPhoto`.

- [ ] **Step 1: Write the failing pure-domain no-photo test**

Add this literal regression:

```python
def test_project_requirement_without_photo_is_direct_reuse() -> None:
    decision = decide_project_inventory_scan(
        collector_no="00001234",
        is_project_requirement=True,
        existing_pool_status=None,
        has_active_photo=False,
    )
    assert decision.kind is ProjectInventoryDecisionKind.DIRECT_REUSE
    assert decision.persist_confirmation is True
    assert decision.requires_photo is False
    assert decision.add_to_pool is False
```

Keep separate existing-status assertions proving `reserved` and `used` still return their terminal decisions and never regress.

- [ ] **Step 2: Run the domain test and verify RED**

```powershell
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_domain.py -q -k "without_photo_is_direct_reuse"
```

Expected: FAIL because the current decision is `direct_needs_photo` with `requires_photo=True`.

- [ ] **Step 3: Change only the direct decision branch**

Replace the photo-conditioned direct decision with:

```python
if is_project_requirement or status == "direct":
    return ProjectInventoryDecision(
        kind=ProjectInventoryDecisionKind.DIRECT_REUSE,
        persist_confirmation=True,
        requires_photo=False,
        add_to_pool=False,
    )
```

Do not change the nonmatching `pool_needs_photo` branch or the existing `available/reserved/used` branches.

- [ ] **Step 4: Add failing service tests for photo-free scan and run binding**

Use the existing project/service fixtures and assert:

```python
result = service.scan_inventory(project_id=str(project.id), collector_no="DIRECT-001")
assert result["decision"] == "direct_reuse"
assert result["requires_photo"] is False
physical = session.scalar(select(PhysicalCollector).where(PhysicalCollector.collector_no == "DIRECT-001"))
assert physical is not None and physical.pool_status == "direct"
assert session.scalar(select(func.count(CollectorPhoto.id))) == 0
assert session.scalar(select(func.count(CollectorScanEvent.id))) == 1

run = service.create_run(project_id=str(project.id), name="direct no photo")
requirement = session.scalar(select(CollectorRequirement).where(CollectorRequirement.run_id == UUID(run["id"])))
item = session.scalar(select(CollectorWorkbenchItem).where(CollectorWorkbenchItem.requirement_id == requirement.id))
assert requirement.status == "direct_ready"
assert item is not None and item.assignment_id is None
assert session.scalar(select(func.count(CollectorAssignment.id))) == 0
```

Add a regression proving an `available` nonmatching pool item is not silently converted into a direct binding unless it has a successful same-number direct scan.

- [ ] **Step 5: Run the focused service tests and verify RED**

```powershell
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_service.py -q -k "direct_without_photo or available_pool_is_not_direct"
```

Expected: FAIL because `_bind_direct_inventory` currently leaves no-photo requirements `direct_pending_photo` and requires a direct assignment/photo before a workbench item exists.

- [ ] **Step 6: Add the direct workbench item path**

Implement:

```python
def _ensure_direct_removal_workbench_item(
    self,
    *,
    run: CollectorTransferRun,
    requirement: CollectorRequirement,
) -> CollectorWorkbenchItem:
    item = self.session.scalar(
        select(CollectorWorkbenchItem).where(
            CollectorWorkbenchItem.run_id == run.id,
            CollectorWorkbenchItem.requirement_id == requirement.id,
        )
    )
    if item is None:
        item = CollectorWorkbenchItem(
            run_id=run.id,
            terminal_id=requirement.terminal_id,
            team_id=self.team_id,
            item_kind="collector_removal",
            source_key=str(requirement.id),
            requirement_id=requirement.id,
            assignment_id=None,
            status="pending",
            sort_order=requirement.sort_order,
        )
        self.session.add(item)
        self.session.flush()
    return item
```

Refactor `_bind_direct_inventory` so only eligible same-number `direct` physical rows are bound without reading or creating a collector photo. Set `requirement.status="direct_ready"`, keep `physical.pool_status="direct"`, create the direct item, and audit `collector_workbench.direct_bound`. Preserve random-pool eligibility and historical rows.

- [ ] **Step 7: Remove the same-number photo UI branch**

Update inventory-page handling so `direct_reuse` always renders “同号已确认，可直接拿实物翻拍”, never opens the file/camera capture step, and refreshes the inventory list. Keep `pool_needs_photo` as the only decision that enters capture and multipart registration.

Add a component assertion:

```ts
serviceMocks.scanProjectCollector.mockResolvedValue({
  collector_id: 'physical-1', collector_no: 'DIRECT-001', decision: 'direct_reuse',
  requires_photo: false, add_to_pool: false, pool_status: 'direct', photo: null,
})
await scan('DIRECT-001')
expect(wrapper.text()).toContain('同号已确认')
expect(wrapper.find('[data-testid="capture-photo"]').exists()).toBe(false)
expect(serviceMocks.registerProjectCollector).not.toHaveBeenCalled()
```

- [ ] **Step 8: Verify GREEN and commit**

```powershell
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_domain.py v2-api/tests/test_collector_transfer_service.py -q -k "inventory or direct"
Push-Location v2-web
npm run test:collector-transfer -- CollectorInventoryView.spec.ts
Pop-Location
git add -- v2-api/app/domain/collector_transfer.py v2-api/app/services/collector_transfer.py v2-api/tests/test_collector_transfer_domain.py v2-api/tests/test_collector_transfer_service.py v2-web/src/views/CollectorInventoryView.vue v2-web/src/views/__tests__/CollectorInventoryView.spec.ts
git commit -m "feat: allow direct collector rephoto without website photo"
```

### Task 2: Add bounded global terminal candidates and immutable hidden snapshots

**Files:**
- Modify: `v2-api/app/domain/collector_transfer.py`
- Modify: `v2-api/app/services/collector_transfer.py:80-745`
- Modify: `v2-api/tests/test_collector_transfer_domain.py`
- Modify: `v2-api/tests/test_collector_transfer_service.py`
- Modify: `v2-api/tests/test_collector_transfer_scale.py`

**Interfaces:**
- Consumes: streamed `_project_meter_projection`, `build_terminal_snapshots`, existing photo precedence, `CollectorTransferRun.stats` JSONB.
- Produces: `terminal_key(project_id: str, terminal_code: str) -> str`, `terminal_source_revision(rows: Iterable[Mapping[str, object]]) -> str`, `list_global_terminals(query, state, page, page_size, include_blocked)`, `open_global_terminal(project_id, terminal_code, source_revision="", terminal_key_value="", force_refresh=False)`, and a single-terminal `global_terminal_workbench` hidden run.

- [ ] **Step 1: Add failing deterministic helper tests**

Define literal contracts:

```python
def test_terminal_key_preserves_leading_zeroes_and_project_identity() -> None:
    assert terminal_key(PROJECT_A, " 000123 ") == terminal_key(PROJECT_A, "000123")
    assert terminal_key(PROJECT_A, "000123") != terminal_key(PROJECT_B, "000123")
    assert terminal_key(PROJECT_A, "000123") != terminal_key(PROJECT_A, "123")

def test_source_revision_is_order_stable_and_photo_sensitive() -> None:
    assert terminal_source_revision(reversed(rows)) == terminal_source_revision(rows)
    assert terminal_source_revision(rows) != terminal_source_revision(rows_with_changed_photo_sha)
```

Use URL-safe base64 for `terminal_key` and canonical JSON SHA256 for `source_revision`; neither helper is an authorization token.

- [ ] **Step 2: Run helper tests and verify RED**

```powershell
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_domain.py -q -k "terminal_key or source_revision"
```

Expected: FAIL because the helpers do not exist.

- [ ] **Step 3: Implement exact pure helpers**

Add:

```python
def terminal_key(project_id: str, terminal_code: str) -> str:
    normalized = normalize_identifier(terminal_code)
    raw = json.dumps([normalize_identifier(project_id), normalized], ensure_ascii=False, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")

def terminal_source_revision(rows: Iterable[Mapping[str, object]]) -> str:
    canonical = sorted(
        (dict(row) for row in rows),
        key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
```

Reject blank project/terminal values before generating a key.

- [ ] **Step 4: Add failing candidate-page tests**

Create two active projects with the same terminal code, one project with multiple groups on that terminal, and one address-conflict terminal. Assert the response includes:

```python
assert [(row["project_id"], row["terminal_code"]) for row in page["items"]] == [
    (str(project_a.id), "T-001"),
    (str(project_b.id), "T-001"),
]
assert all(row["needs_disambiguation"] for row in page["items"])
assert page["items"][0]["meter_count"] == 2
assert conflict["workflow_state"] == "blocked"
assert conflict["selectable"] is False
```

Add team isolation, `query`, `state`, page-size cap 100, leading-zero terminal, physical/missing/pool counts, and authoritative-address/photo-precedence cases.

- [ ] **Step 5: Add a bounded scale regression and verify RED**

On the existing 22,358-group/17,453-photo fixture, request page 1 with `page_size=50`. Record SQL and ORM loads and assert:

```python
assert result["page_size"] == 50
assert len(result["items"]) <= 50
assert loaded_source_entities == []
assert len(source_selects) <= 6
assert not any(statement.count("?") > 1000 for statement in source_selects)
```

Run:

```powershell
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_scale.py -q -k "global_terminal or terminal_candidate"
```

Expected: FAIL because the candidate service does not exist.

- [ ] **Step 6: Implement the bounded page projection**

Add `list_global_terminals` with this exact signature:

```python
def list_global_terminals(
    self,
    *,
    query: str = "",
    state: str | None = None,
    page: int = 1,
    page_size: int = 50,
    include_blocked: bool = False,
) -> dict[str, object]:
```

Use one paged identity query grouped by authenticated team, active project, and trimmed terminal code. For at most 100 keys, use bounded selected-column group/photo reads and feed the same projection rules used by `create_run`; installation address uses the linked total-catalog value first and only falls back to the material-group snapshot when the catalog value is blank. Aggregate direct physical inventory, active hidden assignments, and project `available` pool counts without materializing source ORM entities. Derive `ready`, `needs_replacement`, `pool_shortage`, or `blocked` exactly from the spec.

- [ ] **Step 7: Add failing hidden-snapshot lifecycle tests**

Assert:

```python
opened = service.open_global_terminal(
    project_id=str(project.id), terminal_code="T-001", source_revision=current_revision,
)
assert opened["snapshot_reused"] is False
run = session.get(CollectorTransferRun, UUID(opened["run_id"]))
assert run.stats["workflow_kind"] == "global_terminal_workbench"
assert run.stats["source_revision"] == current_revision
assert run.stats["source_terminal_code"] == "T-001"
assert len(session.scalars(select(CollectorTransferTerminal).where(CollectorTransferTerminal.run_id == run.id)).all()) == 1

reopened = service.open_global_terminal(
    project_id=str(project.id), terminal_code="T-001", source_revision=current_revision,
)
assert reopened["run_id"] == opened["run_id"]
assert reopened["snapshot_reused"] is True
```

Then change a selected source photo SHA and assert an untouched old run becomes `stats["superseded"]=True` and a new run is created. Complete one work item or create an active assignment before changing source and assert the old run is returned with `source_changed=True` and no state is silently released.

- [ ] **Step 8: Factor single-terminal run creation and advisory locking**

Extract the current run-row creation loop into a private helper used by both legacy project runs and global single-terminal runs:

```python
def _create_run_from_projection(
    self,
    *,
    project: Project,
    name: str,
    projection: MeterSourceProjection,
    source_photos_by_id: Mapping[str, _ProjectPhotoRow],
    stats_extra: Mapping[str, object] | None = None,
) -> CollectorTransferRun:
```

`open_global_terminal` filters the selected-column source query by exact normalized terminal, computes the revision, and calls this helper. On PostgreSQL, acquire `pg_advisory_xact_lock` from a stable signed 64-bit hash of `team_id/project_id/terminal_code` before reuse/create; SQLite unit tests use the same transaction path without issuing the PostgreSQL function. Mark old runs by assigning a new `stats` dict, never by inventing a new database status.

- [ ] **Step 9: Verify GREEN and commit**

```powershell
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_domain.py v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_scale.py -q -k "terminal or snapshot or projection"
git add -- v2-api/app/domain/collector_transfer.py v2-api/app/services/collector_transfer.py v2-api/tests/test_collector_transfer_domain.py v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_scale.py
git commit -m "feat: create global terminal collector snapshots"
```

### Task 3: Project present/missing/replaced detail and direct completion

**Files:**
- Modify: `v2-api/app/services/collector_transfer.py:1617-1960`
- Modify: `v2-api/tests/test_collector_transfer_service.py`
- Modify: `v2-api/tests/test_collector_transfer_postgres_integration.py`

**Interfaces:**
- Consumes: hidden run metadata, `CollectorRequirement`, direct no-assignment items, random assignments/photos.
- Produces: `global_terminal_detail(terminal_id)`, `_reconcile_direct_requirements(run, terminal)`, and direct completion/undo transitions.

- [ ] **Step 1: Add failing detail-shape tests**

Build one terminal with three requirements: direct/no-photo, unmatched, random/photo. Require:

```python
detail = service.global_terminal_detail(terminal_id=str(terminal.id))
assert [row["physical_state"] for row in detail["collector_items"]] == [
    "present", "missing", "replaced",
]
present, missing, replaced = detail["collector_items"]
assert present["final_collector_no"] == present["original_collector_no"]
assert present["capture_strategy"] == "live_physical"
assert present["photo"] is None
assert missing["workbench_item_id"] is None
assert missing["final_collector_no"] is None
assert replaced["capture_strategy"] == "screen_photo"
assert replaced["photo"]["sha256"] == pool_photo.sha256
```

Assert `meter_install_items` contain exactly two slots and `pool_summary == {"required": 1, "available": M, "shortage": max(0, 1-M)}`.

- [ ] **Step 2: Run focused detail test and verify RED**

```powershell
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_service.py -q -k "global_terminal_detail"
```

Expected: FAIL because the global detail and physical-state projection do not exist.

- [ ] **Step 3: Implement idempotent direct reconciliation and detail**

Add:

```python
class CollectorDirectConflictError(ValueError):
    pass

def _reconcile_direct_requirements(
    self,
    *,
    run: CollectorTransferRun,
    terminal: CollectorTransferTerminal,
) -> int:
```

Lock the run, terminal, unmatched requirements in sorted ID order, then matching `direct` physical rows in sorted ID order. Before creating a no-assignment item, query non-superseded hidden runs for an existing direct item using the same project and collector number. Raise `CollectorDirectConflictError` if a different terminal owns it. Never displace an active random assignment; after a random rollback, the next detail call may bind the direct physical.

Add:

```python
def global_terminal_detail(self, *, terminal_id: str) -> dict[str, object]:
```

Verify the terminal belongs to an unsuperseded `global_terminal_workbench` run in the authenticated team, reconcile direct requirements, load selected rows in bounded queries, and return the spec's DTO.

- [ ] **Step 4: Add failing direct complete/undo tests**

```python
completed = service.set_workbench_item_status(item_id=str(direct_item.id), completed=True)
assert completed["status"] == "completed"
assert requirement.status == "used"
assert physical.pool_status == "used"
assert session.scalar(select(func.count(CollectorAssignment.id))) == 0

reopened = service.set_workbench_item_status(item_id=str(direct_item.id), completed=False)
assert reopened["status"] == "pending"
assert requirement.status == "direct_ready"
assert physical.pool_status == "direct"
```

Also prove the direct path refuses missing physical provenance and a completed direct physical cannot be claimed by another terminal.

- [ ] **Step 5: Refactor completion to canonical lock order**

For both direct and random items, resolve IDs first without locks, then lock:

```text
run -> terminal -> requirement -> physical -> assignment -> workbench item -> photo evidence
```

Branch on `item.assignment_id is None and item.requirement_id is not None` for direct. Keep existing random validation and transitions. All audit payloads include run, terminal, requirement, physical, mode, old status, and new status.

- [ ] **Step 6: Add a PostgreSQL direct-claim race test**

Use two sessions and two hidden terminals referencing the same source collector. Start both detail reconciliations concurrently; assert exactly one direct workbench item is effective, the loser returns `direct_conflict`, the physical remains `direct`, and no assignment/photo is created. Require both sessions remain usable.

- [ ] **Step 7: Verify GREEN and commit**

```powershell
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_postgres_integration.py -q -k "detail or direct or completion or lock"
git add -- v2-api/app/services/collector_transfer.py v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_postgres_integration.py
git commit -m "feat: expose collector physical states in terminal workbench"
```

### Task 4: Add terminal-level all-or-nothing replacement, rollback, and refresh

**Files:**
- Modify: `v2-api/app/services/collector_transfer.py:1343-1960`
- Modify: `v2-api/tests/test_collector_transfer_service.py`
- Modify: `v2-api/tests/test_collector_transfer_postgres_integration.py`

**Interfaces:**
- Consumes: `plan_random_assignments`, canonical mutation lock order, valid active pool photos, hidden snapshot metadata.
- Produces: `replace_terminal_missing(terminal_id)`, `refresh_global_terminal(terminal_id)`, canonical rollback, idempotent terminal result.

- [ ] **Step 1: Add failing atomic replacement tests**

For a terminal with two unmatched requirements and exactly two available photographed pool collectors, assert:

```python
result = service.replace_terminal_missing(terminal_id=str(terminal.id))
assert result["required"] == 2
assert result["assigned"] == 2
assert len({row["physical_collector_id"] for row in result["assignments"]}) == 2
assert all(row.assignment_mode == "random" and row.status == "reserved" for row in assignments)
assert all(row.status == "assigned" for row in requirements)
assert all(row.pool_status == "reserved" for row in physicals)
```

Call it again and require `assigned == 0`, `required == 0`, and no new assignment/audit mapping.

For two requirements and one pool collector, catch `PoolInsufficientError(required=2, available=1)` and compare literal before/after snapshots of requirements, physicals, assignments, workbench items, and terminal progress; they must be equal.

- [ ] **Step 2: Run replacement tests and verify RED**

```powershell
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_service.py -q -k "replace_terminal_missing"
```

Expected: FAIL because only run-wide allocation exists.

- [ ] **Step 3: Implement terminal-scoped replacement**

Add:

```python
class CollectorSnapshotChangedError(ValueError):
    pass

def replace_terminal_missing(self, *, terminal_id: str) -> dict[str, object]:
```

Validate a current hidden run and lock `run -> terminal -> unmatched terminal requirements -> project available physicals -> active photos` in stable order. Call `plan_random_assignments` only after locks and after filtering collectors without exactly one valid active photo. If the plan raises shortage, roll back without audit/business writes. On success, create `random` assignments, set requirement/physical states, create removal workbench items, write one `collector_workbench.terminal_replaced` summary plus mapping payload, refresh stats, commit once, and return the current terminal detail identifiers.

Legacy `allocate(run_id)` must reject hidden `global_terminal_workbench` runs so it cannot allocate outside this method.

- [ ] **Step 4: Add failing rollback and canonical-order tests**

After replacement and completion, roll back one assignment and assert:

```python
assert assignment.status == "rolled_back"
assert requirement.status == "unmatched"
assert physical.pool_status == "available"
assert session.scalar(select(CollectorWorkbenchItem.id).where(CollectorWorkbenchItem.assignment_id == assignment.id)) is None
```

Then call detail and require the row shows `missing`. Add two-session PostgreSQL tests for replace-vs-rollback and replace-vs-complete; both must finish without deadlock, duplicate active assignment, or mixed terminal counts.

- [ ] **Step 5: Reorder rollback to the canonical lock contract**

Resolve the run/terminal/requirement/physical IDs read-only, then lock in the same order as replacement/completion. Preserve direct rollback rule (direct physical never becomes pool available); the new UI only exposes rollback for `random` assignments.

- [ ] **Step 6: Add snapshot refresh tests and implementation**

Require refresh to reject a terminal with completed items or active assignments using `CollectorSnapshotChangedError`, including before/after equality. After undoing completions and rolling back assignments, require:

```python
refreshed = service.refresh_global_terminal(terminal_id=str(old_terminal.id))
assert refreshed["run_id"] != str(old_run.id)
session.refresh(old_run)
assert old_run.stats["superseded"] is True
assert old_run.stats["superseded_by_run_id"] == refreshed["run_id"]
```

Implement refresh by calling `open_global_terminal(project_id=str(run.project_id), terminal_code=terminal.terminal_code, source_revision=current_revision, force_refresh=True)` only after the no-progress gate.

- [ ] **Step 7: Verify GREEN and commit**

```powershell
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_postgres_integration.py -q -k "replace or rollback or refresh or deadlock"
git add -- v2-api/app/services/collector_transfer.py v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_postgres_integration.py
git commit -m "feat: replace missing collectors per terminal atomically"
```

### Task 5: Publish role-safe global terminal APIs

**Files:**
- Modify: `v2-api/app/api/routes/collector_transfer.py:1-363`
- Modify: `v2-api/tests/test_collector_transfer_api.py`

**Interfaces:**
- Consumes: Tasks 1-4 service methods and authenticated token payload.
- Produces: role-aware `RequestIdentity`, new `/collector-transfer/workbench/terminals*` routes, admin enforcement, stable HTTP errors.

- [ ] **Step 1: Add failing role and DTO tests**

Exercise real route dependencies with admin and constructor tokens. Require:

```python
assert constructor.get("/collector-transfer/workbench/terminals").status_code == 200
assert constructor.post("/collector-transfer/workbench/terminals/open", json=open_body).status_code == 200
assert constructor.patch(f"/collector-transfer/workbench/items/{item_id}", json={"completed": True}).status_code == 200
assert constructor.post(f"/collector-transfer/workbench/terminals/{terminal_id}/replace-missing").status_code == 403
assert constructor.post(f"/collector-transfer/assignments/{assignment_id}/rollback").status_code == 403
assert constructor.post(f"/collector-transfer/workbench/terminals/{terminal_id}/refresh").status_code == 403
assert constructor.post(f"/collector-transfer/runs/{run_id}/allocate").status_code == 403
```

Assert every forbidden response has code `forbidden` and the fake service mutation method was not called. Add request-body `extra="forbid"`, page-size, invalid state/key, team/project spoofing, and custom error mappings.

- [ ] **Step 2: Run API tests and verify RED**

```powershell
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_api.py -q -k "global_terminal or administrator or forbidden"
```

Expected: FAIL because current identity contains no roles and allocate/rollback are not server-side admin-only.

- [ ] **Step 3: Make identity role-aware**

Define:

```python
class RequestIdentity(NamedTuple):
    team_id: str
    actor: str
    roles: frozenset[str]

def roles_from_payload(payload: Mapping[str, object]) -> frozenset[str]:
    raw_roles = payload.get("roles") or []
    roles = {normalize_identifier(payload.get("role")).lower()}
    roles.update(normalize_identifier(value).lower() for value in raw_roles if normalize_identifier(value))
    return frozenset(role for role in roles if role)

GlobalTerminalState = Literal["ready", "needs_replacement", "pool_shortage", "blocked"]

class CollectorForbiddenError(ValueError):
    pass

def require_admin(request: Request) -> RequestIdentity:
    identity = request_identity(request)
    if "admin" not in identity.roles:
        raise CollectorForbiddenError("administrator role is required")
    return identity
```

Retain the existing bearer-token decode block inside `request_identity`, derive `team_id` and `actor` as it does today, then return `RequestIdentity(team_id, actor, roles_from_payload(payload))`. `service_for_request` passes only `identity.team_id` and `identity.actor` into the service. It never trusts a body actor/role/team.

- [ ] **Step 4: Add exact request models and endpoints**

```python
class OpenGlobalTerminalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    terminal_key: str = Field(min_length=1, max_length=2048)
    project_id: str = Field(min_length=1, max_length=64)
    terminal_code: str = Field(min_length=1, max_length=255)
    source_revision: str = Field(default="", max_length=64)

@router.get("/workbench/terminals")
def list_global_terminals(
    request: Request,
    query: str = Query(default="", max_length=255),
    state: GlobalTerminalState | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    include_blocked: bool = Query(default=False),
):
    identity = request_identity(request)
    if include_blocked and "admin" not in identity.roles:
        raise CollectorForbiddenError("administrator role is required")
    return call_service(request, lambda service: service.list_global_terminals(
        query=query, state=state, page=page, page_size=page_size, include_blocked=include_blocked,
    ))

@router.post("/workbench/terminals/open")
def open_global_terminal(payload: OpenGlobalTerminalRequest, request: Request):
    request_identity(request)
    return call_service(request, lambda service: service.open_global_terminal(
        project_id=payload.project_id,
        terminal_code=payload.terminal_code,
        source_revision=payload.source_revision,
        terminal_key_value=payload.terminal_key,
    ))

@router.get("/workbench/terminals/{terminal_id}")
def global_terminal_detail(terminal_id: str, request: Request):
    request_identity(request)
    return call_service(request, lambda service: service.global_terminal_detail(terminal_id=terminal_id))

@router.post("/workbench/terminals/{terminal_id}/replace-missing")
def replace_terminal_missing(terminal_id: str, request: Request):
    require_admin(request)
    return call_service(request, lambda service: service.replace_terminal_missing(terminal_id=terminal_id))

@router.post("/workbench/terminals/{terminal_id}/refresh")
def refresh_global_terminal(terminal_id: str, request: Request):
    require_admin(request)
    return call_service(request, lambda service: service.refresh_global_terminal(terminal_id=terminal_id))
```

Apply the same `require_admin` call to legacy allocate and assignment rollback before creating a service session.

- [ ] **Step 5: Map stable errors without leaking cross-tenant existence**

Map direct conflict, source blocked, snapshot changed, pool shortage, allocation conflict, workbench incomplete, and forbidden to the spec's codes/status. Cross-team/project missing entities return `404 not_found`; do not reveal that a foreign entity exists.

- [ ] **Step 6: Verify GREEN and commit**

```powershell
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_api.py v2-api/tests/test_collector_transfer_service.py -q
git add -- v2-api/app/api/routes/collector_transfer.py v2-api/tests/test_collector_transfer_api.py
git commit -m "feat: expose role-safe global collector workbench APIs"
```

### Task 6: Replace the batch-driven Vue workbench with global terminal workflow

**Files:**
- Modify: `v2-web/src/api/types.ts:718-871`
- Modify: `v2-web/src/api/services.ts:2899-2975`
- Modify: `v2-web/src/features/collectorTransfer/state.ts`
- Modify: `v2-web/src/views/CollectorWorkbenchView.vue`
- Modify: `v2-web/src/views/__tests__/CollectorWorkbenchView.spec.ts`
- Modify: `v2-web/tests/collector-transfer-state.test.ts`
- Modify: `v2-web/src/router/index.ts`
- Modify: `v2-web/src/router/staticPages.ts`
- Modify: `v2-web/src/layouts/AppLayout.vue`
- Delete: `v2-web/src/views/CollectorBatchManagementView.vue`
- Delete: `v2-web/src/views/__tests__/CollectorBatchManagementView.spec.ts`

**Interfaces:**
- Consumes: Task 5 HTTP contracts and authenticated `auth.user.role/roles`.
- Produces: terminal search/open/detail/replace/refresh/rollback clients and a single integrated workbench page.

- [ ] **Step 1: Replace frontend DTOs with literal global contracts**

Add these exact unions and core types:

```ts
export type GlobalCollectorTerminalState = 'ready' | 'needs_replacement' | 'pool_shortage' | 'blocked'
export type CollectorPhysicalState = 'present' | 'missing' | 'replaced'
export type CollectorCaptureStrategy = 'live_physical' | 'unavailable' | 'screen_photo'

export type GlobalCollectorTerminalCandidate = {
  terminal_key: string
  project_id: string
  project_name: string
  terminal_code: string
  installation_address: string
  needs_disambiguation: boolean
  meter_count: number
  collector_count: number
  physical_count: number
  missing_count: number
  pool_available_count: number
  workflow_state: GlobalCollectorTerminalState
  selectable: boolean
  source_revision: string
  diagnostics: CollectorTransferDiagnostic[]
}

export type CollectorRequirementWorkbenchRow = {
  requirement_id: string
  workbench_item_id: string | null
  status: 'pending' | 'completed' | null
  original_collector_no: string
  physical_state: CollectorPhysicalState
  final_collector_no: string | null
  collector_barcode: string | null
  capture_strategy: CollectorCaptureStrategy
  assignment_id: string | null
  photo: CollectorTransferPhoto | null
  diagnostics: CollectorTransferDiagnostic[]
}
```

Define candidate-page, pool-summary, global-terminal-detail, open result, replacement result, and refresh result types using these fields. Keep legacy run types only for compatibility clients not used by the new view.

- [ ] **Step 2: Add failing pure state tests**

Require:

```ts
assert.equal(candidateLabel(duplicate), 'T-001 · 城南项目 · 安装地址')
assert.deepEqual(completionBlockers(present), [])
assert.deepEqual(completionBlockers(missing), ['该采集器没有实物，需先完成替换'])
const replacedWithoutPhoto = Object.assign({}, replaced, { photo: null })
assert.deepEqual(completionBlockers(replacedWithoutPhoto), ['替换采集器照片缺失'])
assert.equal(canReplaceMissing({ isAdmin: false, missing: 2, available: 9 }), false)
assert.equal(canReplaceMissing({ isAdmin: true, missing: 2, available: 1 }), false)
assert.equal(canReplaceMissing({ isAdmin: true, missing: 2, available: 2 }), true)
```

Add a request-sequence assertion proving response sequence 1 cannot replace state after sequence 2 becomes current.

- [ ] **Step 3: Run state tests and verify RED**

```powershell
Push-Location v2-web
node --test --experimental-strip-types tests/collector-transfer-state.test.ts
Pop-Location
```

Expected: FAIL because the global state helpers/types do not exist.

- [ ] **Step 4: Implement API clients**

Add:

```ts
export async function fetchGlobalCollectorTerminals(params: GlobalTerminalQuery): Promise<GlobalTerminalPage>
export async function openGlobalCollectorTerminal(candidate: GlobalCollectorTerminalCandidate): Promise<GlobalTerminalOpenResult>
export async function fetchGlobalCollectorTerminal(terminalId: string): Promise<GlobalTerminalDetail>
export async function replaceGlobalTerminalMissing(terminalId: string): Promise<CollectorTerminalReplacementResult>
export async function refreshGlobalCollectorTerminal(terminalId: string): Promise<GlobalTerminalOpenResult>
export async function rollbackCollectorAssignment(assignmentId: string): Promise<CollectorAssignmentRollbackResult>
```

Use `URLSearchParams`, `encodeURIComponent`, and the existing authenticated `api()` wrapper. `open` sends the four fields from the spec and no team/actor/role.

- [ ] **Step 5: Rewrite component tests around the global flow**

Remove project/run mocks and add literal candidates/details for present, missing, and replaced rows. Require:

```ts
expect(wrapper.find('[aria-label="选择项目"]').exists()).toBe(false)
expect(wrapper.find('[aria-label="选择批次"]').exists()).toBe(false)
expect(wrapper.find('[aria-label="选择可翻拍终端"]').exists()).toBe(true)
expect(wrapper.text()).toContain('有实物')
expect(wrapper.text()).toContain('无需网站照片，请直接拿实物翻拍')
expect(wrapper.text()).toContain('无实物')
expect(wrapper.text()).toContain('已替换')
```

For admin, click `data-testid="replace-all-missing"`, require one call with the selected terminal ID, then require detail reload and persisted replacement values. For constructor, the button does not exist. For pool shortage, the disabled summary says `需要 2 / 可用 1`. Test rollback confirmation, completion rules, source-changed warning, refresh gate, request failure retry, keyboard navigation, and late candidate/detail responses.

- [ ] **Step 6: Run the view test and verify RED**

```powershell
Push-Location v2-web
npx vitest run --config tests/collector-transfer.vitest.config.ts src/views/__tests__/CollectorWorkbenchView.spec.ts
Pop-Location
```

Expected: current project/run-driven UI fails the new selectors, state rows, and integrated replace controls.

- [ ] **Step 7: Implement the global workbench UI**

On mount, load page 1 candidates. Debounce terminal/address search, abort or sequence-guard every request, and open the selected candidate automatically. Render:

- top search/select with duplicate-project disambiguation only when needed;
- source-change warning and admin refresh action;
- new-install list with two Code 128 values and two photos;
- collector cards for `present`, `missing`, `replaced`;
- admin-only atomic replace button with required/available counts;
- admin-only rollback on random rows;
- existing complete/undo controls using `workbench_item_id` only when completion blockers are empty.

Do not access `getUserMedia` from this view. It displays source photos or instructs the operator to use the physical collector.

- [ ] **Step 8: Retire the batch route and component**

Remove `collector-batches` from `StaticPageKey`, `staticPages`, `AppLayout` icon map, and lazy view imports. Add an explicit router record:

```ts
{
  path: '/collector-batches',
  redirect: '/collector-workbench',
}
```

Delete the batch view and its dedicated spec. Add tests that navigation omits it and `router.resolve('/collector-batches').redirectedFrom`/navigation lands on `/collector-workbench`.

- [ ] **Step 9: Verify frontend GREEN and commit**

```powershell
Push-Location v2-web
npm run test:collector-transfer
npm run test:components
npm run type-check
npm run build
Pop-Location
git add -- v2-web/src/api/types.ts v2-web/src/api/services.ts v2-web/src/features/collectorTransfer/state.ts v2-web/src/views/CollectorWorkbenchView.vue v2-web/src/views/__tests__/CollectorWorkbenchView.spec.ts v2-web/tests/collector-transfer-state.test.ts v2-web/src/router/index.ts v2-web/src/router/staticPages.ts v2-web/src/layouts/AppLayout.vue
git add -u -- v2-web/src/views/CollectorBatchManagementView.vue v2-web/src/views/__tests__/CollectorBatchManagementView.spec.ts
git commit -m "feat: integrate collector replacement into global workbench"
```

### Task 7: Run full verification and rebuild the source-bound V3.2.8 release

**Files:**
- Modify: `v2-api/app/static/vue/**`
- Modify: `ops/releases/V3.2.8.md`
- Generate: `build/server-release/module-manager-v2-server-3.2.8.zip`

**Interfaces:**
- Consumes: Tasks 1-6 and existing source-binding release verifier.
- Produces: final source commit, all-green local evidence, immutable verified V3.2.8 ZIP and SHA256.

- [ ] **Step 1: Run the entire collector backend matrix**

```powershell
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests/test_collector_transfer_domain.py v2-api/tests/test_collector_transfer_service.py v2-api/tests/test_collector_transfer_api.py v2-api/tests/test_collector_transfer_postgres_integration.py v2-api/tests/test_collector_transfer_scale.py v2-api/tests/test_models.py v2-api/tests/test_migrations.py -q
```

Expected: final pytest summary with zero failures. A timeout, interrupted command, or missing summary is not a pass.

- [ ] **Step 2: Run all frontend and full repository tests**

```powershell
Push-Location v2-web
npm run test:collector-transfer
npm run test:components
npm run type-check
npm run build
Pop-Location
v2-api\.venv\Scripts\python.exe -m pytest v2-api/tests scripts -q
```

Expected: collector tests, component suite, type check, Vue production build, and full pytest suite all pass. Record exact pass/skip counts in `ops/releases/V3.2.8.md`.

- [ ] **Step 3: Perform local rendered acceptance**

Run the real local app and inspect `/collector-inventory`, `/collector-workbench`, and `/collector-batches` through the browser at 390x844 and desktop width. Require correct identity/content, no console error, no project/run selector, terminal search, three collector states, admin/constructor control differences, redirect, direct no-photo text, and unchanged inventory camera preview/teardown. Use test fixtures/local test data only; do not allocate production inventory.

- [ ] **Step 4: Rebuild and commit tracked Vue assets and release evidence**

Use the repository release build path to sync the final frontend into `v2-api/app/static/vue`. Update `ops/releases/V3.2.8.md` with the new feature, exact tests, unchanged head, pending production fields, and rollback target V3.2.7. Verify only intentional paths plus protected `v2-api/uv.lock` differ.

```powershell
git add -- v2-api/app/static/vue ops/releases/V3.2.8.md
git commit --only -m "release: integrate global collector workbench in V3.2.8" -- v2-api/app/static/vue ops/releases/V3.2.8.md
```

- [ ] **Step 5: Re-run source gates from the final commit**

```powershell
v2-api\.venv\Scripts\python.exe scripts/verify_v3_2_8_release.py --phase source
v2-api\.venv\Scripts\python.exe scripts/verify_release_sop.py --version V3.2.8 --phase source
git diff --check
git status --short
```

Expected: source gates pass and status contains only `?? v2-api/uv.lock`.

- [ ] **Step 6: Build a fresh ZIP and verify every binding**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-client-release.ps1 -Version 3.2.8
v2-api\.venv\Scripts\python.exe scripts/verify-client-release.py build/server-release/module-manager-v2-server-3.2.8.zip
v2-api\.venv\Scripts\python.exe scripts/verify_v3_2_8_release.py --phase package --package build/server-release/module-manager-v2-server-3.2.8.zip
Get-FileHash -Algorithm SHA256 -LiteralPath build/server-release/module-manager-v2-server-3.2.8.zip
```

Open the ZIP and require `SOURCE_COMMIT` equals the final HEAD, root `RELEASE_MANIFEST.md` bytes match that commit under the verifier's EOL policy, Vue `version.json` covers every asset, CRC/path/case/duplicate gates pass, and no `.env`, uploads, backup, or `uv.lock` is present.

- [ ] **Step 7: Record candidate hash without invalidating it**

Write the exact source commit and ZIP SHA256 into a separate local deployment evidence file outside the repository before upload. Do not edit tracked source after building; any tracked edit requires a new commit and full rebuild/reverification.

### Task 8: Back up, deploy, verify, and attest production

**Files:**
- Modify after verified production acceptance: `ops/releases/V3.2.8.md`
- Local recovery artifacts: `$backupRoot`, where `$backupStamp = Get-Date -Format 'yyyyMMdd-HHmmss'` and `$backupRoot = Join-Path 'C:\Users\Administrator\Documents\module-manager-production-backups' $backupStamp`.

**Interfaces:**
- Consumes: verified V3.2.8 ZIP, SHA256, final source commit, `root@www.sgcc.online`, and `C:\Users\Administrator\Downloads\XXXXXX.pem`.
- Produces: production `current` on a new immutable V3.2.8 release, verified backup/rollback, healthy listener, read-only workbench evidence, zero-write inventory smoke, real-phone camera acceptance, restored maintenance services, and attested release record.

- [ ] **Step 1: Reconfirm current production and recovery boundary**

Using nonprinting SSH commands, capture current symlink, release version/commit, Alembic head, systemd states, actual listener/PID, `/health`, disk/memory/swap, PostgreSQL activity, and maintenance worker/timer states. Require current still points to V3.2.7 and head is `20260824_0016`. Stop cutover if SSH, PostgreSQL, disk, or listener state is unstable. Do not delete releases/backups or run retention cleanup.

- [ ] **Step 2: Create and verify a fresh streamed local backup**

Create a new timestamped local directory and stream, without staging plaintext secrets in remote temporary files:

- current symlink/release metadata and checksums;
- `.env` through an encrypted/restricted local channel without printing contents;
- `pg_dump -Fc` and schema-only SQL;
- application `data` and `uploads` tar streams.

Verify every SHA256, `pg_restore -l`, nonempty schema, complete tar listings, and expected source release metadata. Record the exact rollback directory and backup path before upload.

- [ ] **Step 3: Upload and prepare a new immutable release**

Set `release_stamp=$(date -u +%Y%m%d_%H%M%S)` on the server. Upload only `module-manager-v2-server-3.2.8.zip`, compare local/server SHA256, and extract to `/opt/module-manager-v2/releases/v3.2.8-$release_stamp`. Restore `.env` without printing it, install dependencies, enforce ownership and `chmod -R g-w,g+rX`, import Pillow and `app.main` as `modulemgr`, run `unzip -t` and the packaged source verifier, and confirm Alembic remains `20260824_0016`.

- [ ] **Step 4: Cut over and prove real readiness**

Atomically repoint `/opt/module-manager-v2/current`, restart the main service, and wait for a real Uvicorn listener on `127.0.0.1:8000`; systemd `active` alone is insufficient. Require local/public health, version 3.2.8, `/project-board`, `/collector-inventory`, `/collector-workbench`, and `/collector-batches` redirect responses. On any failure, restore the previous symlink and service before investigating.

- [ ] **Step 5: Run bounded non-destructive production acceptance**

Perform exactly one guarded non-photo inventory smoke: generate and print a guaranteed nonmatching barcode and before counts immediately before POST; require `pool_needs_photo`, unchanged physical/photo/scan-event counts, bounded latency, stable RSS/memory, no restart/OOM, and idle PostgreSQL sessions.

Using authenticated read-only requests, require the global terminal page is bounded/paged and cross-team inaccessible. Open the Vue workbench shell and verify no project/run selector and the old batch URL redirects. Do not open a real terminal snapshot or execute real replacement unless a designated test terminal is explicitly identified; all mutation semantics are already proven by local and PostgreSQL integration tests.

- [ ] **Step 6: Complete real-phone camera acceptance**

At 390x844 on a real phone, open `/collector-inventory`, grant camera permission, require live preview without native `BarcodeDetector`, verify Quagga detection or preview-plus-manual fallback, scan a controlled no-write/nonmatching value once, and prove view exit releases the camera. Network logs must contain no client-platform request.

- [ ] **Step 7: Restore maintenance services and soak**

Only after Steps 4-6 pass, restore maintenance worker/timer to their captured enabled/active state. Observe at least one maintenance cycle with repeated listener, `/health`, PostgreSQL sessions, RSS/memory, disk, and journal checks. Any restart, listener loss, growing session count, or OOM blocks attestation and triggers rollback evaluation.

- [ ] **Step 8: Attest and run requirement-by-requirement completion audit**

Update `ops/releases/V3.2.8.md` with final source commit, local/server ZIP hashes, backup path and verification, release/rollback directories, head, listener/health/pages, zero-write smoke counts/latency/resources, global workbench read-only evidence, phone camera evidence, maintenance restoration, and soak results.

Run:

```powershell
v2-api\.venv\Scripts\python.exe scripts/verify_v3_2_8_release.py --phase attestation
git add -- ops/releases/V3.2.8.md
git commit --only -m "release: attest V3.2.8 global collector workbench" -- ops/releases/V3.2.8.md
```

Reconfirm production `current`, exact deployed source/hash, `/health`, Uvicorn listener, database head, workbench routes, maintenance state, journal/resources, rollback artifacts, and local `git status --short == ?? v2-api/uv.lock`. Only then mark the production objective complete.
