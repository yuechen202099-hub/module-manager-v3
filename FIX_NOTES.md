# FIX_NOTES

Last updated: 2026-06-22

本文件记录维护期每次修改。后续修 Bug 时只追加本次相关内容，不重复全项目扫描。

## 2026-06-23 - 管理员施工进度未施工清单下钻

### 修改原因

管理员在施工采集页只能看到终端级进度和未施工数量，无法直接核对未施工明细。用户要求点击“未施工”后弹窗显示未施工清单。

### 修改文件

- `v2-web/src/views/ConstructionView.vue`
- `docs/V2_CHANGE_WORKLOG.md`
- `BUG_HISTORY.md`

### 修改内容

- 管理员终端任务卡的“未施工数”改为可点击指标。
- 新增未施工清单弹窗，展示表号、地址、终端，并支持搜索。
- 弹窗刷新保留搜索词；施工员视角不显示下钻入口。
- 保持原有施工采集、缓存、上传和提交任务逻辑不变。

### 影响范围

- 仅影响 `/construction` 管理员进度查看体验。
- 不新增后端接口，不改数据库结构，不执行 Alembic。

### 验证方法

- `vue-tsc --noEmit`
- `powershell -ExecutionPolicy Bypass -File scripts\build-vue-shell.ps1`
- `python scripts\verify_vue_migration_gate.py --strict-native`
- `git diff --check`

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

## 2026-06-21 - 限定维护基线为仓库最新版本

### 修改原因

用户更正维护规则：后续不是固定只修复 `V2.4.11`，而是按仓库当前最新版本进行修复。

### 修改文件

- `PROJECT_KNOWLEDGE.md`
- `FIX_NOTES.md`

### 修改内容

- 在项目认知顶部标记当前维护基线为 `latest repository version`。
- 在维护原则中增加规则：后续默认只读取和处理仓库当前最新版本，不主动读取旧版本、历史 release 或旧静态页面。

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

## 2026-06-21 - V2.4.12 施工采集扫码相机修复

### 修改原因

施工采集页手机端点击“扫码”后，相机可能无响应。最可能原因是扫码弹层刚打开时 DOM 尚未完成渲染，QuaggaJS 立即绑定相机容器会失败；失败后又自动触发隐藏文件选择器，移动端浏览器会拦截这种非用户直接点击触发的相机/相册动作。

### 修改文件

- `v2-web/src/views/ConstructionView.vue`
- `v2-web/package.json`
- `v2-api/pyproject.toml`
- `v2-api/app/main.py`
- `v2-api/app/services/ops_status.py`
- `v2-web/src/layouts/AppLayout.vue`
- `v2-web/src/components/AppLayout.vue`
- `v2-web/src/views/LoginView.vue`
- `v2-api/app/static/app_shell.html`
- `v2-api/app/static/task_hall.html`
- `v2-api/app/static/vue/**`
- `v2-api/tests/test_api.py`
- `AGENTS.md`
- `PROJECT_KNOWLEDGE.md`
- `BUG_HISTORY.md`
- `FIX_NOTES.md`
- `docs/V2_CHANGE_WORKLOG.md`

### 修改内容

- `startScanner()` 打开扫码弹层后先 `await nextTick()`，确保视频容器已挂载，再启动 QuaggaJS/BarcodeDetector。
- 实时扫码失败时不再自动触发隐藏拍照控件，而是保留扫码弹层并提示用户点击“拍照识别”或“手动输入”。
- 将本次小修版本从 `V2.4.11` 升级为 `V2.4.12`。

### 影响范围

- 影响施工采集页扫码弹层。
- 不改变施工采集业务数据、接口协议、数据库结构、上传逻辑或缓存结构。
- 生产发布由有 SSH 密钥权限的项目工程师线程执行。

### 验证方法

- `powershell -ExecutionPolicy Bypass -File scripts\build-vue-shell.ps1`：通过。
- `python scripts\verify_vue_migration_gate.py --strict-native`：通过。
- `pytest v2-api\tests\test_api.py -q`：`43 passed, 1 warning`。
- 生产发布已由项目工程师线程完成：
  - 备份路径：`/opt/module-manager-v2/backups/runtime/20260621_224811_before_v2.4.12`
  - 当前 release：`/opt/module-manager-v2/releases/v2.4.12-20260621_224816`
  - 服务状态：active。
  - 服务器本机验证：`/health` OK，`/login` 200，`/project-board` 200，`/construction` 200，`/openapi.json` 404，`https://www.sgcc.online/login` 200。
  - 版本文件确认：`v2-api/app/main.py`、`v2-web/package.json`、`v2-api/app/static/vue/index.html` 均为 `2.4.12`。
- 真实手机相机权限和条形码识别仍需现场执行最终验证。

## 2026-06-21 - V2.4.14 施工采集相机启动兜底与缓存筛选修复

### 修改原因

手机端 HTTPS 环境下扫码弹层仍可能停留在“正在启动相机”，黑色预览区不显示真实相机画面。最可能原因是 QuaggaJS 脚本加载或初始化 Promise 在部分移动浏览器上卡住，导致后续原生相机预览没有机会启动。同时，异常工单如果已有本地草稿，会被“已缓存”筛选误收，上传按钮也在非已缓存界面出现，容易误操作。

### 修改文件

- `v2-web/src/views/ConstructionView.vue`
- `BUG_HISTORY.md`
- `FIX_NOTES.md`
- `docs/V2_CHANGE_WORKLOG.md`
- `docs/AGENT_COORDINATION.md`

### 修改内容

- 给 QuaggaJS 加载、初始化和相机启动增加超时，避免扫码弹层无限等待。
- QuaggaJS 实时识别失败时，自动切换到浏览器原生 `getUserMedia` 相机预览；即使浏览器不支持 `BarcodeDetector`，也先保证相机画面打开。
- 将隐藏文件输入从 `display: none` 调整为极小透明元素，降低移动浏览器拦截相机/相册选择的概率。
- “已缓存”只统计普通施工缓存，不再混入异常工单缓存。
- 异常工单固定归入“异常工单”筛选，即使它带本地草稿。
- 顶部上传缓存、一键上传、上传当前组按钮只在“已缓存”筛选中显示。
- 移动端采集表单底部按钮改为普通流式位置，避免打开已缓存资料组时压住照片槽内容。

