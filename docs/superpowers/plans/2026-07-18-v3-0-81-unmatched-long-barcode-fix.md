# V3.0.81 未匹配长条码候选修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复未匹配临时审阅把 22 位现场表条码错误当作总清单表号的问题，使其生成唯一候选并安全并入现有资料组，同时补关联生产中已确认的三条记录。

**Architecture:** 在纯业务模块 `unmatched_review.py` 增加唯一的临时审阅表号标准化入口，候选查询与扫码上下文共同复用。前端只为唯一候选提供默认选择，不自动终结；生产历史数据继续调用现有 `finalize_unmatched_match` 原子事务完成关联和审计。

**Tech Stack:** Python 3.14、FastAPI、SQLAlchemy/PostgreSQL、pytest、Vue 3、TypeScript、Element Plus、Node 静态验收脚本、PowerShell 发布脚本。

## Global Constraints

- 基线必须是 `origin/production/V3/3.0.80` 的 `77fa1b0d8f1ddbc8bf82a3b21c3b864d551db9fd`。
- 修复分支和应用候选版本必须是 `production/V3/3.0.81` / `V3.0.81`。
- 保存、人工确认、候选查看和最终关联继续保持分离；只有管理员能最终关联。
- 模块号和采集器号不能在缺少表号精确候选时单独触发归组。
- 不允许创建空终端、`00000000`、`manual-` 或 `unmatched-` 正式资料组。
- 历史数据先 dry-run，再逐条原子提交；任何零候选、多候选、版本冲突或目标冲突均停止该条。
- 发布前必须完成独立代码审阅、备份、包哈希和发布门禁；服务器仅保留最近五个 release。

---

### Task 1: 后端长条码标准化

**Files:**
- Modify: `v2-api/tests/test_unmatched_review.py`
- Modify: `v2-api/app/services/unmatched_review.py`

**Interfaces:**
- Consumes: `build_long_scan_match_key(value: str) -> str`、`build_total_catalog_match_key(value: str) -> str`。
- Produces: `review_meter_match_key(record, review) -> str` 对长扫码和总清单表号返回同一规范键；`barcode_context(review)` 使用相同键。

- [ ] **Step 1: 写长条码候选失败测试**

在 `v2-api/tests/test_unmatched_review.py` 增加：

```python
def test_long_scanned_meter_barcode_matches_total_catalog_candidate() -> None:
    record = sample_record()
    review = unmatched_review.build_review(record)
    review["meter_no"] = "3130001112100041536116"

    candidates = unmatched_review.build_match_candidates(
        record,
        review,
        [{
            "id": "catalog-long-scan",
            "catalog_row_db_id": "catalog-long-scan-db",
            "terminal": "350000135073",
            "meter_no": "110004153611",
            "meter_match_key": "0004153611",
            "address": "long scan road",
        }],
        [{
            "id": "g-12102",
            "terminal": "350000135073",
            "total_catalog_row_id": "catalog-long-scan-db",
            "meter_match_key": "0004153611",
        }],
    )

    assert unmatched_review.review_meter_match_key(record, review) == "0004153611"
    assert unmatched_review.barcode_context(review)["meter_match_key"] == "0004153611"
    assert len(candidates) == 1
    assert candidates[0]["target_group_id"] == "g-12102"
    assert candidates[0]["has_existing_group"] is True
```

- [ ] **Step 2: 运行测试确认 RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_unmatched_review.py::test_long_scanned_meter_barcode_matches_total_catalog_candidate -q
```

Expected: FAIL，当前返回完整 22 位匹配键且候选数为零。

- [ ] **Step 3: 实现最小标准化修复**

在 `v2-api/app/services/unmatched_review.py` 中导入 `build_long_scan_match_key` 和 `normalize_meter_text`，增加：

```python
def normalized_review_meter_match_key(value: Any) -> str:
    normalized = normalize_meter_text(str(value or ""))
    if not normalized:
        return ""
    try:
        if len(normalized) > 12:
            return build_long_scan_match_key(normalized)
        return build_total_catalog_match_key(normalized)
    except ValueError:
        return ""
```

让 `review_meter_match_key` 和 `barcode_context` 都调用该函数，不改变候选事务、权限或排序规则。

- [ ] **Step 4: 运行聚焦测试确认 GREEN**

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_unmatched_review.py v2-api\tests\test_matching.py -q
```

Expected: 全部通过，10 位、12 位和 22 位三类输入均保持预期行为。

- [ ] **Step 5: 提交后端修复**

```powershell
git add v2-api/tests/test_unmatched_review.py v2-api/app/services/unmatched_review.py
git commit -m "fix: match reviewed long meter barcodes"
```

---

### Task 2: 唯一候选默认选择

**Files:**
- Modify: `scripts/verify_project_board_unmatched_review.js`
- Modify: `v2-web/src/components/UnmatchedReviewDialog.vue`

