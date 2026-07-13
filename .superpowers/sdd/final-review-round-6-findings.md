# V3.0.80 Final Review Round 6 Findings

Review range: `94bdadc..ac0746038fb7f3a3d857d87d8ad24a722ebcd260`

## Critical

No Critical findings.

## High

No High findings.

## Medium

### M1. Release truth parsing still does not isolate modal, negative, and affirmative predicates

**Files:** `scripts/verify_release_sop.py:130`, `scripts/verify_release_sop.py:154`, `scripts/verify_release_sop.py:345`, `scripts/verify_release_sop.py:367`

`clause_has_conditional_language()` marks the entire regex-delimited clause conditional when any modal token appears anywhere. The boundary list does not model causal/subordinate clauses, and the Chinese conditional expression contains the unbounded single character `应`. Negation is likewise matched against the whole string rather than the deployment predicate.

Read-only probes at HEAD produced these results:

- `V3.0.80 was deployed to production because operators can verify it.` -> affirmative claim `False`.
- `V3.0.80 was deployed to production after admins could approve it.` -> affirmative claim `False`.
- `V3.0.80 已部署到生产环境且响应正常。` -> affirmative claim `False` because `应` inside `响应` makes the whole sentence conditional.
- `V3.0.80 did not get deployed to production.` -> affirmative claim `True` because `not get deployed` is outside the negation pattern.

**Impact:** A pending release record can contain a real English or Chinese deployment assertion and still pass truthfulness checks. Conversely, ordinary negative pending prose can be rejected as deployed. The Round 5 source and forged-ZIP tests only cover conjunctions already present in `CLAUSE_BOUNDARY_PATTERN`, so 253 passing release tests do not close this gap.

**Fix:** Tokenize deployment predicates and determine modal/negative/future scope around each predicate rather than suppressing an entire textual fragment. Split causal/subordinate and semicolon-separated independent clauses, use Chinese lexical tokens instead of bare-character substring matching, and recognize `not get deployed`. Add every counterexample above to both `test_verify_release_sop.py` and forged-package tests, with affirmative, negative, conditional, future, and mixed controls.

### M2. The ZIP verifier still accepts an ordinary string or comment as the entry-bundle version attestation

**Files:** `scripts/verify-client-release.py:145`, `scripts/verify-client-release.py:229`, `scripts/verify-client-release.py:270`, `scripts/verify-client-release.py:327`, `scripts/test_verify_client_release.py:108`

`entry_bundle_version()` scans arbitrary entry-bundle bytes for one marker-shaped substring. It does not establish that the marker is executable, reached, or derived from the application version source. The positive test fixture itself satisfies the verifier with an unused `const buildMarker = '...'` string.

A temporary forged ZIP containing all required V3.0.80 metadata and sidecars, but replacing the referenced entry with only:

```js
/* stale V3.0.79 bundle */
/* __MODULE_MANAGER_VUE_ENTRY_VERSION__:3.0.80:__END__ */
```

was accepted in full and printed `FORGED_STALE_BUNDLE_ACCEPTED`. Direct probes also accepted the marker in a comment and in an ordinary unused string.

**Impact:** An old or arbitrary frontend entry bundle can be shipped with fresh V3.0.80 sidecars and a marker comment, bypassing the exact-runtime binding. That can reintroduce retired UI calls or omit candidate security fixes while the package verifier reports success.

**Fix:** Replace byte-substring evidence with a structured executable attestation tied to the actual entry. At minimum, parse a build-generated top-level assignment with a JavaScript parser and execute the extracted package in an isolated browser smoke test to verify the runtime marker. For stronger anti-forgery, bind the entry digest and source version in signed build provenance. Add negative full-ZIP tests for comment, unused string, dead code, stale entry plus candidate marker, duplicate entry names, and unrelated chunks.

### M3. JSON finalization can create a second formal group for an incompatible existing meter identity

**Files:** `v2-api/app/services/unmatched_review.py:121`, `v2-api/app/services/local_simulation.py:1951`, `v2-api/app/services/local_simulation.py:1955`, `v2-api/app/services/state_repository.py:3955`

The JSON candidate builder only selects an existing group when terminal and catalog identity already agree. If a formal group has the same `meter_match_key` under another terminal, `target_group_id` is empty and `_finalize_unmatched_match_in_state()` creates a new group. PostgreSQL instead reselects by `(project_id, meter_match_key)` and returns an identity conflict when the terminal is incompatible.

An isolated JSON probe created `g-00001` for terminal `T-OLD` and meter key `0000912473`, then finalized a server-derived candidate for `T-NEW` with the same key. The candidate had `target_group_id=''`; finalization returned `g-00002`, `attached=False`, leaving both formal groups with the same meter identity.

**Impact:** JSON and PostgreSQL have different formal uniqueness behavior. JSON mode can duplicate formal groups, split photos/tasks/statistics, and make replay/migration behavior backend-dependent.

**Fix:** After authoritative version and candidate validation, JSON finalization must look up the real formal uniqueness identity before any task/group/audit mutation. Reuse a compatible group and raise `FinalizationIdentityConflict` for an incompatible terminal or target, matching PostgreSQL semantics. Add JSON repository and real HTTP tests for compatible reuse and incompatible conflict, asserting groups, tasks, summary, audit, replay ledger, and persisted state remain unchanged on rejection.

### M4. Recursive audit redaction misses common signed-URL, bucket, and object-key variants

**Files:** `v2-api/app/services/unmatched_review.py:45`, `v2-api/app/services/unmatched_review.py:62`, `v2-api/app/services/unmatched_review.py:67`

