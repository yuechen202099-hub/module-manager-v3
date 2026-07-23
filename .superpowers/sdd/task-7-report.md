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

## 2026-07-23 审阅修复追加

本节覆盖上文里已经过时的 `task-hall registry` 说明。

### 修复内容

- 完全移除了 `staticPages` 中的 `task-hall` registry key。
- 完全移除了前端 router `nativePageComponents` 对 `TaskHallView.vue` 的动态 import。
- 保留且仅保留显式旧地址重定向：`/task-hall -> /global-search`。
- `ClaimTasksView.vue` 恢复任务列表请求世代保护：
  - load 请求经 `createMutationGuardedRequestGate()` 分配独立 serial 与 `AbortController`；
  - load 开始时记录当前 `taskMutationVersion`；
  - 仅当请求仍是最新且 `taskMutationVersion` 未变化时才允许覆盖 `tasks`；
  - 指派施工、改派施工、优先施工、批量优先导入成功后都会递增 `taskMutationVersion` 并使在途 load 失效。
- `claimTasksState.mjs/.d.mts` 仅保留生产真实引用的 `priorityRequestBody()`。
- `verify_v3_2_0_single_export_entry.py` 升级为递归扫描 `v2-web/src/**/*.vue`：
  - 业务导出 API / 业务导出按钮只允许 `v2-web/src/views/ExportsView.vue`；
  - `downloadConstructionPriorityTemplate` 仅允许 `ConstructionPriorityImportDialog.vue`；
  - 同时断言无 `task-hall-legacy`、无旧审阅文案泄漏到任务派发页与活动路由注册面。

### 新增/更新测试

- `scripts/test_latest_request_gate.mjs`
- `scripts/test_claim_tasks_state.mjs`
- `scripts/verify_claim_tasks_load_guard.js`
- `scripts/verify_v3_2_0_single_export_entry.py`
- `scripts/verify_v3_2_0_role_routes.py`
- `scripts/verify_vue_migration_gate.py`

### 本轮验证

已于 2026-07-23 重新执行并通过：

```powershell
python scripts\verify_v3_2_0_single_export_entry.py
python scripts\verify_v3_2_0_role_routes.py
python scripts\verify_vue_migration_gate.py --strict-native
python scripts\verify_v3_2_0_dashboard_drilldown.py
python scripts\verify_v3_2_0_data_center_ui.py
python scripts\verify_v3_2_0_export_center_ui.py
node scripts\test_latest_request_gate.mjs
node scripts\test_claim_tasks_state.mjs
node scripts\verify_claim_tasks_load_guard.js
cd v2-web
npx vue-tsc --noEmit
$env:MODULE_MANAGER_VUE_OUT_DIR='C:\Users\Administrator\AppData\Local\Temp\module-manager-v3-task7-build'; npm run build
git diff --name-only 61a7025..HEAD -- v2-api/app/static/vue
```

结果：

- 所有 verifier / node 测试 / `vue-tsc` / build 均通过。
- build 使用隔离 outDir，未改动 `v2-api/app/static/vue`。
- `git diff --name-only 61a7025..HEAD -- v2-api/app/static/vue` 输出为空。

## 2026-07-24 独立复审缺口修复追加

### 修复结果

- 删除死的 `TaskHallView.vue` 审阅工作台和 `task_hall.html` 静态兼容页。
- 保留 `/task-hall -> /global-search`、`/review/:groupId -> /global-search?group_id=:groupId&page=1&page_size=20&review=1`，并继续保留 `/tasks -> /claim-tasks`。
- 从静态页、迁移、烟测、发布包和接受门禁中移除已删除页面/verifier；共享数据中台审阅组件未删除。
- 单入口 verifier 递归检查集合新增 `exportTerminalDeliveryPackage`，不再读取 `TaskHallView.vue`，并断言两个死文件不存在。
- 数据中台、终端交付列表和导出任务列表的静态门禁明确锁定：默认 20、可选值恰为 20/50/100、不支持的 URL page size 回退到 20。
- `v2-web/package.json` 新增 `type-check` 脚本，映射到既有 `vue-tsc --noEmit`。

### Changed files

- `.superpowers/sdd/task-7-report.md`
- `scripts/build-client-release.ps1`
- `scripts/run-client-acceptance-gate.ps1`
- `scripts/smoke-client-demo.py`
- `scripts/test_verify_client_release.py`
- `scripts/verify-client-release.py`
- `scripts/verify-static-pages.py`
- `scripts/verify_v3_2_0_data_center_ui.py`
- `scripts/verify_v3_2_0_export_center_ui.py`
- `scripts/verify_v3_2_0_single_export_entry.py`
- `scripts/verify_vue_migration_gate.py`
- `v2-api/tests/test_api.py`
- `v2-web/package.json`
- 删除 `scripts/verify_task_hall_pagination.js`
- 删除 `scripts/verify_task_hall_region_scan.js`
- 删除 `scripts/verify_v3_1_barcode_views.js`
- 删除 `v2-api/app/static/task_hall.html`
- 删除 `v2-web/src/views/TaskHallView.vue`

### RED 证据

- `python scripts\verify_v3_2_0_single_export_entry.py`：先失败于 `AssertionError: obsolete TaskHallView.vue must be deleted`。
- `npm run type-check`：先失败于 `Missing script: "type-check"`。

### Required verification

```powershell
python scripts\verify_v3_2_0_single_export_entry.py
python scripts\verify_v3_2_0_role_routes.py
python scripts\verify_v3_2_0_data_center_ui.py
python scripts\verify_v3_2_0_export_center_ui.py
python scripts\verify_vue_migration_gate.py --strict-native
cd v2-api
python -m pytest tests/test_api.py -k "task_hall_page or app_shell_page or global_search_page or unmatched_page_redirects" -q
cd ..\v2-web
npm run type-check
npm run build
```

结果：

- `verify_v3_2_0_single_export_entry.py`：通过，`verify_v3_2_0_single_export_entry: OK`。
- `verify_v3_2_0_role_routes.py`：通过，`[OK] V3.2.0 role and legacy route checks passed`。
- `verify_v3_2_0_data_center_ui.py`：通过，exit 0。
- `verify_v3_2_0_export_center_ui.py`：通过，`verify_v3_2_0_export_center_ui: OK`。
- `verify_vue_migration_gate.py --strict-native`：通过；7 个注册页面，0 个 legacy bridge 页面。
- 聚焦 backend pytest：项目 `.venv` 中按上述命令通过，`4 passed, 200 deselected`；有 1 条既有 Starlette/httpx deprecation warning。系统 Python 首次收集因缺少 `fastapi` 失败，切换项目 `.venv` 后通过。
- `npm run type-check`：通过。
- `npm run build`：通过，1679 modules transformed；保留既有 VueUse `/* #__PURE__ */` 和大于 500 kB chunk 警告。
- build 后执行 `git restore --worktree -- v2-api/app/static/vue`，并只清理该目录中新生成的未跟踪 hash 文件；`git status --short -- v2-api/app/static/vue` 输出为空，`git diff --exit-code -- v2-api/app/static/vue` exit 0。

### Additional verification

- `python -m pytest scripts\test_verify_client_release.py -q`：`208 passed`，1 条测试构造重复 zip entry 的预期 warning。
- `python scripts\verify-static-pages.py`：保留的 5 个静态页全部通过。
- `git diff --check`：通过，仅输出工作树既有 LF/CRLF 转换提示。

### Concerns

- 无阻断项。
- build 和测试仍有上述既有 warning；本次未修改依赖或 chunk 拆分。
