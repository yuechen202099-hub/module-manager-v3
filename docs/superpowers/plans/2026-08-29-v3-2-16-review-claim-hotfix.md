# V3.2.16 审阅领取门禁热修发布实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将未匹配列表过滤、审阅保存去领取校验和已下线审阅员文案作为 V3.2.16 可回滚发布上线。

**Architecture:** 以已部署的 V3.2.15 为不可变回滚基线，创建 V3.2.16 生产分支、版本契约、候选记录和独立发布包。生产切换使用时间戳 release 目录、原子 current 链接、Uvicorn 端口就绪门禁和健康/权限/只读业务验收。

**Tech Stack:** FastAPI, SQLAlchemy, Vue 3, Vitest, pytest, PowerShell release builder, systemd, Nginx.

**Spec:** `docs/superpowers/specs/2026-08-26-unified-terminal-review-rephoto-workbench-design.md`

## Global Constraints

- V3.2.15 保持不可变，并作为 V3.2.16 的回滚目录和数据库兼容基线。
- 不新增数据库迁移，不修改生产业务数据，不触发相机或甲方平台请求。
- 只将状态为 `open` 的未匹配记录暴露给审阅入口。
- 审阅决定不再依赖已删除的审阅员领取关系；历史 `reviewer` 字段只用于兼容和留痕。
- 生产发布必须先备份、校验本地/服务器包哈希、等待 `127.0.0.1:8000`、完成健康/页面/权限验收，再执行 release 保留 dry-run。

---

### Task 1: V3.2.16 版本与发布门禁

**Files:**
- Create: `scripts/verify_v3_2_16_release.py`
- Create: `scripts/test_verify_v3_2_16_release.py`
- Create: `ops/releases/V3.2.16.md`
- Modify: `scripts/build-client-release.ps1`
- Modify: `scripts/verify-client-release.py`
- Modify: `scripts/verify_release_sop.py`
- Modify: runtime and frontend version files referenced by the release verifier

**Interfaces:**
- Consumes: V3.2.15 source/package verifier contract.
- Produces: `V3.2.16` source, package, and attestation phases with V3.2.15 rollback baseline.

- [x] **Step 1: Write the failing release-contract and runtime-version tests**

Clone the V3.2.15 verifier tests to V3.2.16, set the deployed baseline to V3.2.15, and change the runtime version assertions to 3.2.16.

- [x] **Step 2: Run the focused tests and confirm failure**

Run: `v2-api\.venv\Scripts\python.exe -m pytest scripts/test_verify_v3_2_16_release.py v2-api/tests/test_v3_1_release.py -q`

Expected: failure because V3.2.16 verifier/runtime markers do not yet exist.

- [x] **Step 3: Implement the minimal V3.2.16 source contract**

Add the cloned verifier, candidate release record, version markers, current-candidate documentation, build allowlist, and generic verifier/SOP routing required to build exactly V3.2.16.

- [x] **Step 4: Run focused tests and source gates**

Run the focused pytest command, `scripts/verify_v3_2_16_release.py --phase source`, and `scripts/verify_release_sop.py --version V3.2.16 --phase source`.

- [x] **Step 5: Commit release preparation**

Commit only the V3.2.16 release/version files and the new plan.

### Task 2: Package and independent verification

**Files:**
- Produce: `build/server-release/module-manager-v2-server-3.2.16.zip`
- Produce: `build/server-release/module-manager-v2-server-3.2.16.sha256`

**Interfaces:**
- Consumes: clean V3.2.16 production branch.
- Produces: package whose `SOURCE_COMMIT`, manifest, CRC, file set, and SHA256 are independently verified.

- [x] **Step 1: Run full backend/frontend verification**

Run the backend full pytest suite, all view/component Vitest suites, and the Vue production build.

- [ ] **Step 2: Build the server release**

Run: `scripts\build-client-release.ps1 -Version 3.2.16`

- [ ] **Step 3: Verify package**

Run the generic package verifier and `scripts/verify_v3_2_16_release.py --phase package --expected-source-commit <commit> --package <zip>`.

### Task 3: Reversible production cutover

**Files:**
- Modify after verified deployment: `ops/releases/V3.2.16.md`

**Interfaces:**
- Consumes: verified V3.2.16 ZIP and `C:\Users\Administrator\Downloads\XXXXXX.pem`.
- Produces: new V3.2.16 release, V3.2.15 rollback point, backup evidence, and production acceptance.

- [ ] **Step 1: Create and verify a restore-ready backup**

Run the production backup script and verify `SHA256SUMS`, PostgreSQL dump listing, and archive listings before cutover.

- [ ] **Step 2: Upload and match SHA256**

Upload to `root@www.sgcc.online:/tmp/` and require exact local/server hash equality.

- [ ] **Step 3: Extract, install, migrate-compatible check, and atomically switch**

Create `/opt/module-manager-v2/releases/v3.2.16-<UTC timestamp>`, preserve shared paths and permissions, keep Alembic at `20260824_0016`, switch `current`, and restart services.

- [ ] **Step 4: Wait for readiness and run acceptance**

Require one Uvicorn listener, internal/public health version 3.2.16, required pages 200, protected APIs 401 when unauthenticated, and read-only checks for the deployed claim-removal/open-record markers.

- [ ] **Step 5: Retention and attestation**

Dry-run retention to 5 releases, remove only the single oldest release if selected, update the release record, run attestation verifier, commit, push the production branch, and tag V3.2.16.
