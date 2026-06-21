# V2.4.x Static HTML To Vue Parity Matrix

Baseline rule: the final static HTML implementation is the only functional baseline. Vue cannot be treated as complete until every blocking static feature below has an equivalent Vue implementation and browser evidence.

Hidden-feature rule: static HTML code that is hidden, has no visible entry, or is unreachable from the final user flow is treated as cancelled by default and must not be counted as a Vue gap unless the user explicitly reactivates it.

## Login

| Static feature | Vue target | Current status | Blocking |
|---|---|---:|---:|
| Username login | `LoginView.vue` | Present | No |
| Password login | `LoginView.vue` | Present | No |
| Team id input | `LoginView.vue` | Implemented and browser verified: visible `团队标识` input is sent to `/auth/login` and defaults from stored team/demo config | No |
| `/auth/config` display/preset accounts | `LoginView.vue` + service | Implemented and browser verified: reads `/auth/config`, renders demo presets when enabled, and renders formal login notice when disabled | No |
| Enter key login | `LoginView.vue` | Browser verified: pressing Enter in the password field logs in and navigates to project board | No |
| Persist login state | auth store | Browser verified: after login and page reload, project board remains accessible and does not return to login | No |

## App Shell

| Static feature | Vue target | Current status | Blocking |
|---|---|---:|---:|
| Unified navigation | `AppLayout.vue` | Browser verified: top navigation renders native Vue routes and does not show cancelled standalone cache/exception pages | No |
| Role-based page visibility | `AppLayout.vue` | Browser verified: admin sees project/claim/review/construction, reviewer sees project/claim/review, constructor sees construction only | No |
| Embedded page mode | Router/layout | Different implementation; acceptable only after page parity | No |
| Cross-page refresh notification | Vue global refresh strategy | Implemented/source verified: successful non-GET/form API calls emit `module-manager:data-mutated`; `AppLayout.vue` broadcasts `module-manager:data-refresh` through same-page message and cross-tab localStorage; project board, claim tasks, review workbench, and construction page listen and refresh their own data | No |
| Shell-level final export | `AppLayout.vue` + export service | Implemented and browser verified: project board submits terminal export to the global shell job bar; switching pages no longer owns the export lifecycle; all-scope export completed with `压缩包已生成，已下载 2 张图片` and no console errors | No |
| Shell-level scan import progress | `AppLayout.vue` + `ProjectBoardView.vue` | Implemented/source verified: project board submits scan file to the global shell job bar; AppLayout starts the async import job, polls `/local-test/scan/import-template-xlsx/jobs/{job_id}`, displays progress, and broadcasts refresh on completion | No |

## Project Board