### 影响范围

- 仅影响施工采集页的扫码弹层、缓存/异常筛选和移动端采集表单布局。
- 不修改接口协议、数据库结构、缓存库结构、任务领取页或审阅工作台。
- 当前工作区存在项目工程师线程的 V2.4.13 未提交改动，本次补丁未纳入其文件。

### 验证方法

- `vue-tsc -p tsconfig.json --noEmit`：通过。
- `vite build`：通过，存在既有 Rollup PURE 注释和 chunk 体积警告。
- 用户现场反馈：扫码相机已能打开。
- 浏览器端真实摄像头授权、焦距和条形码识别仍需手机端复测。

## 2026-06-21 - V2.4.13 Claim task page cleanup

### Reason

The task claiming page still exposed obsolete construction open/close actions. Reviewers also needed a stricter task list that only shows terminals with remaining unreviewed scanned photos. The first visual pass made the primary `领取` button too low contrast because broad card text CSS leaked into Element Plus button spans.

### Changed files

- `v2-web/src/views/ClaimTasksView.vue`
- `v2-web/src/styles/main.css`
- version metadata files
- Vue build output under `v2-api/app/static/vue/**`

### Changes

- Removed the open/close construction action from claim task cards.
- Added admin construction assignment entry on each task card.
- Reviewer task list now filters to terminals with `hasScanInfo` and `unreviewedCount > 0`.
- Admin task list continues to show all terminals.
- Reworked card hierarchy around unreviewed count and review progress.
- Scoped button span CSS so `领取` and other Element Plus button labels keep readable colors.

### Validation

- `vue-tsc --noEmit`: passed.
- `vite build`: passed using bundled Node.
- `python scripts\verify_vue_migration_gate.py --strict-native`: passed.
- `.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -q`: `43 passed, 1 warning`.

## 2026-06-22 - V2.5.3 installer KPI exception drilldown

### Reason

The installer daily workload popup on the project board already showed a per-date exception count, but managers could not click that count to inspect which material groups caused the exceptions.

### Changed files

- `v2-api/app/services/local_simulation.py`
- `v2-api/app/services/state_repository.py`
- `v2-web/src/api/types.ts`
- `v2-web/src/api/services.ts`
- `v2-web/src/views/ProjectBoardView.vue`
- version metadata files
- maintenance documentation

### Changes

- Added `exception_groups` to each installer daily workload row for JSON and PostgreSQL state backends.
- Mapped the abnormal group payload into the Vue API layer.
- Made the daily exception count clickable in the installer workload table.
- Added a lightweight abnormal group detail dialog with meter number, terminal, address, exception reason, and photo count.
- Advanced version metadata to `V2.5.3`.

### Impact

- Project board KPI drilldown only.
- No API path change.
- No database schema change.
- No Alembic migration required.

### Validation

- Frontend typecheck passed using bundled Node.
- Vue production build passed with existing Rollup PURE/chunk-size warnings.
- Vue migration gate passed.
- Backend API tests passed: `43 passed, 1 warning`.
- Browser QA opened `/project-board?qa=v253-installer-exception` and confirmed visible `V2.5.3`; local data is empty, so installer drilldown payload was verified with an in-memory backend sample.

## 2026-06-22 - V2.5.4 construction upload installer name hotfix

### Reason

Construction uploads attributed photo creator/installer to the login username. Installer statistics should use the user's display name so KPI grouping follows the configured personnel name, not the account id.

### Changed files

- `v2-api/app/api/routes/local_test.py`
- `v2-api/app/services/local_simulation.py`
- `v2-api/app/services/state_repository.py`
- `v2-api/tests/test_api.py`
- `scripts/verify-static-pages.py`
- version metadata files
- maintenance documentation

### Changes

- Added server-side display-name resolution for construction upload requests.
- Upload authorization still uses `actor` username, while photo `creator` now uses the resolved display name.
- JSON and PostgreSQL state repositories both accept the resolved `creator`.
- Added API regression coverage that verifies construction uploaded photos use the login user's name and not the username.
- Fixed static-page verifier behavior so pages without inline scripts do not require Node before mojibake checks.
- Advanced version metadata to `V2.5.4`.

### Impact

- Backend-only attribution hotfix plus version metadata.
- No API path change.
- No database schema change.
- No Alembic migration required.

### Validation

- `python -m py_compile v2-api/app/api/routes/local_test.py v2-api/app/services/local_simulation.py v2-api/app/services/state_repository.py`: passed.
- `node vue-tsc --noEmit`: passed using bundled Node.
- `node vite build`: passed with existing Rollup PURE/chunk-size warnings.
- `python scripts\verify_vue_migration_gate.py --strict-native`: passed.
- `.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -q`: `43 passed, 1 warning`.

### Production deployment

- Published by project engineer patch sync on 2026-06-22.
- Commit: `f532eb1`; tag: `v2.5.4`.
- Backup path: `/opt/module-manager-v2/backups/runtime/20260622_105337_before_v2.5.4_patch`.
- Preserved production `.env`, `data`, uploads; no Alembic migration.
- Verified service active, `/health`, `/login`, `/project-board`, `/construction`, `https://www.sgcc.online/login`, and `/openapi.json` 404.

## 2026-06-22 - V2.4.15 review/thumbnail/KPI hotfix

### Reason

Three production bugs were assigned to the BUG fix thread: exception work orders opened in construction collection did not carry collector/module values from review; review thumbnail chips could all fail when the thumbnail proxy failed; installer daily workload grouped by storage/import date instead of scan or construction upload business date.

### Changed files

- `v2-web/src/api/types.ts`
- `v2-web/src/api/services.ts`
- `v2-web/src/views/ConstructionView.vue`
- `v2-web/src/views/TaskHallView.vue`
- `v2-api/app/services/state_repository.py`
- `v2-api/app/services/local_simulation.py`
- version metadata and generated Vue assets

### Changes

- Added exception order `payload` mapping to the frontend API adapter and type.
- Construction exception work orders now fall back to payload collector/module/meter/address when the nested group lacks those values.
- Returning a group to exception order in the PostgreSQL repository now uses the shared exception payload builder.
- Review thumbnail images now fall back from the backend thumbnail proxy to direct thumbnail/preview URLs after an image error.
- Installer KPI daily workload now prefers scan/source created time for imported scan photos and latest construction upload time for construction photos.
- Version metadata advanced to `V2.4.15`.

