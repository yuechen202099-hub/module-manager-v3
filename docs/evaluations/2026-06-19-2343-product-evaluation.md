# 产品评价报告 2026-06-19

## 基本信息

| 项目           | 值                                                     |
| ------------ | ----------------------------------------------------- |
| 项目根目录        | C:\Users\Administrator\Desktop\2025模块改造\模块更换项目管理器V2.0 |
| 评价时间         | 2026-06-19 23:43:17 +0800                             |
| 状态文件         | 未找到                                                   |
| 用户文件         | 未找到                                                   |
| 团队数          | unknown                                               |
| 用户数          | unknown                                               |
| 终端任务数        | unknown                                               |
| 资料组数         | unknown                                               |
| 照片索引数        | unknown                                               |
| 审计/事件数       | unknown                                               |
| Python 测试文件数 | 9                                                     |
| 静态页面数        | 12                                                    |
| Python 文件数   | 67                                                    |
| 文档文件数        | 28                                                    |
| 当前预算         | 130 元                                                 |

## 自动检查结果

| 检查项                                                                                                                                 | 结果 | 说明                                                                                                              |
| ----------------------------------------------------------------------------------------------------------------------------------- | -- | --------------------------------------------------------------------------------------------------------------- |
| Vue 页面登记                                                                                                                            | 通过 | native=7，legacy=0；legacy 页面：无                                                                                   |
| PostgreSQL 仓储                                                                                                                       | 通过 | 检测 PostgresStateRepository                                                                                      |
| dual 仓储                                                                                                                             | 通过 | 检测 DualWriteStateRepository                                                                                     |
| STATE_BACKEND 配置                                                                                                                    | 通过 | 检测 json/dual/postgres 切换入口                                                                                      |
| 照片级去重字段                                                                                                                             | 通过 | 检测 fingerprint/url_hash/import_batch/is_active                                                                  |
| Alembic 迁移                                                                                                                          | 通过 | 3                                                                                                               |
| OSS 存储服务                                                                                                                            | 通过 | 检测 photo_storage.py                                                                                             |
| C:\Users\Administrator\Desktop\2025模块改造\模块更换项目管理器V2.0\.venv\Scripts\python.exe scripts/verify_vue_migration_gate.py                 | 通过 | [OK] Vue shell and static page registry are wired. / [INFO] registered pages: 7 / [INFO] legacy bridge pages: 0 |
| C:\Users\Administrator\Desktop\2025模块改造\模块更换项目管理器V2.0\.venv\Scripts\python.exe scripts/verify_vue_migration_gate.py --strict-native | 通过 | [OK] Vue shell and static page registry are wired. / [INFO] registered pages: 7 / [INFO] legacy bridge pages: 0 |

## 自动扣分上限

- 已具备 PostgreSQL/dual 仓储基础，但在 `STATE_BACKEND=postgres` 验证前，数据结构不得按完全去 JSON 化计分。

## 本次修改范围

生产登记静态页全量迁入 Vue，并补强 dual 写入镜像基础

## 评分表

| 项目      | 权重 | 本次分数 | 加权分 | 评价重点                             |
| ------- | -- | ---- | --- | -------------------------------- |
| 工程管理适配度 | 8  | 待评分  | 待计算 | 现场施工、审阅、异常闭环、终端任务管理              |
| 产品结构    | 7  | 待评分  | 待计算 | 角色主流程、页面职责、管理边界                  |
| 审阅效率    | 8  | 待评分  | 待计算 | 快捷键、切组、归档、补图、异常回退                |
| 施工采集体验  | 8  | 待评分  | 待计算 | 手机采集、扫码、拍照、缓存、上传                 |
| 离线缓存能力  | 6  | 待评分  | 待计算 | 断网缓存、详情编辑、统一上传、失败重试              |
| 数据结构    | 9  | 待评分  | 待计算 | 团队、任务、资料组、照片、事件、异常工单             |
| 代码结构    | 8  | 待评分  | 待计算 | 职责边界、状态仓库、队列、存储抽象                |
| 前端结构    | 6  | 待评分  | 待计算 | 组件、响应式、图片预览、状态同步、卡顿控制            |
| 小程序结构   | 5  | 待评分  | 待计算 | 移动端采集规则与网页同步                     |
| 服务器结构   | 6  | 待评分  | 待计算 | Nginx、FastAPI、PostgreSQL、备份、服务守护 |
| 图片存储结构  | 6  | 待评分  | 待计算 | OSS/local/url、缩略图、预览图、导出图        |
| 安全权限    | 6  | 待评分  | 待计算 | 团队隔离、角色权限、上传访问、生产密钥              |
| 运维备份    | 5  | 待评分  | 待计算 | 备份、恢复、健康检查、磁盘风险、回滚               |
| 可观测性    | 4  | 待评分  | 待计算 | 日志、导入导出进度、异常统计、卡顿定位              |
| 测试覆盖    | 4  | 待评分  | 待计算 | 单元、接口、移动端、导出校验                   |
| 成本控制    | 4  | 待评分  | 待计算 | 预算 130 元内运行、OSS 和服务器成本控制         |

总分：待计算

等级：待判定

## 85+ 硬门槛检查

- Vue 原生生产入口：通过，生产登记页均为原生 Vue。
- `python scripts/verify_vue_migration_gate.py --strict-native`：通过。
- PostgreSQL 作为事实源：待验证，已检测到 PostgreSQL/dual 仓储基础，但仍需切到 `STATE_BACKEND=postgres` 并完成回归。
- JSON 仅作为备份/迁移兼容：待验证，需确认生产 `STATE_BACKEND=postgres` 后不再把 JSON 作为事实源。
- 照片级导入去重与软删除字段：通过字段检查，仍需导入回归。
- 核心链路回归测试：待验证，需记录实际运行的导入、审阅、施工上传、异常回退、导出测试。

## 优势

- 待填写。

## 不足

- 待填写。

## 高风险问题

- 待填写。

## 不增加预算的升级路径

1. 待填写。

## 验证记录

- 待填写：列出实际运行的测试、手测页面、导入导出、移动端检查。

## 变更记录

- 待填写。

## 下次评价触发条件

- 下一次生产发布前后。
- 涉及导入、审阅、施工采集、异常工单、导出、权限、存储、部署的改动完成后。
- 当周有正式业务数据进入系统时。
