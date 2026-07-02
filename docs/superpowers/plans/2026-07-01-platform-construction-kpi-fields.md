# Platform Construction KPI Fields Plan

> For future agents: this package makes required construction KPI fields part of the platform work-order flow.

**Goal:** When a platform work order is collected on site, the system must preserve KPI evidence needed for delivery and efficiency calculations: installer, install time, completion time, upload time, online duration, photo count, and old-device recovery status.

**Product rule:** Operators should see practical field data, not abstract configuration. Required KPI data can be manually entered where needed, while platform-owned values are filled at save time.

## Task 1: Backend KPI Contract

**Files:**

- Modify: `v2-api/tests/test_api.py`
- Modify: `v2-api/app/services/platform/templates.py`
- Modify: `v2-api/app/services/platform/catalog.py`

- [x] Add a failing test for platform construction KPI preservation.
- [x] Save `kpi_values` on platform construction collection drafts.
- [x] Auto-fill installer from actor when missing.
- [x] Auto-fill completed/uploaded time from collection time when missing.
- [x] Preserve install time and online duration from collected field values.
- [x] Calculate photo count from covered photo slots/photos.
- [x] Mark old-device recovery when old-device fields or photo slots are present.
- [x] Summarize project task KPIs: KPI-ready work orders, photo total, old-device recovered, average online duration, and installer count.

## Task 2: Frontend Exposure

**Files:**

- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/views/ConstructionView.vue`
- Add: `scripts/verify_vue_platform_construction_kpi_fields.js`

- [x] Map backend `kpi_values` to frontend `kpiValues`.
- [x] Map project task KPI summary fields.
- [x] Show `KPI 必备资料` in platform construction collection forms.
- [x] Let operators enter install time, completion time, and online duration.
- [x] Show installer, photo count, and old-device recovery status.
- [x] Add a guard script so these fields are not accidentally removed.

## Verification

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py::test_project_construction_work_order_collection_preserves_required_kpi_fields v2-api\tests\test_api.py::test_project_construction_work_order_collection_draft_saves_locally v2-api\tests\test_api.py::test_project_overview_counts_local_platform_work_orders_after_execution v2-api\tests\test_api.py::test_project_overview_splits_platform_work_order_kpis_by_import_and_review_stage -q
node scripts\verify_vue_platform_construction_kpi_fields.js
pnpm --dir v2-web build
.\.venv\Scripts\python.exe scripts\verify_production_baseline.py
```

Observed result on 2026-07-01:

- Backend focused tests: `4 passed, 1 warning`.
- Frontend KPI field guard: passed.
- Frontend build: passed with existing Rollup pure-comment and chunk-size warnings.
- Production baseline check: passed for `origin/production/V3/3.0.71 @ 862659e0e659`; current `HEAD @ 8035f3247b5f` contains the production baseline.
- Sensitive path check for `.env`, `data`, `v2-api/data`, `v2-api/app/static/uploads`, and `uploads`: clean.
- Browser smoke: `/construction?project_id=replacement-project` loaded without console errors. The current replacement demo data did not expose a platform work-order entry, so visible KPI-panel coverage is provided by the guard script and build.

## Migration And Rollback Notes

- No database migration is introduced.
- The local platform work-order JSON store may now contain `kpi_values`.
- Existing work orders without `kpi_values` remain readable; payloads derive empty/default KPI values.
- Rollback can remove `kpi_values` mapping, the construction-page KPI panel, and the new summary fields. Existing local JSON records remain compatible because extra keys are ignored by older readers.
- No production data, OSS object, upload file, or database row is modified.
