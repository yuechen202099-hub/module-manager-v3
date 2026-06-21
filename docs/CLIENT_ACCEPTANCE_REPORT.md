# 甲方第一版验收报告

## 交付目标

本版本用于向甲方展示“模块更换项目管理器 V2.0”多人网页互通版的第一版工作流。重点证明系统已经具备登录、项目看板、任务领取、资料审阅、异常处理、补图恢复、演示自检和服务器部署准备能力。

## 演示入口

本地演示启动命令：

```powershell
.\scripts\run-client-demo.ps1
```

主要页面：

- 登录页：`http://127.0.0.1:8000/login`
- 项目看板：`http://127.0.0.1:8000/project-board`
- 审阅工作台：`http://127.0.0.1:8000/task-hall`
- 任务领取：`http://127.0.0.1:8000/claim-tasks`
- 未匹配处理：`http://127.0.0.1:8000/unmatched`
- 同步方案说明：`http://127.0.0.1:8000/sync-config`

演示账号：

- 管理员：`admin / admin123`
- 审阅员：`reviewer / review123`

生产部署时演示账号默认关闭，正式管理员账号由环境变量配置。

## 已完成能力

### 登录与角色

- 支持管理员和审阅员登录。
- 管理员默认进入项目看板。
- 审阅员默认进入审阅工作台。
- 审阅领取和归档使用登录账号 `reviewer` 作为审计身份，不再暴露本地调试审阅人。
- 管理页带角色保护，审阅员直接访问管理页会回到审阅工作台。
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

### 任务领取与审阅

- 任务按终端领取。
- 只有已有扫码/照片数据的终端进入任务。
- 审阅员只看自己已领取的任务。
- 支持快捷键分类：数字键选择分类，Enter 归档，方向键切换。
- 分类后照片归档文件名使用分类名称。

### 异常处理与恢复

- 未匹配扫码数据可以由管理员处理。
- 未匹配页面会自动选中第一条待处理记录，方便甲方演示时直接看到详情和处理入口。
- 管理员可以把未匹配记录创建为关联终端的资料组。
- 管理员可以新建空资料组后补内容。
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

生成甲方演示发布包：

```powershell
.\scripts\build-client-release.ps1
```

发布包内会包含 `RELEASE_MANIFEST.md`，用于说明版本、生成时间、包含内容、排除项、验证命令和上线前注意事项。

## 当前验证结果

最近一次验证通过：

- 演示启动脚本通过。
- 演示 smoke 自检通过。
- 演示 smoke 已覆盖登录、角色跳转、固定导航选中态、审阅身份口径、同步停用说明、补图本地图片上传、补图页面无 URL 输入和生产环境禁用 demo 账号。
- 全量测试通过：`91 passed, 1 warning`
- 页面脚本语法检查通过。
- 本地 `/health` 正常。

## 上线前注意事项

- 生产环境设置 `APP_ENV=production`。
- 生产环境设置 `DEMO_AUTH_ENABLED=false`。
- 更换 `APP_SECRET`、`JWT_SECRET`、`ADMIN_USERNAME`、`ADMIN_PASSWORD`。
- 启用 HTTPS。
- 配置 PostgreSQL 备份。
- 导入真实生产数据前，先保留原始清单和导入日志。

## 结论

本版本已经具备甲方第一版演示和阶段验收所需的核心闭环：登录、管理看板、任务领取、审阅分类、异常处理、补图恢复、部署准备和自动自检。后续生产上线主要工作是正式账号体系、服务器 HTTPS、数据库备份和真实数据导入。
