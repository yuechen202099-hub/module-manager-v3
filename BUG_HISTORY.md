# BUG_HISTORY

Last updated: 2026-06-24

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
| BH-0139 | 管理员缺少集中入口查看人工换表后已匹配到资料组的记录 | 在 `/project-board` 完成未匹配资料换表匹配后，只能从交付资料包备注间接看到换表结果，无法集中查看旧表号/新表号/地址/资料组 | 已在 `V3.0.4` 本地修复并通过关键回归、类型检查和构建；生产发布需继续满足备份、健康检查和 patch sync 规则 | 2026-06-24 | `ProjectBoardView.vue`、`services.ts`、`types.ts`、`local_test.py`、`local_simulation.py`、`state_repository.py` |
| BH-0138 | 换表场景下如果只按新表号处理，会导致未匹配资料需要人工线下补地址，交付资料包缺少旧表号说明 | 在 `/project-board` 打开未匹配资料弹窗，现场换表扫码资料携带新表号时，旧版本无法直接输入旧表号匹配总清单地址，最终资料包也没有换表备注 | 已在 `V3.0.3` 本地修复并通过关键回归、类型检查和构建；生产发布需继续满足备份、健康检查和 patch sync 规则 | 2026-06-24 | `ProjectBoardView.vue`、`local_simulation.py`、`state_repository.py`、`test_local_simulation.py` |
| BH-0134 | 管理员施工进度只显示未施工数量，不能下钻查看清单 | 管理员打开 `/construction`，终端卡只能看到“未施工数”，无法直接核对未施工表号和地址 | 已修复，本地类型检查和构建通过 | 2026-06-23 | `v2-web/src/views/ConstructionView.vue` |
| BH-0101 | 项目看板左上版本号 `V2.4.11` 显示不全 | 打开生产 `/project-board`，左上角品牌版本徽标被裁切 | 已修复 | 2026-06-21 | `v2-web/src/styles/base.css`、`v2-web/src/styles/main.css` |
| BH-0102 | 终端任务进度只显示前 12 个终端 | 打开项目看板，终端任务表只有前 12 条 | 已修复，全量显示并支持排序 | 2026-06-21 | `v2-web/src/views/ProjectBoardView.vue` |
| BH-0103 | 终端任务表缺少上传率和多字段升降序排序 | 项目看板终端任务表无法按上传率、审阅率、已归档、未审阅等字段排序 | 已修复 | 2026-06-21 | `ProjectBoardView.vue`、`services.ts`、`types.ts` |
| BH-0104 | 账号管理未显示登录 IP 和登录设备 | 项目看板账号管理表只显示账号/姓名/团队/角色/状态/最近登录 | 已修复 | 2026-06-21 | `auth.py`、`account_store.py`、`ProjectBoardView.vue` |
| BH-0105 | 安装人员占比无法查看每日工作量并导出 KPI | 点击安装人员占比区域无明细弹窗 | 已修复，新增每日工作量弹窗和 CSV 导出 | 2026-06-21 | `local_test.py`、`local_simulation.py`、`state_repository.py`、`ProjectBoardView.vue` |
| BH-0106 | 系统状态缺少版本号，“数据文件”含义不清 | 项目看板系统状态只显示服务、磁盘、数据文件、最近备份 | 已修复，新增版本号和说明 | 2026-06-21 | `ops_status.py`、`ProjectBoardView.vue` |
| BH-0107 | 独立缓存上传页和异常处理页仍有旧入口风险 | 访问 `/construction-cache` 或 `/unmatched` 可能进入旧独立页面 | 已修复，统一重定向到施工采集/审阅工作台 | 2026-06-21 | `main.py`、`router/index.ts`、`TaskHallView.vue` |
| BH-0108 | PowerShell 中文输出可能误导源码编码判断 | PowerShell 默认编码显示中文时出现乱码 | 已处理，新增 UTF-8 初始化脚本 | 2026-06-21 | `setup_terminal_utf8.ps1` |
| BH-0109 | 施工采集页手机端点击扫码后相机无响应 | 手机端打开施工采集页，点击采集器/模块扫码，弹层打开后相机未启动或降级拍照无响应 | 已修复，本地构建通过；生产发布交给有 SSH 密钥权限的项目工程师线程 | 2026-06-21 | `v2-web/src/views/ConstructionView.vue` |
| BH-0110 | 施工采集页扫码弹层可能停留在“正在启动相机”且无预览 | 手机端 HTTPS 打开施工采集，点击采集器/模块扫码，QuaggaJS 初始化卡住时黑框不切换到真实相机画面 | 已修复，增加相机启动超时和原生预览兜底；现场反馈相机已能打开 | 2026-06-21 | `v2-web/src/views/ConstructionView.vue` |
| BH-0111 | 施工采集“已缓存”筛选混入异常工单，上传按钮显示范围过宽 | 打开施工采集页，异常工单带本地草稿时出现在“已缓存”；未处于已缓存筛选时仍可见上传入口 | 已修复，本地类型检查和构建通过 | 2026-06-21 | `v2-web/src/views/ConstructionView.vue` |

