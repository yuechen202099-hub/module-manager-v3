# V3.0.80 Final Review Fix Report

## 结论

- 状态：`DONE`
- 绑定 findings：8/8 已修复，Medium/Low 未跳过。
- 起始提交：`e92b2f1d21269052e2d521205bd7436949ee1fec`
- 实现提交：`1f5abcd69c1c51fadc747b0680d6181ca55b5053`
- 当前生产基线仍为 `V3.0.79`。
- 当前候选版本仍为 `V3.0.80`，未推进 baseline。
- 未打包、未部署、未访问生产、未修改生产 PostgreSQL/OSS/data/uploads/.env。

## 根因与修复

### Finding 1 - PostgreSQL 唯一性竞态返回 500

根因：finalization advisory lock 使用 `(team_id, candidate_key)`，但数据库唯一约束使用 `(project_id, meter_match_key)`；重复总清单行可产生不同 candidate key 并竞争同一正式资料组。旧 materialization 查询也没有在锁后按真实唯一身份重新选择资料组，`IntegrityError` 会直接上浮。

修复：

- advisory lock 改为稳定哈希后的 `(project_id, meter_match_key)`。
- 获锁后按 `MaterialGroup.project_id + meter_match_key` 加行锁重新选择。
- 终端和目标组兼容时复用既有组；不兼容时抛出 `FinalizationIdentityConflict`。
- finalization 阶段的 `IntegrityError` 回滚并转为受控 identity conflict。
- API 将该 conflict 映射为 HTTP `409`。

### Finding 2 - dual finalization 可静默留下 PostgreSQL open

根因：dual 只 mirror finalization，没有 mirror save/rescan/confirm 的 review version 演进；finalization 到 PostgreSQL 时发生版本漂移，而 `_mirror_write` 吞掉异常，JSON 仍可能向客户端返回成功。

修复：

- dual 对 save/rescan/confirm/finalize 全部使用 strict unmatched-review write。
- JSON 写入先在隔离 working state 中执行，不立即发布或持久化。
- PostgreSQL 对应操作成功后才提交 JSON working state。
- PostgreSQL 异常会传播并丢弃 JSON working state；客户端不会在 PostgreSQL 仍 open 时收到 finalization success。

### Finding 3 - finalization/audit 泄漏照片 URL 与存储信息

根因：finalization 直接返回完整 group/photo payload；JSON audit 将 `source_url` 等快照原样写入；PostgreSQL 多条 audit writer 也能直接持久化照片快照；production `/local-test/audit-log` 对非管理员认证角色开放。

修复：

- finalization 改为正向 allowlist DTO，只返回安全 group 字段、稳定 photo ID、category 和认证 content route。
- production audit-log 在读取 repository 前强制管理员鉴权。
- 增加递归 audit redactor，覆盖 raw/signed/image/source/photo URL、bucket、storage/object/OSS key 等字段。
- JSON audit 写入和读取都执行递归 redaction。
- PostgreSQL 所有 audit 创建统一经过 `_stage_transactional_audit`，写入前递归 redaction；读取和 API response 再次 redaction。
- 自审补充了 construction activity audit 的 RED/GREEN，确保旧 audit writer 也不能绕过持久化 redaction。

### Finding 4 - JSON/PostgreSQL 正式照片 ID 不一致

根因：review migration rows 没有携带正式照片 `id`，PostgreSQL `_add_photo_records_to_group` 因此生成随机 UUID 片段；JSON 则在另一层生成 group-dependent ID。

修复：

- migration row 统一生成 `p-unmatched-{unmatched_id}-{review_photo_hash}`。
- JSON 和 PostgreSQL 都直接使用 migration row 中的同一 ID。
- ID 不依赖正式 group ID，因此附加到既有组或新建组时结果一致。

### Finding 5 - PostgreSQL legacy unmatched mutation 缺事务审计

根因：update、assign、unassign、outside-project、associate、delete 直接 commit 业务变更，没有在同一 session/transaction 中 stage `AuditLog`。

修复：

- 六个 active mutation 全部通过共享 helper 写 actor、action、entity、expected version、before、after。
- audit 在业务 mutation 后、同一次 commit 前 stage。
- stale version 在 stage audit 前失败；commit failure 会整体 rollback，不能留下 audit。

