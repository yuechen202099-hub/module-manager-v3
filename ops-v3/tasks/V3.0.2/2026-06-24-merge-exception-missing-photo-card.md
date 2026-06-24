# 项目看板合并异常与缺照卡片

- 状态：已发布
- 日期：2026-06-24
- 规则版本：Rules v1
- 应用基线：V3.0.2
- 目标版本：V3.0.5

## 需求

项目看板的项目进度区，将“异常资料组”和“缺照片”两个入口合并为一个入口。

## 原因

缺照记录已经纳入异常处理清单，拆成两个卡片会让同一类待复核/补采事项在看板上重复占位。

## 修改文件

- `v2-web/src/views/ProjectBoardView.vue`
- `scripts/verify_project_board_exception_merge.py`
- 版本号相关文件：`v2-api/app/main.py`、`v2-api/app/services/ops_status.py`、`v2-api/pyproject.toml`、`v2-api/tests/test_api.py`、`v2-web/package.json`、`v2-web/index.html`、`v2-web/src/components/AppLayout.vue`、`v2-web/src/layouts/AppLayout.vue`、`v2-web/src/views/LoginView.vue`

## 影响范围

- 项目看板顶部指标和项目进度风险卡片。
- 异常处理弹窗标题、统计标签、导出文件名和派发备注文案。
- 不涉及数据库结构、生产数据、`.env`、`data`、`uploads`、OSS 或 PostgreSQL 数据写入。

## 验证结果

- `python scripts\verify_project_board_exception_merge.py`：通过；新增检查在改动前已按预期失败。
- `python -m py_compile v2-api\app\main.py v2-api\app\services\ops_status.py`：通过。
- `python scripts\verify_vue_migration_gate.py`：通过。
- `npm run build`：通过，已重新生成 `v2-api/app/static/vue` 静态资源。
- `python scripts\verify-static-pages.py`：通过。
- `C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests\test_api.py`：46 passed，1 个 Starlette/httpx deprecation warning。
- `git diff --check`：通过，仅有 Git LF/CRLF 工作区提示。
- `rg "3\.0\.4|V3\.0\.4" ...`：版本相关文件和 Vue 静态产物无旧版本残留。

## 生产发布结果

- 提交/标签：`7c21885` / `v3.0.5`。
- 服务器：`106.14.122.43`。
- 发布目录：`/opt/module-manager-v2/releases/v3.0.2-20260624_000900-b353ce2`（`/opt/module-manager-v2/current` 指向该目录）。
- 发布前备份：`/opt/module-manager-v2/backups/runtime/20260624-023942`。
- 生产保护：未覆盖 `.env`，未覆盖 `/opt/module-manager-v2/data`，未覆盖 `v2-api/app/static/uploads`。
- 服务：`module-manager-v2.service` 重启后为 `active`。
- 发布后健康检查：磁盘 27%，service/nginx active，最近备份为本次备份。
- 页面检查：`/health`、`/login`、`/project-board`、`/task-hall`、`/construction` 返回 200；`/openapi.json` 返回预期 404。
- 线上版本确认：`/vue/index.html` 标题为 `Module Manager V3.0.5`。
- 线上功能确认：`ProjectBoardView-CT6STBqQ.js` 包含“异常与缺照”，不再包含“缺照片”单独文本。

## 风险/回滚

- 风险：仅前端展示合并，后端接口口径不变；主要风险是用户对合并数字口径理解差异。
- 回滚：恢复 `ProjectBoardView.vue` 中单独“异常资料组”“缺照片”卡片，并回退版本号到上一发布版本。
