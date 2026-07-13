# V3.0.80 Final Review Round 7 Findings

Review range: `94bdadc..938574c30315a7b01af8e24ee0743dd32699c88e`
Branch: `production/V3/3.0.80`
Review mode: independent, read-only production release review; no package or deployment was performed.

## Critical

No Critical findings.

## High

No High findings.

## Medium

### M1. Deployment truth parsing still accepts common affirmative claims and misclassifies modal/negative/future predicates

**Files:** `scripts/verify_release_sop.py:108`, `scripts/verify_release_sop.py:119`, `scripts/verify_release_sop.py:159`, `scripts/verify_release_sop.py:394`, `scripts/test_verify_release_sop.py:484`, `scripts/test_verify_client_release.py:506`

The Round 6 change moved suppression closer to each matched predicate, but the claim vocabulary and auxiliary grammar remain narrow. English `live` requires the literal word `production`; Chinese affirmative patterns require a few exact word orders. The modal and negation prefix expressions also do not support ordinary adverb/perfect-auxiliary chains.

Read-only probes at HEAD produced:

- `V3.0.80 has gone live.` -> affirmative claim `False`.
- `V3.0.80 已经部署到生产环境。` -> affirmative claim `False`.
- Both statements were added to otherwise valid pending fixture ZIPs; `verify_package()` accepted both archives and printed its full `[OK]` result.
- `V3.0.80 could have been deployed to production.` -> affirmative claim `True`.
- `V3.0.80 will have been deployed to production by Friday.` -> affirmative claim `True`.
- `V3.0.80 was not even deployed to production.` -> affirmative claim `True`.
- `V3.0.80 may eventually be deployed to production.` -> affirmative claim `True`.

The positive bypasses allow a candidate release record to remain `Status: pending` while stating in common English or Chinese that the candidate is live/deployed. The false positives make legitimate conditional, future, or negative pending prose fail. Existing Round 6 tests cover only the exact simple auxiliary forms added in that round and therefore do not establish predicate-level semantics.

**Impact:** Release truth can still be forged without supplying backup/hash/live evidence, while valid pending records can be rejected. The source SOP gate and packaged ZIP gate share this parser, so both boundaries are affected.

**Fix:** Parse a bounded deployment predicate with its complete auxiliary/adverb/negation chain and explicit subject/version context. Recognize common factual `live`, `went live`, `has gone live`, `已经/已成功/已于...部署`, and equivalent completion forms. Treat perfect modals, future perfect, adverbial negation, and post-conditions as non-affirmative only when they govern that predicate. Add every probe above to both source-parser and full forged-ZIP tests, including mixed English/Chinese clauses.

### M2. Runtime attestation hashes only the entry chunk; referenced stale chunks and extra executable scripts pass the ZIP verifier

**Files:** `v2-web/vite.config.ts:20`, `v2-web/vite.config.ts:29`, `scripts/verify-client-release.py:190`, `scripts/verify-client-release.py:212`, `scripts/verify-client-release.py:300`, `scripts/verify-client-release.py:369`, `scripts/test_verify_client_release.py:264`, `scripts/test_verify_client_release.py:311`

The emitted runtime artifact contains one SHA-256 value for the Rollup entry chunk. It does not bind the JavaScript/CSS chunks imported by that entry. `VueModuleEntryParser` counts only external `type="module"` scripts with a `src`, so it ignores classic scripts and inline executable scripts in `index.html`.

Two temporary full-ZIP probes were accepted:

1. The attested and correctly hashed entry contained `import "./stale.js";`; the referenced `stale.js` contained arbitrary V3.0.79-era code. The verifier printed `IMPORTED_STALE_CHUNK_ACCEPTED`.
2. `index.html` contained the valid attested module entry plus `<script src="/vue/assets/stale-classic.js"></script>`; the extra executable file contained arbitrary stale code. The verifier printed `EXTRA_CLASSIC_SCRIPT_ACCEPTED`.

This does not rely on defeating a signature or recomputing the attested entry: the stale dependent chunk can be swapped while the entry hash and all version sidecars remain unchanged. The current negative test only puts a marker in an unreferenced chunk; the stale-entry test places text before the required prefix. Neither test exercises a referenced dependent chunk or a second executable script.

**Impact:** A partially stale Vue bundle can pass release verification and ship retired API calls or omit candidate security fixes, even though the entry marker, version, and digest all appear valid.

