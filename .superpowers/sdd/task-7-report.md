# Task 7 Report: Dashboard Unmatched Review Dialog

## Files

- `v2-web/src/components/UnmatchedReviewDialog.vue`
- `v2-web/src/views/ProjectBoardView.vue`
- `v2-web/src/api/services.ts`
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

## Re-review Fixes

### RED

Command:

```powershell
node scripts\verify_project_board_unmatched_review.js
```

Result: exit 1 with `API errors must preserve HTTP status`. The new static checks intentionally failed against the original Task 7 implementation, which inferred 409 conflicts from error text and did not invalidate candidate requests.

### GREEN

Commands:

```powershell
node scripts\verify_project_board_unmatched_review.js
npm --prefix v2-web run build
git diff --check
```

Results:

- UI verifier: exit 0, `project board unmatched review checks passed`.
- Build: exit 0; `vue-tsc --noEmit` and Vite production build passed.
- `git diff --check`: exit 0.
- The build-generated static files were restored or removed before commit.

### Fixes

- Added `ApiRequestError extends Error` with a numeric `status`, plus `getApiErrorStatus`. The shared JSON and form API paths now create this error after their existing response handling, so the 401 clear-and-redirect behavior is unchanged. The unmatched photo-content failure path also reports the structured status.
- All unmatched save, rescan, manual-confirm, and finalize catches continue to use one conflict helper, which now only accepts `getApiErrorStatus(error) === 409`; it no longer inspects localized text or status text.
- Candidate retrieval now accepts an optional abort signal. The dialog owns both a monotonic request serial and an `AbortController`; starting another candidate load, returning to edit, closing, changing `unmatchedId`, and unmounting invalidates the prior request.
- Only the current request for the same visible unmatched record while still in `match` mode may update candidates, loading, or error state. Candidate failures preserve previously loaded candidate data, and stale or aborted failures do not write UI state.
- Candidate page numbers are explicitly clamped to the inclusive `[1, candidateTotalPages]` range. Finalization remains hidden in the template for non-admins and now has an explicit non-admin function guard.
- Extended the verifier to fail for absent structured 409 handling, candidate invalidation/abort/current-request checks, page clamping, and either missing administrator finalization condition.

### Re-review Self-review

- A 409 reload still calls `loadDetail({ preserveDraft: true })`; it retains the draft, selected photo, current mode, selected candidate, and candidate page.
- Candidate request starts keep existing candidate rows until the current request succeeds. Current-request checks prevent failed or invalidated older requests from replacing candidates, clearing newer loading state, or presenting stale errors.
- Closing and reopening invalidates candidate work before reset; a delayed save cannot enter match mode or initiate candidate loading after the dialog closes or the record changes.
- The object URL lifecycle is unchanged: image replacement, stale image completion, close, and unmount all revoke object URLs.

### Re-review Concerns

- Existing Vite VueUse pure-annotation and large-chunk warnings remain. They do not affect the successful TypeScript/Vite build, and static build outputs remain outside the commit.

## Second Re-review Fix

### RED

Command:

```powershell
node scripts\verify_project_board_unmatched_review.js
```

Result: exit 1 with `new candidate cycles must invalidate prior results`. The previous implementation left prior candidates and `selectedCandidateKey` in memory while a new post-save candidate request was pending, so a failed request could expose an outdated finalization target.

### GREEN

Commands:

```powershell
node scripts\verify_project_board_unmatched_review.js
npm --prefix v2-web run build
git diff --check
```

Results:

- UI verifier: exit 0, `project board unmatched review checks passed`.
- Build: exit 0; `vue-tsc --noEmit` and Vite production build passed.
- `git diff --check`: exit 0.
- Build-generated static files were restored or removed before commit.

### Fix And Self-review

- Added `resetCandidateResults()` and invoke it immediately after invalidating an existing request and before creating the new candidate request. It clears candidate rows, clears the selected candidate key, and resets candidate pagination to page 1.
- A current candidate request failure now leaves the dialog with an error plus the empty candidate state; it cannot reveal a prior candidate or permit finalization against an older reviewed version.
- Abort/current-request guards remain unchanged. Return-to-review, close, ID changes, and unmount continue to invalidate in-flight candidate work.
- The 409 path remains separate: it reloads detail with `preserveDraft: true` and does not start a new candidate cycle, so its current UI preservation behavior is retained.

### Second Re-review Concerns

- Existing Vite VueUse pure-annotation and large-chunk warnings remain; they do not affect the successful build. No static build artifacts are included in the commit.
