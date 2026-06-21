# V2.3.1 Static HTML Rollback And V2.4.x Vue Parity Execution Plan

## Summary

Production has to stay on the last stable static HTML workflow until the Vue implementation has feature parity.

The baseline is not conversation memory and not the current Vue implementation. The baseline is the final static HTML implementation under:

- `v2-api/app/static/login.html`
- `v2-api/app/static/app_shell.html`
- `v2-api/app/static/project_board.html`
- `v2-api/app/static/claim_tasks.html`
- `v2-api/app/static/task_hall.html`
- `v2-api/app/static/construction.html`
- `v2-api/app/static/sync_config.html`
- `v2-api/app/static/v201.html`

Baseline interpretation rule:

- A feature is considered part of the Vue parity baseline only when it is visible or reachable in the final static HTML user flow.
- Static HTML code that exists but is hidden, has no visible entry, or is not reachable from the final product UI is treated as cancelled by default.
- Cancelled hidden static features must not be counted as Vue gaps unless the user explicitly reactivates them.

Production rollback target:

- Static release selected on server: `/opt/module-manager-v2/releases/previous-current-20260620_005524`
- Runtime backup created before rollback: `/opt/module-manager-v2/backups/runtime/20260620_233858_before_static_rollback`
- Production `current` now points to the static HTML release.

All future implementation changes must also be logged in `docs/V2_CHANGE_WORKLOG.md`.

## Static HTML Feature Baseline

### Login

- Account login with username, team id, and password.
- Load login configuration from `/auth/config`.
- Submit login to `/auth/login`.
- Persist login state in `localStorage`.
- Support Enter key login and preset account fill.

### App Shell

- Unified static shell navigation.
- Pages: project board, task claim, review workbench, construction collection, cache upload.
- Logout entry.
- iframe-based embedded page loading.
- Cross-page refresh notification.
- Shell-level scan import and final delivery export.
- Frontend concurrent image download and ZIP packaging.

### Project Board

- Project summary, project progress, risk metrics, installer distribution, terminal task progress.
- System status panel.
- Import total catalog.
- Import scan spreadsheet with async job polling.
- Export final delivery.
- Export single-terminal delivery package.
- Export task detail.
- Export exception meters.
- Frontend image download through proxy and ZIP generation.
- Account management: create, update, delete, role, status, team, password.
- Refresh account list and project status.
- Mobile panel collapse.

### Claim Tasks

- Claim overview.
- Terminal task list.
- Claim and release review task.
- Admin release all tasks.
- Construction status label.
- Admin open/close construction.
- Scheduled refresh.
- Mobile collapse.
- Reviewer identity sync from login state.

### Review Workbench

- My claimed tasks.
- Group list and group search by meter, address, and terminal.
- Group filters: all, reviewable, exception, archived, unconstructed.
- Fold unconstructed groups unless found by search.
- Main image review area with thumbnail/current photo switching.
- Preview, thumbnail, original image URL handling.
- Object URL loading fallback.
- Lightbox with zoom, pan, fit, and close.
- Keyboard shortcuts: `1-4` classify, arrow navigation, `Enter` archive, `Esc` close.
- Archive current photo and archive whole group.
- Block group archive when category labels conflict.
- Allow archived photos to be selected and corrected.
- Save meter, collector, and module fields.
- Upload supplement photos.
- Delete photo.
- Restore pending.
- Reset to unconstructed.
- Return to exception work order.
- Exception reason and note editing.
- Export exception meters.
- In-page import of Excel/CSV and JSON URL rows.
- Background refresh without losing active group.
- After archive, select the next unfinished group.

### Construction Collection

- Task selection mode and construction work mode.
- Admin/constructor navigation and logout.
- Show only assigned/open construction terminal tasks according to role.
- Terminal task list with status.
- Return to task view.
- Group list.
- Chinese-style address sorting.
- Fuzzy search by address and meter.
- Scan meter number to open the construction form.
- Group filters: all, unconstructed, cached, exception work order.
- Upload all cached drafts.
- Construction form fields: meter, terminal, address, collector, module asset number.
- Collector scan, module scan, and meter scan.
- QuaggaJS barcode recognition and BarcodeDetector fallback.
- Manual input fallback.
- Camera/photo selection.
- Image compression before cache/upload.
- Photo slots: before, collector, module with meter, after, other.
- Required validation: module number, before photo, module with meter photo, after photo.
- Existing photos shown by slot to avoid duplicate upload.
- IndexedDB local cache.
- Offline terminal snapshot.
- Weak-network collection and later upload.
- Exception work order handling and submit.
- Mobile-first focused layout.