**Fix:** Emit and verify a deterministic manifest of every executable/static Vue asset (path, size, SHA-256), excluding only the manifest itself, and require the archive's Vue asset set to match it exactly. Parse `index.html` so exactly the expected module entry is executable and reject extra classic, module, or inline scripts. Add full-ZIP negatives for substituted imported/dynamic chunks, added executable scripts, missing chunks, extra unreferenced JS, and duplicate/case-colliding assets. No external signing root is required for this accidental/stale-package boundary.

### M3. ZIP member paths are not validated and traversal entries are accepted

**Files:** `scripts/verify-client-release.py:186`, `scripts/verify-client-release.py:276`, `scripts/verify-client-release.py:288`, `scripts/verify-client-release.py:328`, `scripts/test_verify_client_release.py:67`

`normalize_zip_name()` strips leading slashes, and the archive checks reject backslashes and duplicate normalized names, but no check rejects absolute names, `..`, dot segments, drive/colon forms, control characters, or symlink-like entries. The forbidden-part check does not include `..`.

A valid fixture ZIP with one additional member named `../../outside-release.txt` passed verification and printed `TRAVERSAL_MEMBER_ACCEPTED`.

**Impact:** The release gate can approve an archive that may write outside the intended release directory or behave differently across extraction tools. This is unsafe for a production deployment artifact even if the normal local builder currently emits canonical paths.

**Fix:** Before any set conversion or file reads, validate every raw member as a canonical relative POSIX path: reject absolute/drive paths, empty or dot segments, `..`, backslashes, NUL/control characters, normalized spelling changes, symlinks, and case-insensitive collisions where Windows tooling is supported. Add forged-ZIP tests for each class and prove no extraction is attempted.

### M4. Recursive audit redaction still misses common provider URI/link/path/name fields

**Files:** `v2-api/app/services/unmatched_review.py:65`, `v2-api/app/services/unmatched_review.py:69`, `v2-api/app/services/unmatched_review.py:76`, `v2-api/app/services/local_simulation.py:3033`, `v2-api/app/services/state_repository.py:381`, `v2-api/app/api/routes/local_test.py:521`

The Round 6 tokenization correctly closes the reported `presignedUrl`, `rawSignedUrl`, `bucketName`, `storageObjectKey`, and `ossObjectKey` cases. However, URL redaction still requires a `url/urls` token and key redaction requires a literal `key` plus `storage/object/oss`. Provider APIs commonly use semantically equivalent URI, link, path, or object-name fields.

A direct probe of the exact persistence/response redactor returned all of these secrets unchanged:

- `presignedUri`, `rawSignedURI`, `signed-link`
- `s3Key`
- `cos_object_name`
- `ossPath`, `objectPath`

The same helper output is written by JSON audit persistence, staged by PostgreSQL transactional audit, and used again at the HTTP response boundary. Existing tests repeat the Round 6 fixed field list but do not cover these provider variants.

**Impact:** Nested legacy/provider audit payloads can persist and later return signed photo locations or storage object identifiers. Admin-only audit access limits exposure but does not satisfy the no-secret persistence/response invariant.

**Fix:** Extend semantic classification to URI/link/href forms and provider storage/object path/name/key forms (`s3`, `cos`, `oss`, blob/minio equivalents), while retaining business identities such as `candidate_key` and `project_id`. Prefer positive per-action audit DTOs where schemas are known. Add JSON and PostgreSQL tests before persistence and after repository/HTTP response for every variant above and verify non-secret identities remain intact.

### M5. The documented acceptance gate cannot complete with its default version

**Files:** `scripts/run-client-acceptance-gate.ps1:2`, `scripts/run-client-acceptance-gate.ps1:73`, `scripts/build-client-release.ps1:8`, `README.md:102`, `RELEASE_MANIFEST.md:30`, `docs/CLIENT_SIGNOFF_CHECKLIST.md:40`, `scripts/test_verify_client_release.py:177`, `scripts/verify_release_sop.py:533`

`run-client-acceptance-gate.ps1` defaults `$Version` to `final-delivery-ready` and forwards it to `build-client-release.ps1`. The builder now fail-fast rejects every non-semantic version before building. The README and generated/root release manifest instruct operators to run the acceptance gate without a version; the signoff checklist explicitly passes `final-delivery-ready`.

The Round 6 regression only asserts that the administrator gate command text appears in both scripts. `verify_release_sop.py` performs the same textual-presence check. Neither test checks that the acceptance script's parameter contract is compatible with the builder it invokes.