## 处理规则

- 新 Bug 必须先补充复现方式，再写修复方案。
- 修复完成后更新“修复状态、修复时间、涉及文件”。
- 不记录测试账号、密码、Token、密钥。
- PowerShell 显示乱码优先按终端编码处理，不直接认定为业务 Bug。

## 2026-06-21 - Added maintenance item

| ID | Bug | Reproduction | Status | Fixed at | Files |
| --- | --- | --- | --- | --- | --- |
| BH-0112 | Claim task page exposed obsolete construction open/close actions and the primary `领取` label could become unreadable after the card visual cleanup. | Open `/claim-tasks` as admin; task cards showed construction open/close actions in older builds, and the primary button text inherited muted card text styles. | Fixed in `V2.4.13`. | 2026-06-21 | `v2-web/src/views/ClaimTasksView.vue`, `v2-web/src/styles/main.css` |

## 2026-06-22 - V2.4.15 maintenance fixes

| ID | Bug | Reproduction | Status | Fixed at | Files |
| --- | --- | --- | --- | --- | --- |
| BH-0113 | Review-to-exception work orders lost collector/module values on the mobile construction page. | In review workspace, return a group to exception order; open the assigned exception order in construction collection. Collector/module fields could be empty even though the reviewed group already had values. | Fixed and folded into the combined `V2.5.0` release. | 2026-06-22 | `v2-api/app/services/state_repository.py`, `v2-web/src/api/services.ts`, `v2-web/src/api/types.ts`, `v2-web/src/views/ConstructionView.vue` |
| BH-0114 | Review thumbnail strip could show thumbnails as failed when the proxy thumbnail endpoint failed. | Open review workspace for a group whose thumbnail proxy URL fails while direct preview/source URLs still exist. | Fixed and folded into the combined `V2.5.0` release. | 2026-06-22 | `v2-web/src/views/TaskHallView.vue` |
| BH-0115 | Installer daily workload dates used photo import/storage timestamps instead of scan or construction upload business time. | Open project board installer KPI; imported scan data could cluster on import dates such as 6-19/6-20. | Fixed and folded into the combined `V2.5.0` release. | 2026-06-22 | `v2-api/app/services/local_simulation.py`, `v2-api/app/services/state_repository.py` |

## 2026-06-22 - Workflow risk covered by V2.5.0 feature work

| ID | Risk | Reproduction | Status | Fixed at | Files |
| --- | --- | --- | --- | --- | --- |
| BH-0116 | Unmatched address records and exception groups were passive records instead of assignable field tasks. | Reviewers/admins could see unmatched or exception data, but field handling required separate manual coordination and had no project-outside export or replacement-meter rematch workflow. | Covered by the combined `V2.5.0` release. | 2026-06-22 | `local_simulation.py`, `state_repository.py`, `local_test.py`, `exports.py`, `services.ts`, `types.ts`, `TaskHallView.vue` |

## 2026-06-22 - V2.5.2 construction mobile task-card click-through hotfix

| ID | Bug | Reproduction | Status | Fixed at | Files |
| --- | --- | --- | --- | --- | --- |
| BH-0118 | Construction mobile permanent field-task cards could open the field-task list but fail to enter the related collection task. | Open `/construction` on mobile, tap the permanent exception or unmatched task card added in V2.5.1, then tap a listed field task. Records without a direct task id or cards tapped outside the small action button might not enter the terminal collection view. | Fixed locally in `V2.5.2`; pending project-engineer production publish. | 2026-06-22 | `v2-web/src/views/ConstructionView.vue` |

## 2026-06-22 - V2.5.3 installer KPI exception drilldown