The redactor canonicalizes key spelling but compares only against a fixed exact-name set. A read-only probe returned these values unchanged: `presignedUrl`, `rawSignedUrl`, `bucketName`, `storageObjectKey`, and `ossObjectKey`; only exact variants such as `signedUrl` and `storageBucket` were redacted. Existing tests exercise the exact allowlisted spellings and therefore pass.

**Impact:** Arbitrary nested audit payloads, including legacy unmatched `updates` and scanner/provider metadata, can persist and later return signed photo URLs, bucket names, or storage/object keys. Admin-only audit access reduces audience but does not satisfy the no-secret persistence/response boundary.

**Fix:** Split snake/kebab/camel/mixed-case keys into semantic tokens and redact URL keys qualified by raw/signed/presigned/source/image/photo, bucket-bearing keys, and storage/object/OSS key combinations. Prefer positive audit DTOs for known actions. Add nested JSON and PostgreSQL persistence-before and response-after tests for the variants above and provider-style equivalents.

### M5. The shipped administrator release-notes gate fails after the single-version-source change and is not enforced by packaging

**Files:** `scripts/verify_admin_release_notes.js:18`, `v2-web/src/constants/releaseNotes.ts:1`, `scripts/build-client-release.ps1:119`, `ops/releases/V3.0.80.md:22`

Round 5 changed `APP_VERSION` from a literal to `versionArtifact.version`, but the required release verifier still demands `APP_VERSION = '3.0.80'`. Running the documented command at HEAD fails immediately with `AssertionError: APP_VERSION must be 3.0.80`. The package builder copies this verifier but does not execute it, so package construction can remain green while a documented shipped gate is red.

**Impact:** The candidate does not have a coherent passing release chain, and previous reports claiming all release gates passed are no longer reproducible at HEAD. A release operator following `ops/releases/V3.0.80.md` is blocked after packaging; an automated packaging path can miss the failure.

**Fix:** Make the gate parse `v2-web/src/version.json`, assert that `releaseNotes.ts` imports that exact source and derives `APP_VERSION` from it, and reconcile the release-note label with the JSON value. Invoke the gate from the fail-fast acceptance/package chain and add a regression that runs the real script after source-version changes.

## Low

No additional Low findings.

## Confirmed Constraints

- Deployed/candidate markers remain `V3.0.79` / pending `V3.0.80`; `ops/releases/V3.0.80.md` has blank package, backup, deployment, and live-check evidence.
- No `94bdadc..HEAD` diff exists under `v2-api/app/static/vue`, and no release archive is committed.
- Frontend source contains no retired rematch/dedupe call; the reverse UI gate passes.
- Dual unmatched save/rescan/confirm/finalize fail fast before either backend mutates; focused HTTP tests pass and release the team lock.
- Focused PostgreSQL 16 tests ran against `127.0.0.1:15432` without skip: same-terminal concurrent finalization and placeholder legacy assignment passed.
- Focused RBAC, safe DTO, photo-ID, transactional-audit, identity-lock, temporary-isolation, and replay tests passed. They do not cover M1-M4 adversaries.

## Verification Performed

- `pytest scripts/test_verify_release_sop.py scripts/test_verify_client_release.py -q`: `253 passed`.
- Focused backend regression selection: `20 passed, 354 deselected`.
- Real localhost PostgreSQL Round 3/4 suites: `3 passed, 1 existing warning`.
- Security hardening, release SOP, unmatched UI, and strict Vue migration gates: passed.
- `node scripts/verify_admin_release_notes.js`: failed at line 18 as described in M5.
- `git diff --check 94bdadc..HEAD`: passed; the worktree was clean before this requested report was written.

## Residual Risks

- By instruction, this review did not run the full 515-test backend suite, Vue production build, real release packaging, production backup, hash comparison, or live checks.
- The PostgreSQL integration rerun covered the dedicated Round 3/4 tests, not every PostgreSQL mutation path.
- The release truth parser remains rule-based; after fixing M1, adversarial mixed English/Chinese grammar should remain a permanent corpus.

## Required Pre-Release Rerun After Fixes

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:ROUND3_POSTGRES_TEST_URL='postgresql+psycopg://module_manager:module_manager_password@127.0.0.1:15432/module_manager_v3_local'
$env:ROUND4_POSTGRES_TEST_URL=$env:ROUND3_POSTGRES_TEST_URL
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider scripts\test_verify_release_sop.py scripts\test_verify_client_release.py -q
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider v2-api\tests -q
node scripts\verify_admin_release_notes.js
node scripts\verify_project_board_unmatched_review.js
.\.venv\Scripts\python.exe scripts\verify_security_hardening.py
.\.venv\Scripts\python.exe scripts\verify_release_sop.py
.\.venv\Scripts\python.exe scripts\verify_vue_migration_gate.py --strict-native
Push-Location v2-web; npm exec vue-tsc -- --noEmit; npm run build; Pop-Location
.\scripts\build-client-release.ps1 -Version 3.0.80
.\.venv\Scripts\python.exe .\scripts\verify-client-release.py .\build\server-release\module-manager-v2-server-3.0.80.zip
git diff --check 94bdadc..HEAD
git status --short
```

After the build/package verification, remove generated local artifacts and prove that no `v2-api/app/static/vue` or archive delta is committed. Production backup, SHA256 comparison, deployment, and live checks must remain controller-gated and may only update release truth after successful execution.

RELEASE VERDICT: BLOCK
