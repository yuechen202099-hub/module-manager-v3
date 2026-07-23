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

---

## Independent Review Remediation

### RED

- 先扩展 `scripts/test_verify_client_release.py`，加入 env 变体、密钥证书、数据库/dump 和 coverage/test 目录的大小写回归样例，并要求两个 V3.2.0 主页面源码。
- `python -m pytest scripts\test_verify_client_release.py -q`：exit 1，`18 failed, 210 passed, 1 warning`；失败准确覆盖两个主页面缺失及 17 个原先会被验包器接受的禁止路径，混合大小写 `__PyCaChE__/*.pyc` 已由旧后缀规则拒绝。
- 同步先扩展 `scripts\verify_v3_2_0_release.py` 后运行；exit 1，准确报告主页面、`V3.x.y` 正式生产命名空间、V3.2.0 签收段，以及打包/验包对称排除规则缺失。

### 修复

- `scripts/build-client-release.ps1` 与 `scripts/verify-client-release.py` 统一使用大小写归一化规则排除 `.env`/`.env.*`、`pem/key/p12/pfx`、`sql/dump/sqlite/sqlite3/db`，以及任意层级的 coverage/test 产物目录；源码复制后和 Vue 构建后均执行清理。
- `.env.example` 不再进入正式包的复制清单或必需文件清单。
- 两个门禁均强制包含 `v2-web/src/views/GlobalSearchView.vue` 和 `v2-web/src/views/ExportsView.vue`。
- `AGENTS.md` 正式生产命名空间改为 `V3.x.y`，保留 `MP-V1.0.xx` 与 `PM-V1.0.xx` 独立规则。
- `docs/CLIENT_SIGNOFF_CHECKLIST.md` 候选验证和生产记录改为 V3.2.0，Task 9 证据继续使用待填占位。
- `scripts/verify_v3_2_0_release.py` 锁定上述全部复审要求。

### GREEN

- `python -m pytest scripts\test_verify_client_release.py -q`：`228 passed, 1 warning`；warning 为重复 ZIP entry 安全回归的预期构造。
- 五个 V3.2.0 功能专项门禁：全部通过。
- `python scripts\verify_v3_2_0_release.py`：通过。
- `python scripts\test_verify_release_sop.py`：`283 passed`。
- `python scripts\verify-client-release.py --help`：exit 0。
- PowerShell parser：`scripts/build-client-release.ps1` 语法通过。
- `npm run type-check`：通过。
- `npm run build`：通过，`1679 modules transformed`；正式静态产物保持 V3.2.0 且无内容差异。
- `git diff --check`：通过。

### Remediation Concerns

- Task 9 仍需在干净提交上执行正式服务器打包/验包并填写真实包路径、SHA256、备份/release 目录和线上健康证据。
- Vite 仅保留既有 VueUse PURE 注释与大 chunk warning，无本轮新增阻断。

---

## Remediation Round 2

### RED

- 在 `scripts/test_verify_client_release.py` 新增两个嵌套 `.env.*`、嵌套 `.venv` 和嵌套 `build` ZIP 回归。
- 首次运行 `python -m pytest scripts\test_verify_client_release.py -q`：exit 1，`2 failed, 230 passed, 1 warning`；仅 `config/.env.production/settings.json` 与 `nested/.ENV.LOCAL/key.txt` 穿透，`.venv` 和 `build` 已由 ZIP 侧旧集合拒绝。
- 先增强 `scripts/verify_v3_2_0_release.py` 后运行：exit 1，准确报告 build 集合缺少 `.venv`/`build`、ZIP 集合额外包含 `.env`，并报告两侧缺少统一逐组件分类函数。
- 初版 PowerShell 分类器真实运行时因 Windows PowerShell 5.1 不支持 `Path.GetRelativePath` 失败；固化为自动回归后，聚焦测试为 `1 failed, 232 deselected`。

### 修复