**Interfaces:**
- Consumes: `fetchUnmatchedMatchCandidates(unmatchedId)` 返回 `UnmatchedMatchCandidate[]`。
- Produces: 候选数组仅有一项时设置 `selectedCandidateKey`；最终提交仍只由 `finalizeMatch()` 和管理员按钮触发。

- [ ] **Step 1: 先扩充前端静态门禁**

在 `scripts/verify_project_board_unmatched_review.js` 增加断言：

```javascript
assertContains(
  dialog,
  "selectedCandidateKey.value = next.length === 1 ? next[0].candidateKey : ''",
  'a unique unmatched candidate must be selected by default',
)
assertNotContains(
  section(dialog, 'async function loadMatchCandidates()', 'async function finalizeMatch()'),
  'finalizeUnmatchedMatch(',
  'loading candidates must never auto-finalize a match',
)
```

- [ ] **Step 2: 运行门禁确认 RED**

```powershell
node scripts\verify_project_board_unmatched_review.js
```

Expected: FAIL，提示唯一候选尚未默认选中。

- [ ] **Step 3: 实现前端最小修改**

在 `loadMatchCandidates()` 成功分支中设置：

```typescript
candidates.value = next
selectedCandidateKey.value = next.length === 1 ? next[0].candidateKey : ''
clampCandidatePage()
```

- [ ] **Step 4: 验证门禁和构建**

```powershell
node scripts\verify_project_board_unmatched_review.js
npm --prefix v2-web run build
```

Expected: 门禁通过，Vue TypeScript 检查和生产构建通过。

- [ ] **Step 5: 提交前端修改**

```powershell
git add scripts/verify_project_board_unmatched_review.js v2-web/src/components/UnmatchedReviewDialog.vue
git commit -m "fix: preselect unique unmatched candidate"
```

---

### Task 3: V3.0.81 版本和发布契约

**Files:**
- Modify: `AGENTS.md`
- Modify: `v2-api/app/main.py`
- Modify: `v2-api/app/services/ops_status.py`
- Modify: `v2-api/pyproject.toml`
- Modify: `v2-api/tests/test_api.py`
- Modify: `v2-web/index.html`
- Modify: `v2-web/package.json`
- Modify: `v2-web/pnpm-lock.yaml`
- Modify: `v2-web/src/version.json`
- Modify: `v2-web/src/components/AppLayout.vue`
- Modify: `v2-web/src/constants/releaseNotes.ts`
- Modify: `RELEASE_MANIFEST.md`
- Create: `ops/releases/V3.0.81.md`
- Modify: `scripts/verify_release_sop.py`
- Modify: `scripts/test_verify_release_sop.py`

**Interfaces:**
- Consumes: 已部署基线 `V3.0.80`。
- Produces: 发布候选 `V3.0.81`、中文更新记录和严格发布门禁。

- [ ] **Step 1: 先将版本断言改为 V3.0.81 并确认 RED**

将 API 版本测试、SOP 候选测试和前端版本门禁期望改为 `3.0.81`，但保留 `AGENTS.md` 已部署基线为 `V3.0.80`。

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -k version -q
.\.venv\Scripts\python.exe -m pytest scripts\test_verify_release_sop.py -q
```

Expected: FAIL，运行时代码和发布候选仍是 V3.0.80。

- [ ] **Step 2: 更新所有候选版本表面**

更新后必须满足：

```text
Deployed production baseline: V3.0.80
Release candidate: V3.0.81
Release-candidate maintenance branch: production/V3/3.0.81
```

在 `releaseNotes.ts` 增加中文条目“未匹配长条码候选修复”，说明长条码可以命中现有资料组、唯一候选默认选中且仍需管理员确认。

- [ ] **Step 3: 创建待发布记录**

`ops/releases/V3.0.81.md` 必须记录根因和修改范围，并明确写入 `Status: pending`、`Local Verification: not run`、`Package: pending`、`Production Deployment: pending`、`Production Reconciliation: pending` 和回滚目标 V3.0.80。发布执行后再用真实证据替换这些 pending 状态。

- [ ] **Step 4: 运行版本和 SOP 验证**

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -k version -q
.\.venv\Scripts\python.exe -m pytest scripts\test_verify_release_sop.py -q
.\.venv\Scripts\python.exe scripts\verify_release_sop.py
```

Expected: 全部通过，发布记录保持 pending 且没有伪造上线证据。

- [ ] **Step 5: 提交版本候选**

```powershell
git add AGENTS.md v2-api v2-web RELEASE_MANIFEST.md ops/releases/V3.0.81.md scripts/verify_release_sop.py scripts/test_verify_release_sop.py
git commit -m "chore: prepare V3.0.81 production release"
```

---

### Task 4: 独立审阅、全量验证和发布包

