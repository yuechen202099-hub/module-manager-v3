# Review Workbench Platform Filters Plan

> **For agentic workers:** This plan records the review workbench package completed during the PM platform build-out.

**Goal:** Make the review page useful for platform-imported work orders, especially external-completed takeover data that enters the platform at the review stage.

**Product rule:** Review is a first-class platform module. Operators should not have to use only the task hall to find imported work that is pending review, returned, marked exception, approved, or not ready.

## Task 1: Frontend Guard

**Files:**

- Add: `scripts/verify_vue_review_platform_filters.js`

- [x] Add a structure guard requiring `ReviewView.vue` to use the platform review API.
- [x] Require status filters, counts, selected work order state, submit actions, and review history rendering.
- [x] Run the guard before implementation and observe failure.

## Task 2: Review Page Platform Entry

**Files:**

- Modify: `v2-web/src/views/ReviewView.vue`

- [x] Load platform review work orders from `/projects/{project_id}/review/work-orders`.
- [x] Render review status filters: all, pending review, approved, returned, exception, and not ready.
- [x] Select a platform work order from the review queue.
- [x] Show collection metadata, field reviews, photo slot reviews, and review history.
- [x] Submit approve, return, and exception actions through the existing review action endpoint.
- [x] Preserve the older material-group review flow on the same page.

## Verification

Run:

```powershell
node scripts\verify_vue_review_platform_filters.js
node scripts\verify_vue_platform_review_actions.js
node scripts\verify_vue_platform_review_entry.js
pnpm --dir v2-web build
```

Observed result on 2026-07-01:

- `verify_vue_review_platform_filters.js`: passed after implementation.
- `verify_vue_platform_review_actions.js`: passed.
- `verify_vue_platform_review_entry.js`: passed.
- Frontend build: passed with existing Rollup/chunk-size warnings.
- Browser smoke check: `/app?page=review/g-001&project_id=replacement-project` rendered platform review filters and had no console errors.

## Migration And Rollback Notes

- No database migration is introduced.
- No backend endpoint change is introduced; the page uses existing platform review APIs.
- Rollback can remove the `ReviewView.vue` additions and the guard script without touching stored project data.

