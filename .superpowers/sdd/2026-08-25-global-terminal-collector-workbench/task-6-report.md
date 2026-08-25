# Task 6 report: global terminal collector workbench

## Scope

- Replaced the Vue workbench's project/batch/terminal flow with one searchable global-terminal selector that opens or reuses the server snapshot.
- Added global-terminal DTOs and authenticated API clients. The open body is limited to `terminal_key`, `project_id`, `terminal_code`, and `source_revision`; it never sends team, actor, or role.
- Added global candidate/state helpers, request sequencing, state-specific collector presentation, terminal-level replace/refresh/rollback controls, persisted-detail reload after mutations, source-change warning, retry handling, keyboard navigation, and no camera access.
- Retired the batch page from navigation and static pages, added `/collector-batches` redirect, and deleted its view and test.

## TDD evidence

1. State helpers were added first and the mandatory node command was RED because `canReplaceMissing` was not exported.
2. The minimal helpers were implemented and the same command was GREEN: 9 node tests passed.
3. The component/route suite was rewritten with literal global candidate/detail fixtures and the mandatory Vitest command was RED: 7 failures from the old project/batch workbench and batch route.
4. The global-terminal implementation made the focused suite GREEN: 7/7 tests passed.

## Files changed

- `v2-web/src/api/types.ts`
- `v2-web/src/api/services.ts`
- `v2-web/src/features/collectorTransfer/state.ts`
- `v2-web/src/views/CollectorWorkbenchView.vue`
- `v2-web/src/views/__tests__/CollectorWorkbenchView.spec.ts`
- `v2-web/tests/collector-transfer-state.test.ts`
- `v2-web/src/router/index.ts`
- `v2-web/src/router/staticPages.ts`
- `v2-web/src/layouts/AppLayout.vue`
- Deleted `v2-web/src/views/CollectorBatchManagementView.vue`
- Deleted `v2-web/src/views/__tests__/CollectorBatchManagementView.spec.ts`

## Final verification

| Command | Result |
| --- | --- |
| `npm run test:collector-transfer` | PASS: 9 state tests; 5 Vitest files / 42 tests |
| `npm run test:components` | PASS: 1 file / 5 tests |
| `npm run type-check` | PASS |
| `npm run build` | PASS (Vite emitted its pre-existing Rollup PURE-comment and large-chunk warnings) |

`git diff --check` was clean before staging. `v2-api/uv.lock` was already untracked at task start and was not edited, staged, deleted, or committed.

## Build-artifact boundary

`npm run build` generated changes under `v2-api/app/static/vue/`. Per Task 6's source-only commit boundary, these generated static outputs are deliberately left unstaged and are not part of this Task 6 commit; Task 7 will rebuild and bind final artifacts from the committed source.

## Concerns

- Generated `v2-api/app/static/vue/` changes remain in the worktree, unstaged, by the specified Task 6/Task 7 boundary.
- The production build completes but reports third-party Rollup PURE-comment and standard chunk-size warnings; neither is caused by Task 6 source.
