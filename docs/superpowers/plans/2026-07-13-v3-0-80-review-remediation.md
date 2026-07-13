# V3.0.80 独立审阅阻断项修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 V3.0.80 独立代码审阅发现的权限绕过、并发终结、状态重算、URL 泄露和版本基线问题，在第二轮独立审阅通过后再发布生产。

**Architecture:** 新临时审阅接口仍允许审阅员和管理员使用，但只有管理员可以最终确定终端。旧未匹配写接口统一使用 JWT 身份、权威审阅版本和事务审计；旧正式化接口在生产环境停止使用，所有正式化均进入候选终结契约。JSON 与 PostgreSQL 仓储共同拒绝占位终端并保证迁移 ID、审批重算、并发终结和请求重放一致。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、SQLAlchemy/PostgreSQL、pytest、Vue 3、TypeScript、Node 静态验收脚本。

## Global Constraints

- 当前已部署生产版本保持 `V3.0.79`；`V3.0.80` 只能标记为候选版本，部署完成并取得线上证据后才更新生产基线。
- 不得创建空终端、`00000000`、`未关联终端`、`manual-*` 或 `unmatched-*` 等合成正式终端/表号。
- 审阅员可保存临时分类、人工确认和重新扫码；只有管理员可最终匹配终端。
- 所有旧未匹配写操作必须从 JWT 绑定 actor，要求 `expected_version`，版本过期返回 `409`，且不得持久化或写审计。
- 审阅和列表响应不得返回 `source_url`、`photo_urls`、带签名参数的 URL 或原始 `raw`；客户端只接收稳定 ID 和受鉴权内容接口。
- PostgreSQL 终结必须原子、可重放，并在候选资料组尚不存在时避免唯一约束竞争导致 `500`。
- 正式照片证据变化时，无论新增照片还是合并重复照片，都必须撤销旧审批、审阅人、归档和异常结论并重新计算。
- 先测试后实现；每项任务均需独立审阅通过。总分支审阅通过前不得打包、备份、切换生产或清理服务器版本。

## File Structure

- Modify `v2-api/app/main.py`: 生产写接口权限矩阵，覆盖精确 `/local-test/groups` 和所有旧未匹配写路由。
- Modify `v2-api/app/api/routes/local_test.py`: JWT actor、`expected_version`、`409` 映射、旧正式化停用和安全响应 DTO。
- Modify `v2-api/app/services/unmatched_review.py`: 正式身份校验、安全响应投影和版本辅助函数。
- Modify `v2-api/app/services/local_simulation.py`: JSON 版本锁、唯一照片 ID、占位身份拒绝和审计原子性。
- Modify `v2-api/app/services/state_repository.py`: PostgreSQL 版本锁、审计、状态重算、候选锁和幂等终结。
- Modify `v2-web/src/api/types.ts`, `v2-web/src/api/services.ts`, `v2-web/src/views/ProjectBoardView.vue`, `v2-web/src/views/TaskHallView.vue`: 传递权威版本并停止调用生产旧正式化入口。
- Modify `v2-api/tests/test_api.py`, `v2-api/tests/test_local_simulation.py`, `v2-api/tests/test_state_repository.py`: 回归覆盖。
- Modify `AGENTS.md`, `scripts/verify_release_sop.py`, `ops/releases/V3.0.80.md`: 区分已部署基线与候选版本。

---

### Task 1: 封闭旧入口并统一版本与可信 actor

**Files:**
- Modify: `v2-api/app/main.py`
- Modify: `v2-api/app/api/routes/local_test.py`
- Modify: `v2-api/app/services/unmatched_review.py`
- Modify: `v2-api/app/services/local_simulation.py`
- Modify: `v2-api/app/services/state_repository.py`
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/views/ProjectBoardView.vue`
- Modify: `v2-web/src/views/TaskHallView.vue`
- Test: `v2-api/tests/test_api.py`

**Interfaces:**
- Produces: `review_version: int` in unmatched list rows.
- Produces: every legacy mutation request carries `expected_version: int`.
- Produces: stale writes raise `unmatched_review.ReviewVersionConflict` and routes map it to HTTP `409`.
- Produces: `safe_review_response(payload) -> dict[str, Any]` containing IDs, metadata, categories, scan result and authenticated content URLs only.

- [ ] **Step 1: Write failing API tests**

```python
def test_production_exact_group_create_requires_admin(production_client):
    response = production_client.post(
        "/local-test/groups",
        headers=constructor_headers(),
        json={"actor": "forged-admin", "terminal": "T-001", "meter_no": "120000000001"},
    )
    assert response.status_code == 403


def test_production_legacy_unmatched_mutations_require_admin(production_client):
    for method, suffix, body in legacy_unmatched_mutation_cases():
        response = production_client.request(method, f"/local-test/unmatched/u-1/{suffix}", headers=reviewer_headers(), json=body)
        assert response.status_code == 403


