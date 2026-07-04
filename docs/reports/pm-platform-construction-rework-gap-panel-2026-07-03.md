# PM 平台施工退回补采清单报告

## 摘要

本包把审阅退回后的平台工单，在施工采集侧展示为结构化的“退回补采清单”。施工员不再只能看到一段退回原因，而是能看到需要补齐的字段或照片分组。

本包同时固化设备更换层级语义：

- 换模块：在一个任务对象下更换附属设备。
- 换终端：先记录主设备更换，再确认通讯模块、SIM 卡等附属设备是否同步更换。
- 当附属设备确认选择“更换”但旧件、新件或照片缺失时，退回补采清单会保留这些层级缺口。

## 基线

- 生产基线分支：`production/V3/3.0.77`
- 生产基线提交：`4c05cc9`
- 平台开发分支：`pm-platform/production-3.0.77-sync`
- 当前本地 HEAD：`6892205`

## 修改文件

- `v2-api/app/services/platform/templates.py`
- `v2-web/src/api/types.ts`
- `v2-web/src/api/services.ts`
- `v2-web/src/views/ConstructionView.vue`
- `scripts/verify_platform_construction_rework_gap_panel.py`
- `scripts/verify_vue_construction_rework_gap_panel.js`
- `docs/superpowers/plans/2026-07-03-construction-rework-gap-panel.md`
- `docs/reports/pm-platform-construction-rework-gap-panel-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Generated Vue static assets under `v2-api/app/static/vue/`

## 功能说明

- 后端施工工单 payload 新增 `rework_evidence_gap_groups`。
- 只有 `review_status == returned` 的工单会返回补采组，普通待采集、待审阅或已通过工单不显示返工清单。
- 补采组会合并三类缺口：
  - `导入层级缺口`：来自外部已完成数据导入时保留下来的层级/条件字段缺失。
  - `缺少字段`：当前项目配置里仍需现场补采的必填字段。
  - `缺少照片`：当前项目配置里仍需现场补拍的必填照片。
- 前端施工页新增 `退回补采清单` 面板，并在平台接入工单卡片上展示首个缺口组摘要。
- 更换终端样例已覆盖“主设备更换 + 附属设备是否更换 + 条件补采旧件/新件/照片”的关系。

## 验证

- 红灯确认：
  - `python scripts\verify_platform_construction_rework_gap_panel.py` 先失败于缺少 `rework_evidence_gap_groups`。
  - `node scripts\verify_vue_construction_rework_gap_panel.js` 先失败于缺少 `PlatformReworkEvidenceGapGroup`。
- 新守卫通过：
  - `python scripts\verify_platform_construction_rework_gap_panel.py` - `[OK] construction rework gap panel payload is available`
  - `node scripts\verify_vue_construction_rework_gap_panel.js` - `[OK] Vue construction rework gap panel is wired.`
- 回归通过：
  - `python scripts\verify_platform_review_return_reason_suggestions.py`
  - `node scripts\verify_vue_review_return_reason_suggestions.js`
  - `python scripts\verify_platform_review_hierarchy_gap_followup.py`
  - `node scripts\verify_vue_construction_submit_gap_preview.js`
  - `python scripts\verify_platform_construction_required_collection.py`
  - `node scripts\verify_vue_device_replacement_hierarchy_mode.js`
  - `python scripts\verify_platform_device_replacement_hierarchy_mode.py`
- 构建通过：
  - `pnpm --dir v2-web build`
  - 仅出现既有 VueUse PURE 注解和 chunk size 警告。
- 浏览器冒烟通过：
  - `http://127.0.0.1:52147/construction?project_id=draft-project`
  - 页面正常加载，施工采集页可见“主设备更换”“附属设备确认”“条件补采”等层级。
  - 本次页面相关控制台错误数为 0。
- 安全检查通过：
  - `python scripts\verify_pm_platform_team_operating_model.py`
  - `git diff --check`
  - 敏感路径扫描 `.env`、`data`、`uploads`、dump、压缩包、数据库文件无输出。

## 风险

低风险。此包只扩展本地平台工单 payload 和前端展示，不写入生产数据库，不修改 OSS，不触发部署，不创建 tag，不占用正式版本号。

潜在产品风险是：退回补采清单依赖项目字段配置的 `relation_role`、`parent_key` 和 `required_when` 是否配置准确。若项目配置把附属设备字段平铺，清单仍会显示缺口，但层级解释会弱一些。

## 迁移说明

无数据库迁移。现有本地 JSON 平台工单可以继续读取；旧工单没有 `review_hierarchy_gap_items` 时，补采清单会退化为当前字段/照片必采缺口。

## 回滚建议

如需回滚，删除 `_platform_rework_evidence_gap_groups` 和 payload 字段，移除前端 `reworkEvidenceGapGroups` 映射及施工页补采面板，删除两条守卫脚本和本报告，然后重新执行前端构建。无需数据回滚。
