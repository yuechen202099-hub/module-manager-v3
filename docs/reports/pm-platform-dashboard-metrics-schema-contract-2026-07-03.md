# PM 平台驾驶舱指标配置契约报告

## 摘要

本包把项目驾驶舱指标口径纳入项目字段 schema：后端可以接收并归一化结构化 `dashboard_metrics`，前端可以按对象读取、保存回传，并在项目驾驶舱展示“字段配置看板口径”。

这一步服务于多项目平台化：不同项目的主字段、聚合字段和附属设备层级可以不同，但进度、交付能力、现场采集、审阅质量和 KPI 看板需要有一组可配置、可追踪的指标定义。

## 基线

- 生产基线分支：`production/V3/3.0.77`
- 生产基线提交：`4c05cc92a71e08a7eb5da6a25cef654271b4cfc5`
- 平台开发分支：`pm-platform/production-3.0.77-sync`
- 当前本地 HEAD：`689220507d1981a2efd7c6291ba12882d6eda882`

## 修改文件

- `v2-api/app/schemas/project.py`
- `v2-api/app/services/platform/catalog.py`
- `v2-web/src/api/types.ts`
- `v2-web/src/api/services.ts`
- `v2-web/src/views/ProjectsView.vue`
- `v2-web/src/views/ProjectBoardView.vue`
- `scripts/verify_platform_dashboard_metrics_contract.py`
- `scripts/verify_vue_dashboard_metrics_contract.js`
- `docs/superpowers/plans/2026-07-03-dashboard-metrics-schema-contract.md`
- `docs/reports/pm-platform-dashboard-metrics-schema-contract-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- `v2-api/app/static/vue/index.html` 和本次 `pnpm build` 生成的 Vue 静态资产

## 功能说明

- 后端新增 `ProjectDashboardMetricCreate`，项目创建和字段 schema 更新可以接收 `dashboard_metrics`。
- 后端新增指标归一化：保留 `key`、`label`、`source`、`scope`，去重，空配置回退默认指标。
- 前端新增 `ProjectDashboardMetric` 类型，避免把后端对象映射成字符串。
- 前端保存字段配置时会保留 `dashboardMetrics`，避免用户一保存字段层级就丢失驾驶舱口径。
- 项目驾驶舱新增“字段配置看板口径”卡片，展示当前项目 schema 中配置的指标。
- 设备层级语义保持不变：换模块仍是任务对象下更换附属设备；换终端仍是主设备更换后确认附属设备是否更换。

## 红绿验证

红灯确认：

- `python scripts\verify_platform_dashboard_metrics_contract.py`
  - 初始失败：`AssertionError: API schema model must accept dashboard_metrics from project configuration requests`
- `node scripts\verify_vue_dashboard_metrics_contract.js`
  - 初始失败：`ProjectWorkItemSchema must expose dashboardMetrics as ProjectDashboardMetric[]`

修复后通过：

- `python scripts\verify_platform_dashboard_metrics_contract.py`
  - `OK: platform dashboard metrics schema contract is preserved`
- `node scripts\verify_vue_dashboard_metrics_contract.js`
  - `OK: Vue dashboard metrics schema contract is wired`
- `python -m pytest v2-api\tests\test_api.py::test_review_detail_deep_link_serves_vue_shell -q`
  - `1 passed`
- `python scripts\verify_vue_migration_gate.py --strict-native`
  - `[OK] Vue shell and static page registry are wired.`
- `python scripts\verify_pm_platform_team_operating_model.py`
  - `[OK] PM platform team operating model is locked`
- `node scripts\verify_vue_device_replacement_hierarchy_mode.js`
  - `[OK] Vue device replacement hierarchy mode is explicit.`
- `python scripts\verify_platform_device_replacement_hierarchy_mode.py`
  - `[OK] platform device replacement hierarchy mode is explicit`
- `python scripts\verify_platform_device_relation_roles.py`
  - `[OK] platform device relation roles are preserved`
- `node scripts\verify_vue_field_graph_smart_drop.js`
  - `[OK] Vue field graph smart drop is wired.`
- `node scripts\verify_vue_project_board_platform_kpis.js`
  - `[OK] Vue project board exposes platform KPI cockpit cards.`
- `node scripts\verify_vue_platform_delivery_kpis.js`
  - `[OK] Vue project views expose construction delivery KPIs.`
- `node scripts\verify_vue_platform_review_quality_kpis.js`
  - `[OK] Vue project views connect delivery KPIs with review quality metrics.`
- `pnpm --dir v2-web build`
  - `vue-tsc --noEmit && vite build` 通过；仅保留已有 chunk size 和依赖 PURE 注释警告。

浏览器烟测：

- URL：`http://127.0.0.1:52131/project-board?project_id=replacement-project&dashboard_metrics_smoke=<timestamp>`
- 结果：Vue 根节点存在，项目驾驶舱加载，`字段配置看板口径` 标题存在，`.platform-dashboard-metric-card` 数量为 `6`。
- 新加载资产：`/vue/assets/index-B3RoDVwi.js`
- 本次加载后的控制台错误：`0`

## 风险说明

低到中等风险。改动触及项目字段配置契约和前端保存路径，但没有执行数据库迁移，没有连接或修改 PostgreSQL 生产库，没有写 OSS，没有改 `.env`，没有改生产版本号，没有创建 tag，没有发布服务器。

主要风险是：后续如果某个项目配置了自定义指标，但看板计算端还没有实现对应 `key` 的数值来源，界面只能展示口径，不能自动给出业务数值。这个风险是可控的，因为本包只定义并保存指标契约，未声称完成所有指标计算引擎。

## 迁移说明

无数据库迁移。本包只扩展 API 输入模型、字段 schema 归一化和前端映射。既有项目没有 `dashboard_metrics` 时继续使用默认指标。

## 回滚建议

如需回滚本包：

1. 移除 `ProjectDashboardMetricCreate` 和 `ProjectWorkItemSchemaCreate.dashboard_metrics`。
2. 移除 `_normalize_dashboard_metrics`，并把 `_normalize_work_item_schema` 中的 `dashboard_metrics` 恢复为默认列表。
3. 将前端 `dashboardMetrics` 类型恢复为原来的字符串数组处理，移除服务层对象映射。
4. 移除 `ProjectsView.vue` 中对 `dashboardMetrics` 的表单保留逻辑。
5. 移除 `ProjectBoardView.vue` 的“字段配置看板口径”展示区。
6. 删除两个新增验证脚本和本报告/计划记录。

无生产数据回滚要求。
