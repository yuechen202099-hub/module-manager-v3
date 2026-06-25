# 静态页面迁移到 Vue 规则

V2.3 之后，Vue 是正式生产前端入口，`v2-api/app/static/*.html` 只允许作为兼容层存在。

## 当前迁移状态

已完成原生 Vue 化：

1. `project-board`：项目看板，包括总览指标、任务进度、导入入口、系统状态。
2. `claim-tasks`：任务领取。
3. `task-hall`：审阅工作台核心路径，包括我的任务、资料组列表、图片预览、快捷键分类、归档当前图、保存资料组。
4. `construction`：施工采集核心路径，包括指派终端、未施工资料组、槽位照片上传。
5. `construction-cache`：缓存上传，包括 IndexedDB 缓存读取、详情查看、统一上传。
6. `unmatched`：异常处理，包括未匹配记录、异常资料组、字段修正、补图。
7. `sync-config`：后台同步停用说明和导入入口指引。

当前 `python scripts/verify_vue_migration_gate.py --strict-native` 已通过，生产登记页不再依赖 legacy bridge。

## 为什么提前迁移

如果继续把生产功能写在多个静态 HTML 文件中，正式上线后会出现这些问题：

- 页面状态分散，任务领取、审阅、异常、施工采集之间难以同步。
- 图片预览、缓存上传、异常工单、导出等复杂交互会继续堆在单文件脚本里。
- 手机端适配和组件复用成本会持续升高。
- 后续切 PostgreSQL、OSS、权限和审计时，每个静态页都要重复改。

## 迁移策略

第一阶段采用 Vue shell + legacy bridge：

- Vue 路由成为统一入口。
- 旧静态页通过 `LegacyStaticPageView.vue` 作为 iframe 兼容页承载。
- 所有生产页面必须登记在 `v2-web/src/router/staticPages.ts`。
- FastAPI 提供 `/vue` 入口，Vite 构建输出到 `v2-api/app/static/vue`。

第二阶段逐页替换为原生 Vue：

已完成。后续只允许在 Vue 页面内继续补齐功能，不再回到大型静态 HTML。

第三阶段删除旧静态实现：

- 页面迁移状态全部改为 `native_vue`。
- `python scripts/verify_vue_migration_gate.py --strict-native` 必须通过。
- 生产路由只返回 Vue bundle。
- 发布包必须移除旧静态 HTML，只保留 `v2-api/app/static/vue/index.html` 和 Vue assets。
- 源码中的旧 HTML 如需短期保留，只能作为历史参考，不允许作为生产入口。

## 禁止事项

- 不再新增生产功能静态 HTML 页面。
- 不在静态页里继续扩展大型业务逻辑。
- 不在多个页面重复实现同一套图片预览、缓存、导出或权限逻辑。
- 不绕过 Vue 路由直接增加新的生产入口。

## 验证

运行：

```powershell
python scripts/verify_vue_migration_gate.py
```

正式上线前执行严格门禁：

```powershell
python scripts/verify_vue_migration_gate.py --strict-native
```

`--strict-native` 未通过时，评价中的“前端结构”和“产品结构”不得按完全工程化计分。

发布包校验还会拒绝旧静态 HTML：

```powershell
python scripts/verify-client-release.py build\server-release\<release>.zip
```