| Static feature | Vue target | Current status | Blocking |
|---|---|---:|---:|
| Project summary metrics | `ProjectBoardView.vue` | Browser verified: top metric cards show total catalog, groups, scanned groups, archived groups, and exception groups with current data | No |
| Project progress | `ProjectBoardView.vue` | Browser verified: scanned and archived progress rows render with percentages and progress bars | No |
| Risk metrics | `ProjectBoardView.vue` | Browser verified against static labels: scan unmatched, exception groups, unconstructed/unscanned, and missing-photo counts render in the risk block | No |
| Installer distribution | `ProjectBoardView.vue` | Browser verified: installer share chart renders `罗爱民 96% / 22` and `qa 4% / 1` from current data | No |
| Terminal task progress table | `ProjectBoardView.vue` | Browser verified: table renders top 12 terminals sorted by uploaded count with export controls per terminal | No |
| System status | `ProjectBoardView.vue` | Browser verified: system status panel renders service, disk usage, data file, and latest backup rows | No |
| Import total catalog | `ProjectBoardView.vue` | Browser/source verified: visible `.xlsx/.xls` file input and `导入总清单` button are wired to `importTotalCatalog()` | No |
| Import scan spreadsheet with async progress | `ProjectBoardView.vue` | Browser/source verified: visible `.xlsx/.xls/.csv` input and `导入扫码表格` button are wired to async import job polling/progress UI; real file upload remains covered separately by API/import tests | No |
| Export final delivery | `ProjectBoardView.vue` + service | Product-scoped to single terminal; all-data export remains rejected by design | No |
| Export single-terminal delivery | `ProjectBoardView.vue` + service | Browser verified: first terminal supports reviewed/all scope; all-scope export completed through global shell job bar with 2 images downloaded and no console errors; Browser cannot inspect OS download folder, so final file-open remains ordinary browser release smoke | No |
| Export task detail | `ProjectBoardView.vue` + service | Browser verified: `导出明细` button calls export flow and shows `任务明细已导出`; backend Excel response covered by API smoke, while IAB does not expose Blob download events | No |
| Export exception meters | `ProjectBoardView.vue` + service | Browser verified: `导出异常表计` button calls export flow and shows `异常表计已导出`; backend Excel response covered by API smoke, while IAB does not expose Blob download events | No |
| Frontend image ZIP packaging | export utility in `services.ts` | Browser verified success branch: ZIP writer completed after manifest + concurrent image downloads and reported `压缩包已生成`; static-style CSV manifest, terminal/address folders, fallback notes, and 6-concurrency downloads are implemented in `services.ts` | No |
| Account create/update/delete | `ProjectBoardView.vue` + account service | Browser verified: admin panel creates a temporary `qa-vue-*` account, edits its name, deletes it, and leaves no temporary row | No |
| Account role/status/team/password fields | `ProjectBoardView.vue` + account service | Browser verified: form exposes username/name/password/team/role/status fields and saves through `/auth/users` | No |
| Mobile panel collapse | page CSS | Needs verification | No |

## Claim Tasks

| Static feature | Vue target | Current status | Blocking |
|---|---|---:|---:|
| Claim overview | `ClaimTasksView.vue` | Browser verified: summary cards render claimed tasks, my tasks, renovation total, unreviewed count, and review progress | No |
| Terminal task list | `ClaimTasksView.vue` | Browser verified: reviewer sees scanned terminal task cards with terminal, upload count, unreviewed count, and status | No |
| Claim task | `ClaimTasksView.vue` | Browser verified: claiming the visible terminal changes status to `我已领取` and button to `继续持有` | No |
| Release task | `ClaimTasksView.vue` | Browser verified: releasing the claimed terminal returns it to `可领取` and disables release again | No |
| Admin release all | `ClaimTasksView.vue` + service | Implemented and browser verified: admin sees `收回全部`, calls `/local-test/tasks/release-all`, and refreshes tasks | No |
| Construction status label | `ClaimTasksView.vue` | Present through task card status plus admin construction open/close controls; browser verified on 135 task cards | No |
| Admin open/close construction | `ClaimTasksView.vue` + service | Implemented and browser verified: each admin task card shows `开放施工/关闭施工` wired to existing endpoints | No |
| Scheduled refresh | `ClaimTasksView.vue` | Implemented: reloads every 10s and responds to `module-manager:data-refresh` message with debounced refresh | No |
| Mobile collapse | page CSS | Needs verification | No |

## Review Workbench

2026-06-21 audit note: P0 review workbench was rechecked against the static baseline and current rendered Vue page. The audit covered image loading, folded unconstructed groups, construction-style status filters, keyboard group movement with auto-scroll, duplicate-category archive blocking, and mobile 390px layout. No new P0 review blocker was found in this pass. Latest evidence is recorded in `docs/V2_CHANGE_WORKLOG.md` under `审阅工作台 P0：当前 Vue 实现复核`.

