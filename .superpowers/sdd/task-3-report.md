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

---

## 审阅未通过修复追加

### 修复项

- Critical：新增数据中台分类专用链路，JSON/Postgres 在分类最后一张后于可靠写链路内判断分类完整、权威条码通过和正式身份有效，自动归档并排队交付缓存；JSON 同步排队交付包。
- Important 1：新增 `/groups/data-center/groups/{group_id}/photos/{photo_id}/classify|barcode-rescan|region-scan` 管理员端点和前端 typed services，正式组弹窗不再调用 `/local-test/*` 分类/重扫/框选扫码，也不依赖 review claim。
- Important 2：数据中台字段修正、人工确认、分类、重扫、未匹配归并、回退审计补 `source_page/source=data_center`，并包含 actor、reason、before、after。
- Important 3：`?group_id=X&review=1` 直达 URL 现在默认构造 formal group fallback；仅 `data_type=unmatched` 时按未匹配打开。
- Minor 1：`DataCenterFilters` 增加异常状态筛选并同步 URL。
- Minor 2：`fetchGroupPhotoObjectUrl` 接受 `AbortSignal`；弹窗关闭或重载时 abort detail/photo fetch 并 revoke 已创建 object URL。

### RED 记录

- 后端 RED：`4 failed, 110 passed, 354 deselected`，失败点覆盖缺少数据中台分类方法、分类后自动归档/排队、审计 source 字段缺失。
- UI verifier RED：失败于 `data center filters must expose exception status options`。

### 验证结果

- `..\.venv\Scripts\python.exe -m pytest tests/test_data_center_review.py tests/test_local_simulation.py tests/test_state_repository.py -k "data_center or auto_archive or reset_group or unmatched" -q`
  - 114 passed, 354 deselected, 1 warning
- `.\.venv\Scripts\python.exe .\scripts\verify_v3_2_0_data_center_ui.py`
  - passed
- `npm exec vue-tsc -- --noEmit`
  - passed
- `npm run build`
  - passed
  - warnings: Rollup removed third-party `#__PURE__` annotations in `@vueuse/core`; `element-components` chunk remains larger than 500 kB.
- `git diff --check`
  - passed

### 构建产物处理

- 已运行构建用于验证。
- 已恢复并清理 `v2-api/app/static/vue` hashed static churn，提交不包含本次构建产物。

### 剩余疑虑

- 未匹配弹窗仍复用既有 `UnmatchedReviewDialog` 视觉和交互；本轮补了数据中台 finalize wrapper 审计 source 与 `00000000` 拒绝，但未单独重做未匹配弹窗。
- 构建警告为既有 vendor/chunk 体积与第三方注释警告，未在本任务范围内处理。

---

## 第二轮复审修复追加

### 修复项

- Critical：Postgres data-center 分类最后一张后，在同一个 `session`/事务内完成自动归档、delivery cache job staging、pending/ready DeliveryPackageJob 创建或复用，以及 `data_center_delivery_package_requested` 审计；`auto_commit=False` 禁止 package request 自行 commit/rollback，enqueue 或 commit 失败整体回滚。
- Important 1：`manual_confirm_group_barcode` 增加内部 `require_claim` 参数，旧端点默认仍要求 claim；data-center wrapper 传 `require_claim=False`，未认领/他人认领任务可由管理员确认并写 `source_page/source=data_center` 审计。
- Important 2：新增 `return_data_center_group_to_exception_order` repository/service 和 `/groups/data-center/groups/{group_id}/return-exception` 管理员端点，前端正式组弹窗改用新 service；退回异常审计写 actor、reason、source_page/source、before、after。
- Important 3：`UnmatchedReviewDialog` 支持 data-center 模式和注入 finalize callback；数据中台弹窗注入 `finalizeDataCenterUnmatchedToGroup`，不再从该 UI 路径调用旧 `/local-test/unmatched/.../finalize-match`。
- Minor：JSON/PG 数据中台列表将 `exception_status=none` 解释为无异常空值筛选，确保“无异常”返回空异常状态记录。

### RED 记录

- 后端 RED：`4 failed, 62 passed, 189 deselected`，失败点覆盖 data-center 退回异常方法缺失、`none` 无异常筛选返回 0、Postgres 分类 package enqueue 失败未进入同事务、data-center 人工确认仍走 `_ensure_task_claimed_by`。
- UI verifier RED：失败于缺少 `returnDataCenterGroupToException` data-center service，随后同一 verifier 还覆盖未匹配 data-center mode/finalize callback 结构。

### 验证结果

- `..\.venv\Scripts\python.exe -m pytest tests/test_data_center_review.py tests/test_local_simulation.py tests/test_state_repository.py -k "data_center or auto_archive or reset_group or unmatched" -q`
  - 119 passed, 354 deselected, 1 warning
- `.\.venv\Scripts\python.exe .\scripts\verify_v3_2_0_data_center_ui.py`
  - passed
- `npm exec vue-tsc -- --noEmit`
  - passed
- `npm run build`
  - passed
  - warnings: Rollup removed third-party `#__PURE__` annotations in `@vueuse/core`; `element-components` chunk remains larger than 500 kB.
- `git diff --check`
  - passed

### 构建产物处理

- 已运行 `npm run build` 用于验证。
- 已恢复 tracked `v2-api/app/static/vue` 文件，并用 scoped `git clean -f -- v2-api/app/static/vue` 清理本次生成的 untracked hashed assets；本次提交不包含静态构建 churn。

### 剩余疑虑

- `request_postgres_delivery_package(auto_commit=False)` 复用现有 request 逻辑来 stage durable row；它会在外层事务内 `flush()` 以提前暴露 enqueue/约束失败，但最终 commit 仍由 data-center 分类事务统一控制。
- 构建警告为既有第三方注释和 chunk 体积警告，未在本轮复审范围内处理。
