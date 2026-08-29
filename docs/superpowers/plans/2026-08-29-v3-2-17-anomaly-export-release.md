# V3.2.17 异常确认与表号模块号导出发布实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将中文异常原因、手工确认修复留痕和驾驶舱表号模块号 XLSX 导出作为 V3.2.17 可回滚发布上线。

**Architecture:** 以生产 V3.2.16 为不可变回滚基线，在 `production/V3/3.2.17` 固化版本契约、构建独立发布包，并通过时间戳 release 目录原子切换。异常确认只修改现有 JSON/PostgreSQL 结构，不新增迁移；DualWrite 无跨库事务时在任一后端写入前安全拒绝。

**Tech Stack:** FastAPI, SQLAlchemy, Vue 3, Vitest, pytest, PowerShell release builder, systemd, Nginx.

**Spec:** `docs/superpowers/specs/2026-08-26-unified-terminal-review-rephoto-workbench-design.md`

## Global Constraints

- V3.2.16 保持不可变，并作为 V3.2.17 的回滚目录和数据库兼容基线。
- 不新增数据库迁移，不修改生产业务数据，不触发相机、OSS 写入或甲方平台请求。
- 缺采集器照片不计异常；已确认异常必须保留处理人、时间、原因，证据变化后自动重开。
- 全量表号模块号对应关系只通过驾驶舱按钮导出 XLSX，不在页面展示全量表格。
- 生产发布必须先备份、核对本地/服务器包哈希、等待 `127.0.0.1:8000`，再完成健康、页面、权限和只读业务验收。

---

### Task 1: V3.2.17 版本与发布门禁

**Files:**
- Create: `scripts/verify_v3_2_17_release.py`
- Create: `scripts/test_verify_v3_2_17_release.py`
- Create: `ops/releases/V3.2.17.md`
- Modify: `scripts/build-client-release.ps1`
- Modify: `scripts/verify-client-release.py`
- Modify: `scripts/verify_release_sop.py`
- Modify: runtime/frontend version files and current-candidate SOP markers

**Interfaces:**
- Consumes: immutable V3.2.16 source/package verifier and release record.
- Produces: V3.2.17 source, package and attestation phases bound to V3.2.16.

- [x] **Step 1: Add the V3.2.17 release-contract tests**

Clone the V3.2.16 contract tests, bind the baseline record SHA256 to `D12D9C19E75DD25BC0D8CFC35ABADB4F890D0C6F8ECE77EB14856A07FD4BC116`, and require the new anomaly/export files and markers.

- [x] **Step 2: Run the focused test and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest .\scripts\test_verify_v3_2_17_release.py -q`

Expected: fail because `scripts/verify_v3_2_17_release.py` and V3.2.17 runtime markers do not exist.

- [x] **Step 3: Implement the minimal V3.2.17 release contract**

Add the verifier, pending release record, current-candidate routing, package allowlist, version markers and Chinese release notes. Preserve V3.2.16 as an immutable baseline input.

- [x] **Step 4: Run source and SOP gates**

Run the focused release tests, `scripts/verify_v3_2_17_release.py --phase source`, and `scripts/verify_release_sop.py --version V3.2.17 --phase source`.

- [x] **Step 5: Commit release preparation**

Commit only the V3.2.17 release/version/static-source files and this plan on `production/V3/3.2.17`.

### Task 2: Build and verify the exact server package

**Files:**
- Produce: `build/server-release/module-manager-v2-server-3.2.17.zip`

**Interfaces:**
- Consumes: clean V3.2.17 production branch.
- Produces: a ZIP whose `SOURCE_COMMIT`, manifest, CRC, required/forbidden members and SHA256 are verified.

- [x] **Step 1: Run full backend/frontend validation**

Run backend pytest, frontend component/state/view tests, Vue migration/data-center gates, type-check/build and `git diff --check`.

- [x] **Step 2: Build the package**

Run: `powershell -ExecutionPolicy Bypass -File .\scripts\build-client-release.ps1 -Version 3.2.17 -SkipSmoke`

- [x] **Step 3: Verify the package independently**

Run generic package verification and `scripts/verify_v3_2_17_release.py --phase package` with the exact source commit, then compute local SHA256.

### Task 3: Reversible production cutover and attestation

**Files:**
- Modify after live verification: `ops/releases/V3.2.17.md`

**Interfaces:**
- Consumes: verified V3.2.17 ZIP, `root@www.sgcc.online`, and `C:\Users\Administrator\Downloads\XXXXXX.pem`.
- Produces: V3.2.17 current release, V3.2.16 rollback point, backup evidence, acceptance evidence and Git attestation.

- [x] **Step 1: Create and verify a restore-ready backup**

Run the server backup script and verify relative `SHA256SUMS`, current-release/data/uploads archives and PostgreSQL dump listing before cutover.

- [x] **Step 2: Upload and match SHA256**

Upload only the verified ZIP to `/tmp/` and require exact local/server SHA256 equality.

- [x] **Step 3: Extract and atomically switch**

Create `/opt/module-manager-v2/releases/v3.2.17-<UTC timestamp>`, preserve `.env` and shared uploads, install dependencies, confirm Alembic remains `20260824_0016`, switch `current`, restart and automatically roll back to the recorded V3.2.16 directory on any readiness failure.

- [x] **Step 4: Run readiness and functional acceptance**

Require one listener on `127.0.0.1:8000`, local/public version 3.2.17, required pages 200, protected APIs 401 when unauthenticated, authenticated read-only dashboard/data-center checks, and XLSX export response validation without invoking mutation, camera, OSS or client-platform operations.

- [x] **Step 5: Retention and attestation**

Dry-run retention to five release directories, record the selected oldest releases without deleting backups or either V3.2.17 candidate, update the release record with exact evidence, and run attestation verification. Commit, branch push and the `V3.2.17` tag are the final Git bookkeeping after this evidence is recorded.

### Guarded rollback remediation: production-scale XLSX export

- [x] Reproduce the production timeout with `22358` project rows and prove the paginated route repeats about `224` full data-center queries.
- [x] Add failing route, JSON and PostgreSQL regression tests that require one dedicated export read.
- [x] Replace the pagination loop with one terminal-sorted, unbounded projection query containing only workbook fields.
- [x] Re-run the full release gates, rebuild the source-bound package, and require the production XLSX response to finish within 30 seconds before retaining the cutover.

## Final evidence

- The first V3.2.17 candidate was rolled back safely after the paginated export exceeded 60 seconds and produced Nginx `499`.
- Commit `16855540ba4679c43638f5c86f37370f8be2344c` changed the route and both repositories to one terminal-sorted projection read without a migration or workbook-format change.
- The rebuilt package SHA256 is `117241c80c952ffb16694e279b263e1a686f8c279798cc77ec5b91dcb1d9d4a1`; local and server upload hashes matched before cutover.
- Restore-ready backup: `/opt/module-manager-v2/backups/v3.2.17-20260829T095252Z`; successful release: `/opt/module-manager-v2/releases/v3.2.17-20260829T095416Z`; rollback: `/opt/module-manager-v2/releases/v3.2.16-20260829T020456Z`.
- Production exported and parsed `22358` XLSX rows in `4.354` seconds. Protected anonymous APIs returned `401`; health and required routes returned `200`; no camera, OSS write, production business-data mutation or client-platform request was invoked.
- Retention was dry-run only: V3.2.13 and V3.2.12 were listed as candidates, while all backups and both V3.2.17 candidate directories were preserved.