| Static feature | Vue target | Current status | Blocking |
|---|---|---:|---:|
| Claimed task board | `TaskHallView.vue` | Browser verified: only current reviewer claimed scanned task is shown; active task displays terminal, reviewer, renovation count, and unreviewed count | No |
| Group list | `TaskHallView.vue` | Browser verified: selected terminal renders grouped cards, default all view shows `79/87` with 8 unconstructed groups folded, and visible rows match static card content | No |
| Search meter/address/terminal | `TaskHallView.vue` | Browser verified: meter search returns `1/87`, address search returns `1/87`, terminal search returns `87/87`, and folded unconstructed groups become searchable as in static HTML | No |
| Filters: all/reviewable/exception/archived/unconstructed | `TaskHallView.vue` | Browser verified: counts, unconstructed filter, all-filter folded state, and construction-style status cards with non-clipped labels | No |
| Fold unconstructed unless search finds it | `TaskHallView.vue` | Browser verified: all view folds 9 unconstructed groups; searching `120020467667` opens the folded unconstructed group | No |
| Main image and thumbnail switching | `TaskHallView.vue` | Browser verified at 1366/1920/390: main image loads as `blob:` with natural size 810x1080; thumbnails load through backend content URLs; 2026-06-21 recheck shows natural image 810x1080 and no image error tip | No |
| Preview/thumbnail/original URL fallback | `TaskHallView.vue` + service | Fixed: `oss://` is no longer allowed as direct browser fallback; backend content/blob path verified locally; backend now detects gray/vertical-stripe OSS processed previews and falls back to original object/source repair | No |
| Lightbox zoom/pan/fit/close | `TaskHallView.vue` | Fixed and browser verified: double-click opens full image, `+/-/0` zoom/fit, drag pans, Esc closes, mobile 390px has no horizontal overflow | No |
| Keyboard `1-4`, arrows, Enter, Esc | `TaskHallView.vue` | Browser verified: `1-4` changes category, Enter archives current photo, arrows switch photo/group with active card visible, Esc closes lightbox | No |
| Archive current photo | `TaskHallView.vue` | Browser E2E verified through Enter key: current photo category persisted and selection moved to next pending photo | No |
| Archive whole group | `TaskHallView.vue` | Browser E2E verified with real API submit: archive count increased and group was completed | No |
| Duplicate category block | `TaskHallView.vue` | Browser verified: duplicate labels block group archive | No |
| Archived photos can be selected and corrected | `TaskHallView.vue` + PostgreSQL repository | Fixed and browser/API/DB verified | No |
| Save meter/collector/module | `TaskHallView.vue` | Browser/API verified: edited collector/module in Vue for `g-07818 / 110023771246`, saved through `/local-test/groups/{id}/metadata`, API readback matched, then restored original values | No |
| Supplement photos | `TaskHallView.vue` | Fixed: Vue now compresses supplement images before upload; local API/browser verified `g-07829` increased from 4 to 5 photos and rendered on desktop/mobile | No |
| Delete photo | `TaskHallView.vue` | Fixed and browser/API verified: deleting the current photo updates the group from 6→5→4, keeps the adjacent photo selected, refreshes task/group counters silently, and local QA data was cleaned back to the original 4 photos | No |
| Restore pending | `TaskHallView.vue` | Fixed and browser/API verified: exception group restores to pending/incomplete by photo count, sends `note=恢复待审` and clears `exception_note`, syncs inline exception form, and silently refreshes task/group counters | No |
| Reset to unconstructed | `TaskHallView.vue` | Fixed and browser/API verified: current group soft-resets to unconstructed, clears photos/collector/module fields, preserves the no-photo review panel, and refreshes task/group counters silently | No |
| Return to exception work order | `TaskHallView.vue` | Fixed and browser/API verified: creates an open construction exception order, keeps the current group visible as exception, uses static-style note fallback, and silently refreshes task/group counters | No |
| Exception reason/note editing | `TaskHallView.vue` | Fixed and browser verified: exception note now prefills from `exception_reasons` + `exception_note` + exception `review_note`, deduplicates like static HTML, resets category to static default, and edited note submits through return-exception flow | No |
| Export exception meters | `TaskHallView.vue` | Browser/API verified: Vue button is kept inside the review action area and calls `/exports/exception-meters`; no standalone exception page or exception-export tab remains | No |
| In-page Excel/CSV/JSON import | Product decision | Cancelled: review workbench no longer carries table import; import stays in project/import workflow | No |
| Background refresh preserving active group | `TaskHallView.vue` | Browser verified: after the 10s background refresh interval, search value, `1/87` group count, active exception group, and selected photo position remained unchanged | No |
| Select first unfinished group after archive | `TaskHallView.vue` | Fixed to match static `findFirstUnclassifiedGroup`: after real archive submit, refreshes list and selects the first unfinished rendered group; browser E2E verified active first card and no horizontal overflow | No |

