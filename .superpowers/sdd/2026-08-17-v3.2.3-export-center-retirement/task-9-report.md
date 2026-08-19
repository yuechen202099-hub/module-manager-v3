# Task 9 Report — V3.2.3 release contract and operator SOP

Date: 2026-08-19 (Asia/Shanghai)

## Scope and baseline

- Worktree: `C:\Users\Administrator\.config\superpowers\worktrees\module-manager-v3\production-v3.0.24`
- Branch: `production/V3/3.2.3`
- Required BASE / parent before Task 9: `282f548e9457fadfa6c4190da14ce8a26af69951`
- Deployed production baseline remains `V3.2.2`; candidate is `V3.2.3`; rollback target is `V3.2.2`.
- Alembic head remains `20260724_0014` / `0014_export_center_jobs.py`; no migration or requirements file was changed.
- The Task 8 files `scripts/oss_local_export.py` and `scripts/test_oss_local_export.py` were consumed as package inputs but not modified.
- No push, package publication, deployment, production access, real PostgreSQL access, or real OSS access was performed.

## TDD and debugging evidence

### Initial V3.2.3 verifier RED

Before `scripts/verify_v3_2_3_release.py` existed:

```text
1 failed, 42 errors
root cause: V3.2.3 release verifier is missing
```

After the single `collect_failures(root)` verifier was implemented, the focused file reached:

```text
43 passed in 27.81s
[OK] V3.2.3 release contract
```

### Inherited broad RED and root-cause classification

The inherited pre-GREEN Task 9 run reported 232 failures. They were transitional contract failures rather than one production defect: current version surfaces still said 3.2.2; V3.2.2 deployed history was being fed to pending-candidate helpers; package fixtures and lifecycle prose were still bound to earlier candidate identities; generated Vue assets had not yet been rebuilt; and the old exact KPI SHA lock contradicted the intentional export-retirement source changes.

A fresh focused reproduction during this implementation showed the actionable package subset as:

```text
285 passed, 37 failed, 1 warning
```

The 37 failures grouped into stale KPI byte locks, V3.2.2 deployed-record-as-candidate fixtures, old current-version literals, and tests that failed at an earlier version/lifecycle gate than their intended assertion. Historical `ops/releases/V3.2.2.md` was not changed. Candidate behavior now uses V3.2.3 fixtures, while historical parser tests use a synthetic V3.2.2 pending fixture.

The SOP test file initially reported:

```text
274 passed, 9 failed
```

Eight failures were stale 3.2.1/3.2.2 baseline/candidate/version assertions. The remaining failure exposed a real verifier defect: nested Task 9 inputs were rejected unless each path appeared literally in the build script, even though the build intentionally copies `v2-api/app`, `v2-api/alembic`, and `v2-api/scripts` as whole directories.

### Directory-copy regression RED/GREEN

A focused regression was added before extracting the directory-copy helper.

RED:

```text
AttributeError: module verify_release_sop has no attribute release_input_is_copied_by_build_script
1 failed
```

GREEN after the minimal helper and main-loop integration:

```text
2 passed
```

The regression proves nested app, Alembic, and server-script inputs are covered by their parent directory copies, while an unrelated `v2-web` path is not.

## Implementation summary

- Added `scripts/verify_v3_2_3_release.py` and its mutation-oriented tests for version, retirement ordering/copy/path classes, deleted UI, worker kinds, producer tombstones, migration safety, signer/manifest streaming, local-export bounds, Alembic head, package inputs, lifecycle, SOP, and health probes.
- Advanced application, package, display, documentation, branch, and generated Vue version surfaces to 3.2.3 / V3.2.3.
- Preserved V3.2.2 as deployed baseline and as immutable historical release evidence.
- Added `docs/sop/09-export-retirement-and-oss-local-export.md` with four copyable workflows and all specified memory, disk, worker, size, error, allowlist, retry, concurrency, redaction, default-output, rollback, and incomplete-export stop rules.
- Updated package membership to include Task 1–9 scripts/services/tests/SOP/release record and reject credentials, dumps, runtime data, delivery caches, migration reports, allowlists, and local exports.
- Updated the production health check so retained pages stay in the 200 set and every retired export path, including terminal-readiness descendants, must return 410.
- Rebuilt tracked Vue assets; `version.json`, the HTML title, and the executable entry attestation all identify 3.2.3.
- Replaced the stale opt-in PostgreSQL durable-delivery-job assertion with the approved retirement-before-database-access contract; the historical `DeliveryPackageJob` table remains present and must remain empty.

