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