### Impact

- Affects review workspace thumbnail display, construction exception form prefill, and installer KPI daily workload.
- Does not change database schema or public API paths.
- Does not include V2.5 new feature work.

### Validation

- `python -m compileall v2-api\app\services\state_repository.py v2-api\app\services\local_simulation.py v2-api\app\main.py`: passed.
- `.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -q`: `43 passed, 1 warning`.
- `node node_modules\vue-tsc\bin\vue-tsc.js --noEmit`: passed.
- `node node_modules\vite\bin\vite.js build`: passed with existing chunk-size/PURE-comment warnings.
- `python scripts\verify_vue_migration_gate.py --strict-native`: passed.

### Release note

User approved folding this hotfix into the V2.5.0 feature release instead of publishing a separate V2.4.15 tag.

## 2026-06-22 - V2.5.0 unmatched and exception task workflow

### Reason

Unmatched address records and exception groups needed to become actionable workflow tasks instead of passive records. Administrators need to assign them to field constructors, reviewers need to correct meter numbers and replacement-meter cases, and project-outside construction must be traceable and exportable.

### Changed files

- `v2-api/app/services/local_simulation.py`
- `v2-api/app/services/state_repository.py`
- `v2-api/app/api/routes/local_test.py`
- `v2-api/app/api/routes/exports.py`
- `v2-web/src/api/services.ts`
- `v2-web/src/api/types.ts`
- `v2-web/src/views/TaskHallView.vue`
- Vue build output under `v2-api/app/static/vue/**`

### Changes

- Added unmatched-record update, assignment, unassignment, rematch, replacement-meter matching, project-outside marking, and project-outside export APIs.
- Added exception-order assignment and unassignment APIs.
- When assigning an exception order or unmatched record that has a terminal, the backend also assigns the corresponding construction terminal task to the constructor, preserving the one-active-terminal rule.
- Added review-workbench field task cards for unmatched records and exception orders.
- Added quick actions: modify meter, replacement meter, project outside, assign/unassign constructor, delete unmatched record as admin, and export project-outside records.
- Implemented JSON and PostgreSQL repository support without schema migration by storing extension metadata in existing JSONB payload/raw fields.

### Validation

- `python -m py_compile v2-api/app/services/local_simulation.py v2-api/app/services/state_repository.py v2-api/app/api/routes/local_test.py v2-api/app/api/routes/exports.py`: passed.
- `powershell -ExecutionPolicy Bypass -File scripts\build-vue-shell.ps1`: passed with existing Rollup PURE/chunk-size warnings.

### Release note

This workflow feature version (`V2.5.0`) is now the combined release vehicle for both the V2.4.15 hotfix and the V2.5.0 field-task workflow, per user approval.

### Production deployment

- Commit: `eeb0fa9`
- Tag: `v2.5.0`
- Backup: `/opt/module-manager-v2/backups/runtime/20260622_014459_before_v2.5.0_patch`
- Release method: patch sync; production `.env`, `data`, uploads preserved; no Alembic migration.
- Validation: service active; local server pages and public IP pages return `V2.5.0`; server-side `https://www.sgcc.online/login` returns 200.

## 2026-06-22 - V2.5.1 permanent field-task cards and label centering

### Reason

The unmatched and exception workflows should behave like permanent task entries, not a temporary mixed section inside the material-group list. The same task-entry concept is needed on the construction collection page. Some compact labels/buttons also appeared visually off-center because card-level `span` rules overrode Element Plus label internals.

### Changed files

- `v2-web/src/views/TaskHallView.vue`
- `v2-web/src/views/ConstructionView.vue`
- `v2-web/src/styles/element-plus.css`
- `v2-web/src/styles/main.css`
- version metadata files

### Changes

- Added always-visible `异常任务` and `未匹配任务` cards to the review task column.
- Selecting either review field-task card switches the material-group column into the corresponding task operation list.
- Added always-visible `异常任务` and `未匹配任务` cards to the construction task picker.
- Construction exception task cards can jump into the related terminal exception workflow when a terminal is available.
- Construction unmatched task cards show the assigned/field-confirmation queue and can jump into the related terminal when a terminal is available.
- Centered Element Plus button and tag content inside task cards to keep compact labels visually aligned.
- Advanced version metadata to `V2.5.1`.

### Impact

- Frontend-only workflow and style update.
- No database schema change.
- No API path change.
- No Alembic migration required.

### Validation

- `node vue-tsc --noEmit`: passed using bundled Node.
- `powershell -ExecutionPolicy Bypass -File scripts\build-vue-shell.ps1`: passed with existing Rollup PURE/chunk-size warnings.
- `python scripts\verify_vue_migration_gate.py --strict-native`: passed.
- `.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -q`: `43 passed, 1 warning`.
- Browser QA:
  - `/task-hall?qa=v251-field-cards` shows `V2.5.1` and one `异常任务` card plus one `未匹配任务` card.
  - `/construction?qa=v251-field-cards` shows `V2.5.1` and one `异常任务` card plus one `未匹配任务` card.
  - Sample Element Plus button/tag contents report centered flex display.

## 2026-06-22 - V2.5.2 construction mobile field-task card click-through

### Reason

Mobile construction users reported that the two permanent field-task cards added in V2.5.1 could be opened, but tapping them did not reliably jump into the related collection task screen.

### Changed files

- `v2-web/src/views/ConstructionView.vue`
- version metadata files
- maintenance documentation

### Changes

- Added a shared task resolver for construction field-task cards that matches by task id first and terminal second.
- Made exception and unmatched field-task list cards fully clickable and keyboard accessible, not only their small action buttons.
- When a permanent field-task mode contains exactly one actionable card, selecting that mode now enters the related task directly.
- Advanced version metadata to `V2.5.2`.

### Impact

- Frontend-only construction collection workflow hotfix.
- No API path change.
- No database schema change.
- No Alembic migration required.

### Validation

- `node vue-tsc --noEmit`: passed using bundled Node.
- `node vite build`: passed with existing Rollup PURE/chunk-size warnings.
- `python scripts\verify_vue_migration_gate.py --strict-native`: passed.
- `.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -q`: `43 passed, 1 warning`.

