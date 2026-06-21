# 产品评价报告 2026-06-19

## 基本信息

| 项目           | 值                                                     |
| ------------ | ----------------------------------------------------- |
| 项目根目录        | C:\Users\Administrator\Desktop\2025模块改造\模块更换项目管理器V2.0 |
| 评价时间         | 2026-06-19 23:50:35 +0800                             |
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
| 文档文件数        | 29                                                    |
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

生产登记静态页全量迁入 Vue，dual 写入镜像基础完成，summary 接入仓储抽象

## 评分表

| 项目      | 权重 | 本次分数 | 加权分 | 评价重点                             |
| ------- | -- | ---- | --- | -------------------------------- |
| 工程管理适配度 | 8  | 90 | 7.20 | 施工、审阅、异常、终端任务已有闭环，但异常工单仍需继续细化 |
| 产品结构    | 7  | 89 | 6.23 | 管理员、审阅员、施工员主流程清晰，页面职责已从静态页收敛到 Vue |
| 审阅效率    | 8  | 87 | 6.96 | 快捷键、切图、归档路径可用，仍需继续做图片预加载和大图体验 |
| 施工采集体验  | 8  | 85 | 6.80 | 施工采集已迁 Vue，支持指派终端和槽位上传，扫码与压缩体验仍需回归 |
| 离线缓存能力  | 6  | 84 | 5.04 | 缓存页已 Vue 化并可读取 IndexedDB、统一上传，编辑能力仍需增强 |
| 数据结构    | 9  | 82 | 7.38 | PostgreSQL 模型、迁移、dual 写入和 summary 仓储已具备，但生产事实源未切换 |
| 代码结构    | 8  | 88 | 7.04 | Repository 边界扩大，前端 services 隔离后端字段，仍需清理旧静态实现 |
| 前端结构    | 6  | 90 | 5.40 | 7 个生产登记页全部 native Vue，strict-native 已通过 |
| 小程序结构   | 5  | 78 | 3.90 | 移动端规则与网页方向一致，但小程序端仍需与 Vue 页面保持同步验收 |
| 服务器结构   | 6  | 83 | 4.98 | 现有低成本部署可用，PostgreSQL 生产切换和恢复演练未完成 |
| 图片存储结构  | 6  | 85 | 5.10 | OSS、预览图、照片指纹字段已具备，仍需导入重复图片回归 |
| 安全权限    | 6  | 83 | 4.98 | 角色边界基本存在，仍需生产接口和图片访问权限审计 |
| 运维备份    | 5  | 80 | 4.00 | 已有备份/健康检查脚本方向，仍缺恢复演练记录 |
| 可观测性    | 4  | 78 | 3.12 | 导入任务和评价检查有进度记录，前端卡顿和失败链路还需更细日志 |
| 测试覆盖    | 4  | 78 | 3.12 | Vue 构建、strict-native、仓储测试通过，移动端和导出端到端仍不足 |
| 成本控制    | 4  | 92 | 3.68 | 当前仍在 130 元预算内，OSS 成本可控但需继续监控 |

总分：84.93

等级：B / 已逼近 85+，但 PostgreSQL 生产事实源未验证前，不按最终 85+ 完成交付。

## 85+ 硬门槛检查

- Vue 原生生产入口：通过，生产登记页均为原生 Vue。
- `python scripts/verify_vue_migration_gate.py --strict-native`：通过。
- PostgreSQL 作为事实源：待验证，已检测到 PostgreSQL/dual 仓储基础，但仍需切到 `STATE_BACKEND=postgres` 并完成回归。
- JSON 仅作为备份/迁移兼容：待验证，需确认生产 `STATE_BACKEND=postgres` 后不再把 JSON 作为事实源。
- 照片级导入去重与软删除字段：通过字段检查，仍需导入回归。
- 核心链路回归测试：待验证，需记录实际运行的导入、审阅、施工上传、异常回退、导出测试。

## 优势

- 生产登记页已经全部迁入 Vue，`strict-native` 门禁通过，正式上线后继续扩展前端不再依赖大型静态 HTML。
- `STATE_BACKEND=json/dual/postgres` 路径存在，dual 模式已从占位继承变成核心写操作镜像。
- 项目看板 `/summary` 已接入 Repository，postgres 模式可从数据库聚合核心看板统计。
- 图片存储字段、OSS 存储服务、照片级去重字段已具备继续工程化的基础。

## 不足

- PostgreSQL 还没有作为生产唯一事实源完成切换和回归。
- Vue 页面已替代静态入口，但部分页面是“核心可用版”，旧静态页里的细节能力还需要逐项组件化补齐。
- 移动端施工缓存详情编辑、扫码体验、图片压缩和大图查看仍需要端到端手测。
- 导出、异常工单回流、重复导入补图识别还缺完整生产数据回归。

## 高风险问题

- 如果继续以 JSON 为生产事实源，多人并发和恢复能力仍是主要风险。
- 如果 PostgreSQL 切换前不做生产副本演练，迁库失败时会影响正式审阅和施工节奏。
- 旧静态 HTML 虽不再是生产登记页，但仍在仓库中，后续维护时必须避免新功能回流到静态页。

## 不增加预算的升级路径

1. 用生产 JSON 副本跑一次 `migrate_json_to_postgres.py --dry-run` 和正式临时库迁移，记录数量校验。
2. 将测试环境设为 `STATE_BACKEND=dual` 跑 1 天核心流程，核对 JSON 与 PostgreSQL 写入差异。
3. 补 `PostgresStateRepository.summary/list_tasks/list_groups/review/classify/delete/reset/return` 的集成测试。
4. 测试环境切 `STATE_BACKEND=postgres`，完成导入、审阅、施工上传、异常回退、导出回归。
5. 生产低峰期备份后切换 `STATE_BACKEND=postgres`，JSON 只保留 7 天快照。

## 验证记录

- `powershell -ExecutionPolicy Bypass -File scripts\build-vue-shell.ps1`：通过。
- `.venv\Scripts\python.exe -m pytest v2-api\tests\test_state_repository.py v2-api\tests\test_postgres_migration.py`：8 passed。
- `.venv\Scripts\python.exe -m py_compile v2-api\app\services\state_repository.py v2-api\app\api\routes\local_test.py`：通过。
- `python scripts\verify_vue_migration_gate.py --strict-native`：通过，registered pages 7，legacy bridge pages 0。
- 乱码扫描：界面源文件未发现新增乱码；命中项仅为验证脚本中的乱码检测常量。

## 变更记录

- 新增 `ProjectBoardView.vue`、`ConstructionView.vue`、`ConstructionCacheView.vue`、`UnmatchedView.vue`、`SyncConfigView.vue`。
- `staticPages.ts` 中 7 个生产登记页全部标记为 `native_vue`。
- `state_repository.py` 增加 dual 写入镜像和 PostgreSQL summary 聚合。
- `/local-test/summary` 改为通过 Repository 获取，不再直接固定读取 JSON。

## 下次评价触发条件

- 下一次生产发布前后。
- 涉及导入、审阅、施工采集、异常工单、导出、权限、存储、部署的改动完成后。
- 当周有正式业务数据进入系统时。
