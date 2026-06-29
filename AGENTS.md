# 项目协作入口

## Production SOP Override

- Current production baseline: `V3.0.70`.
- Production maintenance branch: `production/V3/3.0.70`.
- Production SOP entrypoint: `docs/sop/README.md`.
- Production release records: `ops/releases/`.
- P0 incident records: `ops/incidents/`.
- Documentation/SOP-only changes do not bump the application version.
- Runtime changes follow the version rule: small feature or bug fix `+0.01`, major workflow change `+0.1` after user confirmation.

## 生产底线

- 禁止覆盖生产 `.env`。
- 禁止覆盖生产 `data`。
- 禁止覆盖生产 `uploads`。
- 禁止直接修改 OSS 生产对象，除非用户单独确认任务和回滚方案。
- 禁止直接修改 PostgreSQL 生产数据，除非用户单独确认数据库方案、备份、dry-run 和回滚方案。
- 禁止在未确认备份、验证和回滚路径前执行生产发布。
- 生产服务器 release 目录只保留最近 5 个可回滚版本；旧版本以 GitHub tag/branch 和 `ops/releases/` 为长期留档。清理旧 release 前必须 dry-run，且不得触碰 `.env`、data、uploads、backups 或数据库 dump。

## 当前基线

- 当前应用基线：`V3.0.70`。
- 当前生产分支：`production/V3/3.0.70`。
- 生产分支命名规则：`production/V3/<version>`，例如 `production/V3/3.0.70`。旧 `production/v3.0.35` 仅保留历史兼容，不作为新开发基线。
- 文档和协作规则使用独立规则版本，不自动修改应用版本。
- 详细生产 SOP 见 `docs/sop/README.md`。

## 工作方式

- 默认由 Codex 作为总执行者：读取上下文、拆解任务、修改、验证、记录、汇报。
- 普通代码修复和小功能直接执行并验证。
- 高风险动作必须先获得用户明确确认：生产发布异常流程、数据库迁移、数据修复、删除文件、大范围重构、权限规则变更、核心业务规则变更、版本号大版本或 minor 升级。
- 所有生产发布都要在 `ops/releases/` 下建立版本记录；P0 事故要在 `ops/incidents/` 下建立复盘记录。
- 默认中文输出；命令、路径、版本号、接口名和代码标识可保留英文。

## 必读和代码发现

- 每次改动前先读取本文件和与任务相关的文档。
- 新 agent 接手前必须读取 `docs/AGENT_REQUIRED_READING.md`，它记录当前生产分支、版本基线、插件/skill、发布边界和常用验证命令。
- 推荐优先使用 codebase-memory-mcp 图谱工具理解代码；图谱不可用或结果不足时，直接使用 `rg`、文件读取和本地测试。
- 修改前尊重当前工作区状态，不回退用户已有改动，除非用户明确要求。

## 核心业务硬规则

- 总清单是安装地址的唯一来源。
- 安装地址不得去重；安装地址、表号和资料组保持一对一业务关系。
- 页面展示表号使用总清单原始表号。
- 长扫码条码匹配键：去掉前 11 位和最后 1 位。
- 总清单短表号匹配键：去掉前 2 位。
- 导入照片行保留 URL 引用，不把表格照片下载到本地磁盘作为业务源数据。
- 手动补图使用本地图片上传；上传结果作为正常照片 URL/OSS key 记录参与审阅和导出。
- 照片分类必须保持快捷键优先，不能把快捷键降级为可选体验。
- 已分类照片归档文件名等于分类标签，并使用合适的文件扩展名。
- 旧 Ezcodes 后端同步代码仅作为兼容和调试能力，不作为主流程依赖，不围绕供应商 API 可用性设计验收标准。

## 前端和客户端规则

- Vue 是目标生产前端。
- `v2-api/app/static/*.html` 只作为兼容入口，不新增生产静态 HTML 页面。
- 涉及前端路由或静态兼容入口时，按风险运行 `python scripts/verify_vue_migration_gate.py`。
- 微信小程序后端接口已在 `V3.0.69` 纳入生产线；小程序前端、APK 或平台扩展不得直接改生产分支，必须从当前生产分支切独立功能分支并通过交接/PR 进入生产维护流程。

## 验证和发布

- 验证按风险选择：小改跑相关测试或检查；核心流程改动跑对应后端、前端、浏览器或脚本验证；发布前跑构建和生产健康检查。
- 普通代码改动测试、构建、生产健康检查通过后可自动发布。
- 数据库迁移、数据修复、`.env`、`uploads`、OSS、PostgreSQL、生产数据相关动作不得自动发布，必须单独确认。
- 代码改动默认自动升 patch 版本；大改、数据库、架构、主流程变化先询问用户确认版本策略。
- 文档或协作规则修改不升应用版本，只更新规则版本或规则记录。

## 最终报告

最终报告使用中文，包含：

- 需求
- 修改文件
- 验证结果
- 版本变化
- 发布状态
- 风险