## 2026-06-22 - V2.5.5 historical construction creator backfill

### Reason

V2.5.4 fixed new construction uploads, but photos already saved before the fix can still store the constructor username in `creator`. Installer KPI and photo details should use the configured user display name for those historical construction uploads too.

### Changed files

- `v2-api/scripts/backfill_construction_creator_names.py`
- `v2-api/tests/test_backfill_construction_creator_names.py`
- version metadata files
- maintenance documentation

### Changes

- Added a dry-run-first backfill script for historical construction-upload photo creators.
- PostgreSQL backfill updates only photos whose `creator` equals a known username and whose source metadata identifies them as construction uploads.
- Optional JSON state backfill is available for compatibility state files.
- The script defaults to dry-run; `--apply` is required for writes.
- Added regression coverage for JSON state behavior so scan/import creators are not accidentally rewritten.
- Advanced version metadata to `V2.5.5`.

### Impact

- One-time data repair utility plus version metadata.
- No runtime API path change.
- No database schema change.
- No Alembic migration required.

### Validation

- `python -m py_compile v2-api/scripts/backfill_construction_creator_names.py`: passed.
- `pytest v2-api/tests/test_backfill_construction_creator_names.py -q`: `1 passed`.
- `node vue-tsc --noEmit`: passed using bundled Node.
- `node vite build`: passed with existing Rollup PURE/chunk-size warnings.
- `python scripts\verify_vue_migration_gate.py --strict-native`: passed.
- `.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py v2-api\tests\test_backfill_construction_creator_names.py -q`: `44 passed, 1 warning`.

### Production deployment

- Published by project engineer patch sync.
- Commit/tag: `f0b0edb` / `v2.5.5`.
- Backup path: `/opt/module-manager-v2/backups/runtime/20260622_114149_before_v2.5.5_patch`.
- Production `.env`, `data`, and uploads were preserved; no Alembic migration was run.
- Dry-run matched only constructor username `xa` and display name `樊哲浩`.
- Dry-run counts: PostgreSQL `matched_creator_username=211`; JSON compatibility state `matched_creator_username=54`.
- Apply counts: PostgreSQL `updated=211`; JSON compatibility state `updated=54`.
- JSON backup from apply: `/opt/module-manager-v2/backups/runtime/20260622_114149_before_v2.5.5_patch/local_state.pre-creator-name-backfill.20260622_034158.json`.
- Verification: service active; `/health`, `/login`, `/project-board`, `/construction`, and `https://www.sgcc.online/login` returned OK.

## 2026-06-22 - V2.5.6 constructor active task cap changed to 5

### Reason

The construction workflow originally enforced one active terminal per constructor. The requested production rule is now that one constructor can hold up to 5 active terminal tasks at the same time.

### Changed files

- `v2-api/app/services/local_simulation.py`
- `v2-api/app/services/state_repository.py`
- `v2-api/alembic/versions/0004_allow_five_construction_tasks.py`
- `v2-api/tests/test_api.py`
- `v2-miniprogram/miniprogram/pages/tasks/tasks.js`
- `v2-miniprogram/miniprogram/pages/tasks/tasks.wxml`
- `v2-miniprogram/miniprogram/utils/api.js`
- version metadata files
- maintenance documentation

### Changes

- Replaced the one-active-construction-task guard with a shared maximum of 5 active terminal tasks per constructor.
- Kept the old helper as a compatibility wrapper while adding list/count helpers for the new capacity rule.
- Updated PostgreSQL assignment checks for normal construction tasks, unmatched field tasks, and exception field tasks.
- Added Alembic migration `20260622_0004` to drop the old PostgreSQL partial unique index that physically enforced one active task.
- Updated the WeChat mini-program task page to show and open up to 5 assigned terminal tasks.
- Updated the mini-program API error text for the new 5-task limit.
- Advanced version metadata to `V2.5.6`.

### Impact

- Runtime behavior change for construction assignment.
- Requires a database migration before production can assign a second active terminal to the same constructor.
- No API path changes.
- Downgrading the migration can fail if production already has constructors with more than one active terminal; rollback should first release extra assignments or restore the pre-migration database backup.

### Validation

- `python -m py_compile v2-api/app/services/local_simulation.py v2-api/app/services/state_repository.py v2-api/app/main.py v2-api/app/services/ops_status.py`: passed.
- `.venv\Scripts\python.exe -m py_compile v2-api/alembic/versions/0004_allow_five_construction_tasks.py`: passed.
- `.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py::test_constructor_can_keep_up_to_five_assigned_terminals -q`: passed.
- `.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -q`: `43 passed, 1 warning`.
- `powershell -ExecutionPolicy Bypass -File scripts\build-vue-shell.ps1`: passed with existing Rollup PURE/chunk-size warnings.
- `.venv\Scripts\python.exe scripts\verify_vue_migration_gate.py --strict-native`: passed.
- Bundled Node syntax checks for mini-program task/API scripts: passed.

## 2026-06-22 - V2.5.7 claim task terminal/address search

### Reason

The task claiming page needed a direct way to locate terminal cards by terminal number or installation address instead of visually scanning the full task card grid.

### Changed files

- `v2-api/app/services/local_simulation.py`
- `v2-api/app/services/state_repository.py`
- `v2-api/tests/test_api.py`
- `v2-web/src/api/types.ts`
- `v2-web/src/api/services.ts`
- `v2-web/src/views/ClaimTasksView.vue`
- `v2-web/src/styles/main.css`
- version metadata files
- maintenance documentation

### Changes

- Added task payload fields for a representative address and a hidden full address search index.
- Backfilled the address search fields at task-list read time so existing JSON state can search without a full rebuild.
- Added a claim task search box that filters the current role-visible task list by terminal number, task id, task name, first address, or full address index.
- Kept reviewer/admin permission behavior unchanged.
- Updated responsive styling so the search box stacks cleanly on mobile.
- Advanced version metadata to `V2.5.7`.

### Impact

- No API path change.
- No database migration.
- No production data rewrite required.

### Validation

