# V3.0.80 Final Review Round 2 Fix Report

Date: 2026-07-14
Branch: `production/V3/3.0.80`
Starting HEAD: `7cb82bb1e8a67da077275df87d662d478758a7d4`
Implementation commit: `f812484ad3db5f2b09d0857581079013a4dce52a`
Production baseline: `V3.0.79`
Release candidate: `V3.0.80` pending

## Outcome

All six round-2 findings are closed. No package was built, no deployment or production access
occurred, and the deployed baseline was not advanced.

The dual unmatched-review write finding uses the review-approved conservative design: save,
rescan, confirm, and finalize return a controlled HTTP 503 before JSON or PostgreSQL mutation.
This is intentionally not described as atomic dual write support. Production currently uses
`STATE_BACKEND=postgres`, so its normal unmatched-review writes remain enabled.

## Root Causes And Fixes

### 1. Dual HTTP deadlock

Root cause: `persist_local_test_state` created and activated a non-reentrant same-team JSON
transaction, then `DualWriteStateRepository._strict_unmatched_review_write()` acquired the same
lock again.

Fix: added `active_authoritative_json_write()` and made the repository reuse an active same-team
transaction. A repository-created transaction is aborted only by the repository; a middleware-
created transaction is left for the middleware to abort after the controlled 503 response.
Real FastAPI tests cover all four routes with a five-second daemon-thread timeout guard.

### 2. PostgreSQL commit before JSON persistence

Root cause: the PostgreSQL repository methods commit internally, while JSON is persisted later by
the middleware. The codebase has no durable cross-resource coordinator, so either commit order can
leave one backend ahead if the second commit fails.

Fix: selected fail-fast rather than claiming unprovable atomicity. The four dual strict operations
raise `StateBackendNotReady` before invoking JSON business mutation, constructing a PostgreSQL
repository, or calling JSON persistence. Routes translate this to HTTP 503. Each HTTP test installs
a PostgreSQL mutation spy and a JSON persistence function that raises; both remain uncalled and the
live JSON state, PostgreSQL spy, audit state, and team lock table remain unchanged.

The limitation and required use of `STATE_BACKEND=postgres` for these writes are documented in
`docs/database/postgresql-schema.md`.

### 3. Release truthfulness prose bypasses

Root cause: any negation on a line suppressed every deployment claim on that line, and prose
required the version and affirmative claim on the same line.

Fix: split prose into paragraphs and deployment clauses, including English/Chinese punctuation,
commas, semicolons, and contrast conjunctions. Version context is paragraph-wide while negation
and future tense are evaluated per clause. The three binding examples plus a comma-separated
variant are rejected when status remains pending.

### 4. Placeholder formal identity mutations

Root cause: the shared validator covered selected creation paths but not terminal updates,
metadata updates, or explicit match keys. The local metadata route also omitted `meter_no` and
`meter_match_key` from its administrator-only field set.

Fix: introduced shared single-value and metadata-update validators for terminal, meter number, and
meter match key. JSON and PostgreSQL create/update/finalize paths validate before mutation; direct
PostgreSQL metadata and terminal updates reject before opening a session. Production metadata
changes to meter number or match key are administrator-only. Tests cover each identity field
against `00000000`, `未关联终端`, `manual-*`, and `unmatched-*`, and assert rejected JSON,
PostgreSQL, API, and audit state is unchanged.

Temporary unmatched source keys are never persisted to a formal group. If a legacy unmatched
record has a synthetic key but the caller provides a real meter number without explicitly
submitting a key, the formal key is derived from that real meter number. An explicitly submitted
synthetic key is rejected.

### 5. Camel/mixed-case audit redaction

Root cause: key normalization lowercased and replaced hyphens, but did not canonicalize camelCase.

Fix: audit keys are canonicalized by case-folding and removing separators before matching the
canonical secret-key set. Nested JSON audit persistence, PostgreSQL audit staging, and production
API response tests cover `signedUrl`, `rawUrl`, `storageKey`, `objectKey`, `ossKey`, and
`storageBucket` alongside snake_case fields.

### 6. Retired rematch frontend API

Root cause: the old `rematchUnmatchedRecord()` service survived after the production route and UI
workflow were retired.

Fix: removed the service and its inline payload contract. The unmatched-review verifier now rejects
both the exported symbol and the retired route string.

## RED Evidence

All RED runs were executed before implementation changes.

1. Dual HTTP deadlock and divergence/failure-injection contract:

   `cd v2-api; ..\.venv\Scripts\python.exe -m pytest tests/test_api.py -q -k "dual_http_unmatched_writes_fail_fast"`

   Result: `4 failed, 120 deselected, 1 warning in 22.57s`. Save, rescan, confirm, and finalize each
   exceeded the five-second deadlock guard.