**Files:**
- Verify: `production/V3/3.0.80...production/V3/3.0.81`
- Modify only if findings require fixes.

**Interfaces:**
- Consumes: 完成的 V3.0.81 候选。
- Produces: 无 P0/P1/P2 未解决问题的审阅结论和可发布 zip。

- [ ] **Step 1: 运行全量本地门禁**

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests -q
.\.venv\Scripts\python.exe -m pytest scripts -q
npm --prefix v2-web run build
node scripts\verify_project_board_unmatched_review.js
.\.venv\Scripts\python.exe scripts\verify_security_hardening.py
.\.venv\Scripts\python.exe scripts\verify_release_sop.py
git diff --check production/V3/3.0.80...HEAD
```

Expected: 全部退出码为 0。

- [ ] **Step 2: 派发独立审阅智能体**

审阅范围包括长条码边界、错误截取、短表号回归、唯一候选是否自动终结、RBAC、事务、占位终端和历史三条关联安全性。发现问题时先补失败测试再修复，并重跑 Step 1。

- [ ] **Step 3: 构建并验证发布包**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-client-release.ps1 -Version 3.0.81
.\.venv\Scripts\python.exe scripts\verify-client-release.py build\server-release\module-manager-v2-server-3.0.81.zip
Get-FileHash -Algorithm SHA256 build\server-release\module-manager-v2-server-3.0.81.zip
```

Expected: 必需文件完整，无 `.env`、数据库、uploads 和缓存；记录本地 SHA256。

- [ ] **Step 4: 推送候选分支**

```powershell
git push -u origin production/V3/3.0.81
```

---

### Task 5: 生产备份、上线与三条补关联

**Files:**
- Modify after deploy: `ops/releases/V3.0.81.md`
- Modify after deploy: production-baseline references in `AGENTS.md` and SOP/team handoff docs.

**Interfaces:**
- Consumes: 已验证发布包、三个未匹配 ID、各自当前 review version 和唯一候选。
- Produces: V3.0.81 线上 release、三条 associated 记录、完整审计和发布证据。

- [ ] **Step 1: 发布前备份并验证完整性**

通过 `scripts/production_backup.sh` 备份当前 release、`.env`、data、uploads 和 PostgreSQL；验证 dump/schema、tar 和关键目录均存在，再继续。

- [ ] **Step 2: 上传包、比对哈希并切换 release**

```powershell
scp -i "C:\Users\Administrator\Downloads\XXXXXX.pem" build\server-release\module-manager-v2-server-3.0.81.zip root@106.14.122.43:/tmp/
ssh -i "C:\Users\Administrator\Downloads\XXXXXX.pem" root@106.14.122.43 "sha256sum /tmp/module-manager-v2-server-3.0.81.zip"
```

服务器解压到新的时间戳 release，复用 `/opt/module-manager-v2/.env` 与持久数据路径，切换 `/opt/module-manager-v2/current` 并重启 `module-manager-v2.service`。

- [ ] **Step 3: 线上健康和候选 dry-run**

验证 `/health`、`/login`、`/project-board`、`/task-hall`、`/construction` 为 200，API 文档为 404，版本为 3.0.81。

对以下记录调用仓储候选逻辑但不提交：

```text
scan-unmatched-422f7a0a030a6d41ebbf788a -> g-12102
scan-unmatched-af685ed60b9d412231b51382 -> g-12164
scan-unmatched-04b5e41fd8391683e1c57419 -> g-12122
```

每条必须为 open、manual_confirmed=true、唯一候选、has_existing_group=true，且目标与上表一致。

- [ ] **Step 4: 逐条调用现有原子终结事务**

使用明确审计身份 `production-maintenance-v3.0.81`，传入 dry-run 得到的当前 `expected_version` 与不透明 `candidate_key` 调用 `PostgresStateRepository.finalize_unmatched_match`。每次成功后重新读取并确认记录为 associated，再处理下一条。

- [ ] **Step 5: 数据验收**

确认：

```text
三条未匹配记录均为 associated
三组资料组照片和临时审阅证据已迁移
三组未创建重复正式资料组
00000000/空值/manual-/unmatched- 正式资料组数量为 0
项目汇总、KPI 和条码准确率可以正常刷新
最近十分钟无 error 级应用日志
```

- [ ] **Step 6: 清理旧 release 并记录证据**

先 dry-run，再执行 `scripts/cleanup_old_releases.sh --keep 5`，确认仅保留最近五个 release。把备份目录、release 目录、包大小、SHA256、健康结果、补关联结果和回滚目标写入 `ops/releases/V3.0.81.md`。

- [ ] **Step 7: 更新已部署基线并提交推送**

将生产基线和团队交接文档从 V3.0.80 更新为 V3.0.81，保持下一个候选在开始新功能前仍为 V3.0.81；重跑 SOP、包验证和 `git diff --check` 后提交并推送。