- `python -m py_compile v2-api/app/services/local_simulation.py v2-api/app/services/state_repository.py v2-api/app/main.py v2-api/app/services/ops_status.py`: passed.
- `.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -q`: `43 passed, 1 warning`.
- `powershell -ExecutionPolicy Bypass -File scripts\build-vue-shell.ps1`: passed with existing Rollup PURE/chunk-size warnings.
- `.venv\Scripts\python.exe scripts\verify_vue_migration_gate.py --strict-native`: passed.
- Bundled Node `vue-tsc --noEmit`: passed.
- Browser QA on `http://127.0.0.1:8000/claim-tasks`: V2.5.7 page loaded, search input visible, terminal search filtered 135 cards down to the matching terminal card.

### Production deployment

- Published by project engineer patch sync.
- Commit/tag: `13074ab` / `v2.5.7`.
- Backup path: `/opt/module-manager-v2/backups/runtime/20260622_163957_before_v2.5.7_patch`.
- Production `.env`, `data`, and uploads were preserved.
- Production was still on `V2.5.5` with Alembic `20260619_0003`; ran `alembic upgrade head` to apply `20260622_0004`.
- Verification:
  - `module-manager-v2.service`: active.
  - Runtime version: `2.5.7`.
  - Alembic current: `20260622_0004 (head)`.
  - `/health`: OK.
  - `/login`: shows `V2.5.7`.
  - `http://106.14.122.43/login`: 200 and shows `V2.5.7`.
  - `http://www.sgcc.online/login`: 200 and shows `V2.5.7`.
  - `https://www.sgcc.online/login`: 200 and shows `V2.5.7`.
  - `/openapi.json`: 404.
  - Production task repository returns non-empty `address_search_text`.

## 2026-06-22 - V2.5.8 installer KPI effective work time

### Reason

Installer KPI needs to infer daily work start/end times and effective working duration from scan time and construction upload time. Long pauses should not be counted as effective working time.

### Changed files

- `v2-api/app/services/local_simulation.py`
- `v2-api/app/services/state_repository.py`
- `v2-api/tests/test_api.py`
- `v2-web/src/api/types.ts`
- `v2-web/src/api/services.ts`
- `v2-web/src/views/ProjectBoardView.vue`
- version metadata files
- maintenance documentation

### Changes

- Added shared work-time parsing and aggregation for JSON and PostgreSQL state backends.
- Work start/end are based on the earliest and latest valid scan/upload time on that date.
- Effective work duration now sums only continuous intervals where adjacent time points are at most 60 minutes apart.
- Gaps longer than 60 minutes are treated as breaks and excluded from effective work duration.
- Added attendance span, effective time point count, and 24-hour segment data to the installer workload payload.
- Added project-board KPI columns for start time, end time, and effective work duration.
- Added a drilldown bar chart showing hourly effective work distribution.
- Added KPI CSV columns for start time, end time, effective work duration, attendance span, and time point count.
- Advanced version metadata to `V2.5.8`.

### Impact

- No API path change.
- No database migration.
- Existing clients that ignore the new fields remain compatible.
- The 60-minute break threshold is currently a server-side constant.

### Validation

- `python -m py_compile v2-api/app/services/local_simulation.py v2-api/app/services/state_repository.py v2-api/app/main.py v2-api/app/services/ops_status.py`: passed.
- `.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py::test_installer_daily_workload_includes_work_time_segments -q`: passed.
- `.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -q`: `44 passed, 1 warning`.
- `powershell -ExecutionPolicy Bypass -File scripts\build-vue-shell.ps1`: passed with existing Rollup PURE/chunk-size warnings.
- `.venv\Scripts\python.exe scripts\verify_vue_migration_gate.py --strict-native`: passed.

## 2026-06-23 - V3.0.0-rc2 施工采集本地缓存占位工单修复

### 修改原因

施工员反馈手机端扫码打开工单后，“已缓存”里出现表号 `0000000000`、地址“待导入总清单地址”的占位卡片，并且无法删除。该问题会干扰现场施工判断，也可能让异常工单草稿混入普通缓存列表。

### 修改文件

- `v2-web/src/views/ConstructionView.vue`
- 版本标识文件
- 维护文档

### 修改内容

- 普通“已缓存”列表只读取普通施工缓存，不再遍历全部 `taskDrafts`。
- 新增占位缓存识别：无照片、无采集器、无异常工单、表号/资料组为全 0 且地址为“待导入总清单地址”的草稿会自动删除，避免缓存膨胀。
- 新增单条“删除缓存”入口，施工员可以删除某一条本机待上传草稿。
- 未增加批量清理按钮或批量清理入口。
- 版本推进到 `V3.0.0-rc2`。

### 影响范围

- 仅影响施工采集页本机 IndexedDB 缓存展示、上传前单条草稿删除和无效占位草稿自动删除。
- 不修改后端接口。
- 不修改数据库结构。
- 不删除服务器资料、OSS 图片或总清单。

### 验证方法

- 打开 `/construction`，进入某个已指派终端。
- 已缓存列表不应再显示 `0000000000 / 待导入总清单地址` 这种无效占位卡片；刷新或进入施工页后该类无效缓存应从本机 IndexedDB 删除。
- 正常缓存卡片应显示“删除缓存”，点击后只删除当前单条本地草稿。
- 异常工单应只出现在“异常工单”分类，不应混入普通“已缓存”分类。

## 2026-06-23 - V3.0.0-rc1 missing collector photo quality exception

### Reason

Construction upload and review quality checks were both treated like a strict 4-photo requirement. The field side should only be blocked when the three required construction photos are missing, while a missing collector barcode photo should become a review/quality exception after upload.

### Changed files

- `v2-api/app/services/local_simulation.py`
- `v2-api/app/services/state_repository.py`
- `v2-api/tests/test_api.py`
- `v2-api/tests/test_state_repository.py`

### Changes

- Added shared slot constants for construction upload-required photos: `before_box`, `module_meter`, and `after_box`.
- Kept `collector_barcode` as quality-required but not upload-required.
- Construction upload now validates the effective required slot set after SHA duplicate filtering.
- Missing upload-required slots returns a 400 error before the group state is accepted.
- Missing collector barcode photo allows upload, marks the group `exception`, stores reason code `missing_collector_photo`, and shows `缺采集器照片`.
- Adding a collector barcode photo clears only this automatic exception.
- Deleting the collector barcode photo re-applies the automatic exception.
- PostgreSQL photo payloads now expose `construction_slot` and `construction_slot_label` for reliable existing-slot detection.

