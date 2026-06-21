# BUG_HISTORY

Last updated: 2026-06-21

本文件只记录维护期 Bug 和风险线索。后续修复时只追加或更新相关条目，不重复扫描全项目。

## 当前开放问题

| ID | Bug / 风险 | 复现方式 | 修复状态 | 修复时间 | 涉及文件 |
| --- | --- | --- | --- | --- | --- |
| BH-0001 | 历史文档和部分兼容源文件存在旧编码乱码片段 | 打开部分历史 docs 或旧兼容文件可见乱码 | 观察中；不影响当前生产功能时不主动修 | - | `docs/`、部分旧兼容入口 |
| BH-0002 | 图片链路曾出现灰图、半图、加载慢问题，需按具体图片来源定位 | 审阅工作台打开特定 OSS/外部 URL/本地上传图片 | 观察中；后续遇到具体图片 URL 再局部定位 | - | `photo_storage.py`、`local_test.py`、`TaskHallView.vue`、`services.ts` |
| BH-0003 | 施工采集缓存和异常补图链路涉及 Web 与小程序两端，容易一端修复另一端遗漏 | 异常工单补图后检查施工页缓存、缓存上传、小程序缓存队列 | 观察中；后续按具体截图/日志定位 | - | `ConstructionView.vue`、`v2-miniprogram/miniprogram/**` |

## 已修复问题

| ID | Bug | 复现方式 | 修复状态 | 修复时间 | 涉及文件 |
| --- | --- | --- | --- | --- | --- |
| BH-0101 | 项目看板左上版本号 `V2.4.11` 显示不全 | 打开生产 `/project-board`，左上角品牌版本徽标被裁切 | 已修复 | 2026-06-21 | `v2-web/src/styles/base.css`、`v2-web/src/styles/main.css` |
| BH-0102 | 终端任务进度只显示前 12 个终端 | 打开项目看板，终端任务表只有前 12 条 | 已修复，全量显示并支持排序 | 2026-06-21 | `v2-web/src/views/ProjectBoardView.vue` |
| BH-0103 | 终端任务表缺少上传率和多字段升降序排序 | 项目看板终端任务表无法按上传率、审阅率、已归档、未审阅等字段排序 | 已修复 | 2026-06-21 | `ProjectBoardView.vue`、`services.ts`、`types.ts` |
| BH-0104 | 账号管理未显示登录 IP 和登录设备 | 项目看板账号管理表只显示账号/姓名/团队/角色/状态/最近登录 | 已修复 | 2026-06-21 | `auth.py`、`account_store.py`、`ProjectBoardView.vue` |
| BH-0105 | 安装人员占比无法查看每日工作量并导出 KPI | 点击安装人员占比区域无明细弹窗 | 已修复，新增每日工作量弹窗和 CSV 导出 | 2026-06-21 | `local_test.py`、`local_simulation.py`、`state_repository.py`、`ProjectBoardView.vue` |
| BH-0106 | 系统状态缺少版本号，“数据文件”含义不清 | 项目看板系统状态只显示服务、磁盘、数据文件、最近备份 | 已修复，新增版本号和说明 | 2026-06-21 | `ops_status.py`、`ProjectBoardView.vue` |
| BH-0107 | 独立缓存上传页和异常处理页仍有旧入口风险 | 访问 `/construction-cache` 或 `/unmatched` 可能进入旧独立页面 | 已修复，统一重定向到施工采集/审阅工作台 | 2026-06-21 | `main.py`、`router/index.ts`、`TaskHallView.vue` |
| BH-0108 | PowerShell 中文输出可能误导源码编码判断 | PowerShell 默认编码显示中文时出现乱码 | 已处理，新增 UTF-8 初始化脚本 | 2026-06-21 | `setup_terminal_utf8.ps1` |

## 处理规则

- 新 Bug 必须先补充复现方式，再写修复方案。
- 修复完成后更新“修复状态、修复时间、涉及文件”。
- 不记录测试账号、密码、Token、密钥。
- PowerShell 显示乱码优先按终端编码处理，不直接认定为业务 Bug。
