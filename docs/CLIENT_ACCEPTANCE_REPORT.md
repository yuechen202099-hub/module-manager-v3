# 甲方第一版验收报告

## 交付目标

本版本用于向甲方展示“模块更换项目管理器 V2.0”多人网页互通版。重点证明系统已经具备登录、项目看板、任务派发、数据中台审阅、异常处理、统一导出、演示自检和服务器部署准备能力。

## 演示入口

本地演示启动命令：

```powershell
.\scripts\run-client-demo.ps1
```

主要页面：

- 登录页：`http://127.0.0.1:8000/login`
- 项目看板：`http://127.0.0.1:8000/project-board`
- 数据中台：`http://127.0.0.1:8000/global-search`
- 任务派发：`http://127.0.0.1:8000/claim-tasks`
- 导出中心：`http://127.0.0.1:8000/exports`
- 未匹配处理：`http://127.0.0.1:8000/global-search` 中的未匹配证据筛选
- 同步方案说明：`http://127.0.0.1:8000/sync-config`

演示账号：

- 管理员：`admin / admin123`
- 施工员：`constructor / construct123`

生产部署时演示账号默认关闭，正式管理员账号由环境变量配置。

## 已完成能力

### 登录与角色

- 支持管理员和施工员登录。
- 管理员默认进入项目看板。
- 施工员进入施工采集和被指派的现场异常处理。
- 数据中台审阅和导出中心使用登录管理员作为审计身份。
- 管理页带角色保护，施工员不能访问数据中台、导出中心和账号管理。
- 生产环境默认禁用 demo 账号，避免把演示密码带到线上。

### 项目看板

- 展示项目整体进度、已扫码照片、已审阅资料组和风险分布。
- 展示安装人员资料组占比。
- 展示终端任务进度，包括改造数量、已上传数量、未审阅数量、上传率、审阅率和领取人。
- 顶部提供甲方演示五步流程：导入、发布任务、快捷键审阅、异常补图、导出交付。

### 表格导入与照片资料

- 主流程改为表格导入，不依赖供应商未公开 API。
- `/sync-config` 已改为同步方案停用说明页，不再引导输入 token 或后台请求 JSON。
- 表格导入的照片以 URL 和元数据形式保存，不下载到本地。
- 支持 Excel/CSV/JSON 行数据导入入口。
- 后端保留表号匹配和资料组补图逻辑。

### 任务派发与审阅

- 管理员按终端派发或改派施工任务，并可设置优先施工。
- 施工员只处理分配给自己的施工任务和现场异常。
- 管理员在数据中台按资料组平铺审阅，不再按终端领取审阅任务。
- 数据中台保留快捷键优先的照片分类与资料组切换操作。
- 分类后照片归档文件名使用分类名称。

### 异常处理与恢复

- 未匹配扫码数据可以由管理员处理。
- 未匹配页面会自动选中第一条待处理记录，方便甲方演示时直接看到详情和处理入口。
- 管理员在临时审阅中修正数据并确认候选终端后，才原子化生成或并入正式资料组。
- 临时审阅阶段不创建正式资料组、任务或占位终端。
- 缺照片资料组可以后续由管理员上传本地图片进行补图。
- 已审阅但资料组不完整时，补充新照片后可回到未审阅状态进行复核。

### 部署准备

- 已提供 Nginx 反代样例：`infra/nginx/module-manager-v2.conf`
- 已提供 systemd 服务样例：`infra/module-manager-v2.service`
- 已提供服务器部署准备文档：`docs/SERVER_DEPLOYMENT_PREP.md`
- 已提供甲方演示脚本：`docs/CLIENT_DEMO_SCRIPT.md`
- 已提供最终证据审计：`docs/CLIENT_FINAL_AUDIT.md`
- 已提供甲方签收清单：`docs/CLIENT_SIGNOFF_CHECKLIST.md`
- 已提供演示前自检脚本：`scripts/smoke-client-demo.py`
- 已提供静态页面校验脚本：`scripts/verify-static-pages.py`
- 已提供一键启动演示脚本：`scripts/run-client-demo.ps1`

## 验收命令

一键启动并自检：

```powershell
.\scripts\run-client-acceptance-gate.ps1
```

本命令会运行全量测试、静态页面校验、演示 smoke、发布包构建、发布包验包和临时补图测试文件清理。

仅启动演示服务并自检：

```powershell
.\scripts\run-client-demo.ps1 -NoOpen
```

仅运行演示自检：

```powershell
.\.venv\Scripts\python.exe .\scripts\smoke-client-demo.py
```

仅检查静态页面文案、固定导航、乱码和页面脚本语法：

```powershell
.\.venv\Scripts\python.exe .\scripts\verify-static-pages.py
```

完整自动化测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

生成 V3.2.0 候选服务器发布包：

```powershell
.\scripts\build-client-release.ps1 -Version 3.2.0 -PerformanceReport .\build\release-evidence\v3.2.0-task-review.json
```

发布包内会包含 `RELEASE_MANIFEST.md`，用于说明版本、生成时间、包含内容、排除项、验证命令和生产运维注意事项。

## 当前验证结果

V3.2.0 将审阅统一收口到数据中台，并新增驾驶舱下钻和统一导出中心。Task 8 本地证据与 Task 9 待填字段统一记录在 `ops/releases/V3.2.0.md`：

- V3.2.0 角色、数据中台、驾驶舱下钻、导出中心、单一导出入口和发布门禁通过。
- SOP 测试、前端类型检查和正式 Vue 构建通过。
- 正式发布包哈希、生产备份、线上健康检查和队列状态由 Task 9 填写。

## 生产运维注意事项

- 保持 `APP_ENV=production` 和 `DEMO_AUTH_ENABLED=false`，不得在生产环境启用演示账号。
- 账号、密钥和管理员凭据变更必须通过 `.env` 与生产安全审计，不得写入仓库。
- 保持 HTTPS、PostgreSQL 备份和发布前校验清单；每次发布只保留最近五个 release。
- 后续导入真实生产数据时，继续保留原始清单、导入日志和可恢复备份。

## 结论

V3.2.0 已完成 Task 8 本地发布准备，仍需 Task 9 完整回归、独立复审、打包和生产验收；当前公网生产基线保持 V3.1.1。
