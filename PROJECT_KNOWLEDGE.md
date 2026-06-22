# PROJECT_KNOWLEDGE

Last full scan: 2026-06-21
Current known version: V2.5.2
Active maintenance baseline: latest repository version
Maintenance mode: active

## 项目用途

本项目是“模块更换项目管理器 V2”生产系统，用于电表/模块改造项目的多人协作管理。

核心业务包括：

- 导入总清单和扫码表格。
- 按表号/条码规则匹配资料组。
- 按终端组织任务。
- 审阅员领取终端任务并对照片进行快捷键分类归档。
- 管理员查看项目看板、任务进度、风险数据、账号和安装人员 KPI。
- 施工员在网页端或微信小程序端进行施工采集、扫码录入、拍照、缓存和上传。
- 处理异常资料组、补图、回退未施工、生成异常表计和终端交付包。

当前阶段是维护、优化和修复 Bug，不是重新开发。

## 技术架构

- 后端：FastAPI、Pydantic、SQLAlchemy、Alembic。
- 前端：Vue 3、TypeScript、Vite、Pinia、Vue Router、Element Plus。
- 小程序：微信小程序原生结构，复用后端施工采集接口。
- 数据库：PostgreSQL 是当前目标事实源；历史上保留 JSON 状态桥接。
- 图片存储：支持本地上传目录和 OSS/S3 风格对象存储。
- 部署：Nginx 反代 FastAPI，systemd 管理服务，生产服务器保留 release 快照和 runtime 备份。
- 兼容层：`/local-test/...` API 仍是大量 Vue 页面使用的业务接口，不代表只用于测试。

## 核心模块

- `v2-api/app/main.py`
  - FastAPI 应用入口。
  - 生产环境关闭 `/docs`、`/redoc`、`/openapi.json`。
  - Vue 页面入口和旧路由重定向。
  - 生产环境 API 鉴权中间件。

- `v2-api/app/api/routes/`
  - `auth.py`：登录、账号管理、JWT。
  - `local_test.py`：当前主要业务 API，包括看板、导入、任务、审阅、施工、异常、图片代理。
  - `exports.py`：任务明细、最终交付、异常表计导出。
  - `catalog.py`、`scan.py`、`tasks.py`、`groups.py`：较正式的 API 表面。

- `v2-api/app/services/`
  - `state_repository.py`：JSON/PostgreSQL 仓储抽象和大量业务读写。
  - `local_simulation.py`：历史 JSON 状态业务逻辑，体量大、风险高。
  - `spreadsheet_import.py`：扫码/照片表格解析。
  - `photo_storage.py`：本地/OSS 图片存储、签名、预览、缩略图 URL。
  - `account_store.py`：账号文件存储和登录信息。
  - `ops_status.py`：系统状态、版本、磁盘、数据文件大小。

- `v2-api/app/models.py`
  - PostgreSQL 模型：teams、users、roles、tasks、material_groups、photos、events、jobs、unmatched_records 等。

- `v2-web/src/`
  - `views/ProjectBoardView.vue`：项目看板、导入、账号、系统状态、KPI。
  - `views/ClaimTasksView.vue`：任务领取。
  - `views/TaskHallView.vue`：审阅工作台，含异常处理入口。
  - `views/ConstructionView.vue`：施工采集和缓存上传合并页面。
  - `views/SyncConfigView.vue`：历史导入配置说明。
  - `api/services.ts`：前端 API 适配、下载导出、终端包 ZIP、图片代理。
  - `router/staticPages.ts`：当前生产 Vue 页面注册。

- `v2-miniprogram/`
  - 微信小程序施工采集端。
  - 主要页面：login、tasks、groups、collect、cache。
  - 主要工具：`utils/api.js`、`utils/config.js`、`utils/photo.js`、`utils/queue.js`。

## 文件结构

```text
AGENTS.md                         项目必读、版本规则、协作边界
README.md                         项目说明和验收命令
docker-compose.yml                本地容器编排
infra/                            systemd 与 Nginx 示例
scripts/                          构建、验收、备份、评估脚本
docs/                             产品、数据库、设计、运维、评估、迁移文档
v2-api/                           FastAPI 后端
v2-api/app/static/                旧静态 HTML、Vue 构建产物、上传目录入口
v2-api/alembic/                   PostgreSQL 迁移
v2-api/tests/                     后端测试
v2-web/                           Vue 前端源码
v2-miniprogram/                   微信小程序源码
build/、exports/、logs/、uploads/  构建、导出、日志、运行产物；不要作为业务源码修改
```

## 数据流

1. 登录与权限
   - 用户通过 `/auth/login` 获取 JWT。
   - 前端同时保存 Vue token 和兼容会话 `module_manager_session`。
   - 生产环境访问 `/local-test`、`/projects`、`/catalog`、`/scan`、`/tasks`、`/groups`、`/exports`、`/jobs`、`/ezcodes` 需要 Bearer Token。

2. 总清单导入
   - 管理员在项目看板导入总清单。
   - 总清单是安装地址唯一来源。
   - 安装地址不去重，和表号/资料组一一对应。

3. 扫码表格导入
   - 管理员导入包含表号、采集器、模块、照片 URL、安装人员等字段的表格。
   - 后端根据条码/短表号规则生成 `meter_match_key`。
   - 匹配成功的记录进入资料组和照片索引；未匹配记录进入未匹配/异常相关流程。
   - 导入应按照片级去重，避免重复导入和重复下载。

