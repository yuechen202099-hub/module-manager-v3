# V3.2.0 生产发布审计

## 审计结论

V3.2.0 已完成版本面、发布门禁、正式 Vue 构建、完整后端回归、独立复审、发布包校验、生产备份、迁移与线上验收。完整证据统一记录在 `ops/releases/V3.2.0.md`。

最终打款前仍建议由项目负责人在浏览器里按演示脚本走一遍真实视觉确认，重点看页面高级感、现场数据展示和甲方关注的业务口径。

## 交付要求与证据

| 要求 | 当前证据 | 状态 |
| --- | --- | --- |
| 登录功能 | `/login` 页面、`/auth/login`、管理员与施工员角色、生产环境禁用 demo 账号检查 | 已完成 |
| 管理端项目看板 | `/project-board`、项目进度总览、安装人员资料组占比、终端任务进度、固定页面清单 | 已完成 |
| 数据中台审阅 | `/global-search`、资料组平铺、服务端筛选、图片审阅、分类归档、管理员审计 | 已完成 |
| 演示图片保障 | `scripts/seed-client-demo-data.py`、本地静态演示图片 URL、数据中台按需打开可见图片 | 已完成 |
| 快捷键分类 | 数字键分类、Enter 归档、方向键切换照片/资料组、`archivePhoto` 流程已测试 | 已完成 |
| 任务派发 | `/claim-tasks`、管理员按终端派发/改派施工并设置优先施工 | 已完成 |
| 异常处理 | `/global-search` 的未匹配证据支持临时审阅、数据修正、重新扫码、二维码/OCR识别和人工确认；管理员确认候选后才生成或并入正式资料组 | 已完成 |
| 统一导出 | `/exports` 提供终端交付、设备清单、业务清单、统计报表和导出任务 | 已完成 |
| 照片复核 | 扫码未匹配弹窗按服务器记录逐张查看和分类照片，不在临时审阅阶段创建正式资料组或占位终端 | 已完成 |
| 同步方案口径 | `/sync-config` 已改为停用说明页，明确第一版使用表格导入，不再暴露 token 输入框 | 已完成 |
| 甲方签收清单 | `docs/CLIENT_SIGNOFF_CHECKLIST.md`，列出可现场确认并签字的验收项 | 已完成 |
| 页面高级感 | 登录页重做，主页面固定导航清理，统一工作台视觉语言 | 已完成，需人眼最终确认 |
| 服务器部署准备 | `docs/SERVER_DEPLOYMENT_PREP.md`、Nginx 配置、systemd 服务、生产账号注意事项 | 已完成 |
| V3.2.0 正式发布包 | `build/server-release/module-manager-v2-server-3.2.0.zip` | 已生成、验包并上线 |

## 已运行验证

```powershell
.\scripts\run-client-acceptance-gate.ps1 -Version 3.2.0
```

结果：门禁通过，生产验收结果已写入 `ops/releases/V3.2.0.md`。

```powershell
cd .\v2-api
..\.venv\Scripts\python.exe -m pytest tests -q
```

结果：`1782 passed, 13 skipped`。

```powershell
.\scripts\run-client-demo.ps1 -NoOpen
```

结果：管理员/施工员角色跳转、数据中台、导出中心、施工采集、同步停用说明和生产环境禁用 demo 账号均已复验。

```powershell
.\.venv\Scripts\python.exe .\scripts\verify-static-pages.py
```

结果：通过。覆盖静态页面标题、关键文案、固定导航文本、乱码替换字符检查和内联脚本语法检查。

```powershell
.\.venv\Scripts\python.exe .\scripts\verify-production-readiness.py --example
```

结果：通过。确认 `.env.example`、Nginx、systemd 和服务器部署准备材料具备生产交接所需的关键配置项。

```powershell
.\.venv\Scripts\python.exe .\scripts\verify-client-release.py .\build\server-release\module-manager-v2-server-3.2.0.zip
```

结果：正式 ZIP 已绑定提交 `fe527eb84064096321e727abf9ccbdc981e10b7e`，167 个必需文件校验通过，SHA256 为 `9448EDDCA27A36F2DF606EC1BC04A3BED05930B3D4D718E2D10381EE7FAEE6DF`。

## 发布包

```text
build/server-release/module-manager-v2-server-3.2.0.zip
```

## 演示顺序

1. 打开 `/login`，展示管理员和施工员角色入口。
2. 管理员进入 `/project-board`，展示项目进度、任务进度、安装人员占比和补图入口。
3. 进入 `/claim-tasks`，展示管理员按终端派发和改派施工。
4. 进入 `/global-search`，展示资料组平铺、组合筛选、图片审阅和快捷键分类。
5. 从 `/project-board` 点击统计项下钻到带筛选条件的数据中台。
6. 进入 `/exports`，展示终端交付、设备清单、业务清单、统计报表和任务记录。
7. 打开一条未匹配证据完成临时审阅、修正、重新识别和人工确认，管理员确认后才生成或并入正式资料组。
8. 展示 `ops/releases/V3.2.0.md`，核对发布包、备份、release 目录和线上健康证据。

## 剩余风险

- V3.2.0 是当前公网生产基线，生产 release 为 `/opt/module-manager-v2/releases/v3.2.0-20260724_105649`。
- 生产账号、密钥、HTTPS 和数据库备份已纳入生产配置与安全审计，后续变更必须按生产 SOP 执行。
- 人工补图长期存储仍建议接 OSS/S3，减少对本地静态目录的依赖。
- 交付缓存仍有 4 条失败记录，但无待处理缓存；后续按现有后台维护机制复核失败原因。
