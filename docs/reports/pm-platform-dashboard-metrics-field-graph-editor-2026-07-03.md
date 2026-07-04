# PM 平台驾驶舱指标图形化配置报告

## 摘要

本包把上一包的结构化 `dashboard_metrics` 契约进一步落到字段图形配置界面：在 `FieldGraphDesigner` 中新增“驾驶舱指标口径”预设卡，用户可以在配置字段层级时直接选择项目进度、交付能力、现场采集、审阅质量和 KPI 效率这些指标口径。

本包不新增指标计算引擎，不执行数据库迁移，不改生产数据。它只让指标口径可以被非技术用户在字段配置界面选择，并通过既有项目 schema 保存路径保存。

## 基线

- 生产基线分支：`production/V3/3.0.77`
- 生产基线提交：`4c05cc92a71e08a7eb5da6a25cef654271b4cfc5`
- 平台开发分支：`pm-platform/production-3.0.77-sync`
- 当前本地 HEAD：`689220507d1981a2efd7c6291ba12882d6eda882`

## 修改文件

- `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
- `v2-web/src/views/ProjectsView.vue`
- `scripts/verify_vue_dashboard_metrics_field_graph_editor.js`
- `docs/superpowers/plans/2026-07-03-dashboard-metrics-field-graph-editor.md`
- `docs/reports/pm-platform-dashboard-metrics-field-graph-editor-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- `v2-api/app/static/vue/index.html` 和本次 `pnpm build` 生成的 Vue 静态资产

## 功能说明

- 字段关系图新增“驾驶舱指标口径”区域。
- 提供 5 类可点击指标卡：
  - 项目进度：工单总数、已完成工单。
  - 交付能力：已完成工单、平均完工时长。
  - 现场采集：已采集工单。
  - 审阅质量：异常工单。
  - KPI 效率：平均在线时长、平均完工时长。
- 点击指标卡会把该类指标加入或移出当前项目 `dashboardMetrics`。
- 新建项目和编辑项目两个字段图都已接入 `dashboardMetrics` 和 `update-dashboard-metrics`。
- 自定义指标不会被预设卡误删；只有当前卡负责的指标会被切换。

## 红绿验证

红灯确认：

- `node scripts\verify_vue_dashboard_metrics_field_graph_editor.js`
  - 初始失败：`FieldGraphDesigner must accept and emit dashboard metric form objects`

修复后通过：

- `node scripts\verify_vue_dashboard_metrics_field_graph_editor.js`
  - `OK: Vue dashboard metrics field graph editor is wired.`
- `node scripts\verify_vue_dashboard_metrics_contract.js`
  - `OK: Vue dashboard metrics schema contract is wired`
- `python scripts\verify_platform_dashboard_metrics_contract.py`
  - `OK: platform dashboard metrics schema contract is preserved`
- `node scripts\verify_vue_field_graph_smart_drop.js`
  - `[OK] Vue field graph smart drop is wired.`
- `node scripts\verify_vue_device_replacement_hierarchy_mode.js`
  - `[OK] Vue device replacement hierarchy mode is explicit.`
- `pnpm --dir v2-web build`
  - `vue-tsc --noEmit && vite build` 通过；仅保留已有 chunk size 和依赖 PURE 注释警告。

浏览器烟测：

- URL：`http://127.0.0.1:52131/platform-projects?metric_editor_smoke=<timestamp>`
- 操作：打开“新建项目”弹窗。
- 结果：`驾驶舱指标口径` 可见，5 张 `.dashboard-metric-editor-card` 可见。
- 点击第 1 张“项目进度”卡后：
  - 第一张卡进入 selected 状态。
  - 指标计数从 `0 项` 变成 `2 项`。
  - 页面可见 `工单总数` 和 `已完成工单`。
- 本次加载后的控制台错误：`0`

## 风险说明

低风险。该包只改前端表单和图形配置界面，不改变后端数据结构，不执行迁移，不连接或修改 PostgreSQL 生产库，不写 OSS，不改 `.env`，不创建 tag，不发布服务器，不占用生产版本号。

主要产品风险：当前是预设指标卡，不是完整公式编辑器。后续如果用户需要“按字段自定义计算公式”，应作为单独高风险设计包推进，并明确计算来源、权限、迁移和回滚。

## 迁移说明

无数据库迁移。既有项目没有选择指标时保持现有默认行为；用户在字段图中选择指标后，会通过已有 `work_item_schema.dashboard_metrics` 保存路径保存。

## 回滚建议

如需回滚本包：

1. 移除 `FieldGraphDesigner.vue` 中 `DashboardMetricForm`、预设卡、选择逻辑和指标编辑面板。
2. 移除 `ProjectsView.vue` 中 `dashboard-metrics` 传参、`update-dashboard-metrics` 监听和两个更新处理函数。
3. 删除 `scripts/verify_vue_dashboard_metrics_field_graph_editor.js`。
4. 删除本报告和对应计划文档记录。

无生产数据回滚要求。
