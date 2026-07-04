# Rework Resubmission Audit Trail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a returned platform work order is recollected and submitted again, record a clear resubmission event and show it in construction/review screens.

**Architecture:** The backend already resets returned work orders to `pending_review` on submitted collection saves. This package adds an explicit `rework_submitted` review-history event at that transition, keeps prior return history intact, and adds frontend labels/messages so operators can tell a pending-review item came from rework.

**Tech Stack:** FastAPI platform template service in `v2-api/app/services/platform/templates.py`, Vue 3 + TypeScript API types/mappers in `v2-web/src/api`, and operator UI in `v2-web/src/views/ConstructionView.vue` plus `v2-web/src/views/ReviewView.vue`.

---

### Task 1: Backend Guard

**Files:**
- Create: `scripts/verify_platform_rework_resubmission_audit.py`
- Modify later: `v2-api/app/services/platform/templates.py`

- [x] **Step 1: Write the failing verifier**

Create a temporary terminal-replacement project, submit a complete collection, return it in review, submit the collection again, then assert:

```python
work_order["review_status"] == "pending_review"
any(event["action"] == "returned" for event in work_order["review_history"])
any(event["action"] == "rework_submitted" for event in work_order["review_history"])
latest_resubmission["actor"] == "constructor"
latest_resubmission["note"] == "返工补采后重新提交审阅"
latest_resubmission["reason"] == "returned_rework_resubmitted"
```

- [x] **Step 2: Run red**

Run:

```powershell
& "C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\verify_platform_rework_resubmission_audit.py
```

Expected red result: status is already `pending_review`, but no `rework_submitted` history event exists.

### Task 2: Frontend Guard

**Files:**
- Create: `scripts/verify_vue_rework_resubmission_audit.js`
- Modify later: `v2-web/src/views/ConstructionView.vue`
- Modify later: `v2-web/src/views/ReviewView.vue`

- [x] **Step 1: Write the failing guard**

The guard requires:

```text
platformWasReworkResubmitted
返工已重新提交审阅
platformReviewHistoryActionLabel
rework_submitted
返工重新提交
returned_rework_resubmitted
```

- [x] **Step 2: Run red**

Run:

```powershell
& "C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" scripts\verify_vue_rework_resubmission_audit.js
```

Expected red result: construction and review pages still show raw action/status text.

### Task 3: Backend Implementation

**Files:**
- Modify: `v2-api/app/services/platform/templates.py`

- [x] Add a tiny helper or inline block in `save_platform_construction_work_order_collection` that runs only when `status == "submitted"` and stored `review_status == "returned"`.
- [x] Preserve the existing returned event in `review_history`.
- [x] Append:

```python
{
    "id": f"review-action-{uuid4().hex[:12]}",
    "action": "rework_submitted",
    "actor": work_order["collected_by"],
    "reviewed_at": collected_at,
    "note": "返工补采后重新提交审阅",
    "reason": "returned_rework_resubmitted",
}
```

- [x] Keep the existing transition to `pending_review` and clearing of `reviewed_by`, `reviewed_at`, `review_note`, and `review_reason`.

### Task 4: Frontend Implementation

**Files:**
- Modify: `v2-web/src/views/ConstructionView.vue`
- Modify: `v2-web/src/views/ReviewView.vue`

- [x] In `ConstructionView.vue`, add `platformWasReworkResubmitted(order)` by checking `reviewHistory` for `rework_submitted`.
- [x] When a platform collection is submitted and `platformWasReworkResubmitted(updated)` is true, show `返工已重新提交审阅`; keep the existing normal submitted message for non-rework submissions.
- [x] In `ReviewView.vue`, add `platformReviewHistoryActionLabel(action)` to map:

```ts
approved -> 通过
returned -> 退回
exception -> 标异常
rework_submitted -> 返工重新提交
```

- [x] Render history rows with the label instead of the raw `event.action`.

### Task 5: Verification and Records

**Files:**
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Create: `docs/reports/pm-platform-rework-resubmission-audit-2026-07-03.md`

- [x] Run the new backend and frontend guards.
- [x] Re-run construction rework gap panel guards.
- [x] Re-run review return reason suggestion guards.
- [x] Build Vue.
- [x] Browser-smoke `/construction` and `/task-hall` as the current review workbench entry.
- [x] Run `git diff --check`, sensitive-path scan, and team operating model guard.
- [x] Record changed files, behavior, risk, migration note, and rollback note.
