# V3.0.80 Final Review Round 6 Fix Report

## Scope And Baseline

- Branch: `production/V3/3.0.80`
- Starting HEAD: `ac0746038fb7f3a3d857d87d8ad24a722ebcd260`
- Production truth remains `V3.0.79`; `V3.0.80` remains a pending candidate.
- No production access, deployment, production-state update, or release-truth advancement was performed.
- Round 6 findings: `.superpowers/sdd/final-review-round-6-findings.md`
- Commit: this report is part of the single Round 6 fix commit. The final object ID is reported by the controller/final response because a Git commit cannot contain its own object ID.

## Root Causes And Fixes

### M1: deployment predicate scope

The parser treated any modal, negative, or future token in a regex-delimited clause as applying to every deployment predicate in that clause. This hid valid assertions in causal/subordinate text, allowed `not get deployed`, and let the bare Chinese character `应` match inside `响应`.

The fix evaluates each deployment predicate with a bounded local prefix/suffix. Negation and modal/future forms must govern the predicate itself; post-conditions must be immediately attached to it. Causal text after an already affirmative predicate no longer vetoes the assertion. `can't` is normalized explicitly, `get` is supported in negation, Chinese modal matching uses lexical forms, and version context across paragraphs remains intact.

### M2: executable entry attestation

The package verifier accepted one arbitrary marker-shaped byte substring. Comments, unused strings, dead code, and stale entries could therefore satisfy the check, and duplicate ZIP members were collapsed into a set before validation.

The Vue build now injects this exact executable top-level assignment at the start of the one Rollup entry chunk:

```javascript
globalThis.__MODULE_MANAGER_VUE_ENTRY_ATTESTATION__={"version":"3.0.80"};
```

The Vite hook runs in post `generateBundle` order so the assignment and digest cover the final Vite dependency-map prefix. Generated `version.json` contains exactly `version`, `entry`, and `entrySha256`. The verifier requires the exact first statement, requires the attested path to equal the sole module entry referenced by `index.html`, verifies SHA-256 over those exact bytes, and rejects raw or normalized duplicate ZIP names before set conversion. Vue application code imports `src/version.json` directly for its runtime dataset value.

### M3: JSON formal meter uniqueness

JSON finalization trusted `target_group_id`; when it was empty, it called `ensure_task_for_terminal` and created a second group without reselecting the real meter identity. PostgreSQL already reselected `(project_id, meter_match_key)`.

JSON state is team/project scoped, so finalization now reselects `meter_match_key` inside the authoritative team state before task, group, summary, audit, replay, or persistence mutation. A compatible terminal reuses the group. An incompatible terminal or conflicting target raises `FinalizationIdentityConflict`. Replay lookup no longer uses a mutating `setdefault` before validation.

### M4: recursive audit redaction

Redaction removed punctuation and case but compared only a fixed exact-name set. Common provider keys such as `presignedUrl`, `rawSignedUrl`, `bucketName`, `storageObjectKey`, and `ossObjectKey` escaped.

Keys are now split across camel, acronym, snake, kebab, and mixed-case boundaries. URL keys qualified by raw/signed/presigned/source/image/photo, bucket-bearing keys, and storage/object/OSS key combinations are recursively redacted. Existing exact spellings remain supported, while business keys such as `candidate_key` remain visible.

### M5: administrator release-notes gate

The gate still required a literal `APP_VERSION = '3.0.80'` after Round 5 moved the value to `versionArtifact.version`. Packaging copied the script but did not execute it.

The Node gate now parses `v2-web/src/version.json`, requires a single semantic `version`, verifies the exact import and derived `APP_VERSION`, and requires exactly one matching `V3.0.80` release-note entry. Both `build-client-release.ps1` and `run-client-acceptance-gate.ps1` execute the real script through fail-fast checks. The SOP verifier enforces both invocations.

## RED Evidence

### M1

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider scripts\test_verify_release_sop.py scripts\test_verify_client_release.py -q -k round6
```

Result: exit 1, `8 failed, 6 passed, 253 deselected`. The three affirmative counterexamples and `did not get deployed` failed in both source and forged-ZIP paths.

Additional predicate-scope self-review RED:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider scripts\test_verify_release_sop.py scripts\test_verify_client_release.py -q -k "modal_tokens_outside_deployment_predicate"
```

Result: exit 1, `2 failed, 6 passed, 270 deselected`. An `if` inside a causal verification clause incorrectly suppressed the earlier deployment predicate.

### M2

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider scripts\test_verify_client_release.py -q -k "non_executable_or_stale or duplicate_entry_bundle or unrelated_chunk"
```

Result: exit 1, `5 failed, 1 passed, 60 deselected`. Marker comments, unused strings, dead code, a stale entry with candidate text, and duplicate entry members were accepted. The unrelated-chunk-only control was already rejected.

### M3

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider v2-api\tests\test_local_simulation.py v2-api\tests\test_api.py -q -k "reselects_compatible_formal_meter_identity or rejects_incompatible_formal_meter_identity or json_http_finalization_identity_conflict"
```

Result: exit 1, `3 failed, 270 deselected`. JSON created a second group for compatible and incompatible identities, and real FastAPI HTTP returned 200 instead of 409.

### M4

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider v2-api\tests\test_local_simulation.py::test_json_audit_events_recursively_redact_photo_storage_secrets v2-api\tests\test_state_repository.py::test_postgres_construction_activity_audit_redacts_nested_photo_secrets_before_persistence v2-api\tests\test_state_repository.py::test_postgres_audit_response_recursively_redacts_provider_style_secret_keys v2-api\tests\test_api.py::test_production_audit_log_is_admin_only_and_recursively_redacted -q
```

Result: exit 1, `4 failed`. All requested provider-style variants remained visible in JSON persistence, PostgreSQL persistence/response, or HTTP response paths.

### M5

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider scripts\test_verify_client_release.py -q -k "admin_release_notes_gate_executes or package_and_acceptance_chains"
```

