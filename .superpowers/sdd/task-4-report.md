# V3.2.0 Task 4 Report

- Status: DONE_WITH_CONCERNS
- Worktree: `C:\Users\Administrator\.config\superpowers\worktrees\module-manager-v3\production-v3.0.24`
- Branch: `production/V3/3.2.0`
- Base HEAD: `8af1f0e`
- Date: `2026-07-23`

## Requirement

将项目驾驶舱中的卡片、进度、风险和安装人员图统一下钻到数据中台，按 `useDataCenterQuery` 既有 URL keys 传递筛选、日期/人员上下文，并移除驾驶舱里的重复明细弹窗、照片加载和业务导出入口；保留服务器快照汇总和图表，确保按钮键盘可访问，不改数据中台与导出中心实现。

## Changed Files

- `v2-web/src/utils/dataCenterDrilldown.ts`
- `v2-web/src/views/ProjectBoardView.vue`
- `v2-web/src/router/index.ts`
- `scripts/verify_v3_2_0_dashboard_drilldown.py`
- `v2-api/app/static/vue/index.html`
- `v2-api/app/static/vue/version.json`
- `v2-api/app/static/vue/assets/*` build output refreshed to the current hash set

## Implementation Summary

1. 新增白名单 `buildDataCenterDrilldown(kind, context)`，统一输出 `/global-search` 路由和 `page=1&page_size=20`。
2. 将驾驶舱的资料组卡片、条码卡片、项目进度、风险卡、安装人员完成量分布、终端流转态势全部接到统一 drilldown helper。
3. 安装人员下钻保留 `installer`、`date_from`、`date_to` 上下文；按日/周/月 scope 生成相应时间范围。
4. 删除项目驾驶舱里重复的数据明细弹窗、照片对象 URL 加载逻辑和前端业务导出按钮，仅保留服务器快照汇总和图表本身。
5. 修正 legacy router 兼容入口：
   - `/app?page=unmatched` -> `/global-search?data_type=unmatched&page=1&page_size=20`
   - `/review/:groupId` -> `/global-search?page=1&page_size=20&group_id=...&review=1`
6. 重新构建 Vue 静态资源，并清掉旧 hash 产物；对 hash 未变但被 build 改写行尾的文件做了恢复，避免无意义 churn。

## Verification

- `2026-07-23` `python scripts\verify_v3_2_0_dashboard_drilldown.py`
  - PASS
- `2026-07-23` `.\node_modules\.bin\vue-tsc.cmd --noEmit`
  - PASS
- `2026-07-23` `npm run build`
  - PASS
  - Vite/Rollup warnings remained:
    - `@vueuse/core` `/* #__PURE__ */` annotation position warning
    - `element-components` chunk larger than 500 kB warning

## Self Review

- 驾驶舱 drilldown 全部走同一白名单 helper，没有直连数据中台 query 拼接散落在组件里。
- 路由兼容入口已固定 `page=1&page_size=20`，不会带着旧的空 review 参数落到空白态。
- 旧照片加载、旧明细弹窗、旧前端导出逻辑已从 `ProjectBoardView.vue` 移除。
- 构建产物只保留当前 hash 集；旧孤儿 assets 删除，未把 hash 未变的行尾噪音保留下来。

## Version Change

- None. This task did not change `APP_VERSION`.

## Release Status

- Local code, verifier, type-check and build complete.
- Not released.

## Concerns

1. 受 `useDataCenterQuery` 在 `2026-07-23` 的既有 key 面限制，驾驶舱里两个聚合口径只能映射到最接近的单筛选：
   - `已扫码组` -> `construction_status=in_progress`
   - `未完成施工` -> `construction_status=in_progress`
   现有 query 不能直接表达 `photo_count > 0` 或多状态并集。
2. 数据中台页面当前仍是管理员路由，因此驾驶舱 drilldown 仅对管理员渲染为可点击按钮；非管理员继续看到静态汇总。