def test_unmatched_mutation_rejects_stale_version_without_write_or_audit(admin_client, repository):
    before = repository.snapshot()
    response = admin_client.patch(
        "/local-test/unmatched/u-1",
        json={"actor": "forged", "expected_version": 1, "updates": {"note": "stale"}},
    )
    assert response.status_code == 409
    assert repository.snapshot() == before


def test_unmatched_review_response_hides_raw_photo_urls(admin_client):
    payload = admin_client.get("/local-test/unmatched/u-1/review").json()["data"]
    serialized = json.dumps(payload)
    assert "source_url" not in serialized
    assert "photo_urls" not in serialized
    assert "token=secret" not in serialized
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `\.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -k "exact_group_create or legacy_unmatched or unmatched_mutation_rejects_stale or review_response_hides" -q`

Expected: tests fail because the exact group route and legacy routes are not fully protected, body actors are trusted, versions are absent, and raw URLs are returned.

- [ ] **Step 3: Implement the minimal route and DTO contract**

```python
LEGACY_UNMATCHED_ADMIN_SUFFIXES = (
    "/assign", "/unassign", "/outside-project", "/rematch", "/associate", "/create-group", "/delete"
)

def safe_review_response(payload: dict[str, Any]) -> dict[str, Any]:
    review = deepcopy(payload["review"])
    for photo in review.get("photos", []):
        photo.pop("source_url", None)
        photo.pop("image_url", None)
    record = {key: payload["record"].get(key) for key in SAFE_UNMATCHED_RECORD_FIELDS}
    return {"record": record, "review": review}
```

Use `request_actor(request)` for every legacy mutation. Add `expected_version` to each request model and repository method. In production, `/rematch`, `/associate`, and `/create-group` return `410` with the instruction to use `/review`, `/match-candidates`, and `/finalize-match`; update both Vue callers to open the review flow instead of invoking those endpoints.

- [ ] **Step 4: Run focused backend and frontend contract checks**

Run: `\.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -k "production and unmatched or exact_group_create or review_response_hides" -q`

Run: `npm --prefix v2-web run build`

Expected: all focused tests and the TypeScript production build pass.

- [ ] **Step 5: Commit**

```powershell
git add v2-api/app/main.py v2-api/app/api/routes/local_test.py v2-api/app/services/unmatched_review.py v2-api/app/services/local_simulation.py v2-api/app/services/state_repository.py v2-api/tests/test_api.py v2-web/src/api/types.ts v2-web/src/api/services.ts v2-web/src/views/ProjectBoardView.vue v2-web/src/views/TaskHallView.vue
git commit -m "fix: close legacy unmatched write bypasses"
```

### Task 2: 保证正式资料写入的一致性与幂等性

**Files:**
- Modify: `v2-api/app/services/unmatched_review.py`
- Modify: `v2-api/app/services/local_simulation.py`
- Modify: `v2-api/app/services/state_repository.py`
- Test: `v2-api/tests/test_local_simulation.py`
- Test: `v2-api/tests/test_state_repository.py`

**Interfaces:**
- Produces: `require_real_formal_identity(*, terminal: str, meter_no: str) -> tuple[str, str]`.
- Produces: JSON migrated photo IDs include unmatched ID and review photo ID hash.
- Produces: PostgreSQL finalization takes a transaction-scoped candidate lock and stores a replayable result in unmatched `raw_data`.

- [ ] **Step 1: Write failing repository tests**

```python
@pytest.mark.parametrize("terminal", ["", "00000000", "未关联终端", "manual-1", "unmatched-1"])
def test_formal_group_creation_rejects_synthetic_terminal(repository, terminal):
    with pytest.raises(ValueError):
        repository.create_empty_group_for_terminal(terminal=terminal, actor="admin", meter_no="120000000001")


def test_json_migrated_photo_ids_do_not_collide_across_unmatched_records(json_repository):
    first = finalize_fixture(json_repository, unmatched_id="u-1", candidate_key="c-1")
    second = finalize_fixture(json_repository, unmatched_id="u-2", candidate_key="c-1")
    ids = [photo["id"] for photo in second["group"]["photos"]]
    assert len(ids) == len(set(ids))


def test_postgres_duplicate_evidence_resets_formal_review_state(postgres_repository):
    result = finalize_duplicate_evidence_fixture(postgres_repository, status="approved", archived=True)
    assert result["group"]["status"] == "pending"
    assert result["group"]["reviewer"] == ""
    assert result["group"]["reviewed_at"] == ""
    assert result["group"]["archive_status"] != "archived"


def test_postgres_finalize_replay_returns_same_result_without_duplicate_group(postgres_repository):
    first = postgres_repository.finalize_unmatched_match("u-1", actor="admin", candidate_key="c-1", expected_version=1)
    second = postgres_repository.finalize_unmatched_match("u-1", actor="admin", candidate_key="c-1", expected_version=1)
    assert second == first
```