| ID | Request | Reproduction | Status | Fixed at | Files |
| --- | --- | --- | --- | --- | --- |
| BH-0119 | Project board installer workload popup showed daily exception counts but could not open the underlying abnormal groups. | Open `/project-board`, click an installer in the installer distribution panel, then inspect the daily workload table; the exception count was only a number. | Released through the `V2.5.4` production patch; exception counts now open a daily abnormal group detail dialog. | 2026-06-22 | `local_simulation.py`, `state_repository.py`, `services.ts`, `types.ts`, `ProjectBoardView.vue` |

## 2026-06-22 - V2.5.4 construction upload installer name hotfix

| ID | Bug | Reproduction | Status | Fixed at | Files |
| --- | --- | --- | --- | --- | --- |
| BH-0120 | Construction uploads used the account username as installer/creator instead of the user's display name. | Log in as a constructor account whose name differs from username, upload construction photos, then check installer KPI or group photo creator. The installer was grouped by username. | Released in `V2.5.4` by production patch sync. | 2026-06-22 | `local_test.py`, `local_simulation.py`, `state_repository.py`, `test_api.py` |

## 2026-06-22 - V2.5.1 UX maintenance

| ID | Bug / UX issue | Reproduction | Status | Fixed at | Files |
| --- | --- | --- | --- | --- | --- |
| BH-0117 | Review and construction field-task workflows were not exposed as stable task cards, and some Element Plus labels were vertically off-center inside cards. | Open `/task-hall` or `/construction`; unmatched/exception work was shown as a secondary mixed section or hidden behind terminal context, and compact tags such as `可审阅` could appear visually high/low in their pill. | Fixed in `V2.5.1`. | 2026-06-22 | `TaskHallView.vue`, `ConstructionView.vue`, `element-plus.css`, `main.css` |

## 2026-06-22 - V2.5.5 historical construction creator backfill

| ID | Bug | Reproduction | Status | Fixed at | Files |
| --- | --- | --- | --- | --- | --- |
| BH-0121 | Construction photos uploaded before V2.5.4 can still have `creator` saved as the constructor account username, so installer KPI remains split by account id until old rows are backfilled. | Open installer distribution or group photo details for historical construction uploads created before V2.5.4; old photos can still show username. | Released in `V2.5.5`; production dry-run matched only constructor `xa` -> `樊哲浩`, then applied PostgreSQL `211` rows and JSON compatibility state `54` rows. | 2026-06-22 | `backfill_construction_creator_names.py`, `test_backfill_construction_creator_names.py` |
## 2026-06-22 - V2.5.6 construction assignment rule change

| ID | Request / Risk | Reproduction | Status | Fixed at | Files |
| --- | --- | --- | --- | --- | --- |
| BH-0122 | The old one-terminal-per-constructor rule blocks field work when one constructor needs to handle multiple nearby terminals. PostgreSQL also had a partial unique index that would still reject a second assignment even after code changes. | Assign one terminal to a constructor, then try to assign a second terminal to the same constructor. Old behavior rejected the second assignment. | Fixed locally in `V2.5.6`; rule is now max 5 active terminal tasks per constructor. Production deployment must run Alembic migration `20260622_0004` before using the new capacity. | 2026-06-22 | `local_simulation.py`, `state_repository.py`, `0004_allow_five_construction_tasks.py`, `test_api.py`, `v2-miniprogram/miniprogram/**` |

## 2026-06-22 - V2.5.7 claim task search

| ID | Request / Risk | Reproduction | Status | Fixed at | Files |
| --- | --- | --- | --- | --- | --- |
| BH-0123 | The task claiming page required terminal/address search; without it, users had to scan the full terminal card grid manually. | Open `/claim-tasks` with many terminal cards and try to find a specific terminal or installation address. | Fixed locally in `V2.5.7`; the claim task page now filters role-visible tasks by terminal number, task id, and full task address index. | 2026-06-22 | `ClaimTasksView.vue`, `main.css`, `services.ts`, `types.ts`, `local_simulation.py`, `state_repository.py`, `test_api.py` |

## 2026-06-22 - V2.5.8 installer KPI work time

