# Platform Review Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let reviewers approve, return, or mark exception for locally staged platform work orders without touching production review data.

**Architecture:** Store review decisions on the existing local platform work order record, then project them through the existing platform review endpoint. The frontend adds a small action strip in the existing platform review detail panel and refreshes the read model after each decision.

**Tech Stack:** FastAPI service functions in `v2-api`, pytest API tests, Vue 3 + TypeScript frontend, local JSON platform work order store.

---

### Task 1: Backend Review Decision API

**Files:**
- Modify: `v2-api/tests/test_api.py`
- Modify: `v2-api/app/services/platform/templates.py`
- Modify: `v2-api/app/api/routes/projects.py`

- [ ] **Step 1: Write the failing test**

Add a test that creates a platform work order, saves submitted collection data, posts an approve decision, and confirms `GET /projects/{project_id}/review/work-orders` returns `review_status=approved`, reviewer metadata, and the decision note.

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api/tests/test_api.py::test_project_review_work_order_action_persists_local_status -q
```

Expected: fails with 404 because the review action route does not exist.

- [ ] **Step 3: Implement the minimal backend**

Add `review_platform_work_order(project_id, work_order_id, payload)` to validate `approved`, `returned`, and `exception`, then store `review_status`, `reviewed_by`, `reviewed_at`, `review_note`, and `review_reason`.

- [ ] **Step 4: Expose route**

Add `POST /projects/{project_id}/review/work-orders/{work_order_id}/actions` and keep errors local to this platform work order path.

- [ ] **Step 5: Run backend test**

Run the focused test and the existing platform review/collection tests.

### Task 2: Frontend Review Actions

**Files:**
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/views/TaskHallView.vue`
- Modify or create: `scripts/verify_vue_platform_review_actions.js`

- [ ] **Step 1: Add service contract guard**

Add a small verifier that checks the frontend exposes `reviewProjectReviewWorkOrder`, action payload typing, and Task Hall action buttons.

- [ ] **Step 2: Run verifier to verify it fails**

Run:

```powershell
node scripts\verify_vue_platform_review_actions.js
```

Expected: fails until the frontend contract exists.

- [ ] **Step 3: Add API types and mapper fields**

Expose review action payload and review metadata on `PlatformReviewWorkOrder`.

- [ ] **Step 4: Add Task Hall buttons**

In the platform review detail panel, add compact buttons for `通过`, `退回`, and `标异常`. Prompt for a reason on return/exception, call the API, refresh the platform review list, and keep the selected work order.

- [ ] **Step 5: Run frontend guard and build**

Run:

```powershell
node scripts\verify_vue_platform_review_actions.js
pnpm --dir v2-web build
```

Expected: verifier passes and build exits 0.

### Task 3: Browser And Safety Verification

**Files:**
- No production files. Local ignored `data/` may change during runtime testing.

- [ ] **Step 1: Restart local service**

Run the local start script on port 52131.

- [ ] **Step 2: Verify page behavior**

Open `http://127.0.0.1:52131/task-hall?project_id=draft-project-3`, select a platform review work order, and confirm the action buttons are visible.

- [ ] **Step 3: Verify safety boundaries**

Confirm no `.env`, `v2-api/data`, `v2-api/app/static/uploads`, or production data path was modified by the implementation.
