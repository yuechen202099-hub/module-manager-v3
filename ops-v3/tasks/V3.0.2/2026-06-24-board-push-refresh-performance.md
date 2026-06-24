# 看板推送刷新与任务领取加载加速

- 状态：已发布
- 日期：2026-06-24
- 规则版本：Rules v1
- 应用基线：V3.0.2
- 目标版本：V3.0.8

## 需求

项目看板页面改为每 15 分钟由服务器推送刷新到前端，减少前端频繁主动加载；任务领取页在没有新总清单或任务状态变化时不再每次加载完整终端数量和地址清单，只加载清单状态；继续加速每个标签页打开速度。

## 原因

- 项目看板首屏只需要终端聚合态势，却会拉取完整 `/local-test/tasks`，其中包含较长的地址搜索文本。
- 任务领取页原来每 10 秒调度一次完整任务列表刷新，会重复计算终端数量和地址搜索字段。
- 管理员进入看板和任务领取页时会自动加载账号列表，该数据不属于首屏关键路径。

## 修改文件

- `v2-api/app/api/routes/local_test.py`
- `v2-api/app/services/local_simulation.py`
- `v2-api/app/services/state_repository.py`
- `v2-api/tests/test_api.py`
- `v2-web/src/api/services.ts`
- `v2-web/src/api/types.ts`
- `v2-web/src/views/ProjectBoardView.vue`
- `v2-web/src/views/ClaimTasksView.vue`
- `scripts/verify_board_refresh_performance.py`
- `v2-web/package.json`
- `v2-web/index.html`
- `v2-api/app/main.py`
- `v2-api/app/services/ops_status.py`
- `v2-api/pyproject.toml`

## 影响范围

- 新增 `/local-test/events` SSE 推送接口，每 15 分钟发送 `board-refresh`；前端使用带认证头的流式 `fetch` 订阅，断线或不支持流式读取时退回 15 分钟轮询。
- 新增 `/local-test/tasks/status` 轻量接口，返回任务版本和聚合数量，不返回地址搜索全文。
- 项目看板首屏改为 `summary + tasks/status`，不再加载完整任务列表。
- 任务领取页首屏先恢复会话缓存，再请求轻量状态；版本不变时不再拉完整 `/tasks`。
- 管理员账号列表改为按需加载：看板异常弹窗或任务领取指派弹窗打开时再加载。

## 验证结果

- `.venv\Scripts\python.exe -m py_compile ...`：通过。
- `.venv\Scripts\python.exe scripts\verify_board_refresh_performance.py`：通过。
- `.venv\Scripts\python.exe scripts\verify_vue_migration_gate.py`：通过。
- `.venv\Scripts\python.exe scripts\verify-static-pages.py`：通过。
- `v2-web\node_modules\.bin\vue-tsc.cmd --noEmit`：通过。
- `v2-web\node_modules\.bin\vite.cmd build`：通过。
- `.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py`：46 passed，1 个 Starlette/httpx2 迁移警告。
- Browser 烟测：
  - `http://127.0.0.1:8020/project-board?qa=v308-board-single`：V3.0.8 渲染，项目驾驶舱和终端总数可见，控制台无 error/warn，无 `Invalid access token`。
  - `http://127.0.0.1:8020/claim-tasks?qa=v308-claim-single`：V3.0.8 渲染，任务领取和终端任务可见，控制台无 error/warn，无 `Invalid access token`。
- `git diff --check`：通过。
- 发布：
  - 提交/标签：`1c8dcd2` / `v3.0.8`。
  - 生产 release：`/opt/module-manager-v2/releases/v3.0.8-20260624_121441-1c8dcd2`。
  - 生产备份：`/opt/module-manager-v2/backups/runtime/20260624-121441-v3.0.8`，记录上一版 `/opt/module-manager-v2/releases/v3.0.7-20260624_114155-eba4a02`。
  - 生产检查：`/health` ok，`/project-board` 200，`/claim-tasks` 200，`/vue/index.html` 200 且标题为 `Module Manager V3.0.8`；`module-manager-v2.service` 与 `nginx` 均 active。

## 风险/回滚

- 风险：浏览器或代理不支持长连接时，项目看板会退回 15 分钟轮询；不会影响手动刷新。
- 风险：任务领取页使用会话缓存首屏展示，若状态接口异常且缓存存在，页面会保留旧列表并提示状态加载失败。
- 回滚：回退 V3.0.8 提交并恢复 V3.0.7 静态包；生产发布前保留服务器备份，可切回上一 release 并重启 `module-manager-v2.service`。
