# Task 7 Report: Dashboard Unmatched Review Dialog

## Files

- `v2-web/src/components/UnmatchedReviewDialog.vue`
- `v2-web/src/views/ProjectBoardView.vue`
- `scripts/verify_project_board_unmatched_review.js`
- `.superpowers/sdd/task-7-report.md`

## RED

Command:

```powershell
node scripts\verify_project_board_unmatched_review.js
```

Result: exit 1 with `ENOENT` for `v2-web/src/components/UnmatchedReviewDialog.vue`. This was the expected missing-component failure after extending the Task 6 contract verifier with the Task 7 UI assertions.

## GREEN

Commands:

```powershell
node scripts\verify_project_board_unmatched_review.js
npm --prefix v2-web run build
```

Results:

- UI verifier: exit 0, `project board unmatched review checks passed`.
- Build: exit 0; `vue-tsc --noEmit` and Vite production build passed.
- The production build regenerated static files as a side effect; all generated static changes were restored or removed before commit, leaving them outside the Task 7 diff.

## Design And State Machine

- `UnmatchedReviewDialog` exposes only `v-model`, `unmatched-id`, `matched`, and `updated` at its integration boundary.
- The dialog has `review` and `match` modes. Review keeps temporary unmatched metadata and photo categories; completing review saves first, then retrieves paginated 20-item candidate pages.
- Photo content is obtained only through `fetchUnmatchedReviewPhotoObjectUrl(unmatchedId, photoId)` and shown with native `img`. Replacing a URL, closing, unmounting, and obsolete async results revoke object URLs.
- Rescan sends the current detail version. A 409 reloads detail with the current mode, photo selection, candidate page, selection, and draft state preserved, then shows a short message. Failed rescans do not overwrite the visible form or photo category.
- Only administrators see the final candidate confirmation button. Successful finalization emits `matched`; the dashboard clamps the retained list page, reloads unmatched rows, and reloads dashboard data.

## Self-review

- Confirmed table-row clicks open the review dialog while the review button, dropdown, and dropdown entries stop propagation.
- Confirmed finalization is hidden for non-admin users, with backend authorization remaining the production enforcement boundary.
- Confirmed object URL stale-request, replacement, close, unmount, and close/reopen paths revoke or reset safely.
- Confirmed candidate paging is fixed at 20, clamps after data changes, supports empty candidates with only return/close actions, and supports single selection across multiple pages.
- Confirmed the dialog resets its mode/candidate state on close/reopen and preserves active UI state on 409 reload.
- Confirmed no `sourceUrl`, `el-image`, placeholder terminal, group/task/KPI/archive mutation, or formal barcode-accuracy mutation was introduced.
- Confirmed desktop uses a two-column review layout, while screens at or below 768px use fullscreen/single-column controls without fixed-width text overlap.

## Concerns

- Vite still emits the existing VueUse pure-annotation and large-chunk warnings. The build exits successfully; no static artifacts are included in this task.
