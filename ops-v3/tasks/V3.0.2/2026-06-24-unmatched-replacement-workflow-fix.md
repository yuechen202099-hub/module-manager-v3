# 未匹配清单换表流程修复

- 状态：已发布
- 日期：2026-06-24
- 规则版本：Rules v1
- 应用基线：V3.0.2
- 目标版本：V3.0.6

## 需求

修复未匹配清单与换表按钮相关问题：

- 导入时有图的未匹配记录，进入未匹配清单后也要显示照片数。
- 未匹配清单支持人工删除记录。
- 未匹配记录完成换表后，下次导入同一记录不应再次出现在未匹配清单。
- 换表完成后，当前未匹配记录的数据要进入绑定终端资料组；资料组应进入已采集/异常等可处理状态，不停留为未施工。

## 原因

PostgreSQL 未匹配列表 payload 只读取 `photo_urls/images`，漏掉扫码导入常用的 `image_urls` 字段，导致有图记录显示为 0 图。导入未匹配去重只看 `legacy_id`，同一换表记录在新批次或行号变化后可能重新回流。项目看板已有删除接口但未暴露人工删除按钮。

## 修改文件

- `v2-api/app/api/routes/local_test.py`
- `v2-api/app/services/state_repository.py`
- `v2-api/tests/test_state_repository.py`
- `v2-web/src/views/ProjectBoardView.vue`
- `scripts/verify_unmatched_replacement_workflow.py`
- 版本号相关文件：`v2-api/app/main.py`、`v2-api/app/services/ops_status.py`、`v2-api/pyproject.toml`、`v2-api/tests/test_api.py`、`v2-web/package.json`、`v2-web/index.html`、`v2-web/src/components/AppLayout.vue`、`v2-web/src/layouts/AppLayout.vue`、`v2-web/src/views/LoginView.vue`

## 影响范围

- 项目看板“扫码未匹配”弹窗。
- PostgreSQL 后端扫码导入未匹配记录生成逻辑。
- PostgreSQL 未匹配记录 payload 展示口径。
- 不涉及数据库结构变更，不执行 Alembic，不覆盖 `.env`、`data`、`uploads`、OSS 或 PostgreSQL 生产数据。

## 验证结果

- `python scripts\verify_unmatched_replacement_workflow.py`：通过；新增检查在改动前已按预期失败。
- `python scripts\verify_project_board_exception_merge.py`：通过。
- `python -m py_compile v2-api\app\api\routes\local_test.py v2-api\app\services\state_repository.py v2-api\app\main.py v2-api\app\services\ops_status.py`：通过。
- `python -m pytest tests\test_state_repository.py -q`：11 passed；新增两条回归在改动前已按预期失败。
- `python -m pytest tests\test_api.py tests\test_local_simulation.py tests\test_state_repository.py`：104 passed，1 个 Starlette/httpx deprecation warning。
- `python scripts\verify_vue_migration_gate.py`：通过。
- `npm run build`：通过，已重新生成 `v2-api/app/static/vue` 静态资源。
- `python scripts\verify-static-pages.py`：通过。
- `git diff --check`：通过，仅有 Git LF/CRLF 工作区提示。
- `rg "3\.0\.5|V3\.0\.5" ...`：版本相关文件和 Vue 静态产物无旧版本残留。

## 生产发布结果

- 提交/标签：`ce9b0e4` / `v3.0.6`。
- 服务器：`106.14.122.43`。
- 发布目录：`/opt/module-manager-v2/releases/v3.0.2-20260624_000900-b353ce2`（`/opt/module-manager-v2/current` 指向该目录）。
- 发布前备份：`/opt/module-manager-v2/backups/runtime/20260624-025824`。
- 生产保护：未覆盖 `.env`，未覆盖 `/opt/module-manager-v2/data`，未覆盖 `v2-api/app/static/uploads`。
- 服务：`module-manager-v2.service` 重启后为 `active`。
- 发布后健康检查：磁盘 27%，service/nginx active，最近备份为本次备份。
- 页面检查：`/health`、`/login`、`/project-board`、`/task-hall`、`/construction` 返回 200；`/openapi.json` 返回预期 404。
- 线上版本确认：`/vue/index.html` 标题为 `Module Manager V3.0.6`。
- 线上功能确认：`ProjectBoardView-CFnyTvCx.js` 包含“删除未匹配记录”；后端生产代码包含 `image_urls` payload 兼容和 `existing_unmatched_keys` 导入回流保护。

## 风险/回滚

- 风险：同一未匹配记录被人工删除、项目外处理或换表关联后，再次导入会被视为已处理并跳过回流；如确需重新处理，需要新增不同表号/扫码内容或手工创建。
- 回滚：恢复本次代码提交并重新构建/发布 V3.0.5 静态资源与后端代码。