| ID | Request / Risk | Reproduction | Status | Fixed at | Files |
| --- | --- | --- | --- | --- | --- |
| BH-0124 | Installer KPI needed start/end time and effective work duration; using only daily counts cannot support fair KPI assessment. Long idle gaps must not be counted as effective work. | Open `/project-board`, click an installer workload popup, and inspect daily KPI rows. Older versions only showed counts and exception drilldown, with no work start/end, effective duration, or hourly distribution. | Released in `V2.5.8`; daily workload now returns start/end, effective work duration, attendance span, hourly work segments, and excludes gaps over 60 minutes from effective duration. | 2026-06-22 | `local_simulation.py`, `state_repository.py`, `services.ts`, `types.ts`, `ProjectBoardView.vue`, `test_api.py` |

## 2026-06-22 - V2.6.0 installer KPI efficiency model

| ID | Request / Risk | Reproduction | Status | Fixed at | Files |
| --- | --- | --- | --- | --- | --- |
| BH-0125 | KPI chart needed 2-hour dimensions, completion trend, per-effective-hour output, and clickable address evidence. Raw counts alone could reward easy concentrated jobs or penalize harder scattered/charging-pile jobs unfairly. | Open `/project-board`, click an installer, then click a daily work duration. Older chart only showed hourly work minutes and could not inspect address difficulty or completion efficiency. | Fixed locally in `V2.6.0`; chart now uses 2-hour segments, adds completion line, per-hour completion and weighted efficiency, and each segment opens an address list with explainable difficulty weights. | 2026-06-22 | `local_simulation.py`, `state_repository.py`, `services.ts`, `types.ts`, `ProjectBoardView.vue`, `test_api.py` |

## 2026-06-22 - V2.6.1 installer KPI PostgreSQL field hotfix

| ID | Bug | Reproduction | Status | Fixed at | Files |
| --- | --- | --- | --- | --- | --- |
| BH-0126 | Personnel KPI popup failed on PostgreSQL-backed production data because the workload address drilldown referenced non-existent `MaterialGroup.meter_no` and `MaterialGroup.address` fields. | Open `/project-board`, click an installer in the installer distribution panel. Production PostgreSQL path could return a 500 error before the daily workload dialog rendered. | Fixed locally in `V2.6.1`; PostgreSQL workload now uses `display_meter_no` and `installation_address`, with a regression test. | 2026-06-22 | `state_repository.py`, `test_state_repository.py` |

## 2026-06-22 - V2.6.2 installer KPI chart visual refinement

| ID | UX issue | Reproduction | Status | Fixed at | Files |
| --- | --- | --- | --- | --- | --- |
| BH-0127 | Personnel KPI work-time popup looked visually noisy and the completion line chart was hard to read. | Open `/project-board`, click an installer, then click a daily work-time value. V2.6.0/V2.6.1 displayed a thick completion line above the bars, making the popup feel cluttered. | Fixed locally in `V2.6.2`; the line chart was removed and the chart was restyled as a quieter Apple Screen Time style 2-hour bar view with direct completion labels and address drilldown preserved. | 2026-06-22 | `ProjectBoardView.vue` |

## 2026-06-22 - V2.6.3 安装人员 KPI 同楼栋地址聚类

| ID | 问题 / 风险 | 复现方式 | 修复状态 | 修复时间 | 涉及文件 |
| --- | --- | --- | --- | --- | --- |
| BH-0128 | 安装人员 KPI 地址权重可能把同一楼栋拆散：一条是住户地址，另一条是公用设备时，同楼栋公用设备会被计算得像零散地址。 | 构造同一天 KPI 数据，包含 `95弄18号201室`、`95弄18号公用设备`、`95弄19号公用设备`；旧逻辑可能只依赖后缀裁剪，没有优先把 `95弄18号` 作为共享楼栋键。 | 已在 `V2.6.3` 本地修复；地址聚类会优先使用 `弄+号` / `号` 作为楼栋键，再处理室号、公用设备等后缀。 | 2026-06-22 | `local_simulation.py`, `test_api.py` |

## 2026-06-22 - V2.6.4 permanent field task cards removed

| ID | UX issue | Reproduction | Status | Fixed at | Files |
| --- | --- | --- | --- | --- | --- |
| BH-0129 | The permanent exception/unmatched task cards made the review workbench and construction collection task list noisy after those workflows were folded back into normal handling. | Open `/task-hall` or `/construction`; the always-visible exception/unmatched cards appeared before normal terminal tasks. | Fixed locally in `V2.6.4`; the permanent entry cards were removed while the underlying APIs/data remain unchanged. | 2026-06-22 | `TaskHallView.vue`, `ConstructionView.vue` |