### Finding 6 - 前端仍暴露 retired dedupe

根因：项目驾驶舱仍保留 dedupe import、loading state、handler、菜单项、service 和 type。

修复：

- 完整删除 dedupe UI、调用、API service 和类型。
- unmatched UI verifier 增加反向断言，禁止这些 token 和 retired endpoint 回归。

### Finding 7 - release truthfulness 漏掉英文和正文矛盾

根因：verifier 只解析中文 deployed/candidate marker，且部署判断主要依赖 status-like field；正文中带版本号的 affirmative deployment prose 可绕过。

修复：

- 分别解析 English/Chinese deployed baseline 和 candidate marker，并要求语义一致。
- 扫描整个 release record 中带标题版本号的 affirmative deployed/shipped/released/已部署/已发布/已上线正文。
- pending status 与 affirmative prose 同时存在时失败。
- 保留 not/never/未/尚未、pending、future/scheduled/计划等否定或待部署语义。

### Finding 8 - package verifier 未要求 V3.0.80.md

根因：`verify-client-release.py` 的 `REQUIRED_FILES` 停留在旧版本记录集合。

修复：

- `REQUIRED_FILES` 增加 `ops/releases/V3.0.80.md`。
- 新增 archive fixture 测试，删除该文件后必须验证失败。

## TDD RED/GREEN 记录

以下 RED 均在 production code 修改前运行，失败原因与对应 finding 一致；随后使用同一 focused command 获得 GREEN。

### Finding 1

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_state_repository.py::test_postgres_finalization_reuses_compatible_group_after_duplicate_catalog_race v2-api\tests\test_state_repository.py::test_postgres_finalization_rejects_incompatible_group_on_unique_identity -q
```

- RED：`2 failed`，表现为未处理的 `IntegrityError`/缺少受控 identity conflict。
- GREEN：`2 passed`。

### Finding 2

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_local_simulation.py::test_dual_unmatched_review_evolves_both_backends_before_finalization v2-api\tests\test_local_simulation.py::test_dual_finalization_failure_keeps_json_unmatched_record_open -q
```

- RED：`2 failed`，save/rescan/confirm 未 mirror，且 finalization mirror failure 被吞掉。
- GREEN：`2 passed`。

### Finding 3

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py::test_unmatched_finalization_response_uses_stable_ids_and_content_routes v2-api\tests\test_api.py::test_production_audit_log_is_admin_only_and_recursively_redacted v2-api\tests\test_local_simulation.py::test_json_audit_events_recursively_redact_photo_storage_secrets -q
```

- RED：`3 failed`，分别证明 unsafe finalization DTO、非管理员 audit access、JSON audit 未递归脱敏。
- GREEN：`3 passed`。

受控 `409` 路由补充：

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py::test_production_finalization_identity_conflict_returns_409 -q
```

- GREEN：`1 passed`。

持久化全局不变量自审补充：

```powershell
cd v2-api
..\.venv\Scripts\python.exe -m pytest tests\test_state_repository.py::test_postgres_construction_activity_audit_redacts_nested_photo_secrets_before_persistence -q
```

- RED：`1 failed`，nested `source_url/storage_bucket/storage_key` 被原样 stage。
- GREEN：`1 passed`。

### Finding 4

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_unmatched_review.py::test_migrated_photo_rows_include_backend_independent_formal_ids v2-api\tests\test_state_repository.py::test_postgres_migrated_photo_uses_same_backend_independent_id_as_json v2-api\tests\test_local_simulation.py::test_json_migrated_photo_ids_do_not_collide_across_unmatched_records -q
```

- RED：`3 failed`，migration ID 缺失或 backend ID 格式不一致。
- GREEN：`3 passed`。

### Finding 5

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_state_repository.py -k "postgres_legacy_unmatched" -q
```

- RED：`6 failed, 12 passed`；六个成功 mutation 都没有 audit，stale/failing 无 audit 的 12 个用例已通过。
- GREEN：`18 passed`。

### Finding 6

```powershell
node scripts\verify_project_board_unmatched_review.js
```

- RED：verifier 在 `dedupeUnmatchedRecords` import 上失败。
- GREEN：`project board unmatched review checks passed`。

