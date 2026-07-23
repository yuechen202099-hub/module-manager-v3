# Task 1 Report: Retire Reviewer Login Role And Redirect Legacy Routes

## Status
- Status: implemented and follow-up review fixes completed
- Branch: `production/V3/3.2.0`
- Commit: `HEAD` (final new commit hash is recorded in the final reply)

## Scope handled
- Retired reviewer login role without deleting historical reviewer business fields or audit data
- Redirected legacy reviewer routes to the supported V3.2.0 destination
- Fixed independent review findings on export permissions, backend legacy redirects, frontend legacy session handling, and build-artifact diff cleanup

## Modified files
- `v2-api/app/services/account_store.py`
- `v2-api/app/api/routes/auth.py`
- `v2-api/app/api/routes/local_test.py`
- `v2-api/app/api/routes/exports.py`
- `v2-api/app/main.py`
- `v2-api/tests/test_api.py`
- `scripts/verify_v3_2_0_role_routes.py`
- `v2-web/src/api/mock.ts`
- `v2-web/src/api/types.ts`
- `v2-web/src/api/services.ts`
- `v2-web/src/router/staticPages.ts`
- `v2-web/src/router/index.ts`
- `v2-web/src/views/AccountManagementView.vue`
- `v2-web/src/views/TaskHallView.vue`
- `v2-web/src/stores/auth.ts`
- `v2-web/src/layouts/AppLayout.vue`
- `v2-api/app/static/vue/index.html`
- `v2-api/app/static/vue/version.json`
- `v2-api/app/static/vue/assets/*`

## Original RED commands and results
1. Initial backend RED attempt from brief:
   - `python -m pytest tests/test_api.py -k "reviewer_only or requires_admin_after_v3_2_0 or constructor_cannot_use_export" -q`
   - Result: failed because system Python lacked `fastapi`
2. RED rerun with repo venv:
   - `..\.venv\Scripts\python.exe -m pytest tests/test_api.py -k "reviewer_only or requires_admin_after_v3_2_0 or constructor_cannot_use_export" -q`
   - Result: `2 failed, 1 passed, 199 deselected, 1 warning`
   - Confirmed failures:
     - reviewer-only account was not disabled by migration
     - reviewer bearer token could still call `/local-test/groups/{group_id}/barcode-manual-confirm`
3. Original static route verifier RED:
   - `..\.venv\Scripts\python.exe ..\scripts\verify_v3_2_0_role_routes.py`
   - Result: failed because reviewer role and legacy route traces still existed in frontend code

## Original GREEN commands and results
1. Initial RED cases after implementation:
   - `..\.venv\Scripts\python.exe -m pytest tests/test_api.py -k "reviewer_only or requires_admin_after_v3_2_0 or constructor_cannot_use_export" -q`
   - Result: `3 passed, 199 deselected, 1 warning`
2. Static role/route verifier:
   - `..\.venv\Scripts\python.exe ..\scripts\verify_v3_2_0_role_routes.py`
   - Result: `[OK] V3.2.0 role and legacy route checks passed`
3. Focused backend subset from brief:
   - `..\.venv\Scripts\python.exe -m pytest tests/test_api.py -k "reviewer or account or production_review or export" -q`
   - Result: `22 passed, 180 deselected, 1 warning`
4. Brief-specified frontend check:
   - `npm run type-check`
   - Result: failed because current `v2-web/package.json` has no `type-check` script
5. Equivalent frontend type check:
   - `npm exec vue-tsc -- --noEmit`
   - Result: passed
6. Extra build verification during the first implementation pass:
   - `npm run build`
   - Result: passed and wrote generated assets into `v2-api/app/static/vue/`
7. Diff health:
   - `git diff --check`
   - Result: passed

## Review-fix RED commands and results
1. Backend RED slice for independent review findings:
   - `..\.venv\Scripts\python.exe -m pytest tests/test_api.py -k "task_hall_page_is_available or direct_workspace_routes_redirect_to_app_shell or unmatched_page_redirects_to_global_search_review_mode or legacy_review_page_redirects_to_global_search_with_encoded_group_id or excel_exports_return_real_workbooks or production_legacy_export_endpoints_require_admin" -q`
   - Result: `5 failed, 1 passed, 198 deselected, 1 warning`
   - Confirmed failures:
     - `/task-hall` still served the Vue shell instead of redirecting to `/global-search`
     - `/unmatched` still redirected to `/task-hall`
     - `/review/{group_id}` was missing server-side
     - constructor/reviewer could still use `/exports/task-detail`, `/exports/exception-meters`, `/exports/project-outside`
