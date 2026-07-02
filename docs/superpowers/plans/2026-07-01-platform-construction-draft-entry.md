# Platform Construction Draft Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let local platform work orders move beyond read-only display by saving construction collection draft/submission metadata in the isolated local platform store.

**Architecture:** Extend the existing local platform work-order JSON store with collection metadata only. Keep production construction tables, OSS, uploads, and PostgreSQL untouched; this stage does not upload binary photos.

**Tech Stack:** FastAPI, pytest, Vue 3, TypeScript, Element Plus, local JSON platform stores.

---

### Task 1: Backend Collection Draft API

**Files:**
- Modify: `v2-api/tests/test_api.py`
- Modify: `v2-api/app/services/platform/templates.py`
- Modify: `v2-api/app/api/routes/projects.py`

- [ ] **Step 1: Write the failing test**

Add a pytest case that creates a draft project, imports external completed rows, executes them into local platform work orders, then posts collection metadata:

```python
saved = client.post(
    f"/projects/{project_id}/construction/work-orders/{work_order_id}/collection-draft",
    json={
        "actor": "constructor-a",
        "client_batch_id": "platform-draft-001",
        "status": "cached",
        "field_values": {
            "communication_module_no": "COMM-SCAN-001",
            "new_sim_card_no": "SIM-MANUAL-001",
        },
        "covered_photo_slots": ["before_photo", "module_photo"],
    },
)
assert saved.status_code == 200
assert saved.json()["data"]["collection_status"] == "cached"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest v2-api/tests/test_api.py::test_project_construction_work_order_collection_draft_saves_locally -q`

Expected: FAIL with `404 Not Found` because the route does not exist.

- [ ] **Step 3: Implement the service function**

Add `save_platform_construction_work_order_collection(project_id, work_order_id, payload)` in `templates.py`. It should load the platform work-order store, validate the project/work-order relationship, accept only configured field keys/photo slot keys, store `collection_status`, `collection_field_values`, `covered_photo_slots`, `client_batch_id`, `collected_by`, and `collected_at`, then persist the local JSON store.

- [ ] **Step 4: Add the route**

Add `POST /projects/{project_id}/construction/work-orders/{work_order_id}/collection-draft` to `projects.py`. Return the updated work-order payload in the same API envelope style as existing project routes.

- [ ] **Step 5: Run backend tests**

Run: `python -m pytest v2-api/tests/test_api.py::test_project_construction_work_order_collection_draft_saves_locally v2-api/tests/test_api.py::test_project_construction_work_orders_expose_schema_and_local_platform_orders -q`

Expected: PASS.

### Task 2: Frontend API Contracts

**Files:**
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`

- [ ] **Step 1: Extend types**

Add collection metadata fields to `PlatformConstructionWorkOrder`: `collectionStatus`, `collectionFieldValues`, `coveredPhotoSlots`, `clientBatchId`, `collectedBy`, and `collectedAt`.

- [ ] **Step 2: Add save function**

Add `saveProjectConstructionWorkOrderCollection(projectId, workOrderId, payload)` that posts to the new route and maps the returned work order.

- [ ] **Step 3: Build check**

Run: `pnpm --dir v2-web build`

Expected: TypeScript and Vite build succeed.

### Task 3: Construction Page Entry

**Files:**
- Modify: `v2-web/src/views/ConstructionView.vue`

- [ ] **Step 1: Make platform work orders selectable**

Render a compact list under the “平台接入工单” card with a single `打开采集` action per displayed item. The action should convert the platform work order into a safe local `MaterialGroup`-shaped object, set it as `activeGroup`, and enter work mode without calling existing `/local-test` upload endpoints.

- [ ] **Step 2: Add draft metadata save**

When a platform work order is open, provide a safe local `保存平台草稿` action that posts field values and covered photo slot keys to the new backend endpoint. Do not upload binary files in this stage.

- [ ] **Step 3: Browser check**

Open `http://127.0.0.1:52131/construction?project_id=draft-project-3` and verify the platform entry still renders, console has no app error/warn, and opening a platform work order does not change production/local-test tasks.

### Task 4: Documentation and Release Safety

**Files:**
- Modify: `docs/reports/pm-platform-full-flow-evaluation-2026-06-30.md`

- [ ] **Step 1: Update report**

Append a section describing the isolated local collection draft API, frontend behavior, test commands, remaining risk, and rollback path.

- [ ] **Step 2: Safety verification**

Run:

```powershell
python scripts/verify_production_baseline.py
git status --short -- .env data v2-api/data v2-api/app/static/uploads
```

Expected: baseline check passes; sensitive path check has no output.
