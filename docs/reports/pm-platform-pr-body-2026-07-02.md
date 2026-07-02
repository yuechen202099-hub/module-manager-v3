## Summary

- Extend the replacement-project manager toward a configurable operations engineering management platform.
- Add project-specific field graph, workflow, import handoff, construction checklist, review, KPI, and delivery visibility slices.
- Add backend decomposition checkpoints, read-only persistence status, PostgreSQL persistence design, project config persistence contract preview, project readiness check, and a frontend `上线检查` panel without running any database migration.
- Add Team Operating Model Lock documentation and guard coverage for the multi-agent development setting.
- Add read-only `/projects/readiness/summary` with `action_counts`, plus a `/platform-projects` `上线状态` and `接入待办` area for scan-friendly multi-project readiness.
- Add clickable Project Readiness Action Filter: operators can click a `接入待办` tag, see `筛选中`, filter to matching projects through `filteredProjects`, and use `清除筛选` to restore the full list.
- Add Project Persistence Readiness Frontend: `字段配置` now shows read-only `持久化准备`, current storage, PostgreSQL migration approval state, target tables, round-trip status, and safety gates.
- Add Platform Migration Readiness Gate: `GET /projects/persistence/migration-readiness` and `字段配置` show backup, dry-run, verification, rollback, approval, and cutover blockers before any PostgreSQL migration can proceed.
- Add Platform Handoff Readiness Summary: `GET /projects/handoff/readiness` and `/platform-projects` now show `交付就绪`, `可评审包`, target baseline `production/V3/3.0.71`, and `生产迁移未放行` before PR/patch review.
- Add Platform LAN Tablet Access: local start remains `127.0.0.1` by default, but `-HostAddress 0.0.0.0` enables trusted LAN tablet review and prints a `LAN URL`.

## Baseline

- Target branch: `production/V3/3.0.71`
- Feature branch: `pm-platform/project-drafts`
- Production branch commit: `862659e0e6599367e7dbb164659b7ccd147c2574`
- Feature HEAD at handoff: `8035f3247b5f2aaf579747fe4d71ae25fe2211e5`
- Merge base: `862659e0e6599367e7dbb164659b7ccd147c2574`

## 平台版本号评估

- 建议采用独立平台进度号：`PM-V1.0.xx`。
- 平台版本号只记录项目管理平台自身开发进度，例如：`PM-V1.0.03，基于生产 V3.0.77`。
- 平台版本号不替代、不占用、不预留生产主系统 `V3.0.xx`。
- 生产主系统仍由生产维护线统一分配 `V3.0.xx`，平台 PR/patch 只声明“基于哪个生产版本”。
- 采用该方案不会改变生产版本递增规则：小修仍按生产规则 `+0.01`，大流程变更仍需用户确认后 `+0.1`，文档/SOP-only 不升应用版本。
- 当前 GitHub Issue #1 已提示最新生产基线为 `production/V3/3.0.77`。本平台分支在正式 PR/patch 前需要先合并或 rebase 最新生产线，并将本节中的“基于生产版本”更新为实际合并后的基线。

## Test Plan