2. Frontend static verifier RED after tightening expectations:
   - `..\.venv\Scripts\python.exe ..\scripts\verify_v3_2_0_role_routes.py`
   - Result: failed because legacy-session invalidation helpers were still missing from `v2-web/src/api/services.ts`

## Final GREEN commands and results
1. Review-fix regression slice:
   - `..\.venv\Scripts\python.exe -m pytest tests/test_api.py -k "task_hall_page_is_available or direct_workspace_routes_redirect_to_app_shell or unmatched_page_redirects_to_global_search_review_mode or legacy_review_page_redirects_to_global_search_with_encoded_group_id or excel_exports_return_real_workbooks or production_legacy_export_endpoints_require_admin" -q`
   - Result: `6 passed, 198 deselected, 1 warning`
2. Required focused backend subset on final tree:
   - `..\.venv\Scripts\python.exe -m pytest tests/test_api.py -k "reviewer or account or production_review or export or task_hall_page_is_available or direct_workspace_routes_redirect_to_app_shell or unmatched_page_redirects_to_global_search_review_mode or legacy_review_page_redirects_to_global_search_with_encoded_group_id" -q`
   - Result: `27 passed, 177 deselected, 1 warning`
3. Role / route / session verifier on final tree:
   - `..\.venv\Scripts\python.exe ..\scripts\verify_v3_2_0_role_routes.py`
   - Result: `[OK] V3.2.0 role and legacy route checks passed`
4. Required frontend type check on final tree:
   - `npm exec vue-tsc -- --noEmit`
   - Result: passed
5. Final diff health:
   - `git diff --check`
   - Result: passed (only LF/CRLF warnings from Git; no diff-format errors)

## What changed

### Original Task 1 implementation
- Account migration:
  - restricted valid login roles to `admin` and `constructor`
  - reviewer-only accounts are migrated to disabled with reason `V3.2.0 已停用审阅员角色`
  - preserved historical reviewer-related business fields and audit data
- Backend permissions:
  - production-only review mutation path now resolves to admin-only behavior
  - reviewer demo/login defaults removed
- Frontend role and route cleanup:
  - `UserRole` now only allows `admin | constructor`
  - reviewer option removed from account management
  - `/task-hall` and `/review/:groupId` frontend routes redirect to `/global-search`

### Follow-up review fixes
- Critical export fix:
  - `v2-api/app/api/routes/exports.py`
  - `task-detail`, `exception-meters`, and `project-outside` now all require `Depends(require_admin)`
  - added tests proving constructor/reviewer `403` and admin `200`
- Important backend redirect fix:
  - `v2-api/app/main.py`
  - `/task-hall` now redirects to `/global-search`
  - `/unmatched` now redirects to `/global-search?review=1`
  - added `/review/{group_id}` redirect to `/global-search?group_id=...&review=1`
  - group id is encoded with `quote(..., safe="")`
- Important frontend legacy-session fix:
  - `v2-web/src/api/services.ts`
  - legacy `module_manager_session` now only accepts explicit `admin|constructor` roles
  - reviewer-era, mixed-invalid, malformed, or role-less legacy sessions are cleared and redirected to `/login`
  - `fetchCurrentUser()` no longer falls back to `mockUser` when legacy session is invalid
  - `currentActor()` no longer revives the removed reviewer fallback from `module_manager_reviewer`
  - `v2-web/src/stores/auth.ts` now reads legacy tokens through the validated services helper instead of parsing raw legacy session JSON independently
  - `v2-web/src/layouts/AppLayout.vue` now swallows the expected redirect-side rejection from `hydrateFromLegacySession()`
- Minor net-diff cleanup:
  - restored `v2-api/app/static/vue/` to `HEAD^` state so the branch net diff no longer carries the earlier ad hoc hashed build outputs
  - intentionally did not generate a fresh release bundle in this fix commit

## Self-review
- Scope control:
  - stayed within Task 1 plus the explicit review findings
  - did not touch Task 2+ behavior
- Data preservation:
  - no historical reviewer business fields or audit records were deleted
- Export guard correctness:
  - protected all three requested legacy export endpoints uniformly with `require_admin`
- Redirect correctness:
  - server-side tests now prove legacy entry points land on `/global-search` instead of the removed workbench
  - `/review/{group_id}` encoding is covered by a focused redirect test
- Legacy session correctness:
  - invalid legacy sessions are rejected at the read boundary instead of being silently mapped into a mock user
  - auth-store startup and app hydration now both flow through the validated path
- Build artifact cleanup:
  - no fresh hashed bundle was committed in this follow-up
  - the branch diff now removes the prior Task 1 hashed output churn instead of adding more

## Remaining concern
- No functional concern remains.
- The repo still does not define `npm run type-check`; the final required frontend verification used `npm exec vue-tsc -- --noEmit` exactly as requested in this follow-up.
