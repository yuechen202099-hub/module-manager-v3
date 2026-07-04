# Review Return Reason Suggestions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn imported hierarchy evidence gaps into a usable review return reason so reviewers can return mid-project takeover work orders without manually rewriting the missing device evidence list.

**Architecture:** Backend review payloads expose a read-only `suggested_review_return_reason` derived from existing `review_hierarchy_gap_items`. Review actions use the same suggestion as a defensive fallback when a returned action has no reason. The two Vue review workbenches map, display, and apply the suggestion without changing the review state machine.

**Tech Stack:** FastAPI service helpers in `v2-api/app/services/platform/templates.py`, Vue 3 + TypeScript API mapping in `v2-web/src/api`, and Element Plus review controls in `ReviewView.vue` and `TaskHallView.vue`.

---

### Task 1: Backend Guard

**Files:**
- Create: `scripts/verify_platform_review_return_reason_suggestions.py`
- Modify later: `v2-api/app/services/platform/templates.py`

- [ ] **Step 1: Write the failing verifier**

Create an external-completed terminal replacement work order with `review_hierarchy_gap_items`, fetch review work orders, and assert the payload exposes `suggested_review_return_reason` containing `导入层级缺口`, `旧通讯模块号`, `新通讯模块号`, and `新旧模块照片`.

The verifier then calls the return action with blank `reason` and asserts the stored `review_reason` falls back to the same suggestion.

- [ ] **Step 2: Run red**

Run:

```powershell
& "C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\verify_platform_review_return_reason_suggestions.py
```

Expected red result: the payload does not expose `suggested_review_return_reason`.

### Task 2: Frontend Guard

**Files:**
- Create: `scripts/verify_vue_review_return_reason_suggestions.js`
- Modify later: `v2-web/src/api/types.ts`
- Modify later: `v2-web/src/api/services.ts`
- Modify later: `v2-web/src/views/ReviewView.vue`
- Modify later: `v2-web/src/views/TaskHallView.vue`

- [ ] **Step 1: Write the failing guard**

The guard requires these tokens:

```text
suggested_review_return_reason
suggestedReviewReturnReason
reviewReturnReasonSuggestion
platformReviewReturnReasonSuggestion
采用缺口原因
建议退回原因
inputValue: platformReviewReturnReasonSuggestion
```

- [ ] **Step 2: Run red**

Run:

```powershell
& "C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" scripts\verify_vue_review_return_reason_suggestions.js
```

Expected red result: frontend does not map or use return reason suggestions.

### Task 3: Backend Implementation

**Files:**
- Modify: `v2-api/app/services/platform/templates.py`

- [ ] Add `_platform_review_return_reason_suggestion(work_order)` that formats hierarchy gap item labels into a short return reason.
- [ ] Add `suggested_review_return_reason` to `_platform_review_work_order_payload`.
- [ ] In `review_platform_work_order`, when `action == "returned"` and no explicit reason is provided, use the suggested reason for both `review_reason` and the history reason.

### Task 4: Frontend Implementation

**Files:**
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/views/ReviewView.vue`
- Modify: `v2-web/src/views/TaskHallView.vue`

- [ ] Add `suggestedReviewReturnReason` to `PlatformReviewWorkOrder`.
- [ ] Map backend `suggested_review_return_reason`.
- [ ] In `ReviewView.vue`, compute `reviewReturnReasonSuggestion`, show a `建议退回原因` helper near the note input, and add a small `采用缺口原因` action that fills `reviewNote`.
- [ ] In `TaskHallView.vue`, compute `platformReviewReturnReasonSuggestion` and use it as the default `inputValue` for return prompts.

### Task 5: Verification and Records

**Files:**
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Create: `docs/reports/pm-platform-review-return-reason-suggestions-2026-07-03.md`

- [ ] Run the new backend and frontend guards.
- [ ] Re-run the review hierarchy gap follow-up guards.
- [ ] Build Vue and smoke the review workbench.
- [ ] Run `git diff --check` and sensitive-path checks.
- [ ] Record behavior, risk, and rollback notes.