## Construction Collection

| Static feature | Vue target | Current status | Blocking |
|---|---|---:|---:|
| Task selection mode | `ConstructionView.vue` | Browser verified: admin task picker shows assigned terminal `350000434929`, assignment/admin controls, and no horizontal overflow | No |
| Construction work mode | `ConstructionView.vue` | Browser verified: selecting the terminal hides task picker and shows focused group panel + collection editor with static-style filter counts | No |
| Role-aware task display | `ConstructionView.vue` | Browser verified: constructor only sees assigned terminal in local snapshot | No |
| Return to task view | `ConstructionView.vue` | Browser verified: `返回任务区` hides group/editor panels and returns to the terminal task card list | No |
| Group list | `ConstructionView.vue` | Browser verified: assigned terminal shows ordinary unconstructed groups, exception orders separated | No |
| Chinese address sorting | `ConstructionView.vue` | Browser verified: static-style segmented address order on terminal 350000434929 | No |
| Fuzzy address/meter search | `ConstructionView.vue` | Browser verified: `52号101` filters to the target group; broad token behavior follows static HTML semantics | No |
| Scan meter opens form | `ConstructionView.vue` | Browser verified: entering `110023765004` and pressing Enter opens the collection form | No |
| Filters: all/unconstructed/cached/exception | `ConstructionView.vue` | Browser verified: filters show `全部8 / 未施工7 / 已缓存1 / 异常工单0`; cached filter shows only the cached group | No |
| Upload all cached drafts on construction page | `ConstructionView.vue` | Browser verified: saving a draft exposes `1 个本地缓存 / 一键上传`; incomplete draft keeps one-click upload disabled like static HTML | No |
| Collector/module/meter scan | `ConstructionView.vue` | Source/browser verified: meter direct-open flow was verified earlier, module scan manual fallback fills the module field, collector/module/meter share `startScanner/applyScanValue`; physical camera scan remains device QA | No |
| QuaggaJS + BarcodeDetector fallback | `ConstructionView.vue` | Source/browser verified: Quagga script path, BarcodeDetector fallback, photo/manual fallback are implemented; desktop fallback opened correctly without accepting camera permission | No |
| Manual scan input fallback | `ConstructionView.vue` | Browser verified: module scan opens scanner fallback with `拍照识别/手动输入`; manual value `QA-MODULE-SCAN` fills the module field and shows success | No |
| Camera and album photo selection | `ConstructionView.vue` | Source/browser verified: every slot exposes `拍照/相册`; camera input uses `capture=environment`, album input omits capture, both route through `pickFile()` compression/cache path; real OS picker remains device QA | No |
| Image compression before cache/upload | `ConstructionView.vue` | Source verified against static baseline: `pickFile()` calls `compressImageFile()` before preview/cache; upload uses cached compressed `File` objects | No |
| Required module/before/module-after/after validation | `ConstructionView.vue` | Browser verified: empty collection form disables `上传当前组` and shows module required plus missing required photos `改造前照片 / 模块与电表照片 / 改造后照片` | No |
| Existing photos shown by slot | `ConstructionView.vue` | Browser verified on local exception order `g-07818`: existing `collector_barcode` and `after_box` photos render in their slots with `系统已有`, while missing required slots remain flagged | No |
| IndexedDB cache | `ConstructionView.vue` | Browser verified by behavior: after saving a draft, reload/login/navigation still restores cached task state; 2026-06-21 update aligned static auto-save behavior so collector/module/note input is debounced into IndexedDB, switching task/group or closing the mobile drawer flushes the draft, and empty drafts are deleted instead of polluting the cached filter | No |
| Offline terminal snapshot | `ConstructionView.vue` | Browser verified: after backend stop, task zone and group list restore from local terminal snapshot | No |
| Exception work order submit | `ConstructionView.vue` | Worklog/API verified: exception order appears in exception/cached filters, cached exception can upload and resolve locally; current API still returns assigned exception orders for task `67` | No |
| Mobile focused layout | `ConstructionView.vue` | Browser verified at 390 x 844: no horizontal overflow, filters/list/upload entry visible | No |