- build cleanup 与 ZIP verifier 现在共享严格相等的三组策略：17 个禁止目录名、12 个禁止文件后缀和 3 个禁止文件名；release gate 解析 PowerShell 数组和 Python literal set 后逐组精确比较。
- 两侧都先统一路径分隔符与大小写，再检查每一级组件的精确目录名及 `.env`/`.env.*`，最后仅对叶文件检查禁止名称和后缀。
- build 目录集合补齐 `.venv` 与 `build`；ZIP 集合移除冗余 `.env` 精确项，统一交由逐组件 env 规则处理，并删除旧 prefix-only 分支。
- PowerShell 分类器使用 5.1 兼容的绝对路径前缀校验和 `Substring` 相对化，同时拒绝 staging 外路径；目录和文件清理均调用同一分类函数。
- `scripts/verify_v3_2_0_release.py` 将算法断言限定在两个分类函数体内，确认 cleanup/verify_package 实际调用分类器，并禁止旧 prefix-only 与 `GetRelativePath` 实现回归。

### GREEN

- PowerShell build classifier 聚焦回归：`1 passed, 232 deselected`。
- `python -m pytest scripts\test_verify_client_release.py -q`：`233 passed, 1 warning`；warning 为重复 ZIP entry 安全回归的预期构造。
- `python scripts\verify_v3_2_0_release.py`：通过。
- `python scripts\test_verify_release_sop.py`：`283 passed`。
- `git diff --check`：通过。

### Round 2 Concerns

- Task 9 仍需在干净提交上执行正式服务器打包/验包并填写真实路径、SHA256、备份/release 目录和线上健康证据。
- 本轮唯一 warning 是既有重复 ZIP entry 测试的预期构造，无新增阻断。

---

## Remediation Round 3

### RED

- 在 `scripts/test_verify_client_release.py` 新增两个语义门禁回归，分别将 Python classifier 和真实 PowerShell classifier 人工退化为 leaf-only。
- 首次运行 `python -m pytest scripts\test_verify_client_release.py -q -k "v320_semantic_gate_rejects_leaf_only"`：exit 1，`2 failed, 233 deselected`；两项均明确失败于 `verify_v3_2_0_release.py` 尚无双端 classifier 实际执行入口。

### 修复

- `scripts/verify_v3_2_0_release.py` 定义一份共享语义 fixtures：Round 2 的四个嵌套禁止路径、3 个代表性禁止后缀/文件名路径，以及 1 个允许的 Vue 源码路径。
- Python 侧编译并执行真实 `scripts/verify-client-release.py` 源码，再逐 fixture 调用 `is_forbidden_release_path`。
- PowerShell 侧从真实 `scripts/build-client-release.ps1` 提取三组数组和 `Test-ForbiddenReleasePath` 函数，生成临时 PowerShell harness，并对完全相同的 fixtures 实际执行。
- 语义门禁逐项检查两端是否符合 expected，并比较 Python/PowerShell 结果是否一致；任一端接受禁止路径、拒绝允许路径或两端分歧均失败。
- 保留三组集合的精确解析与相等比较；移除以函数体 marker 充当循环语义证明的检查，只保留 classifier 在 cleanup/verify_package 中的接线检查。
- leaf-only Python 与 leaf-only PowerShell 两种人工退化现在都会被嵌套 `.env.*` fixtures 拦截。

### GREEN

- leaf-only 聚焦回归：`2 passed, 233 deselected`。
- `python scripts\verify_v3_2_0_release.py`：通过，实际执行双端 classifier。
- `python -m pytest scripts\test_verify_client_release.py -q`：`235 passed, 1 warning`；warning 为重复 ZIP entry 安全回归的预期构造。
- `python scripts\test_verify_release_sop.py`：`283 passed`。
- `git diff --check`：通过。

### Round 3 Concerns

- Task 9 仍需在干净提交上执行正式服务器打包/验包并填写真实路径、SHA256、备份/release 目录和线上健康证据。
- 本轮唯一 warning 是既有重复 ZIP entry 测试的预期构造，无新增阻断。
