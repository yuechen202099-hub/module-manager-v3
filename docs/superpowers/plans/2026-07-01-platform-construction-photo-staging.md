# Platform Construction Photo Staging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow platform construction work orders to stage photo files locally while preserving production data isolation.

**Architecture:** Store photo files under the local platform data directory and store only photo metadata on the local platform work-order record. Do not use OSS, PostgreSQL production tables, or `v2-api/app/static/uploads` in this stage.

**Tech Stack:** FastAPI multipart upload, pytest `TestClient`, Vue 3, TypeScript, local JSON platform work-order store.

---

### Task 1: Backend Local Photo Upload

**Files:**
- Modify: `v2-api/tests/test_api.py`
- Modify: `v2-api/app/services/platform/templates.py`
- Modify: `v2-api/app/api/routes/projects.py`

- [ ] **Step 1: Write the failing upload/delete test**

Add `test_project_construction_work_order_photo_upload_and_delete_are_local` to create a draft project, execute a local platform work order, upload a `before_photo` file, assert `storage=local_platform_store`, assert `static/uploads` is not in `storage_key`, then delete the photo and assert `collection_photos=[]`.

- [ ] **Step 2: Verify red**

Run: `python -m pytest v2-api/tests/test_api.py::test_project_construction_work_order_photo_upload_and_delete_are_local -q`

Expected: FAIL with `404 Not Found`.

- [ ] **Step 3: Add service functions**

Add `upload_platform_construction_work_order_photo` and `delete_platform_construction_work_order_photo` in `templates.py`. Validate the photo slot against project schema, write bytes to `platform-construction-photos/{project_id}/{work_order_id}/{photo_id}.jpg`, update `collection_photos`, and recompute `covered_photo_slots`.

- [ ] **Step 4: Add routes**

Add:

```text
POST /projects/{project_id}/construction/work-orders/{work_order_id}/photos
DELETE /projects/{project_id}/construction/work-orders/{work_order_id}/photos/{photo_id}
```

Both routes return the updated platform work-order payload.

- [ ] **Step 5: Verify green**

Run: `python -m pytest v2-api/tests/test_api.py::test_project_construction_work_order_photo_upload_and_delete_are_local -q`

Expected: PASS.

### Task 2: Frontend Save Flow Uploads Pending Photos

**Files:**
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/views/ConstructionView.vue`

- [ ] **Step 1: Extend types**

Add `PlatformConstructionPhoto` and `PlatformConstructionPhotoUploadPayload`, and include `collectionPhotos` on `PlatformConstructionWorkOrder`.

- [ ] **Step 2: Add upload service**

Add `uploadProjectConstructionWorkOrderPhoto(projectId, workOrderId, payload)` using `FormData` and the new backend upload route.

- [ ] **Step 3: Update save flow**

In `savePlatformCollectionDraft`, upload every selected local file first, merge returned `coveredPhotoSlots`, then call `saveProjectConstructionWorkOrderCollection`.

- [ ] **Step 4: Build check**

Run: `pnpm --dir v2-web build`

Expected: TypeScript and Vite build succeed.

### Task 3: Safety and Documentation

**Files:**
- Modify: `docs/reports/pm-platform-full-flow-evaluation-2026-06-30.md`

- [ ] **Step 1: Update report**

Append the local photo staging section with API paths, storage boundary, tests, and remaining risk.

- [ ] **Step 2: Verify production guardrails**

Run:

```powershell
python scripts/verify_production_baseline.py
git status --short -- .env data v2-api/data v2-api/app/static/uploads
```

Expected: baseline check passes; sensitive path check has no output.