- [x] `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_contracts.py v2-api\tests\test_platform_persistence_status.py v2-api\tests\test_platform_postgres_design.py -q`
- [x] `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_project_config_persistence_contract.py v2-api\tests\test_platform_postgres_design.py v2-api\tests\test_platform_persistence_status.py v2-api\tests\test_platform_contracts.py -q`
- [x] `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_project_readiness.py v2-api\tests\test_platform_project_config_persistence_contract.py v2-api\tests\test_platform_contracts.py -q`
- [x] `.\.venv\Scripts\python.exe scripts\verify_platform_backend_contract_snapshot.py`
- [x] `.\.venv\Scripts\python.exe scripts\verify_platform_persistence_status.py`
- [x] `.\.venv\Scripts\python.exe scripts\verify_platform_postgres_design.py`
- [x] `.\.venv\Scripts\python.exe scripts\verify_platform_project_config_persistence_contract.py`
- [x] `.\.venv\Scripts\python.exe scripts\verify_platform_migration_readiness.py`
- [x] `.\.venv\Scripts\python.exe scripts\verify_platform_handoff_readiness.py`
- [x] `.\.venv\Scripts\python.exe scripts\verify_platform_local_start_script.py`
- [x] `.\.venv\Scripts\python.exe scripts\verify_platform_project_readiness.py`
- [x] `.\.venv\Scripts\python.exe scripts\verify_pm_platform_team_operating_model.py`
- [x] `node scripts\verify_vue_project_readiness_summary_list.js`
- [x] `.\.venv\Scripts\python.exe scripts\verify_production_baseline.py`
- [x] `node scripts\verify_vue_construction_checklist_consumption.js`
- [x] `node scripts\verify_vue_project_field_graph_template_actions.js`
- [x] `node scripts\verify_vue_project_workflow_module_toggles.js`
- [x] `node scripts\verify_vue_project_readiness_panel.js`
- [x] `node scripts\verify_vue_project_field_graph_designer.js`
- [x] `node scripts\verify_vue_project_persistence_readiness.js`
- [x] `node scripts\verify_vue_platform_handoff_readiness.js`
- [x] `pnpm --dir v2-web build` with bundled Node/Pnpm on PATH
- [x] Browser smoke: `/platform-projects` -> `字段配置` shows `上线检查`, pass/fail summary, and next-action hints
- [x] Browser smoke: `/platform-projects` -> click `接入待办` tag; `筛选中` appears, table filters from 193 rows to 154 rows, and `清除筛选` restores 193 rows
- [x] Browser smoke: `/platform-projects` -> `字段配置` shows `持久化准备`, `当前存储`, `PostgreSQL`, `迁移审批`, `目标表`, and `安全门槛`; refresh keeps the panel visible
- [x] Browser smoke: `/platform-projects` -> `字段配置` shows `迁移门禁`, backup, dry-run, rollback, approval, and `待审批`; refresh keeps the gate populated
- [x] Browser smoke: `/platform-projects` -> top band shows `交付就绪`, `可评审包`, `production/V3/3.0.71`, `生产迁移未放行`, and appears before `上线检查`
- [x] LAN smoke: local service listens on `0.0.0.0:52131`; `http://127.0.0.1:52131/platform-projects` and `http://192.168.50.162:52131/platform-projects` return `HTTP 200`
- [x] Sensitive path check for `.env`, `data`, `v2-api/data`, `v2-api/app/static/uploads`, and `uploads`
- [x] PR/patch handoff guard scans for live OSS/PostgreSQL, SQL, dump, and key-like changed paths

## Migration / Rollback

- No production database migration is included.
- No production data, OSS object, upload file, version tag, or deployment is changed.
- Rollback before merge: close this PR or discard this branch.
- Rollback after merge: revert the merge commit and rebuild generated frontend assets from source.
- Future PostgreSQL persistence migration requires explicit approval, backup, dry-run, verification, and rollback rehearsal.

## Risks

- Broad platform branch: review by file group and feature slice.
- Generated Vue assets are included as build output.
- Full backend pytest is not used as the local gate because the full suite expects missing local business workbook samples.
- PostgreSQL work is design-only; persistence write/read migration is the next gated package.
- Handoff readiness is review-only; it keeps `ready_for_production_migration` and `ready_for_production_release` false.
- LAN tablet access is local-review only; it is opt-in and should be used only on trusted private Wi-Fi/LAN.
- GitHub Issue #1 reports the current production baseline has advanced to `production/V3/3.0.77`; this branch must follow that baseline before final PR/patch handoff.
- Production 3.0.77 Sync Readiness evidence: `production_changed=145`, `dirty=192`, `overlap=43`. Do not merge directly into the dirty worktree; first create a WIP snapshot and isolated sync workspace.