4. 审阅
   - 审阅员按终端领取任务。
   - 审阅工作台加载资料组和照片。
   - 快捷键分类照片，整组归档或转异常/回退未施工。
   - 异常处理已合并到审阅工作台，不再作为独立页面。

5. 施工采集
   - 管理员按终端指派施工任务。
   - 施工员只处理被指派终端。
   - 网页和小程序端支持扫码、拍照、压缩、本地缓存、统一上传。
   - 施工采集和缓存上传在同一个施工页面内处理。

6. 图片
   - 外部 URL、服务器本地上传、OSS 对象都可成为照片引用。
   - 列表应优先用缩略图/预览图，大图或导出按后端解析的 URL 或缓存取图。
   - 已归档组可在服务器本地静默缓存交付图片，后续导出减少重复远程读取。

7. 导出
   - 异常表计导出为 Excel。
   - 单终端交付包由前端下载图片并打包 ZIP。
   - 当前策略拒绝全量项目图片打包，优先单终端导出。

## 关键依赖

后端：

- fastapi
- uvicorn
- pydantic / pydantic-settings
- sqlalchemy
- alembic
- psycopg
- python-jose
- python-multipart
- openpyxl
- oss2
- Pillow

前端：

- vue
- vue-router
- pinia
- element-plus
- @element-plus/icons-vue
- axios
- vite
- typescript
- vue-tsc

小程序：

- 微信小程序原生 API。
- `wx.request`、`wx.uploadFile`、`wx.scanCode`、本地缓存队列。

## 风险模块

- `v2-api/app/services/local_simulation.py`
  - 历史逻辑集中，函数多、耦合高。
  - 修改时必须只动当前问题相关函数，不做大范围重构。

- `v2-api/app/services/state_repository.py`
  - JSON/PostgreSQL 双路径桥接层。
  - 新接口必须确认 JSON 和 PostgreSQL 后端行为一致。

- 图片加载链路
  - 涉及 OSS 签名、本地代理、预览图、缩略图、浏览器缓存、导出缓存。
  - 处理灰图、半图、加载慢时，先定位具体 URL/接口/响应内容。

- 施工采集离线缓存
  - Web 端 IndexedDB/localStorage 和小程序缓存队列都可能参与。
  - 不要只修一端而忘记同步原则。

- 审阅快捷键与队列排序
  - 审阅效率依赖键盘流程、当前组/当前图焦点、自动滚动。
  - 修 Bug 时要验证快捷键和鼠标路径都不退化。

- 账号与会话兼容
  - Vue token 与旧 `module_manager_session` 兼容并存。
  - 前端请求头主要依赖兼容会话，修登录问题时要同时检查两类存储。

- 生产部署
  - 当前服务器使用 systemd + Nginx。
  - 发版前要备份 current、data、.env、uploads、PostgreSQL dump。
  - `/openapi.json` 在生产应为 404。

- 历史文档和部分旧兼容源文件
  - 存在旧编码遗留片段。
  - 不要因为 PowerShell 或历史文档显示乱码就直接修改业务代码。

## 已知问题

- 历史文档中存在部分旧编码乱码片段；除非影响当前可见 UI 或维护判断，否则不作为业务 Bug 扩大处理。
- `local_simulation.py` 和 `state_repository.py` 体量大，Bug 修复时应小范围定位。
- 旧 Ezcodes 后台同步逻辑仍存在，但产品主流程已改为表格导入，不应恢复为核心路径。
- 静态 HTML 是兼容面；Vue 是当前生产目标。静态 HTML 已隐藏/取消的功能默认取消。
- 生产使用 OSS、本地上传和外部 URL 混合图片来源，图片问题要按具体来源分层排查。

## 维护原则

1. 第一次接手项目时允许完整扫描项目并建立项目认知。
2. 建立项目认知后，禁止重复扫描整个项目。
3. 后续修 Bug 时，优先读取 PROJECT_KNOWLEDGE.md、BUG_HISTORY.md、FIX_NOTES.md。
4. 不要重构已经稳定运行的功能。
5. 不要擅自修改无关代码。
6. 不要因为一个 Bug 大范围改动项目架构。
7. 优先采用影响范围最小、风险最低的修复方案。
8. 保持现有 UI、交互逻辑、数据库结构和接口协议不变，除非我明确要求。
9. 每次处理问题时，先分析原因，再给出修复方案。
10. 如果信息不足，不要猜测整个项目结构，而是明确告诉我需要查看哪些文件。
11. 只关注当前问题相关代码，不要重新审查整个项目。
12. 默认项目其他功能均正常工作。
13. 每次修复完成后，只增量更新项目认知文档，不重复全项目扫描。
14. PowerShell 中文乱码属于终端编码问题，优先修复终端编码，不作为业务代码 Bug 处理。
15. 运行 PowerShell 命令前，优先执行 setup_terminal_utf8.ps1。
16. 不要因为 PowerShell 显示乱码而误判源码编码问题。
17. 不要将测试账号、密码、Token、密钥写入日志或文档。
18. 不要把敏感配置提交到 Git。
19. 版本号规则：大改动 `+0.1.0`，小改动 `+0.0.1`。
20. 后续回答按用户指定结构输出：问题分析、需要查看、修复方案、修改文件、影响范围、风险等级、验证步骤。
21. 后续 Bug 修复默认只读这三个维护文档和相关局部代码，不再全项目扫描。
22. 后续维护默认只读取和处理仓库当前最新版本，不主动读取旧版本、历史 release 或旧静态页面；只有用户明确要求回滚、对比或追溯时才查看历史版本。
