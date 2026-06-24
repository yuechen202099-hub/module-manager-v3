# 项目看板换表清单

- 状态：已发布
- 日期：2026-06-24
- 规则版本：Rules v1
- 应用基线：V3.0.3
- 目标版本：V3.0.4

## 需求

在项目看板增加“换表清单”，用于查看人工换表后已经通过旧表号匹配到总清单资料组的记录。

## 原因

V3.0.3 已支持在未匹配资料中输入旧表号完成换表匹配，并在交付资料包备注旧表号。现场还需要一个集中清单，便于管理员查看这些人工换表匹配记录。

## 修改文件

- `v2-api/app/services/local_simulation.py`
- `v2-api/app/services/state_repository.py`
- `v2-api/app/api/routes/local_test.py`
- `v2-api/tests/test_local_simulation.py`
- `v2-api/tests/test_state_repository.py`
- `v2-web/src/api/types.ts`
- `v2-web/src/api/services.ts`
- `v2-web/src/views/ProjectBoardView.vue`
- 版本号相关文件

## 影响范围

- 新增只读接口 `/local-test/replacements`。
- 项目看板新增“换表清单”入口和弹窗。
- 不新增数据库表，不执行 Alembic，不直接修改生产数据。
- 应用版本从 V3.0.3 升级到 V3.0.4。

## 验证结果

- `python -m pytest v2-api\tests\test_local_simulation.py::test_list_replacement_records_includes_matched_manual_replacements v2-api\tests\test_local_simulation.py::test_replacement_rematch_adds_delivery_export_remark v2-api\tests\test_state_repository.py::test_json_state_repository_delegates_core_task_operations v2-api\tests\test_api.py::test_system_status_requires_admin_and_reports_runtime_state -q`：通过，4 passed。
- `python -m py_compile v2-api\app\services\state_repository.py v2-api\app\services\local_simulation.py v2-api\app\api\routes\local_test.py v2-api\app\main.py`：通过。
- `python scripts\verify_vue_migration_gate.py`：通过。
- `python scripts\verify-static-pages.py`：通过。
- `vue-tsc --noEmit`：通过。
- `vite build`：通过，已刷新 `v2-api/app/static/vue/` 生产静态资源。
- `git diff --check`：通过。
- `rg "V3\.0\.3|3\.0\.3" v2-api v2-web`：无残留应用版本标识。

## 生产发布

- 发布时间：2026-06-24
- 提交/标签：`b3f7cfc` / `v3.0.4`
- 发布方式：patch sync 到 `106.14.122.43:/opt/module-manager-v2/current`，仅同步本次变更源码、文档和 `v2-api/app/static/vue/` 构建产物；未覆盖生产 `.env`、`data`、`uploads`。
- 生产备份：`/opt/module-manager-v2/backups/runtime/20260624-011733`
- 备份内容：`local_state.json`、`users.json`、`env.backup`、`uploads.tar.gz`、`postgres.dump`，`postgres.dump.status=ok`。
- 生产校验：`production_health_check.sh` 通过，`module-manager-v2.service=active`，`nginx=active`，磁盘使用率 27%。
- 页面探测：`/health`、`/login`、`/project-board`、`/task-hall`、`/construction`、`/vue/assets/index-Bvvbn8bU.js`、`/vue/assets/ProjectBoardView-uva5WQkn.js` 返回 200；`/openapi.json` 返回预期 404；`https://www.sgcc.online/login` 返回 200。
- 新接口校验：未登录访问 `/local-test/replacements` 返回鉴权错误；服务器内部仓库调用 `list_replacement_records(limit=3)` 返回 `total=5`、`sample_count=3`。
- 线上版本确认：`/login` 可见 `V3.0.4`，后端版本文件和 Vue 入口均为 `3.0.4`。

## 风险/回滚

低风险。该功能只读取已保存的换表字段，不改变匹配逻辑。回滚方式为回退本次提交并恢复版本号到 V3.0.3。
