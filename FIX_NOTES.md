# FIX_NOTES

Last updated: 2026-06-21

本文件记录维护期每次修改。后续修 Bug 时只追加本次相关内容，不重复全项目扫描。

## 2026-06-21 - 建立长期维护基线

### 修改原因

用户指定项目进入长期维护阶段，需要建立一次性项目认知文档、Bug 历史、修复记录和 PowerShell UTF-8 初始化脚本。后续维护必须低 Token、低风险、最小改动。

### 修改文件

- `PROJECT_KNOWLEDGE.md`
- `BUG_HISTORY.md`
- `FIX_NOTES.md`
- `setup_terminal_utf8.ps1`

### 修改内容

- 建立项目用途、架构、核心模块、文件结构、数据流、关键依赖、风险模块和维护原则。
- 建立 Bug 历史和已知风险清单。
- 建立后续修复记录模板和本次维护基线记录。
- 新增 PowerShell UTF-8 初始化脚本：
  - `chcp 65001`
  - `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`
  - `$OutputEncoding = [System.Text.Encoding]::UTF8`

### 影响范围

- 仅影响维护文档和本地终端初始化。
- 不影响生产业务逻辑。
- 不影响 UI、接口、数据库结构、部署配置。

### 验证方法

- 执行 `.\setup_terminal_utf8.ps1`，确认 PowerShell 切换到 UTF-8。
- 打开三个维护文档，确认包含用户要求的栏目和维护原则。
- 确认没有写入测试账号、密码、Token、密钥。

## 2026-06-21 - 限定维护基线为 V2.4.11

### 修改原因

用户明确要求后续只需要读取最新版本 `V2.4.11`。

### 修改文件

- `PROJECT_KNOWLEDGE.md`
- `FIX_NOTES.md`

### 修改内容

- 在项目认知顶部标记当前维护基线为 `V2.4.11 only`。
- 在维护原则中增加规则：后续默认只读取和处理最新版本 `V2.4.11`，不主动读取旧版本、历史 release 或旧静态页面。

### 影响范围

- 仅影响后续维护流程。
- 不影响业务代码、数据库、接口、UI 或部署。

### 验证方法

- 查看 `PROJECT_KNOWLEDGE.md` 顶部版本标记。
- 查看 `PROJECT_KNOWLEDGE.md` 维护原则第 22 条。

## 2026-06-21 - V2.4.11 项目看板生产补丁基线

### 修改原因

项目看板生产页存在版本徽标裁切、终端任务表只显示前 12 个、缺少上传率排序、账号管理缺少登录设备/IP、安装人员 KPI 不可展开、系统状态缺少版本号和数据文件说明等问题。

### 修改文件

- `v2-web/src/views/ProjectBoardView.vue`
- `v2-web/src/api/services.ts`
- `v2-web/src/api/types.ts`
- `v2-web/src/styles/base.css`
- `v2-web/src/styles/main.css`
- `v2-web/src/layouts/AppLayout.vue`
- `v2-web/src/views/LoginView.vue`
- `v2-web/src/components/AppLayout.vue`
- `v2-api/app/api/routes/auth.py`
- `v2-api/app/api/routes/local_test.py`
- `v2-api/app/services/account_store.py`
- `v2-api/app/services/local_simulation.py`
- `v2-api/app/services/state_repository.py`
- `v2-api/app/services/ops_status.py`
- `v2-api/app/main.py`
- `v2-api/pyproject.toml`
- `v2-api/tests/test_api.py`
- `AGENTS.md`
- Vue 构建产物 `v2-api/app/static/vue/**`

### 修改内容

- 版本从 `V2.4.10` 更新为 `V2.4.11`。
- 修复版本徽标宽度。
- 终端任务进度改为全量显示。
- 增加上传率、审阅率、已归档、未审阅等字段排序。
- 记录和展示账号最近登录 IP、登录设备。
- 新增安装人员每日工作量 API、弹窗和 KPI CSV 导出。
- 系统状态增加版本号和“数据文件”说明。

### 影响范围

- 项目看板。
- 账号管理显示字段。
- 安装人员 KPI 查询。
- 系统状态展示。
- 不改变数据库结构和主要业务接口协议。

### 验证方法

- `vue-tsc --noEmit`
- `powershell -ExecutionPolicy Bypass -File scripts\build-vue-shell.ps1`
- `python scripts\verify_vue_migration_gate.py --strict-native`
- `pytest v2-api\tests\test_api.py -q`
- `pytest v2-api\tests\test_state_repository.py v2-api\tests\test_postgres_migration.py -q`
- `python scripts\smoke-client-demo.py`
- 浏览器打开生产项目看板，确认：
  - `V2.4.11` 完整显示。
  - 终端任务全量显示。
  - 上传率排序可用。
  - 账号表有登录 IP 和登录设备。
  - 安装人员 KPI 弹窗可打开并可导出 CSV。
  - 系统状态显示版本号和数据文件说明。
