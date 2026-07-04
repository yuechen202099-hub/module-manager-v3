# Review Hierarchy Gap Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Carry external-completed import hierarchy gaps into the platform review workbench, so reviewers can see and block missing device hierarchy evidence.

**Architecture:** The import draft already records `missing_conditional_field` warnings per preview row. Execution will persist those warnings on created work orders, the review payload will expose them as `review_hierarchy_gap_items`, and the Vue review workbench will render them inside the existing evidence-gap gate.

**Tech Stack:** FastAPI service helpers in `v2-api/app/services/platform/templates.py`, Vue 3 + TypeScript API mapping in `v2-web/src/api`, and review UI in `v2-web/src/views/ReviewView.vue`.

---

### Task 1: Backend Guard

**Files:**
- Create: `scripts/verify_platform_review_hierarchy_gap_followup.py`
- Read: `scripts/verify_platform_import_draft_hierarchy_gap_summary.py`
- Modify later: `v2-api/app/services/platform/templates.py`

- [ ] **Step 1: Write the failing verifier**

Create a verifier that:

```python
# Build a terminal replacement project schema with accessory confirmation fields.
# Upload an external_completed workbook where the confirmation says "更换"
# but old/new accessory values and required evidence are blank.
# Create an import batch, create a work-order task, execute it,
# then fetch review work orders and assert:
# - the selected review work order has review_hierarchy_gap_items
# - the items include 通讯模块（旧）, 通讯模块（新）, 新旧模块照片
```

- [ ] **Step 2: Run red**

Run:

```powershell
& "C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\verify_platform_review_hierarchy_gap_followup.py
```

Expected red result: the review payload does not expose `review_hierarchy_gap_items`.

### Task 2: Frontend Guard

**Files:**
- Create: `scripts/verify_vue_review_hierarchy_gap_followup.js`
- Modify later: `v2-web/src/api/types.ts`
- Modify later: `v2-web/src/api/services.ts`
- Modify later: `v2-web/src/views/ReviewView.vue`

- [ ] **Step 1: Write the failing guard**

The guard reads the three frontend files and requires these tokens:

```text
review_hierarchy_gap_items
reviewHierarchyGapItems
PlatformReviewHierarchyGapItem
importedReviewHierarchyGapItems
导入层级缺口
```

- [ ] **Step 2: Run red**

Run:

```powershell
& "C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" scripts\verify_vue_review_hierarchy_gap_followup.js
```

Expected red result: the frontend does not yet map or render imported hierarchy gaps.

### Task 3: Backend Implementation

**Files:**
- Modify: `v2-api/app/services/platform/templates.py`

- [ ] **Step 1: Add a small sanitizer helper**

Add a helper that extracts only `missing_conditional_field` warnings from a preview row and returns dictionaries with stable keys:

```python
{
    "row": row_number,
    "field_key": field_key,
    "field_label": field_label,
    "message": message,
    "value": value,
}
```

- [ ] **Step 2: Persist gaps during external-completed execution**

Inside `execute_import_work_order_task`, when `template_type == "external_completed"`, store:

```python
"review_hierarchy_gap_items": _platform_hierarchy_gap_items_from_warnings(row)
```

on the created work order.

- [ ] **Step 3: Expose gaps in review payload**

Inside `_platform_review_work_order_payload`, include:

```python
"review_hierarchy_gap_items": _platform_review_hierarchy_gap_items(work_order)
```

### Task 4: Frontend Implementation

**Files:**
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/views/ReviewView.vue`

- [ ] **Step 1: Add frontend type**

Add `PlatformReviewHierarchyGapItem` with `row`, `fieldKey`, `fieldLabel`, `message`, and `value`.

- [ ] **Step 2: Map backend payload**

Map `review_hierarchy_gap_items` to `reviewHierarchyGapItems`.

- [ ] **Step 3: Render as review evidence gap**

Add `importedReviewHierarchyGapItems` and push a `导入层级缺口` group into `reviewEvidenceGapGroups`, so approval remains blocked until the evidence is resolved through project data correction or rework.

### Task 5: Verification and Records

**Files:**
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Create: `docs/reports/pm-platform-review-hierarchy-gap-followup-2026-07-03.md`

- [ ] **Step 1: Run targeted guards**

Run the backend and frontend guards, plus the existing import/review hierarchy checks.

- [ ] **Step 2: Build and smoke test**

Run the Vue build and open the local review page in the in-app browser.

- [ ] **Step 3: Safety checks**

Run `git diff --check` and a sensitive-path scan. Confirm no `.env`, production data, uploads, OSS, PostgreSQL, tag, release, or deployment action was touched.