### Impact

- No API path change.
- No database migration.
- No Alembic.
- Web, mini-program, and future native clients all go through the same backend `upload-batch` validation.

### Validation

- `python -m py_compile v2-api/app/services/local_simulation.py v2-api/app/services/state_repository.py v2-api/app/api/routes/local_test.py`: passed.
- `.venv\Scripts\python.exe -m pytest v2-api/tests/test_api.py::test_construction_task_open_claim_and_upload_batch -q`: passed.
- `.venv\Scripts\python.exe -m pytest v2-api/tests/test_state_repository.py::test_postgres_quality_exception_marks_and_clears_missing_collector_photo -q`: passed.
- `.venv\Scripts\python.exe -m pytest v2-api/tests/test_api.py -q`: `45 passed, 1 warning`.
- `.venv\Scripts\python.exe -m pytest v2-api/tests/test_state_repository.py -q`: `9 passed`.
- `vue-tsc --noEmit`: passed.
- `powershell -ExecutionPolicy Bypass -File scripts\build-vue-shell.ps1`: passed with existing Rollup warnings.
- `python scripts\verify_vue_migration_gate.py --strict-native`: passed.
- `git diff --check`: passed with CRLF warnings only.

### Production deployment

- Commit: `9f3fc67`.
- Branch: `feature/v3.0.0-apple-ui-lab`.
- Deployment method: patch sync into the current V3.0.0-rc1 release; no full release replacement.
- Backup path: `/opt/module-manager-v2/backups/runtime/20260623_180532_before_v3_missing_collector_patch`.
- PostgreSQL dump: `/opt/module-manager-v2/backups/runtime/20260623_180532_before_v3_missing_collector_patch/postgres.dump`.
- Production `.env`, `data`, and uploads were preserved.
- No Alembic migration was executed.
- Production checks passed for `/health`, `/login`, `/project-board`, `/claim-tasks`, `/task-hall`, `/construction`, and `https://www.sgcc.online/login`.
- `/openapi.json`: `404`.

## 2026-06-23 - V3.0.0-rc1 construction completion time

### Reason

Construction completion time must represent when the field-side data became complete, not when the server later received an upload. This matters when a constructor works offline and uploads cached groups after network recovery.

### Fix

- Web construction drafts now keep `client_completed_at` once a draft is valid: module number exists and required slots `before_box`, `module_meter`, and `after_box` are present.
- Web and mini-program upload payloads send `client_completed_at`.
- Backend `upload-batch` accepts optional `client_completed_at`, stores it in photo raw metadata, and keeps upload compatible for old clients.
- KPI, daily workload, two-hour time segments, and efficiency calculations prefer `client_completed_at`; malformed or missing values fall back to server upload time.
- No database schema change and no Alembic migration.

### Validation

- `python -m py_compile v2-api\app\api\routes\local_test.py v2-api\app\services\local_simulation.py v2-api\app\services\state_repository.py`: passed.
- `.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -q`: `45 passed, 1 warning`.
- `.venv\Scripts\python.exe -m pytest v2-api\tests\test_state_repository.py -q`: `8 passed`.
- `vue-tsc --noEmit`: passed.
- `powershell -ExecutionPolicy Bypass -File scripts\build-vue-shell.ps1`: passed with existing Rollup warnings.
- `python scripts\verify_vue_migration_gate.py --strict-native`: passed.
- `git diff --check`: passed with CRLF conversion warnings only.

## 2026-06-22 - V2.6.1 installer KPI PostgreSQL field hotfix

### Reason

Clicking the installer KPI popup on PostgreSQL-backed production data could fail because the V2.6.0 address drilldown payload referenced `MaterialGroup.meter_no` and `MaterialGroup.address`, while the actual model fields are `display_meter_no` and `installation_address`.

### Changed files

- `v2-api/app/services/state_repository.py`
- `v2-api/tests/test_state_repository.py`
- version metadata files
- maintenance documentation

### Changes

- Changed PostgreSQL installer workload completion records to use `display_meter_no` and `installation_address`.
- Added a regression test with a fake PostgreSQL material group that only exposes the real model fields.
- Advanced version metadata to `V2.6.1`.

### Impact

- Affects only the project-board installer KPI popup in the PostgreSQL state backend.
- No API path change.
- No database migration.

### Validation

- `pytest v2-api\tests\test_state_repository.py::test_postgres_installer_workload_uses_material_group_installation_address -q`: passed.
- `python -m py_compile v2-api/app/services/state_repository.py v2-api/app/main.py v2-api/app/services/ops_status.py`: passed.
- `pytest v2-api\tests\test_api.py -q`: `44 passed, 1 warning`.
- `powershell -ExecutionPolicy Bypass -File scripts\build-vue-shell.ps1`: passed with existing Rollup PURE/chunk-size warnings.
- `python scripts\verify_vue_migration_gate.py --strict-native`: passed.
- Browser QA on `http://127.0.0.1:8000/project-board?qa=v261-kpi`: page title `V2.6.1`, installer KPI dialog opens, no console error/warn.

## 2026-06-22 - V2.6.2 installer KPI chart visual refinement

### Reason

The V2.6.0 completion line chart made the work-time popup visually noisy and did not match the desired Apple Screen Time style. The completion count is easier to read when it is integrated directly into each 2-hour bar segment.

### Changed files

- `v2-web/src/views/ProjectBoardView.vue`
- version metadata files
- maintenance documentation

### Changes

- Removed the separate completion line chart and related computed state.
- Restyled the 2-hour KPI chart as a single quiet screen-time card.
- Kept each segment clickable so users can still open the address list.
- Kept direct labels for completion count, effective work duration, and per-hour efficiency.
- Advanced version metadata to `V2.6.2`.

### Impact

- Frontend visual-only change.
- No API path change.
- No database migration.
- Address drilldown and KPI weighting remain unchanged.

### Validation

- `python -m py_compile v2-api/app/main.py v2-api/app/services/ops_status.py`: passed.
- `pytest v2-api\tests\test_api.py -q`: `44 passed, 1 warning`.
- `powershell -ExecutionPolicy Bypass -File scripts\build-vue-shell.ps1`: passed with existing Rollup PURE/chunk-size warnings.
- `python scripts\verify_vue_migration_gate.py --strict-native`: passed.