Result: exit 1, `2 failed, 67 deselected`. The real Node process failed with `APP_VERSION must be 3.0.80`; neither chain contained the execution command.

## GREEN Evidence

- M1 initial focused: `14 passed, 253 deselected`.
- M1 final predicate-scope focused: `8 passed, 270 deselected`.
- M2 focused after final exact-grammar fixtures: `7 passed, 62 deselected`.
- M3 JSON repository and real HTTP: `3 passed, 270 deselected`.
- M4 JSON/PostgreSQL persistence and response: `4 passed`.
- M5 executable gate regression: `2 passed, 67 deselected`; direct Node output was `admin release notes checks passed`.

## Full Verification

### Release and package tests

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider scripts\test_verify_release_sop.py scripts\test_verify_client_release.py -q
```

Result: `278 passed, 1 warning in 1.02s`. The warning is the intentional duplicate-name forged ZIP fixture emitted by Python `zipfile`.

### Full backend with local PostgreSQL 16

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:ROUND3_POSTGRES_TEST_URL='postgresql+psycopg://module_manager:module_manager_password@127.0.0.1:15432/module_manager_v3_local'
$env:ROUND4_POSTGRES_TEST_URL=$env:ROUND3_POSTGRES_TEST_URL
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider v2-api\tests -q
```

Result: `519 passed, 1 warning in 131.79s`; no tests were skipped. The warning is the existing Starlette/httpx deprecation warning.

### Node/Python gates

- `node scripts\verify_admin_release_notes.js`: passed, `admin release notes checks passed`.
- `node scripts\verify_project_board_unmatched_review.js`: passed.
- `.\.venv\Scripts\python.exe scripts\verify_security_hardening.py`: passed.
- `.\.venv\Scripts\python.exe scripts\verify_release_sop.py`: passed.
- `.\.venv\Scripts\python.exe scripts\verify_vue_migration_gate.py --strict-native`: passed; 7 registered pages, 0 legacy bridge pages.

### Vue

```powershell
Push-Location v2-web
npm exec vue-tsc -- --noEmit
npm run build
Pop-Location
```

Result: exit 0; `1890 modules transformed`, build completed in 4.75s in the combined run. Existing Rollup pure-comment and chunk-size warnings remain.

### Formal local package smoke and verifier

```powershell
.\scripts\build-client-release.ps1 -Version 3.0.80
.\.venv\Scripts\python.exe .\scripts\verify-client-release.py .\build\server-release\module-manager-v2-server-3.0.80.zip
```

The first attempt exposed that Vite prepended its dependency map after the original hook; verifier failed closed with `Vue entry bundle must start with the executable build attestation`. After moving the hook to post order, the complete build and demo smoke passed, then the verifier passed: ZIP `1412445 bytes`, `121` required files, no forbidden cache/local files.

Generated `v2-api/app/static/vue` output and the staging directory/ZIP were removed after verification. Tracked static assets were restored from the starting HEAD.

## Changed Files

Release parser/package/gates:

- `scripts/verify_release_sop.py`
- `scripts/verify-client-release.py`
- `scripts/verify_admin_release_notes.js`
- `scripts/build-client-release.ps1`
- `scripts/run-client-acceptance-gate.ps1`
- `scripts/test_verify_release_sop.py`
- `scripts/test_verify_client_release.py`

Backend behavior/tests:

- `v2-api/app/services/local_simulation.py`
- `v2-api/app/services/unmatched_review.py`
- `v2-api/tests/test_local_simulation.py`
- `v2-api/tests/test_state_repository.py`
- `v2-api/tests/test_api.py`

Vue source/build contract:

- `v2-web/src/main.ts`
- `v2-web/src/vite-env.d.ts`
- `v2-web/vite.config.ts`

Review evidence:

- `.superpowers/sdd/final-review-round-6-findings.md`
- `.superpowers/sdd/final-review-round-6-fix-report.md`

## Self-Review

- All five Medium findings have direct RED/GREEN coverage.
- JSON identity validation occurs after version/candidate validation but before task/group/summary/audit/replay/persistence mutation.
- HTTP conflict coverage traverses the real repository selection and `persist_local_test_state` middleware and verifies state/file bytes remain unchanged.
- Audit redaction is applied both before persistence and after retrieval/HTTP response; non-secret match keys stay visible.
- ZIP duplicate detection precedes name-set conversion.
- Actual Vite output, not only synthetic fixtures, was packaged and verified.
- Production markers and pending prose were not changed.
- `v2-api/app/static/vue` and package artifacts are excluded from the commit.

## Residual Risk And Concerns

- The entry attestation and digest detect stale, mismatched, ambiguous, and casually forged package contents, but there is no signing key or external trusted provenance. An active attacker able to rebuild/repackage can replace the entry and recompute the sidecar digest. This work does not claim otherwise.
- Release truth parsing remains rule-based. The English/Chinese adversarial corpus should continue to grow when new prose forms appear.
- Vue build still reports existing large-chunk and Rollup annotation warnings; neither is introduced as a correctness/security failure here.
- Starlette's existing TestClient/httpx deprecation warning remains.
- No production deployment, live health check, backup, or production database write was performed by design.

No Round 6 Medium finding remains open based on the required local evidence.