## 2026-06-22 - V2.6.5 construction task submit button

| ID | UX issue | Reproduction | Status | Fixed at | Files |
| --- | --- | --- | --- | --- | --- |
| BH-0130 | After a constructor finished field collection, there was no explicit submit action to release the assigned terminal, so the task kept occupying the construction collection page. | Log in as a constructor, open `/construction`, finish uploading a terminal's construction data, then try to mark the terminal task complete. Older UI only had refresh/back/logout actions. | Fixed locally in `V2.6.5`; the selected assigned terminal now has a submit button that calls the existing construction release API, warns about local cache/unbuilt groups, and refreshes the task picker. | 2026-06-22 | `ConstructionView.vue`, `services.ts`, `test_api.py` |

## 2026-06-23 - V3.0.0-rc1 construction completion-time accounting

| ID | Bug / Risk | Reproduction | Status | Fixed at | Files |
| --- | --- | --- | --- | --- | --- |
| BH-0131 | Construction KPI and daily workload could use the server upload time instead of the field-side completion time. When offline cache is uploaded later, this shifts work to the wrong date/time window and distorts KPI. | Cache a completed construction group in the field, upload it later, then inspect installer daily workload or 2-hour efficiency. Old behavior could count the server upload timestamp. | Fixed locally for `V3.0.0-rc1`; Web and mini-program uploads send `client_completed_at` from the last valid cache time, backend stores it in photo raw metadata, and KPI prefers it. Missing or invalid values fall back to server upload time. No database schema change. | 2026-06-23 | `ConstructionView.vue`, `services.ts`, `types.ts`, `local_test.py`, `local_simulation.py`, `state_repository.py`, `test_api.py`, `test_state_repository.py`, `v2-miniprogram/**` |

## 2026-06-23 - V3.0.0-rc1 missing collector photo quality exception

| ID | Bug / Risk | Reproduction | Status | Fixed at | Files |
| --- | --- | --- | --- | --- | --- |
| BH-0132 | Construction upload completeness and review quality completeness used the same 4-photo rule, so missing collector barcode photos could either block field upload too aggressively or fail to become a clear quality exception. | Upload a construction group with `before_box`, `module_meter`, and `after_box` but without `collector_barcode`, then inspect review exceptions and project-board counts; old behavior did not distinguish upload-required photos from quality-required photos. | Fixed locally for `V3.0.0-rc1`; upload now requires only `before_box`, `module_meter`, and `after_box`; missing `collector_barcode` uploads successfully but auto-marks the group with `missing_collector_photo` / `缺采集器照片`. Adding the collector photo clears that auto exception; deleting it marks it again. No database schema change. | 2026-06-23 | `local_simulation.py`, `state_repository.py`, `test_api.py`, `test_state_repository.py` |
## 2026-06-23 - V3.0.0-rc1 missing collector photo production deployment

BH-0132 was deployed to production on 2026-06-23 as commit `9f3fc67` by patch sync into the current `V3.0.0-rc1` release.

- Backup path: `/opt/module-manager-v2/backups/runtime/20260623_180532_before_v3_missing_collector_patch`
- PostgreSQL dump: `/opt/module-manager-v2/backups/runtime/20260623_180532_before_v3_missing_collector_patch/postgres.dump`
- No Alembic migration was executed.
- Production `.env`, `data`, and uploads were preserved.

## 2026-06-23 - V3.0.0-rc2 施工采集无效缓存占位工单

| ID | 问题 / 风险 | 复现方式 | 修复状态 | 修复时间 | 涉及文件 |
| --- | --- | --- | --- | --- | --- |
| BH-0133 | 手机施工端扫码打开工单后，可能出现表号 `0000000000`、地址“待导入总清单地址”的本地缓存卡片，且施工员无法删除。异常工单草稿也可能被普通“已缓存”列表混入。 | 在 `/construction` 打开已指派终端，扫码或弱网缓存后切换到“已缓存”，可看到无照片、仅有模块号的占位卡片；点击后没有删除缓存入口。 | 已在 `V3.0.0-rc2` 本地修复；普通缓存列表只显示普通施工缓存，明显无效占位草稿会自动删除，真实单条缓存可手动删除。 | 2026-06-23 | `ConstructionView.vue` |
## 2026-06-23 - Project-board unmatched list and duplicate cleanup

