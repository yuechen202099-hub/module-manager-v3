# PM 平台审阅深链 Vue 兜底报告

## 摘要

本包修复一个本地平台入口问题：从浏览器地址栏或消息链接直接打开 `/review/:groupId` 时，后端原本返回 `404`，现在会返回 Vue 生产外壳，由前端路由继续加载审阅详情页。

同时按用户最新提醒复核了设备更换层级规则：换模块属于“任务对象下更换附属设备”；换终端属于“主设备更换后确认附属设备是否更换”。现有字段图谱、后端就绪检查和拖拽规则均已覆盖该模型。

## 基线

- 生产基线分支：`production/V3/3.0.77`
- 生产基线提交：`4c05cc9`
- 平台开发分支：`pm-platform/production-3.0.77-sync`
- 当前本地 HEAD：`6892205`

## 修改文件

- `v2-api/app/main.py`
- `v2-api/tests/test_api.py`
- `docs/superpowers/plans/2026-07-03-review-deep-link-spa-fallback.md`
- `docs/reports/pm-platform-review-deep-link-spa-fallback-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

## 功能说明

- 新增后端显式路由 `/review/{group_id}`，返回 `v2-api/app/static/vue/index.html`。
- 不新增宽泛 catch-all，不接管 `/api`、`/static`、`/vue/assets`、`/docs` 等路径。
- 保持前端 Vue Router 的 `review/:groupId` 为实际页面解析来源。
- 保持既有 `/task-hall`、`/construction`、`/project-board` 等入口行为不变。
- 设备更换层级规则本轮不另改模型，仅验证当前平台已经按“换模块/换终端”两种业务语义区分。

## 验证

- 红灯确认：
  - `python -m pytest v2-api\tests\test_api.py::test_review_detail_deep_link_serves_vue_shell -q`
  - 失败原因：`404 Not Found`
- 修复后通过：
  - `python -m pytest v2-api\tests\test_api.py::test_review_detail_deep_link_serves_vue_shell -q`
  - 结果：`1 passed`
- 相邻入口回归：
  - `python -m pytest v2-api\tests\test_api.py::test_direct_workspace_routes_redirect_to_app_shell v2-api\tests\test_api.py::test_task_hall_page_is_available v2-api\tests\test_api.py::test_construction_page_is_available -q`
  - 结果：`3 passed`
- 设备层级规则验证：
  - `node scripts\verify_vue_device_replacement_hierarchy_mode.js`
  - `python scripts\verify_platform_device_replacement_hierarchy_mode.py`
  - `python scripts\verify_platform_device_relation_roles.py`
  - `node scripts\verify_vue_field_graph_smart_drop.js`
  - 结果：全部 `[OK]`
- Vue 迁移入口守卫：
  - `python scripts\verify_vue_migration_gate.py --strict-native`
  - 结果：`[OK] Vue shell and static page registry are wired.`
- 团队记忆守卫：
  - `python scripts\verify_pm_platform_team_operating_model.py`
  - 结果：`[OK] PM platform team operating model is locked`
- 浏览器冒烟：
  - 已重启本地 `0.0.0.0:52131` uvicorn 服务。
  - 新标签页打开 `http://127.0.0.1:52131/review/g-001?project_id=draft-project`。
  - 页面加载 `Module Manager V3.0.77` Vue 应用，`#app` 存在，`ReviewView` 资产加载，页面不是 `{"detail":"Not Found"}`。
  - 按当前页面资产过滤后，相关控制台错误数为 `0`。
- 安全检查：
  - `git diff --check` 无输出。
  - git 状态敏感路径扫描未发现 `.env`、`data`、`uploads`、dump、压缩包或密钥文件。

## 风险

低风险。此包只增加一个 Vue 深链入口，不修改数据库结构、不写 OSS、不改生产数据、不改 `.env`、不创建 tag、不发布服务器、不占用正式生产版本号。

## 迁移说明

无数据库迁移。旧链接无需转换；此前 404 的 `/review/:groupId` 链接在前端包存在时会直接加载 Vue 应用。

## 回滚建议

如需回滚，删除 `v2-api/app/main.py` 中的 `/review/{group_id}` 路由和 `test_review_detail_deep_link_serves_vue_shell` 测试，并移除本报告和计划记录。无数据回滚要求。