- [ ] **Step 2: Run repository tests and verify RED**

Run: `\.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_local_simulation.py v2-api\tests\test_state_repository.py -k "synthetic_terminal or photo_ids_do_not_collide or duplicate_evidence_resets or finalize_replay" -q`

Expected: placeholder creation, photo ID collision, stale approval, or replay tests fail for the reviewed reasons.

- [ ] **Step 3: Implement shared validation, evidence reset and candidate locking**

```python
SYNTHETIC_FORMAL_VALUES = {"00000000", "未关联终端"}

def require_real_formal_identity(*, terminal: str, meter_no: str) -> tuple[str, str]:
    terminal_value = terminal.strip()
    meter_value = meter_no.strip()
    if not terminal_value or terminal_value in SYNTHETIC_FORMAL_VALUES or terminal_value.lower().startswith(("manual-", "unmatched-")):
        raise ValueError("A real terminal is required")
    if not meter_value or meter_value in SYNTHETIC_FORMAL_VALUES or meter_value.lower().startswith(("manual-", "unmatched-")):
        raise ValueError("A real meter number is required")
    return terminal_value, meter_value
```

For PostgreSQL, acquire `pg_advisory_xact_lock` from a stable signed 64-bit hash of `(team_id, candidate_key)` before selecting or creating the group. Persist `{candidate_key, expected_version, result}` on successful finalization and return it on an exact replay. Any `photos_new > 0` or `photos_merged > 0` path must call one shared reset/recompute helper before commit.

- [ ] **Step 4: Run focused and broad repository tests**

Run: `\.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_local_simulation.py v2-api\tests\test_state_repository.py -q`

Expected: all JSON and PostgreSQL repository tests pass.

- [ ] **Step 5: Commit**

```powershell
git add v2-api/app/services/unmatched_review.py v2-api/app/services/local_simulation.py v2-api/app/services/state_repository.py v2-api/tests/test_local_simulation.py v2-api/tests/test_state_repository.py
git commit -m "fix: make unmatched finalization atomic and replayable"
```

### Task 3: 修正版本基线并完成第二轮总审阅与发布门禁

**Files:**
- Modify: `AGENTS.md`
- Modify: `scripts/verify_release_sop.py`
- Modify: `ops/releases/V3.0.80.md`
- Verify: all branch changes since `94bdadc`

**Interfaces:**
- Produces: separate `deployed production baseline` and `release candidate` values.
- Produces: a clean second independent review before release packaging.

- [ ] **Step 1: Write a failing release verifier assertion**

```python
assert agents_text_contains_deployed_baseline("V3.0.79")
assert agents_text_contains_release_candidate("V3.0.80")
assert not release_record_claims_deployed_without_live_evidence("ops/releases/V3.0.80.md")
```

- [ ] **Step 2: Run release verifier and verify RED**

Run: `\.\.venv\Scripts\python.exe scripts\verify_release_sop.py`

Expected: failure because `AGENTS.md` currently labels V3.0.80 as production.

- [ ] **Step 3: Implement distinct baseline/candidate markers**

Before deployment, `AGENTS.md` must state `当前已部署生产版本：V3.0.79` and `当前发布候选版本：V3.0.80`. `verify_release_sop.py` parses the two markers independently and forbids claiming deployment when backup, package hash, release directory and live checks are still empty.

- [ ] **Step 4: Run the complete local verification stack**

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests -q
npm --prefix v2-web run build
node scripts\verify_project_board_unmatched_review.js
.\.venv\Scripts\python.exe scripts\verify_security_hardening.py
.\.venv\Scripts\python.exe scripts\verify_release_sop.py
.\.venv\Scripts\python.exe scripts\verify-client-release.py --help
git diff --check 94bdadc..HEAD
```

Expected: every command exits `0`; generated Vue static assets are restored before reviewing the worktree.

- [ ] **Step 5: Dispatch a fresh memory-free whole-branch review**

Review range: `94bdadc..HEAD`. Required verdict: no Critical/High/Medium release blockers across RBAC, actor binding, optimistic locking, response secrecy, placeholder identities, JSON IDs, PostgreSQL state reset, concurrency, idempotency and version truthfulness.

- [ ] **Step 6: Package and deploy only after APPROVE**

Build `module-manager-v2-server-3.0.80.zip`, verify local/server SHA256, back up current release plus `.env`, data, uploads, PostgreSQL dump/schema and hashes, then cut over and verify `/health`, `/login`, `/project-board`, `/task-hall`, `/review`, unmatched review APIs and live RBAC. Use server IP `106.14.122.43`; retain only the newest five release directories.

- [ ] **Step 7: Record live evidence and advance the deployed baseline**

Only after successful live checks, update `AGENTS.md` to `当前已部署生产版本：V3.0.80`, clear the candidate marker, fill `ops/releases/V3.0.80.md` with backup directory, package SHA256, release directory, service status and page/API results, commit and push.
