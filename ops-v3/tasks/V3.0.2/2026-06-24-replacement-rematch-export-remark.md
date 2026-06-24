# 项目看板未匹配资料换表匹配与导出备注

- 状态：已发布
- 日期：2026-06-24
- 规则版本：Rules v1
- 应用基线：V3.0.2
- 目标版本：V3.0.3

## 需求

项目看板的未匹配资料窗口打开后，每一条数据新增“换表”按键；操作者输入旧表号，用旧表号匹配总清单地址；导出资料包时对换表资料做备注。

## 原因

现场换表时，扫码资料可能携带新表号，无法按总清单旧表号直接匹配地址。需要在未匹配清单中人工输入旧表号完成地址匹配，并在最终资料包中保留换表说明。

## 修改文件

- `v2-web/src/views/ProjectBoardView.vue`
- `v2-api/app/services/local_simulation.py`
- `v2-api/app/services/state_repository.py`
- `v2-api/tests/test_local_simulation.py`
- `v2-api/app/main.py`
- `v2-api/app/services/ops_status.py`
- `v2-api/pyproject.toml`
- `v2-api/tests/test_api.py`
- `v2-web/package.json`
- `v2-web/index.html`
- `v2-web/src/components/AppLayout.vue`
- `v2-web/src/layouts/AppLayout.vue`
- `v2-web/src/views/LoginView.vue`
- `v2-api/app/static/vue/`

## 影响范围

- 项目看板未匹配清单弹窗新增换表操作。
- 未匹配记录 rematch 成功后持久记录换表旧表号、新表号和操作人。
- 最终交付资料包 Excel 新增“备注”列，换表资料组显示旧表号说明。
- 应用版本从 V3.0.2 升级到 V3.0.3。

## 验证结果

- `python -m pytest v2-api\tests\test_local_simulation.py::test_replacement_rematch_adds_delivery_export_remark -q`：通过，1 passed。
- `python -m pytest v2-api\tests\test_api.py::test_excel_exports_return_real_workbooks v2-api\tests\test_api.py::test_system_status_requires_admin_and_reports_runtime_state -q`：通过，2 passed。
- `python -m py_compile v2-api\app\services\state_repository.py v2-api\app\services\local_simulation.py v2-api\app\main.py`：通过。
- `python scripts\verify_vue_migration_gate.py`：通过。
- `python scripts\verify-static-pages.py`：通过。
- `vue-tsc --noEmit`：通过。
- `vite build`：通过，已刷新 `v2-api/app/static/vue/` 生产静态资源。
- `git diff --check`：通过。
- `rg "V3\.0\.2|3\.0\.2" v2-api v2-web`：无残留应用版本标识。

## 生产发布

- 发布时间：2026-06-24
- 提交/标签：`9343549` / `v3.0.3`
- 发布方式：patch sync 到 `106.14.122.43:/opt/module-manager-v2/current`，仅同步本次变更源码、文档和 `v2-api/app/static/vue/` 构建产物；未覆盖生产 `.env`、`data`、`uploads`。
- 生产备份：`/opt/module-manager-v2/backups/runtime/20260624-004854`
- 备份内容：`local_state.json`、`users.json`、`env.backup`、`uploads.tar.gz`、`postgres.dump`，`postgres.dump.status=ok`。
- 生产校验：`production_health_check.sh` 通过，`module-manager-v2.service=active`，`nginx=active`，磁盘使用率 27%。
- 页面探测：`/health`、`/login`、`/project-board`、`/task-hall`、`/construction`、`/vue/assets/index-Bb3LQB_W.js` 返回 200；`/openapi.json` 返回预期 404；`https://www.sgcc.online/login` 返回 200。
- 线上版本确认：`/login` 可见 `V3.0.3`，后端版本文件和 Vue 入口均为 `3.0.3`。

## 风险/回滚

中低风险。主要风险是导出 Excel 新增列后，下游如果按固定列号解析可能需要同步适配。回滚方式为回退本次提交，并恢复版本号到 V3.0.2。
