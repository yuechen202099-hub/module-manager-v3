# Task 6 Report: Unmatched Review Client Contract

## Files

- `v2-web/src/api/types.ts`
- `v2-web/src/api/services.ts`
- `scripts/verify_project_board_unmatched_review.js`
- `.superpowers/sdd/task-6-report.md`

## RED

Command:

```powershell
node scripts\verify_project_board_unmatched_review.js
```

Result: exit 1, with the expected failure `missing UnmatchedReviewDetail`.

## GREEN

Commands:

```powershell
node scripts\verify_project_board_unmatched_review.js
npm --prefix v2-web run build
```

Results:

- Contract verifier: exit 0, `project board unmatched review API contract checks passed`.
- Build: exit 0; `vue-tsc --noEmit` and Vite production build passed.

## Self-review

- Added the three brief-specified exported types and mapped Task 5 snake_case response fields to the frontend contract.
- Added all seven required API functions with the specified review, photo-content, rescan, confirm, candidates, and finalize routes.
- Preserved optimistic-lock request fields for save, confirm, and finalize operations.
- Photo retrieval accepts only `unmatchedId` and server-owned `photoId`, verifies the returned image blob, and does not proxy a caller-supplied URL.
- Kept the change within the Task 6 write scope; no UI, backend, version, or unrelated-script changes were made.

## Concerns

No blocking concerns. The Vite build emitted its existing vendor pure-annotation and chunk-size warnings; it still exited successfully. UI integration remains intentionally deferred to Task 7.
