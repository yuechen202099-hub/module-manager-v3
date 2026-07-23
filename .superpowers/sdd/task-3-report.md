# V3.2.0 Task 3 Report

## 需求

- 统一管理员数据中台前端，使用 `/groups/data-center` 服务端查询和 URL 驱动过滤。
- 支持 20/50/100 分页、旧响应淘汰、列表轻量化和详情懒加载。
- 统一审阅弹窗复用重新扫码、框选扫码、人工确认、分类、字段修正、异常、回退、审计链路，禁止普通“完成审阅”。
- 证据修改后失效扫码、归档和交付缓存；人工确认满足条件后自动归档并保持交付包排队状态。
- 未匹配归并禁止 `00000000` 占位目标。

## 修改文件

- `v2-api/app/api/routes/groups.py`
- `v2-api/app/services/state_repository.py`
- `v2-api/tests/test_data_center_review.py`
- `scripts/verify_v3_2_0_data_center_ui.py`
- `v2-web/src/api/services.ts`
- `v2-web/src/api/types.ts`
- `v2-web/src/composables/useDataCenterQuery.ts`
- `v2-web/src/components/data-center/DataCenterFilters.vue`
- `v2-web/src/components/data-center/DataCenterReviewDialog.vue`
- `v2-web/src/views/GlobalSearchView.vue`

## 实现摘要

- 新增数据中台 repository 入口：`update_data_center_group`、`manual_confirm_group_barcode`、`finalize_unmatched_to_group`。
- 新增 `/groups/data-center/groups/{group_id}`、`/groups/data-center/groups/{group_id}/barcode-manual-confirm`、`/groups/data-center/unmatched/{unmatched_id}/finalize-to-group` 管理员接口。
- `update_data_center_group` 使用 `data_center_group_updated` 审计动作，身份字段修改会失效条码验证、已归档状态和交付缓存/交付包旧作业。
- `manual_confirm_group_barcode` 复用现有人工确认，随后尝试自动归档；交付缓存未 ready 时保留 pending 交付包作业，不同步构建包。
- `finalize_unmatched_to_group` 在写入前拒绝 `00000000` 和非唯一真实目标。
- 前端新增 `useDataCenterQuery`，用 URL query 驱动列表、分页和弹窗状态，使用 `AbortController` 和 serial 防止旧响应覆盖新列表。
- `GlobalSearchView` 改为数据中台表格，列表不请求照片缩略图；`DataCenterReviewDialog` 打开后懒加载 detail 和照片 object URL，并在关闭时 abort/revoke/clear。
- 未匹配审阅复用现有 `UnmatchedReviewDialog`。

## RED 记录

- 后端首次有效 RED：`3 failed, 109 passed`，失败点为 `JsonStateRepository` 缺少 `update_data_center_group`、`manual_confirm_group_barcode`、`finalize_unmatched_to_group`。
- UI verifier RED：失败于 `data center pagination must expose 20/50/100`。

## 验证结果

- `..\.venv\Scripts\python.exe -m pytest tests/test_data_center_review.py tests/test_local_simulation.py tests/test_state_repository.py -k "data_center or auto_archive or reset_group or unmatched" -q`
  - 112 passed, 354 deselected, 1 warning
- `python .\scripts\verify_v3_2_0_data_center_ui.py`
  - passed
- `npm exec vue-tsc -- --noEmit`
  - passed
- `npm run build`
  - passed
  - warnings: Rollup removed third-party `#__PURE__` annotations in `@vueuse/core`; `element-components` chunk remains larger than 500 kB.
- `git diff --check`
  - passed

## 构建产物处理

- 已运行构建用于验证。
- 已恢复并清理 `v2-api/app/static/vue` hashed static churn，提交不包含本次构建产物。

## 自审结论

- 未发现阻断发布的代码问题。
- 剩余疑虑：正式资料组弹窗的框选扫码目前把识别结果写入字段草稿，仍需点击字段修正落库；未匹配路径复用既有 `UnmatchedReviewDialog`，其最终归并继续走旧 local-test endpoint，但后端已有真实目标校验，本任务新增的数据中台 endpoint 也补了 `00000000` 前置拒绝。

## 发布状态

- 未发布。
- 未修改生产 `.env`、data、uploads、OSS 或数据库。