### Production deployment

- Commit: `f4d32c2`.
- Tag: `v2.6.2`.
- Deployment mode: patch sync to the existing production `current` target; no full release replacement.
- Backup path: `/opt/module-manager-v2/backups/runtime/20260622_202711_before_v2.6.2_patch`.
- Production `.env`, `data`, uploads preserved.
- No Alembic migration.
- Production checks passed for `/health`, `/login`, `/project-board`, `/task-hall`, `/construction`, and `https://www.sgcc.online/login`.
- `/openapi.json`: `404`.


## 2026-06-22 - V2.6.4 remove permanent field task cards

### Reason

The always-visible exception and unmatched task cards in the review workbench and construction collection page added visual noise after the workflow was folded back into normal task handling.

### Changed files

- `v2-web/src/views/TaskHallView.vue`
- `v2-web/src/views/ConstructionView.vue`
- Version metadata files
- Maintenance documentation

### Changes

- Removed the permanent exception/unmatched task entry cards from `/task-hall`.
- Removed the permanent exception/unmatched task entry cards from `/construction`.
- Kept existing underlying APIs/data structures and terminal workflows unchanged.
- Advanced visible/runtime version metadata to `V2.6.4`.

### Impact

- UI-only change.
- No API path changes.
- No Alembic migration.
- Existing exception/unmatched data remains intact.

### Validation

- `python -m py_compile v2-api/app/main.py v2-api/app/services/ops_status.py`: passed.
- `.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -q`: `45 passed, 1 warning`.
- `powershell -ExecutionPolicy Bypass -File scripts\build-vue-shell.ps1`: passed with existing Rollup PURE/chunk-size warnings.
- `python scripts\verify_vue_migration_gate.py --strict-native`: passed.
- `rg "field-entry-card|field-task-entry|异常任务 3|未匹配任务 97" v2-web\src\views v2-api\app\static\vue`: no matches.

### Production deployment

- Commit: `443482d`.
- Tag: `v2.6.4`.
- Deployment method: patch sync into the existing production `current` directory; no full release replacement.
- Backup path: `/opt/module-manager-v2/backups/runtime/20260622_213557_before_v2.6.4_patch`.
- Production `.env`, `data`, uploads preserved.
- No Alembic migration.
- Production checks passed: `/health`, `/login`, `/project-board`, `/task-hall`, `/construction`, `https://www.sgcc.online/login`.
- `/openapi.json`: `404`.

## 2026-06-22 - V2.6.5 construction task submit button

### Reason

Constructors needed a clear completion action after finishing field collection. Without it, an assigned terminal could remain visible in the construction page even after the photos and data had been uploaded.

### Changed files

- `v2-web/src/api/services.ts`
- `v2-web/src/views/ConstructionView.vue`
- `v2-api/tests/test_api.py`
- Version metadata files
- Maintenance documentation

### Changes

- Added a `releaseConstructionTask()` frontend API wrapper for the existing backend release endpoint.
- Added a `提交施工任务` button to the selected construction terminal header for the assigned constructor.
- Added a confirmation message that warns when the current terminal still has local cache or unbuilt groups before releasing the task.
- On successful submit, the construction page clears the selected terminal, closes the collection sheet, refreshes tasks, and returns to the task picker.
- Added API regression coverage to ensure constructor release clears `construction_claimed_by` and the released terminal no longer occupies the constructor task list.

### Impact

- No API path change.
- No database migration.
- No production data rewrite.
- Existing admin assignment/unassignment behavior is unchanged.

### Validation

- `python -m py_compile v2-api/app/main.py v2-api/app/services/ops_status.py`: passed.
- `.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -q`: `45 passed, 1 warning`.
- `powershell -ExecutionPolicy Bypass -File scripts\build-vue-shell.ps1`: passed with existing Rollup PURE/chunk-size warnings.
- `python scripts\verify_vue_migration_gate.py --strict-native`: passed.

## 2026-06-22 - V2.6.3 安装人员 KPI 同楼栋地址聚类

### 修改原因

安装人员 KPI 地址权重需要把同一楼栋号的数据视为同一工作簇。`95弄18号公用设备` 这类同楼栋公用设备，应和 `95弄18号201室` 这类住户地址归到一起，而不是被当作零散地址。

### 修改文件

- `v2-api/app/services/local_simulation.py`
- `v2-api/tests/test_api.py`
- 版本标识文件
- 维护文档

### 修改内容

- KPI 地址聚类键优先识别楼栋级 `弄+号` / `号`，再执行室号、车位、充电桩等后缀清理。
- 新增回归测试，确认 `95弄18号201室` 和 `95弄18号公用设备` 归为同一簇，同时 `95弄19号公用设备` 保持独立。
- 版本标识推进到 `V2.6.3`。

### 影响范围

- 仅影响安装人员 KPI 地址权重和地址明细聚类。
- 不改变 API 路径。
- 不需要数据库迁移。

### 验证方法

- `python -m py_compile v2-api/app/services/local_simulation.py v2-api/app/main.py v2-api/app/services/ops_status.py`：通过。
- `pytest v2-api\tests\test_api.py::test_installer_kpi_clusters_same_building_number_public_equipment -q`：通过。
- `pytest v2-api\tests\test_api.py -q`：`45 passed, 1 warning`。
- `powershell -ExecutionPolicy Bypass -File scripts\build-vue-shell.ps1`：通过，仍有既有 Rollup PURE / chunk-size 警告。
- `python scripts\verify_vue_migration_gate.py --strict-native`：通过。

### 生产发布

- Commit: `5e748ca`.
- Tag: `v2.6.3`.
- 发布方式：patch sync 到现有生产 `current` 目录；未做完整 release 替换。
- 备份路径：`/opt/module-manager-v2/backups/runtime/20260622_204933_before_v2.6.3_patch`。
- 生产 `.env`、`data`、uploads 均保留。
- 未执行 Alembic 迁移。
- 生产检查通过：`/health`、`/login`、`/project-board`、`https://www.sgcc.online/login`。
- `/openapi.json`: `404`.

## 2026-06-22 - V2.6.0 installer KPI efficiency model

### Reason

