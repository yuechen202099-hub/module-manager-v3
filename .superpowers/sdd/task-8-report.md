# V3.2.0 Task 8 报告

- 日期：2026-07-24
- 分支：`production/V3/3.2.0`
- 基线 HEAD：`20e04fe`
- 任务：版本面、发布门禁与正式 Vue 构建产物
- 结论：`DONE_WITH_CONCERNS`

## 需求

- 使用 TDD，先新增并运行失败的 `scripts/verify_v3_2_0_release.py`。
- 将正式版本统一到 `3.2.0` / `V3.2.0`。
- 中文更新内容包含数据中台统一审阅、驾驶舱下钻、统一导出中心、审阅员角色下线，以及所有相关分页默认 20、可选 20/50/100。
- 将 V3.2.0 新脚本、组件、schema、service、迁移和发布记录纳入打包与验包门禁。
- 生成并提交最终 `v2-api/app/static/vue` 正式构建产物，不恢复 Task Hall。
- 保留生产、平台、小程序三线协作规则，并补充数据中台与导出中心维护入口。

## RED

首次执行：

```powershell
python scripts\verify_v3_2_0_release.py
```

结果为 exit 1。失败覆盖旧 `3.1.1` 版本面、缺失 V3.2.0 发布记录、缺失新打包必需文件、新门禁未接入，以及静态 `version.json`、HTML 标题和资源仍为 V3.1.1。

## 修改

### 版本与更新内容

- 对齐 Vue package/source version、HTML 标题、FastAPI、ops status、API pyproject、兼容布局和正式交付文件名。
- 新增 V3.2.0 中文更新内容，五项要求均使用明确文案。
- 更新 `README.md`、验收/审计/签收文档中的当前候选打包命令与包路径。

### 发布与打包门禁

- 新增 `scripts/verify_v3_2_0_release.py`，覆盖版本面、迁移、路由、退役页面、发布记录、打包接线和正式静态产物。
- `scripts/build-client-release.ps1` 在打包前运行六个 V3.2.0 门禁，并显式校验、复制新发布输入。
- `scripts/verify-client-release.py` 要求新脚本、组件、composable、schema、service、路由、迁移和发布记录。
- 验包禁止 `.env`、data、uploads、node_modules、缓存、数据库、日志、coverage 和测试结果文件。
- `scripts/verify_release_sop.py` 与测试同步到 V3.2.0 候选生命周期。

### 发布记录与协作规则

- 新增 `ops/releases/V3.2.0.md`，记录 V3.1.1 基线、迁移、权限、备份、rollback、健康路由、专项/完整验证命令和 `PENDING_TASK_9` 证据字段。
- `AGENTS.md` 保持生产、项目平台、小程序三线版本规则，明确 codebase-memory-mcp 顺序、工具/skill 必读要求和数据中台/导出中心维护入口。
- 部署基线继续为 `V3.1.1`，发布候选更新为 `V3.2.0`。

### 正式构建产物

- `npm run build` 直接重建 `v2-api/app/static/vue`。
- `version.json` 版本为 `3.2.0`，HTML 标题为 `Module Manager V3.2.0`。
- 新 hash 资源包含 V3.2.0 中文更新内容。
- 旧 `TaskHallView`、`ReviewView` 和 Task Hall 静态资源未生成。

## 验证

按 brief 执行并通过：

```powershell
python scripts\verify_v3_2_0_role_routes.py
python scripts\verify_v3_2_0_data_center_ui.py
python scripts\verify_v3_2_0_dashboard_drilldown.py
python scripts\verify_v3_2_0_export_center_ui.py
python scripts\verify_v3_2_0_single_export_entry.py
python scripts\verify_v3_2_0_release.py
python scripts\test_verify_release_sop.py
```

- 六个 V3.2.0 专项门禁通过。
- SOP 测试：`283 passed`。
- `npm run type-check`：通过。
- `npm run build`：通过，`1679 modules transformed`。

追加验证：

- `python -m pytest scripts/test_verify_client_release.py -q`：`210 passed`，1 条测试构造重复 ZIP entry 的预期 warning。
- `.\.venv\Scripts\python.exe -m pytest v2-api/tests/test_v3_1_release.py -q`：`37 passed`。
- 版本状态与交付文件名聚焦 API 测试：`2 passed, 202 deselected`，1 条既有 Starlette/httpx deprecation warning。
- `node scripts/verify_admin_release_notes.js`：通过。
- `python scripts/verify_release_sop.py --version V3.2.0`：通过。

## 发布状态

- Task 8 本地版本、门禁和正式静态产物完成。
- 未生成最终服务器 ZIP，未填写真实 SHA256、备份目录、release 目录或线上健康证据。
- 未执行生产迁移、切换或数据写入。

## Concerns

- Task 9 仍需执行完整后端 pytest、独立全分支复审、正式打包验包、SHA256、生产备份、迁移、切换和线上验收。
- Vite 构建保留既有 VueUse `/* #__PURE__ */` 注释 warning 与大于 500 kB chunk warning；构建成功，未发现本任务新增阻断。
- 聚焦 API 测试保留既有 Starlette/httpx deprecation warning。
