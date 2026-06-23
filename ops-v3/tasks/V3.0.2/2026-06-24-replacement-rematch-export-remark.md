# 项目看板未匹配资料换表匹配与导出备注

- 状态：已验证
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

## 风险/回滚

中低风险。主要风险是导出 Excel 新增列后，下游如果按固定列号解析可能需要同步适配。回滚方式为回退本次提交，并恢复版本号到 V3.0.2。