### Finding 7

```powershell
.\.venv\Scripts\python.exe -m pytest scripts\test_verify_release_sop.py -k "disagreement_between_english_and_chinese or affirmative_candidate_deployment_prose or preserves_negated_or_pending" -q
```

- RED：`5 failed, 4 passed`。
- GREEN：`9 passed`。

### Finding 8

```powershell
.\.venv\Scripts\python.exe -m pytest scripts\test_verify_client_release.py -q
```

- RED：`1 failed`，缺少 `ops/releases/V3.0.80.md` 的 archive 被错误接受。
- GREEN：`1 passed`。

## 最终验证

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests -q
```

- `470 passed, 1 warning in 121.91s`。
- warning 为现有 FastAPI TestClient 的 `StarletteDeprecationWarning`。

```powershell
.\.venv\Scripts\python.exe -m pytest scripts\test_verify_release_sop.py scripts\test_verify_client_release.py -q
```

- `143 passed in 0.45s`。

```powershell
node scripts\verify_project_board_unmatched_review.js
```

- PASS：`project board unmatched review checks passed`。

```powershell
.\.venv\Scripts\python.exe scripts\verify_security_hardening.py
```

- PASS：`[OK] security hardening static checks passed`。

```powershell
.\.venv\Scripts\python.exe scripts\verify_release_sop.py
```

- PASS：`[OK] release SOP files and references are consistent`。

```powershell
cd v2-web
npm run build
```

- PASS：`vue-tsc --noEmit` 和 Vite build 成功，`1889 modules transformed`，`built in 4.67s`。
- 非阻断 warning：VueUse PURE annotation 位置、两个 chunk 大于 500 kB。

```powershell
git diff --check
git status --short -- v2-api/app/static/vue
```

- PASS：无 whitespace error。
- PASS：build 后已 restore/clean，generated static asset 路径无变更。

## 修改文件

- `scripts/test_verify_client_release.py`
- `scripts/test_verify_release_sop.py`
- `scripts/verify-client-release.py`
- `scripts/verify_project_board_unmatched_review.js`
- `scripts/verify_release_sop.py`
- `v2-api/app/api/routes/local_test.py`
- `v2-api/app/services/local_simulation.py`
- `v2-api/app/services/state_repository.py`
- `v2-api/app/services/unmatched_review.py`
- `v2-api/tests/test_api.py`
- `v2-api/tests/test_local_simulation.py`
- `v2-api/tests/test_state_repository.py`
- `v2-api/tests/test_unmatched_review.py`
- `v2-web/src/api/services.ts`
- `v2-web/src/api/types.ts`
- `v2-web/src/views/ProjectBoardView.vue`
- `.superpowers/sdd/final-review-fix-report.md`

## 自审

- 逐项对照 binding findings，8/8 均有 focused regression coverage。
- `PostgresStateRepository` 中只有共享 helper 保留直接 `AuditLog(...)` 构造，其他 writer 均经写前脱敏。
- finalization response 使用正向字段 allowlist，没有依赖黑名单删字段。
- dual strict path 不使用会吞异常的 `_mirror_write`。
- legacy mutation 的 audit 和业务写使用同一 session/commit；stale/failure 用例证明不会持久化 audit。
- 前端 dedupe 的 import/state/handler/menu/service/type 均已删除并由 verifier 反向约束。
- 未修改 `ops/releases/V3.0.80.md` 的 pending 状态、AGENTS baseline/candidate、应用版本或生成静态资源。

## 关注点

- 无 release-blocking concern。
- 本任务按禁令未访问生产，也未运行真实生产 PostgreSQL 并发；唯一身份 SQL、锁 key、真实 materialization 路径、冲突转换和事务 rollback 由 focused repository tests 覆盖。
- dual 是跨 JSON/PostgreSQL 的协调写而非数据库级分布式事务；PostgreSQL 失败会阻止 JSON 发布并向客户端报错，满足本次“不得在 PostgreSQL 仍 open 时返回成功”的绑定要求。
- 前端 build 的现有 chunk-size/Rollup warning 未在本次 scope 内处理。

## 发布状态

- `V3.0.80` 仍为 pending candidate。
- 未 package、未 deploy、未 production access、未 baseline advance。
