# Task 1 Report: Retire Reviewer Login Role And Redirect Legacy Routes

## 状态

- 状态：已完成实现
- 分支：`production/V3/3.2.0`
- 提交：`HEAD（本次提交哈希见最终回复）`

## 修改文件

- `v2-api/app/services/account_store.py`
- `v2-api/app/api/routes/auth.py`
- `v2-api/app/api/routes/local_test.py`
- `v2-api/tests/test_api.py`
- `scripts/verify_v3_2_0_role_routes.py`
- `v2-web/src/api/mock.ts`
- `v2-web/src/api/types.ts`
- `v2-web/src/api/services.ts`
- `v2-web/src/router/staticPages.ts`
- `v2-web/src/router/index.ts`
- `v2-web/src/views/AccountManagementView.vue`
- `v2-web/src/views/TaskHallView.vue`
- `v2-api/app/static/vue/index.html`
- `v2-api/app/static/vue/version.json`
- `v2-api/app/static/vue/assets/*`（由 `npm run build` 更新的生产静态产物）

## RED 命令与结果

1. 首次按 brief 直接运行：
   - 命令：`python -m pytest tests/test_api.py -k "reviewer_only or requires_admin_after_v3_2_0 or constructor_cannot_use_export" -q`
   - 结果：失败，原因不是业务断言而是系统 Python 缺少 `fastapi`
2. 改用仓库虚拟环境后：
   - 命令：`..\.venv\Scripts\python.exe -m pytest tests/test_api.py -k "reviewer_only or requires_admin_after_v3_2_0 or constructor_cannot_use_export" -q`
   - 结果：`2 failed, 1 passed, 199 deselected, 1 warning`
   - 失败点：
     - reviewer-only 账号仍未被迁移为停用
     - reviewer bearer token 仍可进入 `/local-test/groups/{group_id}/barcode-manual-confirm`
3. 前端静态校验：
   - 命令：`..\.venv\Scripts\python.exe ..\scripts\verify_v3_2_0_role_routes.py`
   - 结果：失败，`'reviewer'` 仍存在于 `UserRole` 与旧路由/页面文本中

## GREEN 命令与结果

1. 新增 RED 用例回放：
   - 命令：`..\.venv\Scripts\python.exe -m pytest tests/test_api.py -k "reviewer_only or requires_admin_after_v3_2_0 or constructor_cannot_use_export" -q`
   - 结果：`3 passed, 199 deselected, 1 warning`
2. 静态角色/路由校验：
   - 命令：`..\.venv\Scripts\python.exe ..\scripts\verify_v3_2_0_role_routes.py`
   - 结果：`[OK] V3.2.0 role and legacy route checks passed`
3. 按 brief 聚焦后端验证：
   - 命令：`..\.venv\Scripts\python.exe -m pytest tests/test_api.py -k "reviewer or account or production_review or export" -q`
   - 结果：`22 passed, 180 deselected, 1 warning`
4. brief 指定命令检查：
   - 命令：`npm run type-check`
   - 结果：失败，当前 `v2-web/package.json` 不存在 `type-check` script
5. 等价前端类型校验：
   - 命令：`npm exec vue-tsc -- --noEmit`
   - 结果：通过
6. 额外前端构建验证：
   - 命令：`npm run build`
   - 结果：通过，产出已写回 `v2-api/app/static/vue/`
7. Diff 健康检查：
   - 命令：`git diff --check`
   - 结果：通过（仅有 LF/CRLF 提示，无 diff 格式错误）

## 自审

- 后端账号迁移：
  - 仅迁移账号角色集合，不删除历史 reviewer 字段、业务审阅人字段、审计记录或登录历史
  - reviewer-only 账号被统一标记为 `disabled=True`、`status="disabled"`、`disabled_reason="V3.2.0 已停用审阅员角色"`
  - 新建账号默认角色改为 `constructor`，不再回落到 reviewer
- 后端权限：
  - 生产态 `require_production_reviewer_or_admin` 改为直接复用 `require_admin`
  - 生产态 review 写动作与敏感条码人工确认统一收口到 admin-only
  - constructor 在生产态仍可访问自身施工能力，但不能再进入 review/export 写路径
- 前端路由与角色：
  - `UserRole` 删除 reviewer
  - 账号管理页删除 reviewer 选项并把默认角色切到 constructor
  - 静态导航移除“审阅工作台”，`/task-hall` 与 `/review/:groupId` 统一重定向到 `/global-search`
  - `/review/:groupId` 保留 `group_id` 查询参数，兼容旧链接
- 风险控制：
  - 没有删除任何历史 reviewer 业务字段或审计数据
  - 修改聚焦在 brief 指定文件与前端构建产物

## 疑虑

- `npm run type-check` 不是当前仓库已存在的 script；我使用 `npm exec vue-tsc -- --noEmit` 和 `npm run build` 完成了等价/更强验证。若后续要求严格保留该命令本身，需要单独决定是否把 `package.json` 脚本补齐。