2. Release prose:

   `.\.venv\Scripts\python.exe -m pytest scripts/test_verify_release_sop.py -q -k "clause_scoped_and_cross_line"`

   Result: `3 failed, 142 deselected in 0.08s`; all binding examples returned without raising.

3. Formal identity:

   `cd v2-api; ..\.venv\Scripts\python.exe -m pytest tests/test_local_simulation.py tests/test_state_repository.py tests/test_api.py -q -k "camel or formal_identity_updates or placeholder_match_key"`

   Result: `18 failed, 336 deselected, 1 warning in 3.90s`; invalid updates reached JSON mutation,
   PostgreSQL session creation, or fake API repositories.

4. Audit redaction:

   `cd v2-api; ..\.venv\Scripts\python.exe -m pytest tests/test_local_simulation.py::test_json_audit_events_recursively_redact_photo_storage_secrets tests/test_state_repository.py::test_postgres_construction_activity_audit_redacts_nested_photo_secrets_before_persistence tests/test_api.py::test_production_audit_log_is_admin_only_and_recursively_redacted -q`

   Result: `3 failed, 1 warning in 1.54s`; camelCase secret values remained visible.

5. Retired frontend service gate:

   `node scripts/verify_project_board_unmatched_review.js`

   Result: exit 1, `Error: API services must not expose retired unmatched rematch`.

## GREEN Evidence

- Dual real HTTP: `4 passed, 120 deselected, 1 warning in 2.36s`.
- Dual repository/HTTP regression set: `10 passed, 344 deselected, 1 warning in 2.61s`.
- Audit persistence/response set: `3 passed, 1 warning in 1.20s`.
- Expanded identity matrix: `24 passed, 218 deselected, 1 warning in 0.95s`.
- Release parser suite: `146 passed in 0.34s`.
- Unmatched UI verifier: `project board unmatched review checks passed`.
- Core backend modules (`test_local_simulation.py`, `test_state_repository.py`, `test_api.py`):
  `354 passed, 1 warning in 119.78s`.
- Full `v2-api/tests`: `504 passed, 1 warning in 125.53s`.
- Release and package verifier tests: `147 passed in 0.43s`.
- `scripts/verify_security_hardening.py`: `[OK] security hardening static checks passed`.
- `scripts/verify_release_sop.py`: `[OK] release SOP files and references are consistent`.
- `scripts/verify_project_board_unmatched_review.js`: passed.
- `npm run build` in `v2-web`: passed; `vue-tsc --noEmit` and Vite transformed 1889 modules.
- `git diff --check 94bdadc..HEAD`: exit 0 with no findings.
- Generated `v2-api/app/static/vue` assets were restored; path-specific `git status` was empty.

## Changed Files

- `.superpowers/sdd/final-review-round-2-findings.md`
- `.superpowers/sdd/final-review-round-2-fix-report.md`
- `docs/database/postgresql-schema.md`
- `scripts/test_verify_release_sop.py`
- `scripts/verify_project_board_unmatched_review.js`
- `scripts/verify_release_sop.py`
- `v2-api/app/api/routes/local_test.py`
- `v2-api/app/services/local_simulation.py`
- `v2-api/app/services/state_repository.py`
- `v2-api/app/services/unmatched_review.py`
- `v2-api/tests/test_api.py`
- `v2-api/tests/test_local_simulation.py`
- `v2-api/tests/test_state_repository.py`
- `v2-web/src/api/services.ts`

## Self-Review

- Transaction ownership: active middleware transactions are never finished or aborted by the
  repository; direct repository transactions are always aborted on fail-fast.
- Mutation ordering: dual strict writes fail before JSON business functions, PostgreSQL factory
  construction, persistence, or audit mutation.
- Security: meter/match-key RBAC is checked in production before repository mutation; all repository
  implementations independently validate formal identity.
- Audit: canonicalization preserves ordinary payload keys and only replaces values whose canonical
  key equals an established secret field.
- Release truth: English and Chinese baseline/candidate markers remain reconciled at V3.0.79 and
  pending V3.0.80. No affirmative V3.0.80 deployment prose was added.
- Frontend: only the retired service was removed; current unmatched-review services and verifier
  contracts remain present, and TypeScript/build validation passed.
- Scope: no production access, package, deploy, baseline advance, unrelated revert, or generated
  static asset commit occurred.

## Residual Risk

- Dual unmatched-review writes remain intentionally unavailable until a durable JSON/PostgreSQL
  coordinator or recovery journal is designed and proven. This is a controlled availability
  limitation, not a consistency risk; live production uses PostgreSQL.
- The backend suite reports the existing Starlette `httpx` deprecation warning.
- The frontend build reports existing Rollup annotation and large-chunk warnings; type checking and
  production build still succeed.
