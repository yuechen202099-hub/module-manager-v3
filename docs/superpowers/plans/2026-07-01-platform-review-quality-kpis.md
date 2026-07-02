# Platform Review Quality KPI Plan

> For future agents: this package connects delivery KPI visibility with review pass/return quality indicators.

**Goal:** Project managers should read field evidence completeness and review quality together from `/project-board` and `/platform-projects`.

**Product rule:** Delivery KPI answers whether现场资料 has enough measurable evidence; review quality answers whether that evidence passed, was returned, or is still waiting.

## Task 1: Frontend Guard

**Files:**

- Add: `scripts/verify_vue_platform_review_quality_kpis.js`

- [x] Require `ProjectBoardView.vue` to render review quality KPI cards.
- [x] Require review quality to derive from `approvedArchive`, `returnedRework`, and `pendingReview`.
- [x] Require `ProjectsView.vue` to show a compact review quality line.
- [x] Verify the guard fails before implementation and passes after implementation.

## Task 2: Project Views

**Files:**

- Modify: `v2-web/src/views/ProjectBoardView.vue`
- Modify: `v2-web/src/views/ProjectsView.vue`

- [x] Add `审阅质量` cards under the project cockpit platform KPI section.
- [x] Show pass/archive count, returned rework count, pending review count, pass rate, and return rate.
- [x] Add a short quality note that tells operators how to interpret blank or returned data.
- [x] Add compact project-list quality line next to field delivery KPI line.

## Verification

Run:

```powershell
node scripts\verify_vue_platform_review_quality_kpis.js
node scripts\verify_vue_platform_delivery_kpis.js
node scripts\verify_vue_project_platform_kpis.js
node scripts\verify_vue_project_board_platform_kpis.js
pnpm --dir v2-web build
python scripts\verify_production_baseline.py
git status --short -- .env data v2-api/data v2-api/app/static/uploads uploads
```

Observed result on 2026-07-01:

- Review quality KPI guard: passed.
- Delivery KPI visibility guard: passed.
- Project-list platform KPI guard: passed.
- Project-board platform KPI guard: passed.
- Frontend build: passed with existing Rollup pure-comment and chunk-size warnings.
- Production baseline check: passed.
- Sensitive path check: passed with no reported changes.
- Local server restart on port `52131`: passed.
- Browser smoke:
  - `/project-board?project_id=replacement-project` shows `审阅质量`, `通过与返工`, `通过归档`, `退回返工`, `待审工单`, `通过率`, and `返工率`.
  - `/platform-projects` shows compact `审阅质量`, `通过`, `返工`, `待审`, and `通过率` labels.
  - Browser console check: no error or warning logs observed during the smoke check.

## Migration And Rollback Notes

- No database migration is introduced.
- No backend contract change is introduced; the package consumes existing task summary fields.
- Rollback can remove `scripts/verify_vue_platform_review_quality_kpis.js` and the review-quality UI additions in `ProjectBoardView.vue` and `ProjectsView.vue`.
- No production data, OSS object, upload file, or database row is modified.
