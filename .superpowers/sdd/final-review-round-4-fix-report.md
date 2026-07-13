# V3.0.80 Final Review Round 4 Fix Report

Date: 2026-07-14

## Scope And Boundaries

- Branch: `production/V3/3.0.80`
- Starting HEAD: `bf929472404c44bf0cc1712e609ddb114bf35aa5`
- Implementation commit: `610a21413ec23b0f50359fc4b27da09236ebc775`
- Production remains `V3.0.79` with `STATE_BACKEND=postgres`.
- Candidate remains `V3.0.80` pending.
- No package was created, no deployment was attempted, no production path or production database was accessed, and no baseline marker was advanced.

## Finding 1: PostgreSQL Legacy Assign Validation

### Root Cause

`PostgresStateRepository.assign_unmatched_record()` locked the unmatched row and then used `record.terminal` directly for task lookup. It only checked whether the stripped string was non-empty. Values such as `00000000`, `未关联终端`, `manual-*`, and `unmatched-*` therefore reached task mutation, review payload advancement, transactional audit staging, and commit.

The JSON implementation already used `validate_real_formal_identity_value()`, so the PostgreSQL legacy path had diverged from the shared formal identity contract.

### Fix

- Call the shared terminal validator immediately after the unmatched row is found and before review payload access, task lookup, task mutation, audit staging, or commit.
- Keep valid-terminal task assignment behavior unchanged.
- Add a real PostgreSQL repository test and a real FastAPI `STATE_BACKEND=postgres` HTTP test for all four invalid terminal classes.
- Snapshot every unmatched row, embedded review version, historical task, and audit row before each rejected call and prove the complete database snapshot is unchanged afterward.
- Protect each HTTP request with a 5-second deadlock timeout.

### Test Isolation Correction

The first RED run exposed that `Base.metadata.create_all()` with only `search_path` could see existing `public` tables during `checkfirst` and skip creation in the random schema. The Round 4 fixture was corrected with `schema_translate_map={None: schema}`. The same correction was applied to the required Round 3 concurrency fixture.

Five historical `round3-team-*` rows left in the local test database by the old fixture were deleted by their dedicated test prefix. Final cleanup query result:

```text
leaked_test_teams | leftover_test_schemas
------------------+----------------------
0                 | 0
```

## Finding 2: Release Truth Semantics

### Root Cause

- Contraction normalization converted `can't` to `cannot`, but the negation matcher did not understand `cannot`.
- Deployment matching treated a bare `deployed` token as affirmative without excluding modal and conditional language.
- Clause splitting discarded separator semantics, so a condition in one clause could be detached from its consequent.
- `has/have gone live in production` and Chinese forms such as `已在生产环境上线`, `已完成生产上线`, and `现已在生产环境正式生效` were outside the affirmative vocabulary.

### Fix

- Normalize `can't` and `cannot` to `can not` and extend live negation matching.
- Treat `can/could/may/might/if/unless` and tested Chinese conditional forms as non-affirmative.
- Preserve clause separators and carry conditional scope across comma/conjunctive consequents, resetting it at sentence/paragraph and adversative `but/但` boundaries.
- Preserve full-document version context across lines and blank lines.
- Recognize `has/have gone live in production` and the required Chinese production-live/completion forms.
- Add the same adversarial corpus to the source parser and forged ZIP suites, plus negative, pending, future, and mixed conditional-then-actual-positive controls.

## Finding 3: Exact Package Version Truth

### Root Cause

The package verifier used the first manifest `Version` match and accepted any JavaScript chunk containing the candidate version substring. A runtime `3.0.79` bundle could therefore pass if unrelated prose contained `3.0.80`, and duplicate/conflicting manifest versions were ignored after the first match.

### Fix

- Require exactly one manifest `Version` line and require a strict semantic version without a `V` prefix, prerelease suffix, or timestamp.
- Add `v2-web/public/version.json` as the single machine-readable source artifact. Vite copies it to `v2-api/app/static/vue/version.json` during a production build.
- Require both source and built artifacts in package coverage and parse JSON with duplicate-key rejection, exactly one `version` field, and strict semantic-version validation.
- Reconcile manifest, source artifact, built runtime artifact, exact HTML title, English/Chinese AGENTS candidate markers, and V3.0.80 release record version/status.
- Remove arbitrary JavaScript substring scanning as runtime evidence.
- Make the release builder default to semantic candidate `3.0.80`, reject non-semantic `-Version` values, and fail if either version artifact is absent after Vue build.
- Add source SOP checks and version-update documentation for the new artifact.

## RED Evidence

### PostgreSQL Repository And HTTP

```powershell
$env:ROUND4_POSTGRES_TEST_URL='postgresql+psycopg://module_manager:module_manager_password@127.0.0.1:15432/module_manager_v3_local'
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_round4_postgres_assign_validation.py -q
```

Expected RED after correcting schema isolation:

```text
2 failed, 1 warning in 1.74s
repository: Failed: DID NOT RAISE ValueError
HTTP: assert 200 == 400
```

### Source Release Parser

```powershell
.\.venv\Scripts\python.exe -m pytest scripts\test_verify_release_sop.py -q -k round4
```

Expected RED:

```text
17 failed, 7 passed, 159 deselected in 0.27s
```