Installer KPI should focus on efficiency, not only attendance span or photo/group counts. The work-time chart also needed to move from 1-hour bars to 2-hour periods, show completion trend, expose each period's address list, and account for address concentration/difficulty.

### Changed files

- `v2-api/app/services/local_simulation.py`
- `v2-api/app/services/state_repository.py`
- `v2-api/tests/test_api.py`
- `v2-web/src/api/types.ts`
- `v2-web/src/api/services.ts`
- `v2-web/src/views/ProjectBoardView.vue`
- version metadata files
- maintenance documentation

### Changes

- Changed installer KPI visual segments from 1-hour bars to 2-hour periods.
- Added completion counts, completion per effective hour, weighted completion, and weighted completion per effective hour to the workload payload.
- Added a 2-hour completion line chart above the effective-work bar chart.
- Added clickable segment drilldown with the address list for that period.
- Added explainable address difficulty weights:
  - same building / same area lowers weight because search path can be reused;
  - missing room number raises weight as shop/villa/site-search risk;
  - scattered addresses raise weight;
  - charging pile / parking-space addresses raise weight, but clustered charging-pile areas get partial search-path reuse.
- Added KPI CSV columns for completion count, per-hour completion, weighted completion, and weighted efficiency.
- Advanced version metadata to `V2.6.0`.

### Impact

- No API path change.
- No database migration.
- Existing clients that ignore new KPI fields remain compatible.
- Address difficulty is heuristic and intentionally explainable; future tuning can adjust constants without data migration.

### Validation

- `python -m py_compile v2-api/app/services/local_simulation.py v2-api/app/services/state_repository.py v2-api/app/main.py v2-api/app/services/ops_status.py`: passed.
- `.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py::test_installer_daily_workload_includes_work_time_segments -q`: passed.
- `.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -q`: `44 passed, 1 warning`.
- `powershell -ExecutionPolicy Bypass -File scripts\build-vue-shell.ps1`: passed with existing Rollup PURE/chunk-size warnings.
- `.venv\Scripts\python.exe scripts\verify_vue_migration_gate.py --strict-native`: passed.
## 2026-06-23 - Project-board unmatched list modal and duplicate cleanup

### Reason

The project board showed the unmatched count but did not let administrators directly inspect, export, or remove duplicate unmatched records. Repeated incremental imports can produce duplicate unmatched rows, so the cleanup needs to be available from the production management surface.

### Changed files

- `v2-api/app/api/routes/local_test.py`
- `v2-api/app/services/local_simulation.py`
- `v2-api/app/services/state_repository.py`
- `v2-api/tests/test_local_simulation.py`
- `v2-web/src/api/services.ts`
- `v2-web/src/api/types.ts`
- `v2-web/src/views/ProjectBoardView.vue`
- `v2-api/app/static/vue/**`

### Changes

- Made the project-board `扫码未匹配` risk card open a dialog with searchable unmatched records.
- Added CSV export inside that dialog.
- Added a `删除重复项` action that removes duplicate unmatched records by meter/barcode/fallback identity while preferring assigned, project-outside, replacement, photo-rich, and newer records.
- Added repository support for JSON, PostgreSQL, and dual-write state backends.
- Added an API endpoint: `POST /local-test/unmatched/dedupe`.
- Added a regression test for JSON-state unmatched duplicate cleanup.

### Impact

- No database schema change.
- No Alembic migration.
- Existing unmatched edit/assign/project-outside workflows remain unchanged.
- PostgreSQL cleanup soft-deletes duplicate unmatched rows by setting status to `deduped`; JSON cleanup removes duplicate entries from the compatibility state and writes an audit event.

### Validation

- `python -m py_compile v2-api\app\services\local_simulation.py v2-api\app\services\state_repository.py v2-api\app\api\routes\local_test.py`: passed.
- `.venv\Scripts\python.exe -m pytest v2-api\tests\test_local_simulation.py::test_unmatched_dedupe_removes_duplicate_meter_records -q`: `1 passed, 1 warning`.
- `.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -q`: `45 passed, 1 warning`.
- `vue-tsc --noEmit`: passed.
- `powershell -ExecutionPolicy Bypass -File scripts\build-vue-shell.ps1`: passed with existing Rollup PURE/chunk-size warnings.
- `python scripts\verify_vue_migration_gate.py --strict-native`: passed.
- `git diff --check`: passed; only CRLF conversion warnings were reported.
## 2026-06-23 - V3.0.0 exception group dispatch workflow

### Reason

Administrators needed to open exception material groups directly, assign selected exception groups to a constructor, and have the constructor receive a focused exception task card that leads into the existing construction collection workflow.

### Changed files

- `v2-api/app/services/local_simulation.py`
- `v2-api/tests/test_api.py`
- `v2-web/src/api/services.ts`
- `v2-web/src/views/ProjectBoardView.vue`
- `v2-web/src/views/ConstructionView.vue`
- version metadata files
- maintenance documentation

### Changes

- Made the project-board exception risk card open a searchable exception-group dialog.
- Added exception-group CSV export inside the dialog.
- Added administrator assign/unassign controls that create or reuse construction exception orders and assign them to a constructor.
- Added a constructor-side exception task entry on `/construction` when assigned exception orders exist.
- Opening an exception task enters the normal construction collection form and pre-fills existing meter, collector, module, address, exception note, and existing photos where available.
- Added a JSON repository helper used by exception-order assignment paths, closing a no-schema-change compatibility gap.
- Advanced the production version marker to `V3.0.0`.

### Impact

- No database schema change.
- No Alembic migration.
- Existing review, construction upload, and normal terminal assignment flows remain compatible.
- The exception task entry is conditional: constructors see it only when exception orders have been assigned to their account.

### Validation

- Target API regression for exception assignment: passed.
- Full API regression: `46 passed, 1 warning`.
- Vue typecheck: passed.
- Vue shell build: passed with existing Rollup PURE/chunk-size warnings.
- Vue migration gate: passed.
- `git diff --check`: passed with CRLF warnings only.
- Browser QA on a temporary local V3 service:
  - `/project-board` exception card opens the exception dialog.
  - Dialog shows exception rows, export, and assign controls.
  - `/construction` shows the assigned exception task card for the constructor.
  - Opening the exception task enters the collection form with collector/module values prefilled.
