# V3.0.80 Final Review Round 8 Findings

Review range: `94bdadc..10406b177f655ac40e4790dd9cffcf288c407a06`

## Medium

### M1. 发布真值解析仍会漏掉常见的已上线表述

**Files:** `scripts/verify_release_sop.py:108`, `scripts/verify_release_sop.py:397`, `scripts/verify-client-release.py:464`, `scripts/test_verify_release_sop.py:325`

`DEPLOYMENT_CLAIM_PATTERN` 在 `is` 与 `live` 之间只接受 `already/now/successfully/fully`，不接受常见的 `currently`。对当前 pending 发布记录追加普通陈述 `V3.0.80 is currently live in production.` 时，`has_deployment_claim()` 和 `release_record_has_affirmative_version_deployment_prose()` 都返回 `False`，因此空白 SHA256、备份目录、release 目录和公网健康证据仍会通过源码门禁；验包器复用同一解析器，也受同一绕过影响。现有测试覆盖 `is now live`，没有覆盖 `is currently live`。

**Impact:** 候选记录可以同时保持 `pending`、缺失全部上线证据并明文声称当前已在生产运行，发布门禁无法保证记录真实性。

**Fix:** 将 `currently/presently` 等当前状态副词纳入受限 live 谓词，或改为解析完整系词、副词与 `live in production` 结构；在源码解析和完整 ZIP 验证测试中加入该常见表述。

### M2. 人工确认与重新扫码没有绑定弹窗中的当前修改

**Files:** `v2-web/src/components/UnmatchedReviewDialog.vue:192`, `v2-web/src/components/UnmatchedReviewDialog.vue:224`, `v2-web/src/components/UnmatchedReviewDialog.vue:255`, `v2-api/app/services/local_simulation.py:2172`, `v2-api/app/services/unmatched_review.py:349`, `v2-api/app/services/unmatched_review.py:235`, `docs/superpowers/specs/2026-07-13-unmatched-temporary-review-design.md:60`

弹窗允许先修改表号、采集器、模块号和分类，但 `rescanPhoto()` 只发送已持久化版本与当前分类，服务端据旧 `review` 构造条码上下文；`confirmReview()` 也只发送版本，不先保存草稿。更严重的是，后续 `apply_review_patch()` 深拷贝旧审阅并保留 `manual_confirmed/reviewed_at`，所以“确认旧值 -> 修改并保存新值”的正常流程仍保持 `manual_confirmed=true`。只读探针确认修改表号后结果为 `{'manual_confirmed': True, 'version': 2}`，最终迁移还会把该过期确认写入正式照片的 `temporary_review_manual_confirmed`。

**Impact:** 重新扫码可能按旧表号判断，审计与正式资料组又会声称审阅员确认过其实际未确认的新录入值，违反“人工确认当前照片和录入值”的设计契约。

**Fix:** 重新扫码和人工确认前原子保存当前草稿，或让接口同时接收并校验当前元数据；任何元数据、分类或识别结果变化都应清除人工确认及确认时间。补充确认后再编辑、未保存编辑后扫码/确认的后端和组件交互测试。

### M3. 发布包仍携带会确定失败的旧版最终审计指令

**Files:** `docs/CLIENT_FINAL_AUDIT.md:19`, `docs/CLIENT_FINAL_AUDIT.md:25`, `docs/CLIENT_FINAL_AUDIT.md:30`, `docs/CLIENT_FINAL_AUDIT.md:60`, `scripts/build-client-release.ps1:103`, `scripts/run-client-acceptance-gate.ps1:29`, `scripts/test_verify_client_release.py:211`

构建脚本会把 `CLIENT_FINAL_AUDIT.md` 放入 V3.0.80 包，但该文档仍声明旧的直接关联/空白组流程，并要求运行 `-Version final-delivery-ready`、验证 `build/client-release/module-manager-v2-client-demo-final-delivery-ready.zip`。当前验收脚本会在第 29 行因版本不等于机器源 `3.0.80` 立即失败。Round 7 的回归测试只扫描 README、根 manifest 和 signoff checklist，验包器也只要求该审计文件存在，因而 302 个发布测试全部通过仍未发现这份冲突文档；signoff/acceptance 文档中的 `91 passed` 证据也与本轮实际套件不一致。

**Impact:** 已验签的生产包向操作人员提供不可执行的命令、错误包路径和已退休业务流程，破坏发布可复现性与交付审计可信度。

**Fix:** 将最终审计和验收证据更新为 V3.0.80 server-release 流程，或明确移出生产包并标记为历史文档；让包测试扫描所有随包操作文档中的旧版本参数、旧路径和退休端点。

## Verification

- `517 passed, 3 skipped` for `v2-api/tests`; `302 passed` for release verifier tests; focused unmatched tests `27 passed`.
- Vue typecheck, temporary-output Vite build, unmatched UI verifier, release SOP verifier, admin release-note gate, security gate, and strict Vue migration gate passed.
- `git diff --check` passed; the commit range contains no ZIP, cache, build, log, or bytecode artifacts; the worktree was clean before this report was written.
- Green gates do not cover M1-M3 for the reasons above.

RELEASE VERDICT: BLOCK