### Cache Upload

- Standalone cache upload page is cancelled.
- Cache upload remains inside Construction Collection.
- Construction Collection keeps IndexedDB read/write, local draft display, cached filter, one-click upload, and exception work order cached upload.
- Legacy static source `construction_cache.html` has been removed and must not be restored unless explicitly reactivated.
- Legacy Vue page/CSS remnants for standalone cache upload have been removed.
- Legacy `/construction-cache` direct access redirects to `/construction`.

### Unmatched And Exception Handling

- Standalone unmatched/exception handling page is cancelled.
- Exception handling remains inside the Review Workbench.
- Review Workbench keeps metadata correction, supplement photo upload, restore pending, reset to unconstructed, return to exception work order, and exception meter export.
- Legacy static source `unmatched.html` has been removed and must not be restored unless explicitly reactivated.
- Orphan Vue view `ExceptionsView.vue` and standalone unmatched/cache page CSS remnants have been removed.
- Static `task_hall.html` exception tabs and page-style exception workspace remnants have been removed; they are not part of the parity baseline.
- Legacy `/unmatched` direct access redirects to `/task-hall`; old exception-mode query parameters must not force the review workbench into exception mode.
- Hidden or unreachable static unmatched features must not be restored unless the user explicitly reactivates them.

### Sync Config

- Show backend sync disabled notice.
- Explain spreadsheet import as the main workflow.
- Link to project board import.
- Link to terminal task view.

### V201 Redirect

- Show entering official review workbench.
- Auto/manual navigation to review workbench.

## Vue Parity Work Order

### P0 Review Workbench

- Fix half-loaded/gray image states against the static object URL and fallback behavior.
- Align group filters and unconstructed folding with static HTML.
- Allow archived photos to be selected and corrected.
- Block whole-group archive when duplicate labels exist.
- Auto-scroll the group list when navigating by keyboard.
- Preserve active group during background refresh.

### P0 Construction Collection

- Reapply static Chinese address sort and fuzzy search.
- Restore upload-all cached drafts in the construction page.
- Ensure meter scan opens the matching construction form.
- Ensure exception work order supplement photos appear in cache upload.
- Verify offline terminal snapshot can support no-network collection.

### P1 Construction Cache Inside Collection

- Keep cache upload inside construction page.
- Do not restore the standalone cache upload route unless explicitly reactivated by the user.

### P1 Project Board And Claim Tasks

- Restore account management and all export entries on project board.
- Restore admin release-all and construction open/close on claim tasks.
- Keep standalone unmatched/exception handling cancelled; exception editing and export must remain inside the review workbench.

### P2 Login And Sync Config

- Restore team id login field and `/auth/config` rendering.
- Keep sync disabled explanation and links.

## Local Production Data Simulation

- Export from production:
  - PostgreSQL custom dump when `DATABASE_URL` is available.
  - `/opt/module-manager-v2/data/local_state.json`.
  - `/opt/module-manager-v2/data/users.json`.
  - Upload samples or OSS photo index only; do not download all original images by default.
- Restore locally:
  - Use a local PostgreSQL database or Docker Postgres.
  - Point local `.env` to the local database only.
  - Never let local Vue write to the production database.
- Test data must include:
  - Claimed tasks.
  - Unconstructed groups.
  - Exception work orders.
  - Archived photos.
  - Cached construction drafts.
  - Supplement photo and export flows.

## Release Gate

- Every page must have a parity table:
  - Static HTML feature.
  - Vue implementation.
  - Test evidence.
  - Blocking status.
- Required local commands:
  - `vue-tsc --noEmit`
  - `vite build`
  - `python scripts/verify_vue_migration_gate.py --strict-native`
  - `pytest v2-api/tests/test_api.py -q`
- Required browser checks:
  - Desktop 1366px.
  - Desktop 1920px.
  - Mobile 390px.
- Production must not switch back to Vue until all static HTML features are implemented in Vue or explicitly marked as user-approved deferred items.

## Operating Rules

- Do not judge parity from memory.
- Do not remove a static feature during Vue migration.
- Do not add new production static HTML features.
- Log every completed modification in `docs/V2_CHANGE_WORKLOG.md`.
- If a page fails browser validation, the worklog entry must say "modified, pending verification" instead of "complete".
