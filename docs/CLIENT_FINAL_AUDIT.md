# V3.0.84 甲方发布审计

## 审计结论

V3.0.84 完成生产部署后，客户侧功能、发布包、生产备份、独立复审和健康检查证据统一记录在 `ops/releases/V3.0.84.md`。

最终打款前仍建议由项目负责人在浏览器里按演示脚本走一遍真实视觉确认，重点看页面高级感、现场数据展示和甲方关注的业务口径。

## 交付要求与证据

| 要求 | 当前证据 | 状态 |
| --- | --- | --- |
| 登录功能 | `/login` 页面、`/auth/login`、管理员与审阅员 demo 账号、生产环境禁用 demo 账号检查 | 已完成 |
| 管理端项目看板 | `/project-board`、项目进度总览、安装人员资料组占比、终端任务进度、固定页面清单 | 已完成 |
| 审阅端工作台 | `/task-hall`、只显示已领取任务、图片审阅、元数据展示、分类归档、审阅身份使用登录账号 `reviewer` | 已完成 |
| 演示图片保障 | `scripts/seed-client-demo-data.py`、本地静态演示图片 URL、审阅页优先打开可见图片 | 已完成 |
| 快捷键分类 | 数字键分类、Enter 归档、方向键切换照片/资料组、`archivePhoto` 流程已测试 | 已完成 |
| 任务领取 | `/claim-tasks`、按终端领取、仅有扫码/照片数据的终端可进入任务 | 已完成 |
| 异常处理 | `/project-board` 的扫码未匹配清单支持临时审阅、数据修正、重新扫码、二维码/OCR识别和人工确认；管理员确认候选后才生成或并入正式资料组 | 已完成 |
| 照片复核 | 扫码未匹配弹窗按服务器记录逐张查看和分类照片，不在临时审阅阶段创建正式资料组或占位终端 | 已完成 |
| 同步方案口径 | `/sync-config` 已改为停用说明页，明确第一版使用表格导入，不再暴露 token 输入框 | 已完成 |
| 甲方签收清单 | `docs/CLIENT_SIGNOFF_CHECKLIST.md`，列出可现场确认并签字的验收项 | 已完成 |
| 页面高级感 | 登录页重做，主页面固定导航清理，统一工作台视觉语言 | 已完成，需人眼最终确认 |
| 服务器部署准备 | `docs/SERVER_DEPLOYMENT_PREP.md`、Nginx 配置、systemd 服务、生产账号注意事项 | 已完成 |
| 发布包 | `build/server-release/module-manager-v2-server-3.0.84.zip` | 发布流程中 |

## 已运行验证

```powershell
.\scripts\run-client-acceptance-gate.ps1 -Version 3.0.84
```

结果：最终发布门禁、生产部署和线上验收结果见 `ops/releases/V3.0.84.md`。

```powershell
cd .\v2-api
..\.venv\Scripts\python.exe -m pytest tests -q
```

结果：以 `ops/releases/V3.0.84.md` 本轮记录为准，不沿用历史测试计数。

```powershell
.\scripts\run-client-demo.ps1 -NoOpen
```

结果：通过。覆盖登录、角色跳转、固定导航选中态、核心页面入口、审阅身份口径、同步停用说明、演示图片可见性、补图本地图片上传、补图页面无 URL 输入、生产环境禁用 demo 账号和部署文件存在性。

```powershell
.\.venv\Scripts\python.exe .\scripts\verify-static-pages.py
```

结果：通过。覆盖静态页面标题、关键文案、固定导航文本、乱码替换字符检查和内联脚本语法检查。

```powershell
.\.venv\Scripts\python.exe .\scripts\verify-production-readiness.py --example
```

结果：通过。确认 `.env.example`、Nginx、systemd 和服务器部署准备材料具备生产交接所需的关键配置项。

```powershell
.\.venv\Scripts\python.exe .\scripts\verify-client-release.py .\build\server-release\module-manager-v2-server-3.0.84.zip
```

结果：以 `ops/releases/V3.0.84.md` 记录的实际大小、SHA256 和验包结论为准。

## 发布包

```text
build/server-release/module-manager-v2-server-3.0.84.zip
```

## 演示顺序

1. 打开 `/login`，展示管理员和审阅员角色入口。
2. 管理员进入 `/project-board`，展示项目进度、任务进度、安装人员占比和补图入口。
3. 进入 `/claim-tasks`，展示按终端领取任务。
4. 进入 `/task-hall`，展示已领取任务、图片审阅、快捷键分类和归档。
5. 进入 `/project-board` 的扫码未匹配清单，打开一条记录完成临时审阅、修正、重新识别和人工确认。
6. 管理员确认候选终端后完成匹配，才生成或并入正式资料组；审阅员不执行最终匹配。
7. 打开 `/sync-config`，说明供应商 API 不可用，第一版以表格导入为准。
8. 展示 `ops/releases/V3.0.84.md`，核对生产备份、发布目录、回滚目录和线上健康检查。

## 剩余风险

- V3.0.84 只有在生产备份、部署、健康检查和页面验收全部完成后才可标记为公网生产基线。
- 生产账号、密钥、HTTPS 和数据库备份已纳入生产配置与安全审计，后续变更必须按生产 SOP 执行。
- 人工补图长期存储仍建议接 OSS/S3，减少对本地静态目录的依赖。
- 页面视觉高级感已做代码层打磨，但最终仍应以负责人现场浏览器观感为准。
