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

## Re-review Fixes

### Findings fixed

- Candidate retrieval now models the server `{ total, items }` envelope and maps only `items`.
- Rescans require and forward `expected_version` through the frontend, request model, route, repository contract, JSON implementation, and PostgreSQL implementation.
- JSON rescans reject a stale version before starting the barcode scan or mutating state. PostgreSQL verifies the version in the unlocked snapshot before CPU work, then verifies it again after acquiring the persistence lock.
- `UnmatchedReviewPhoto` no longer exposes `sourceUrl`; its backend adapter no longer reads `source_url`. Review image content remains addressable only by `unmatchedId` and server-owned `photoId`.
- The verifier now detects candidate-envelope misuse, missing rescan versions, review-photo source URL exposure, and arbitrary URL proxy parameters.

### RED

Commands:

```powershell
node scripts\verify_project_board_unmatched_review.js
..\.venv\Scripts\python.exe -m pytest -q tests/test_api.py::test_unmatched_rescan_accepts_json_category_and_rejects_invalid tests/test_api.py::test_unmatched_rescan_version_conflict_returns_409_without_persisting tests/test_state_repository.py::test_postgres_rescan_unmatched_review_rejects_stale_expected_version_before_scan tests/test_local_simulation.py::test_unmatched_rescan_rejects_stale_expected_version_without_scanning_or_persisting
```

Results:

- Contract verifier: exit 1 with `candidates must model the server envelope`.
- Backend regression set: exit 1 with 4 failures. The route did not forward `expected_version`, and JSON/PostgreSQL rescan methods rejected the new keyword argument. This reproduced the missing version contract before implementation.

### GREEN

Commands:

```powershell
node scripts\verify_project_board_unmatched_review.js
npm --prefix v2-web run build
..\.venv\Scripts\python.exe -m pytest -q tests/test_api.py::test_production_unmatched_review_role_matrix tests/test_api.py::test_unmatched_rescan_accepts_json_category_and_rejects_invalid tests/test_api.py::test_unmatched_rescan_version_conflict_returns_409_without_persisting tests/test_api.py::test_production_unmatched_review_routes_use_postgres_repository_transactions tests/test_state_repository.py::test_postgres_rescan_unmatched_review_scans_outside_session_then_relocks_once tests/test_state_repository.py::test_postgres_rescan_unmatched_review_rejects_version_drift_before_persistence tests/test_state_repository.py::test_postgres_rescan_unmatched_review_rejects_stale_expected_version_before_scan tests/test_local_simulation.py::test_unmatched_rescan_uses_ocr_persists_audits_and_keeps_formal_accuracy_unchanged tests/test_local_simulation.py::test_unmatched_rescan_return_value_is_mutation_isolated tests/test_local_simulation.py::test_unmatched_rescan_rejects_stale_expected_version_without_scanning_or_persisting tests/test_local_simulation.py::test_unmatched_rescan_with_sparse_meter_uses_empty_match_key_and_persists tests/test_local_simulation.py::test_json_state_repository_delegates_unmatched_rescan_and_confirmation
git diff --check
```

Results:

- Contract verifier: exit 0.
- Frontend build: exit 0; `vue-tsc --noEmit` and Vite build passed.
- Backend focused rescan suite: 12 passed; it emits the existing FastAPI TestClient deprecation warning.
- `git diff --check`: exit 0.

### Re-review self-review

- Confirmed all reviewed paths encode IDs for review-photo content and do not accept a caller URL.
- Confirmed stale expected versions return the existing `ReviewVersionConflict`, which the route maps to HTTP 409; tests assert no scanner invocation or persisted JSON mutation for stale JSON calls, and no PostgreSQL commit or scan for stale snapshot calls.
- Confirmed the PostgreSQL happy-path and drift tests still prove CPU scanning happens outside the session and persistence performs a second `FOR UPDATE` check.
- Confirmed the diff is limited to the explicitly authorized frontend, backend, test, verifier, and report files.

### Re-review concerns

No blocking concerns. Existing Vite vendor warnings and the FastAPI TestClient deprecation warning remain outside this change.