## Fresh local verification

### Required Task 9 suite

```text
645 passed, 1 warning in 32.17s
```

The warning is intentional: the test constructs a duplicate ZIP member to prove the verifier rejects duplicate archive paths.

Both CLIs exited 0:

```text
[OK] V3.2.3 release contract
[OK] release SOP files and references are consistent
```

### Complete repository script suite

```text
746 passed, 1 warning in 33.87s
```

The warning is the same intentional duplicate-member fixture.

### Frontend

```text
npm run type-check -> exit 0
npm run build -> exit 0; 1670 modules transformed; built in 4.18s
```

Vite/Rollup emitted two dependency annotation notices for `@vueuse/core` and the existing over-500-kB chunk-size advisory. These are warnings, not build failures.

Generated evidence:

- title: `Module Manager V3.2.3`
- runtime version: `3.2.3`
- entry: `assets/index-CHHY9zoG.js`
- entry SHA256: `acf06168f380c0870f54e6f18f7bda8db7e0a4a494be7d8fc0993c0cb1f9f056`
- executable entry attestation starts with version `3.2.3`.

### Backend and PostgreSQL boundary

```text
v2-api/tests/test_task6_review_fixes.py -> 36 passed, 8 skipped
retirement routes plus retired worker kinds -> 47 passed, 1 pre-existing Starlette/httpx warning
```

The eight skips include the isolated real-PostgreSQL fixture because neither `TASK6_POSTGRES_TEST_URL` nor `ROUND3_POSTGRES_TEST_URL` was configured. No remote or production database was substituted.

A diagnostic selector that also included two unowned legacy version tests produced `47 passed, 1 skipped, 2 failed`. Both failures are exact stale `3.2.2` expectations in `v2-api/tests/test_v3_1_release.py` and `v2-api/tests/test_api.py`; those files are outside Task 9 authorization and were not modified. The current 3.2.3 runtime/version behavior is independently covered by the required 645-test suite, both CLIs, and the generated-asset attestation.

### Static and repository gates

- `py_compile` exited 0 for all modified tracked Python files.
- `git diff --check` exited 0; Git printed only Windows LF-to-CRLF advisories.
- Package required/forbidden-member classifiers are exercised in the 645-test required suite.
- Task 8 scripts, Alembic files, and requirements files have an empty diff.

## Candidate lifecycle truth

- Local Verification: passed
- Package: pending
- Production Deployment: pending
- Production Reconciliation: pending

No package hash, backup path, release directory, public health claim, or production reconciliation value was invented.

## Authorized-path audit

Tracked Task 9 changes are limited to the plan-authorized version/release/SOP/package/health files, generated `v2-api/app/static/vue/` assets, the controller-authorized `v2-api/tests/test_task6_review_fixes.py`, and this report. The explicit-path commit must include every one of those paths and must not include Task 8 source, requirements, Alembic, data, build output, migration reports, allowlists, or local exports.

## Residual risk and deferred verification

- The isolated PostgreSQL retirement test was not executed against a real local PostgreSQL instance in this task because no approved local URL was available; it remains an explicit Task 10 verification input.
- Two unowned legacy version tests still assert 3.2.2 and should be resolved by the controller before any full-backend zero-failure claim. They do not justify reverting current version surfaces.
- Production Nginx/application probes, package generation/hash, deployment, migration execution, real OSS download, and reconciliation belong to Tasks 10–11 and remain pending.
- Build size warnings remain unchanged in severity; no performance or code-splitting redesign was authorized in Task 9.