| ID | Request / Risk | Reproduction | Status | Fixed at | Files |
| --- | --- | --- | --- | --- | --- |
| BH-0135 | Unmatched scan records could accumulate duplicate items after repeated imports, and project managers had to leave the project board to inspect or export the unmatched list. | Open `/project-board`, inspect the `扫码未匹配` risk number, then try to view/export details or remove duplicate unmatched rows. Older UI only showed the count. | Fixed locally; the project-board risk card opens a searchable unmatched-list dialog with CSV export and a duplicate cleanup action. Backend JSON/PostgreSQL repositories now expose a no-schema-change unmatched dedupe operation. | 2026-06-23 | `ProjectBoardView.vue`, `services.ts`, `types.ts`, `local_test.py`, `local_simulation.py`, `state_repository.py`, `test_local_simulation.py` |
## 2026-06-23 - V3.0.0 exception group dispatch to construction

| ID | Request / Risk | Reproduction | Status | Fixed at | Files |
| --- | --- | --- | --- | --- | --- |
| BH-0136 | Exception material groups needed a direct management surface and a way to dispatch selected exception work back to constructors. Without this, administrators could see exception counts but had to rely on manual coordination, and constructors had no focused exception task entry. | Open `/project-board`, click the exception count, then try to inspect and assign exception groups; log in as a constructor and look for the assigned exception work. Older builds did not provide a project-board exception dispatch dialog and constructor task-card entry. | Fixed locally for `V3.0.0`; the project-board exception risk card opens a searchable exception-group dialog with CSV export and admin assign/unassign controls. Assigned constructors see an exception task card on `/construction`, and opening it enters the normal collection form with existing meter, collector, module, address, and photos prefilled where available. | 2026-06-23 | `ProjectBoardView.vue`, `ConstructionView.vue`, `services.ts`, `local_simulation.py`, `test_api.py` |

## 2026-06-23 - V3.0.0 总清单 10 位表号匹配规则修复

| ID | 问题 / 风险 | 复现方式 | 修复状态 | 修复时间 | 涉及文件 |
| --- | --- | --- | --- | --- | --- |
| BH-0137 | 总清单表号原逻辑只要长度大于 2 就去前 2 位，导致 10 位表号也被错误截断；施工端扫码或导入匹配时，明明未施工列表存在 `2004243564`，仍可能匹配不到。 | 总清单存在 10 位表号资料组，例如 `2004243564`；在施工采集页按 10 位表号或相关条码打开施工单，旧逻辑会把总清单侧变成 `04243564`，造成候选键不一致。 | 已本地修复：总清单表号长度为 12 位时才去前 2 位，长度为 10 位时保持原表号；前端施工扫码候选逻辑同步该规则。 | 2026-06-23 | `matching.py`, `test_matching.py`, `ConstructionView.vue` |
# V3.0.2 - 生产未匹配重匹配脚本导入错误

Date: 2026-06-23

## Symptom
- V3.0.1 发布后，生产执行未匹配重匹配 dry-run 失败：
  `ImportError: cannot import name 'state_repository' from 'app.services.state_repository'`

## Root Cause
- 维护脚本使用了不存在的旧仓储工厂名。

## Fix
- 改为导入并调用 `get_state_repository()`。
- 版本提升到 V3.0.2，避免重写已经发布的 V3.0.1 tag。

## Production Result
- V3.0.2 已发布到生产并完成未匹配维护重匹配。
- 同步修复生产历史数据中 10 位总清单 key 仍为旧规则的问题。
- `2004243564` spot check 通过。

# V3.0.1 - 总清单 10 位表号匹配规则与未匹配重匹配

- 日期：2026-06-23
- 类型：匹配规则 BUG 修复 / 生产维护
- 问题：总清单表号为 10 位时，旧规则仍按“去前 2 位”生成匹配 key，导致扫码资料进入未匹配列表。
- 修复：`build_total_catalog_match_key` 改为仅当总清单表号长度为 12 位时去前 2 位；10 位表号保持原样参与匹配。
- 维护：新增 `v2-api/scripts/rematch_unmatched_records.py`，支持 dry-run/apply，对生产未匹配记录按最新规则做一次维护性重匹配。
- 风险控制：脚本只移动唯一明确匹配成功的记录；找不到、歧义或失败记录继续保留在未匹配列表；照片补入沿用现有仓储去重逻辑。
