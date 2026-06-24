# 按钮整合与页面首屏加载优化

- 状态：已验证，待发布
- 日期：2026-06-24
- 规则版本：Rules v1
- 应用基线：V3.0.2
- 目标版本：V3.0.7

## 需求

用户反馈任务卡片和审阅页底部按钮太多、太乱，并且每个页面打开加载时间太长。

## 原因

- 任务领取卡片同时平铺导出、范围选择、指派、释放、领取、审阅等操作，低频操作挤占主动作区域。
- 审阅工作台底部同时平铺保存、补图、状态回退、异常、删除、归档、导出等操作，危险动作容易误触。
- 审阅页首屏在加载终端任务时同步触发未匹配/异常施工任务清单加载；全局布局挂载时为了顶部工程名调用全量 `workspace.bootstrap()`，额外拉取任务和资料组。

## 修改文件

- `v2-web/src/views/ClaimTasksView.vue`
- `v2-web/src/views/TaskHallView.vue`
- `v2-web/src/layouts/AppLayout.vue`
- `v2-web/src/stores/workspace.ts`
- `v2-web/src/styles/main.css`
- `scripts/verify_action_consolidation_performance.py`
- `v2-web/package.json`
- `v2-web/index.html`
- `v2-web/src/components/AppLayout.vue`
- `v2-web/src/views/LoginView.vue`
- `v2-api/app/main.py`
- `v2-api/app/services/ops_status.py`
- `v2-api/pyproject.toml`
- `v2-api/tests/test_api.py`
- `v2-api/app/static/vue/**`

## 影响范围

- `/claim-tasks`：卡片主操作保留领取/进入审阅；管理员导出、指派、暂存释放、导出范围切换收进“更多”菜单。
- `/task-hall`：底部主操作保留保存资料组、补图、归档资料组、Enter 归档当前图；恢复待审、回退未施工、转异常工单、删除当前图、导出异常表计收进“更多”菜单。
- `/task-hall` 首屏：终端审阅模式不再立即拉取未匹配和异常任务清单，切换到对应模式时强制刷新。
- 全局布局：页面挂载只加载项目摘要，不再为顶部工程名全量拉取任务和资料组。

## 验证结果

- `python -m py_compile v2-api/app/main.py v2-api/app/services/ops_status.py scripts/verify_action_consolidation_performance.py`：通过。
- `python scripts/verify_action_consolidation_performance.py`：通过。
- `python scripts/verify_vue_migration_gate.py`：通过。
- `npm run build`：通过。
- `python scripts/verify-static-pages.py`：通过。
- `python -m pytest v2-api/tests/test_api.py`：46 passed，1 个第三方 deprecation warning。
- Browser 渲染检查：
  - `http://127.0.0.1:8020/claim-tasks?qa=v307`：V3.0.7 渲染，卡片“更多”菜单包含导出终端包、导出明细、改派施工、暂存释放、导出范围切换，控制台无错误。
  - `http://127.0.0.1:8020/task-hall?qa=v307`：V3.0.7 渲染，危险动作未平铺，“更多”菜单包含恢复待审、回退未施工、转异常工单、删除当前图、导出异常表计，控制台无错误。
- `git diff --check`：通过。

## 风险/回滚

- 风险：低。此次主要是前端操作层级和首屏加载策略调整，不改数据库结构，不改导入/导出后端数据语义。
- 回滚：回退 V3.0.7 提交并恢复上一版静态包；生产发布前保留服务器备份，可切回备份目录并重启 `module-manager-v2.service`。
