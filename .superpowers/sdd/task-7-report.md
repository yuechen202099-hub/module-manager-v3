# Task 7 Report: 移除旧业务导出入口并完成任务派发 UI

## 需求

- 按 TDD 新增单入口 verifier，阻断旧业务导出入口回流。
- 旧业务导出入口只保留 `导出中心 /exports`；导入模板下载保留，批量归档保留。
- 任务派发可见入口不再出现“任务领取 / 任务大厅 / 审阅工作台”语义。
- 任务派发页只保留施工派发相关动作，旧路由重定向继续保留。

## 修改文件

### 前端源码

- `v2-web/src/views/ClaimTasksView.vue`
- `v2-web/src/views/TaskHallView.vue`
- `v2-web/src/layouts/AppLayout.vue`
- `v2-web/src/router/index.ts`
- `v2-web/src/router/staticPages.ts`

### 验证脚本

- `scripts/verify_v3_2_0_single_export_entry.py`

### 生产静态构建产物

- `v2-api/app/static/vue/index.html`
- `v2-api/app/static/vue/version.json`
- `v2-api/app/static/vue/assets/*` 中本次 `vite build` 重新生成的 hash 产物

## 实现结果

- `ClaimTasksView` 改为真正的“任务派发”页，只保留施工派发、改派、优先施工、已施工链路。
- `ClaimTasksView` 移除了旧审阅领取/释放、旧导出终端包、旧导出明细、旧导出范围和旧全局导出消息通道。
- `TaskHallView` 移除了“导出项目外施工 / 导出异常表计”按钮与 handler。
- `AppLayout` 移除了旧 `module-manager:start-terminal-export` 入口和 `exportTerminalDeliveryPackage` 壳层调度。
- `staticPages` 将可见入口整理为：
  - `claim-tasks` -> `任务派发`
  - `global-search` -> `数据中台`
  - `exports` -> `导出中心`
- `task-hall` 保留 registry key 以通过迁移门禁，但不再作为可见入口；真实旧地址 `/task-hall` 继续重定向到 `/claim-tasks`。
- `review/:groupId` 旧跳转仍保留，继续导向 `/global-search`。

## RED

命令：

```powershell
python scripts\verify_v3_2_0_single_export_entry.py
```

结果：

- 首次执行于 2026-07-23 报红，失败点为 `staticPages` 仍未把 `/global-search` 明确为 `数据中台`，证明 verifier 已经覆盖到目标边界。

## GREEN

命令：

```powershell
python scripts\verify_v3_2_0_single_export_entry.py
python scripts\verify_v3_2_0_dashboard_drilldown.py
python scripts\verify_v3_2_0_data_center_ui.py
python scripts\verify_v3_2_0_export_center_ui.py
python scripts\verify_v3_2_0_role_routes.py
python scripts\verify_vue_migration_gate.py
cd v2-web
npx vue-tsc --noEmit
npm run build
```

结果：

- `verify_v3_2_0_single_export_entry.py`: 通过。
- `verify_v3_2_0_dashboard_drilldown.py`: 通过，`[OK] V3.2.0 dashboard drilldown checks passed`。
- `verify_v3_2_0_data_center_ui.py`: 通过（exit 0，无 stderr）。
- `verify_v3_2_0_export_center_ui.py`: 通过，`verify_v3_2_0_export_center_ui: OK`。
- `verify_v3_2_0_role_routes.py`: 通过，`[OK] V3.2.0 role and legacy route checks passed`。
- `verify_vue_migration_gate.py`: 通过，`[OK] Vue shell and static page registry are wired.`。
- `npx vue-tsc --noEmit`: 通过。
- `npm run build`: 通过；其中再次执行了 `vue-tsc --noEmit && vite build`。

## 版本变化

- 未修改应用版本号。
- 未修改 `APP_VERSION`、`package.json` 版本号或生产 release 记录。

## 发布状态

- 代码与生产静态构建产物已完成本地验证。
- 尚未发布。

## 风险

- `vite build` 仍有既有警告：
  - VueUse `/* #__PURE__ */` 注释位置警告。
  - 500 kB 以上 chunk 警告。
- 这些警告在 2026-07-23 的本次构建中仍存在，但不影响 `vue-tsc` 和 `vite build` 成功退出。
- `task-hall` 作为迁移 registry 兼容 key 仍保留；当前真实旧地址通过路由重定向进入 `claim-tasks`，后续如果迁移门禁规则调整，可再评估是否完全移除该 key。