## Cache Upload

Independent cache upload page is cancelled by product decision. Cache upload remains part of `ConstructionView.vue` inside the construction collection workflow. `/construction-cache` must not be treated as a Vue parity page. The legacy static source file has been removed, legacy Vue/CSS page remnants have been cleaned up, and legacy direct access redirects to `/construction`.

| Static feature | Vue target | Current status | Blocking |
|---|---|---:|---:|
| Standalone cache upload page | Product decision | Cancelled; static/Vue page source removed; standalone static entry links removed; functionality integrated into construction collection page | No |
| Construction page one-click cache upload | `ConstructionView.vue` | Browser verified under Construction Collection section | No |
| Construction page IndexedDB cache | `ConstructionView.vue` | Browser verified under Construction Collection section | No |
| Construction page exception work order cache upload | `ConstructionView.vue` | Worklog/API verified under Construction Collection section | No |

## Unmatched And Exception Handling

Independent unmatched/exception handling page is cancelled by product decision. Exception editing, supplement photo upload, reset to unconstructed, return to exception work order, metadata correction, and exception-meter export remain part of `TaskHallView.vue` inside the review workbench. `/unmatched` must not be treated as a Vue parity page. Static HTML code that only preserves hidden exception-page remnants is treated as cancelled by the hidden-feature rule. The Vue standalone exception page, the Vue review-workbench exception tab/section, and the static review-workbench exception tab/section have been removed. Legacy direct access redirects to the normal review workbench at `/task-hall`.

| Static feature | Vue target | Current status | Blocking |
|---|---|---:|---:|
| Standalone unmatched/exception page | Product decision | Cancelled; standalone Vue page and both Vue/static internal exception tab/section remnants removed; visible functionality is integrated into review workbench actions | No |
| Legacy `/unmatched` direct access | FastAPI route | Redirects to `/task-hall`; old exception-page URL parameters no longer force exception mode | No |
| Exception metadata correction | `TaskHallView.vue` | Present in review workbench group metadata section | No |
| Supplement photo upload | `TaskHallView.vue` | Present as `补图` action | No |
| Reset to unconstructed | `TaskHallView.vue` | Present as `回退未施工` action | No |
| Return to exception work order | `TaskHallView.vue` | Present as `转异常工单` action | No |
| Export exception meters | `TaskHallView.vue` | Present as an action inside the review workbench; no standalone page or exception export tab remains | No |

## Sync Config

| Static feature | Vue target | Current status | Blocking |
|---|---|---:|---:|
| Backend sync disabled notice | `SyncConfigView.vue` | Browser verified: page states supplier/backend API sync is disabled and retained only as historical explanation | No |
| Spreadsheet import explanation | `SyncConfigView.vue` | Browser verified: explains supplier spreadsheet export and project board import workflow in three steps | No |
| Link to project board import | `SyncConfigView.vue` | Browser verified: primary action routes to `/project-board` | No |
| Link to task view | `SyncConfigView.vue` | Browser verified: secondary action routes to `/claim-tasks` like the static baseline | No |

## V201

| Static feature | Vue target | Current status | Blocking |
|---|---|---:|---:|
| Manual/auto entry to review workbench | backend route | Redirects to app/task hall | No |

## Next Implementation Order

1. Keep P0 review workbench verified after each related change.
2. Continue strengthening P0 construction collection evidence, especially exception-work-order cache/upload behavior and offline terminal snapshot behavior.
3. Verify remaining nonblocking responsive evidence for project board and claim tasks.
4. Keep cache upload inside construction collection; do not restore standalone cache page.
5. Keep standalone unmatched/exception page cancelled; handle exception operations inside review workbench.
