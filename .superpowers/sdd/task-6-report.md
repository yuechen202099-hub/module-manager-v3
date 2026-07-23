# V3.2.0 Task 6 报告

- 日期：2026-07-23
- 分支：`production/V3/3.2.0`
- 基线 HEAD：`74989e7`
- 任务：管理员导出中心前端
- 当前结论：`DONE_WITH_CONCERNS`

## 需求

重建管理员导出中心 Vue 页面与路由，满足：

- `/exports` 管理员路由
- 四标签：`终端交付 / 设备清单 / 业务清单 / 统计报表`
- `tab / page / page_size / filter` 与 URL 同步
- 默认 `20`，可选 `20 / 50 / 100`
- 旧响应淘汰
- 终端交付展示阻断、最近生成、操作
- 四类设备导出可发起
- catalog 项可发起
- job history 展示类型、范围、行数、创建人、时间、状态、失败原因、下载
- 按 TDD 先写 RED verifier，再实现
- 不删除其他页面出口，保留 `task-hall` 兼容入口

## 修改文件

前端源码：

- `v2-web/src/views/ExportsView.vue`
- `v2-web/src/components/export-center/TerminalDeliveryTab.vue`
- `v2-web/src/components/export-center/ExportCatalogTab.vue`
- `v2-web/src/components/export-center/ExportJobsTable.vue`
- `v2-web/src/composables/useExportCenterQuery.ts`
- `v2-web/src/api/services.ts`
- `v2-web/src/api/types.ts`
- `v2-web/src/router/staticPages.ts`
- `v2-web/src/router/index.ts`
- `v2-web/src/layouts/AppLayout.vue`

验证脚本：

- `scripts/verify_v3_2_0_export_center_ui.py`

后端兼容补丁：

- `v2-api/app/services/state_repository.py`
  - PostgreSQL `list_export_jobs()` 补齐 `created_by` 透传，避免 job history “创建人” 列在真实库上为空。

构建产物：

- `v2-api/app/static/vue/index.html`
- `v2-api/app/static/vue/version.json`
- `v2-api/app/static/vue/assets/*`
  - 已清理旧 hash 文件并更新本轮 build 产物。

## 验证结果

已执行并通过：

1. `python scripts/verify_v3_2_0_export_center_ui.py`
2. `python scripts/verify_vue_migration_gate.py`
3. `cd v2-web && npm exec vue-tsc -- --noEmit`
4. `cd v2-web && npm run build`
5. `git diff --check`

构建附带告警：

- Vite / Rollup 对 `@vueuse/core` 的 `/* #__PURE__ */` 注释位置给出 warning
- 既有大 chunk warning 仍然存在

以上告警未阻断构建，且不由本任务新引入。

## 版本变化

- 未修改应用版本号
- 当前工作基于 `production/V3/3.2.0` 分支任务推进
- 新增导出中心页面与构建产物，不单独切应用 patch 版本

## 发布状态

- 已完成本地实现、路由接线、类型/服务补齐、前端构建
- 已生成最新 Vue 静态产物
- 尚未执行发布

## 风险

1. `created_by` 的 PostgreSQL 透传补丁已落代码，但没有补跑独立后端 pytest 用例；当前仅通过前端链路和代码审查确认。
2. `task-hall` 作为兼容入口保留在静态页注册表中，但已从左侧导航隐藏，避免与 `global-search` 重复显示。
3. 构建仍存在既有 chunk size warning，未在本任务内做额外拆包优化。
## 2026-07-23 Review Fixes

- 追加修复导出中心审阅未通过的 2 Important + 1 Minor：
  - `task_detail` catalog 现在通过 catalog 元数据 `required_filters` 渲染任务选择器，复用现有 `/local-test/tasks` 列表，按终端 / 任务号搜索，只在选定有效 `task_id` 后发起导出。
  - `/exports/jobs` 扩展为服务端分页过滤，支持白名单 `category` / `job_types` / `status`；JSON / PostgreSQL 路径都在 count 与 rows 上应用同一过滤条件。
  - 终端下载动作不再依赖当前 history 页的最近 job，改为幂等 `createExportJob('final_delivery', { terminals: [terminal] })`；若返回 `succeeded` 直接下载，若返回 `pending` 刷新状态。
  - `useExportCenterQuery.ts` 改为 `Number.isFinite` + 正整数 + `MAX_EXPORT_CENTER_PAGE` 上限的 URL 页码解析，非法值回退到 `1`，`page_size` 继续只允许 `20 / 50 / 100`。
- 新增 / 更新 RED -> GREEN 验证：
  - `v2-api/tests/test_export_center.py`
    - `test_export_jobs_forward_server_side_filters`
    - `test_json_export_jobs_filter_by_category_job_types_and_status`
    - `test_export_catalog_marks_task_detail_required_filters`
    - `test_task_detail_export_job_requires_positive_task_id`
    - 保留并回归 `test_postgres_export_jobs_include_created_by`
  - `scripts/verify_v3_2_0_export_center_ui.py` 增补 strict page parse、task selector、server-side jobs query、terminal 幂等下载检查。
- 本次验证（2026-07-23）:
  - `python -m pytest v2-api/tests/test_export_center.py -k "export_jobs_forward_server_side_filters or json_export_jobs_filter_by_category_job_types_and_status or export_catalog_marks_task_detail_required_filters or task_detail_export_job_requires_positive_task_id or export_jobs_use_supported_page_sizes or postgres_export_jobs_include_created_by" -q` -> `8 passed, 31 deselected`
  - `python scripts/verify_v3_2_0_export_center_ui.py` -> `OK`
  - `cd v2-web && npm exec vue-tsc -- --noEmit` -> `0`
  - `cd v2-web && MODULE_MANAGER_VUE_OUT_DIR=.tmp/task6-build npm run build` -> `0`（仅既有 Rollup chunk / PURE comment warnings）
  - `git diff --name-only 74989e7..HEAD -- v2-api/app/static/vue` -> 空输出
