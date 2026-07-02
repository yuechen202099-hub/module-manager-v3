# Platform Delivery KPI Visibility Plan

> For future agents: this package promotes construction delivery KPI summaries into project management views.

**Goal:** Project managers should see delivery capability indicators from `/platform-projects` and `/project-board?project_id=<project>`, not only inside construction collection forms.

**Product rule:** Keep work-order flow stages separate from delivery capability metrics. Flow stages answer "where is the work"; delivery KPIs answer "whether field evidence is complete and measurable".

## Task 1: Frontend Guard

**Files:**

- Add: `scripts/verify_vue_platform_delivery_kpis.js`

- [x] Require frontend API contracts to map construction delivery KPI fields.
- [x] Require `ProjectBoardView.vue` to render delivery KPI cards.
- [x] Require `ProjectsView.vue` to show delivery KPI summaries in the task center column.
- [x] Verify the guard fails before implementation and passes after implementation.

## Task 2: Project Views

**Files:**

- Modify: `v2-web/src/views/ProjectBoardView.vue`
- Modify: `v2-web/src/views/ProjectsView.vue`

- [x] Add a `交付能力` section under the project-board platform cockpit.
- [x] Show KPI-ready work orders, field photos, old-device recovery, average online duration, and installer count.
- [x] Add a compact delivery KPI line to the project list task center.
- [x] Keep labels short enough for dense operational scanning.

## Verification

Run:

```powershell
node scripts\verify_vue_platform_delivery_kpis.js
node scripts\verify_vue_project_board_platform_kpis.js
node scripts\verify_vue_project_platform_kpis.js
node scripts\verify_vue_platform_construction_kpi_fields.js
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py::test_project_construction_work_order_collection_preserves_required_kpi_fields -q
pnpm --dir v2-web build
.\.venv\Scripts\python.exe scripts\verify_production_baseline.py
```

Observed result on 2026-07-01:

- Delivery KPI visibility guard: passed.
- Project-board platform KPI guard: passed.
- Project-list platform KPI guard: passed.
- Construction KPI field guard: passed.
- Backend construction KPI focused test: `1 passed, 1 warning`.
- Frontend build: passed with existing Rollup pure-comment and chunk-size warnings.
- Production baseline check: passed.
- Sensitive path check for `.env`, `data`, `v2-api/data`, `v2-api/app/static/uploads`, and `uploads`: passed with no reported changes.
- Local server restart on port `52131`: passed.
- Browser smoke:
  - `/project-board?project_id=replacement-project` shows `平台运营指标`, `交付能力`, `KPI资料完整`, `现场照片`, `旧设备回收`, `平均在线时长`, and `安装人员`.
  - `/platform-projects` shows compact delivery KPI line labels: `KPI`, `旧设备`, `在线`, and `人员`.
  - Browser console check: no error or warning logs observed during the smoke check.

## Migration And Rollback Notes

- No database migration is introduced.
- No backend contract changes are introduced in this package; it consumes fields already mapped by the construction KPI package.
- Rollback can remove the delivery KPI UI blocks and delete `scripts/verify_vue_platform_delivery_kpis.js`.
- No production data, OSS object, upload file, or database row is modified.
