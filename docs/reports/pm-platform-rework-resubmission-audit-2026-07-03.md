# PM 平台返工重新提交审计报告

## 摘要

本包补齐审阅退回后的返工闭环：施工员补采后再次提交时，工单继续回到 `pending_review`，并新增一条 `rework_submitted` 审计历史。审阅台不再只看到工单重新进入待审，还能看到它是返工后重新提交。

## 基线

- 生产基线分支：`production/V3/3.0.77`
- 生产基线提交：`4c05cc9`
- 平台开发分支：`pm-platform/production-3.0.77-sync`
- 当前本地 HEAD：`6892205`

## 修改文件

- `v2-api/app/services/platform/templates.py`
- `v2-web/src/views/ConstructionView.vue`
- `v2-web/src/views/ReviewView.vue`
- `scripts/verify_platform_rework_resubmission_audit.py`
- `scripts/verify_vue_rework_resubmission_audit.js`
- `docs/superpowers/plans/2026-07-03-rework-resubmission-audit-trail.md`
- `docs/reports/pm-platform-rework-resubmission-audit-2026-07-03.md`
- `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Generated Vue static assets under `v2-api/app/static/vue/`

## 功能说明

- 后端在 `save_platform_construction_work_order_collection` 中识别 `returned -> submitted` 的返工重新提交。
- 保留原 `returned` 审阅历史。
- 追加审计事件：
  - `action`: `rework_submitted`
  - `note`: `返工补采后重新提交审阅`
  - `reason`: `returned_rework_resubmitted`
  - `actor`: 本次提交施工员
- 保持既有状态流转：返工重新提交后 `review_status` 回到 `pending_review`，清空上一轮审阅人、审阅时间、审阅备注和退回原因。
- 施工页提交成功时，如识别到返工重新提交历史，提示 `返工已重新提交审阅`。
- 审阅页历史记录把 `rework_submitted` 显示为 `返工重新提交`，不再直接暴露原始动作码。

## 验证

- 红灯确认：
  - `python scripts\verify_platform_rework_resubmission_audit.py` 先失败于缺少 `rework_submitted` 历史事件。
  - `node scripts\verify_vue_rework_resubmission_audit.js` 先失败于施工/审阅页面缺少返工重提识别与文案。
- 新守卫通过：
  - `python scripts\verify_platform_rework_resubmission_audit.py`
  - `node scripts\verify_vue_rework_resubmission_audit.js`
- 回归通过：
  - `python scripts\verify_platform_construction_rework_gap_panel.py`
  - `node scripts\verify_vue_construction_rework_gap_panel.js`
  - `python scripts\verify_platform_review_return_reason_suggestions.py`
  - `node scripts\verify_vue_review_return_reason_suggestions.js`
  - `python scripts\verify_platform_construction_required_collection.py`
  - `node scripts\verify_vue_construction_submit_gap_preview.js`
- 构建通过：
  - `pnpm --dir v2-web build`
  - 仅出现既有 VueUse PURE 注解和 chunk size 警告。
- 浏览器冒烟：
  - `/construction?project_id=draft-project` 正常加载施工采集页和平台接入工单入口。
  - `/task-hall?project_id=draft-project` 正常加载审阅工作台入口。
  - 当前端口相关控制台错误数为 0。
  - 说明：直接打开 `/review/:groupId` 会被当前后端静态服务返回 404，这是既有深链兜底限制；本包用实际审阅工作台入口 `/task-hall` 做页面冒烟，`ReviewView.vue` 的组件变更由 guard 和构建覆盖。
- 安全检查通过：
  - `python scripts\verify_pm_platform_team_operating_model.py`
  - `git diff --check`
  - 敏感路径扫描 `.env`、`data`、`uploads`、dump、压缩包、数据库文件无输出。

## 注意事项

一次并行回归中，多个后端 TestClient 脚本同时写本地 JSON 临时文件，触发 Windows `WinError 32` 文件锁。串行复跑 `verify_platform_construction_required_collection.py` 后通过。后续后端验证脚本应尽量串行执行，或确保每个脚本的临时存储完全隔离。

## 风险

低风险。此包只追加本地平台工单 JSON 中的历史事件和前端展示文案，不改数据库结构，不写 OSS，不触发生产部署，不创建 tag，不占用正式版本号。

潜在风险是旧工单没有 `review_history` 时只能从本次之后开始记录返工重新提交；不会影响旧工单读取。

## 迁移说明

无数据库迁移。旧平台工单可以继续读取；没有 `rework_submitted` 历史时，前端不会显示返工重提提示。

## 回滚建议

如需回滚，移除 `save_platform_construction_work_order_collection` 中追加 `rework_submitted` 的逻辑，删除施工页 `platformWasReworkResubmitted` 文案逻辑，删除审阅页历史动作映射，删除两条守卫脚本和本报告，然后重新执行前端构建。无需数据回滚。
