# Platform Review Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make locally staged platform work orders visible in the review workbench with enough field and photo metadata for reviewers to start checking them.

**Architecture:** Keep platform work orders in the existing local platform store and expose a read-only review projection from `v2-api/app/services/platform/templates.py`. The Vue review workbench consumes this projection as a separate platform review mode, without mixing local platform photos into production OSS/static uploads.

**Tech Stack:** FastAPI, local JSON platform stores, pytest, Vue 3 + TypeScript + Element Plus.

---

### Task 1: Backend Review Projection

**Files:**
- Modify: `v2-api/tests/test_api.py`
- Modify: `v2-api/app/services/platform/templates.py`
- Modify: `v2-api/app/api/routes/projects.py`

- [ ] **Step 1: Write the failing test**

Add a pytest that creates a draft terminal project, imports/executes one platform work order, saves field collection metadata and uploads one local photo. Assert `GET /projects/{project_id}/review/work-orders` returns one item with project id, primary value, aggregate value, collection status, field labels, photo slots, collection photos, and review status `pending_review`.

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api/tests/test_api.py::test_project_review_work_orders_include_collected_platform_items -q
```

Expected: fail because the endpoint does not exist yet.

- [ ] **Step 3: Implement minimal backend code**

Add `list_platform_review_work_orders(project_id)` to `templates.py`. Reuse `_platform_construction_schema()` and `_construction_work_order_payload()`, then map the work order into a review-safe payload:

- `id`
- `project_id`
- `primary_value`
- `aggregate_value`
- `collection_status`
- `review_status`
- `field_values`
- `collection_field_values`
- `field_reviews`
- `photo_slots`
- `collection_photos`
- `collected_by`
- `collected_at`

Add route `GET /projects/{project_id}/review/work-orders`.

- [ ] **Step 4: Run backend test to verify it passes**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api/tests/test_api.py::test_project_review_work_orders_include_collected_platform_items -q
```

Expected: PASS.

### Task 2: Frontend Review Workbench Entry

**Files:**
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/views/TaskHallView.vue`

- [ ] **Step 1: Add API types and service mapping**

Add `PlatformReviewWorkOrder`, `PlatformReviewWorkOrders`, backend mapping, and `fetchProjectReviewWorkOrders(projectId)`.

- [ ] **Step 2: Add review page platform mode**

In `TaskHallView.vue`, fetch platform review work orders for the active project, show a compact "平台接入审阅" section beside normal tasks, and allow opening one item in the right review panel. Display primary/aggregate value, collection status, required field values, and photo slot coverage.

- [ ] **Step 3: Build frontend**

Run:

```powershell
$env:PATH='C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin;C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin;' + $env:PATH
pnpm --dir v2-web build
```

Expected: build exits 0.

### Task 3: Verification And Report

**Files:**
- Modify: `docs/reports/pm-platform-full-flow-evaluation-2026-06-30.md`

- [ ] **Step 1: Run focused backend regression**

Run the new review test plus the existing platform construction tests.

- [ ] **Step 2: Run production baseline and sensitive file checks**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_production_baseline.py
git status --short -- .env data v2-api/data v2-api/app/static/uploads
```

- [ ] **Step 3: Browser QA**

Restart the local platform service on port `52131`, open `/task-hall?project_id=draft-project-3`, and verify the platform review entry renders without console errors.

- [ ] **Step 4: Update report**

Append the new review-entry behavior, verification commands, risk, and rollback notes to the evaluation report.