**Impact:** The documented end-to-end acceptance command deterministically fails before producing/verifying the V3.0.80 package. This leaves the release chain non-reproducible even though `node scripts\verify_admin_release_notes.js` itself now passes.

**Fix:** Make the acceptance default derive from the same machine-readable `3.0.80` source (or require an explicit semantic version), update all copied instructions, and compare the requested package version to the source artifact before any build work. Add a fast contract test that exercises or parses the actual parameter flow, not only command-string presence.

## Low

No additional Low findings.

## Round 6 Finding Status

1. **Truth parser:** not closed; M1 gives new full-ZIP affirmative bypasses and modal/negative/future failures.
2. **Executable entry attestation:** partially closed; comment/unused-prefix attacks are rejected, but M2 shows stale referenced chunks and extra executable scripts still pass.
3. **JSON formal meter uniqueness:** closed for the reviewed path. Identity re-selection occurs before task/group/audit/replay mutation; compatible reuse and incompatible 409 focused tests passed, including unchanged persisted bytes and released team lock.
4. **Audit redaction:** partially closed; the five reported Round 6 spellings are fixed, but M4 shows equivalent provider field names still leak through both boundaries.
5. **Administrator release-notes gate:** the direct Node gate and both invocation sites are fixed. The broader acceptance chain remains broken by M5's incompatible version contract.

## Confirmed Constraints

- HEAD and branch matched the requested `938574c30315a7b01af8e24ee0743dd32699c88e` and `production/V3/3.0.80`; the worktree was clean before writing this report.
- `AGENTS.md` still declares deployed `V3.0.79` and candidate `V3.0.80` in English and Chinese. `ops/releases/V3.0.80.md` remains `pending` with package, backup, deployment, hash, and live evidence blank.
- No `94bdadc..HEAD` changes exist under `v2-api/app/static/vue`; no committed ZIP/build/cache artifact was found.
- Focused temporary-review isolation, RBAC/actor binding, safe finalization DTO, stable photo ID, retired legacy production write, and dual HTTP fail-fast tests passed.
- The JSON compatible/incompatible meter-identity tests passed. No task, group, summary, audit, replay, file byte, or lock mutation remained after the incompatible HTTP 409 case.
- The five Round 6 audit spellings passed JSON persistence, PostgreSQL staging/response, and admin-only HTTP response tests.
- `node scripts\verify_admin_release_notes.js`, unmatched UI reverse gate, security hardening gate, release SOP gate, and `git diff --check 94bdadc..HEAD` passed. Their green result does not cover M1-M5.

## Verification Performed

- Round 6 release/package focused selection: `24 passed, 254 deselected, 1 intentional duplicate-ZIP warning`.
- JSON identity focused selection: `3 passed, 270 deselected, 1 existing Starlette warning`.
- Audit persistence/response focused selection: `4 passed, 1 existing Starlette warning`.
- Temporary isolation/RBAC/dual/safe-response focused selection: `11 passed, 270 deselected, 1 existing Starlette warning`.
- Independent temporary ZIP probes confirmed affirmative truth bypass, stale imported chunk acceptance, extra classic script acceptance, and traversal-member acceptance.

## Residual Risks

- By instruction, this round did not run the full backend suite, Vue typecheck/build, package build, real package smoke, or localhost PostgreSQL concurrency suites.
- Round 6 did not change the PostgreSQL advisory-lock implementation; source inspection found no regression, but its real PostgreSQL concurrency proof was not rerun in this round.
- There is still no signing key/external trust root. This report does not treat an actor who can deliberately rebuild and recompute every artifact as an unmet requirement; M2 instead reproduces stale dependent-code substitution without changing the attested entry or digest.
- No production backup, hash comparison, deployment, production access, or live check was performed.

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
.\scripts\run-client-acceptance-gate.ps1 -Version 3.0.80
.\scripts\build-client-release.ps1 -Version 3.0.80
.\.venv\Scripts\python.exe .\scripts\verify-client-release.py .\build\server-release\module-manager-v2-server-3.0.80.zip
git diff --check 94bdadc..HEAD
git status --short
```

After build/package verification, remove generated local static/staging/archive artifacts and prove that no `v2-api/app/static/vue` or archive delta is committed. Production evidence must remain blank until controller-approved backup, hash comparison, deployment, and live verification actually complete.

RELEASE VERDICT: BLOCK