All 12 conditional/negated false positives and all 5 missing live/completion positives failed for the intended semantic reason.

### Forged Package Verification

```powershell
.\.venv\Scripts\python.exe -m pytest scripts\test_verify_client_release.py -q -k "manifest_must_have_exactly_one or manifest_version_must_be_semantic or runtime_version_cannot or requires_machine_readable or round4 or conditional_or_negated or negative_pending_and_future_live"
```

Expected RED:

```text
22 failed, 7 passed, 9 deselected in 0.48s
```

The failures included duplicate same-version manifest lines, conflicting manifest lines, non-semantic manifest input, runtime `3.0.79` plus unrelated `3.0.80`, missing runtime artifact, conditional false positives, and live synonym bypasses.

### Builder Version Surface

```powershell
.\.venv\Scripts\python.exe -m pytest scripts\test_verify_client_release.py -q -k release_builder_default_version
```

Expected RED:

```text
1 failed, 42 deselected in 0.09s
```

The old timestamp default did not match the semantic candidate version.

## GREEN And Full Verification

### Focused GREEN

| Command | Exact result |
| --- | --- |
| Round 4 PostgreSQL repository + HTTP suite | `2 passed, 1 warning in 1.69s` |
| Round 4 source parser selection | `30 passed, 159 deselected in 0.11s` |
| Legacy PostgreSQL audit/conflict/rollback selection | `18 passed, 86 deselected in 0.52s` |
| Round 3 real PostgreSQL concurrency | `1 passed in 1.74s` |

Both PostgreSQL test modules ran against localhost PostgreSQL 16 and did not skip.

### Complete Suites

| Command | Exact result |
| --- | --- |
| `pytest v2-api/tests -q` with both Round 3/4 PostgreSQL URLs | `515 passed, 1 warning in 132.63s` |
| `pytest scripts/test_verify_release_sop.py -q` | `191 passed in 0.43s` |
| `pytest scripts/test_verify_client_release.py -q` | `43 passed in 0.44s` |

The backend warning is the existing FastAPI `TestClient` Starlette/httpx deprecation warning.

### Build And Gates

| Command | Result |
| --- | --- |
| `npm run build` in `v2-web` | PASS, 1889 modules transformed, built in 4.90s |
| built `v2-api/app/static/vue/version.json` inspection | exact `{"version":"3.0.80"}` |
| `python scripts/verify_security_hardening.py` | `[OK] security hardening static checks passed` |
| `python scripts/verify_release_sop.py` | `[OK] release SOP files and references are consistent` |
| `node scripts/verify_project_board_unmatched_review.js` | `project board unmatched review checks passed` |
| `python scripts/verify_vue_migration_gate.py --strict-native` | PASS, 7 registered pages, 0 legacy bridge pages |
| `git diff --check 94bdadc..HEAD` | exit 0, no output |

Vite emitted only the existing Rollup pure-annotation and large-chunk warnings. After verification, all generated/untracked files under `v2-api/app/static/vue` were removed and tracked static assets were restored; no generated static asset is committed.

## Changed Files

- `.superpowers/sdd/final-review-round-4-findings.md`
- `.superpowers/sdd/final-review-round-4-fix-report.md`
- `docs/sop/02-production-branch-versioning.md`
- `docs/sop/05-release-package-and-hash.md`
- `scripts/build-client-release.ps1`
- `scripts/test_verify_client_release.py`
- `scripts/test_verify_release_sop.py`
- `scripts/verify-client-release.py`
- `scripts/verify_release_sop.py`
- `v2-api/app/services/state_repository.py`
- `v2-api/tests/test_round3_postgres_concurrency.py`
- `v2-api/tests/test_round4_postgres_assign_validation.py`
- `v2-api/tests/test_state_repository.py`
- `v2-web/public/version.json`

## Self-Review

- Transaction safety: invalid terminals are rejected after the locked record lookup but before version/payload access, task lookup, task mutation, audit staging, and commit. Context-manager exit rolls back the read transaction.
- Security: no role or endpoint permissions were widened. The real production-mode HTTP test authenticates an administrator and still receives a controlled 400 before mutation.
- Release truth: conditional scope is conservative inside a clause/consequent but explicitly resets at adversative and sentence/paragraph boundaries, so later actual deployment claims remain detectable.
- Package truth: no ordinary source, prose, comment, or JavaScript version substring can satisfy runtime identity. Duplicate JSON keys and extra artifact fields are rejected.
- Version truth: deployed production remains V3.0.79 in both AGENTS markers, V3.0.80 remains the candidate, and the release record remains pending.
- Repository hygiene: findings are preserved, generated static assets are absent, local PostgreSQL test rows/schemas are zero, and unrelated commits/changes were not reverted.

## Residual Risk

- The release parser is intentionally rule-based. The English/Chinese adversarial corpus now covers the reviewed contractions, modals, conditions, clause carry, live synonyms, negation, pending, and future forms, but a novel idiom may still require a new test case.
- The runtime artifact exists in source and was proven copied by a real Vue build. Because this review explicitly forbids committing generated `static/vue` output, a future release package must run the Vue build before package verification; the build script now fails closed if the copied artifact is absent.
- No unresolved Medium finding remains. The only observed warnings are existing test/build warnings described above.
