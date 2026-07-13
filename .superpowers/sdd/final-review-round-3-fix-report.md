# V3.0.80 Final Review Round 3 Fix Report

Date: 2026-07-14
Branch: `production/V3/3.0.80`
Starting HEAD: `98cdaa62010769d1e427e84b57e3fa21d38aed51`
Implementation commit: `5a2cabc51f899878684c13fa220056fa8d2f344d`
Production baseline: `V3.0.79`
Release candidate: `V3.0.80` pending

## Outcome

All four round-3 Medium findings are closed with focused RED/GREEN evidence. No package was
created, no deployment or production write path was accessed, and the production baseline and
pending candidate markers were not advanced.

The real PostgreSQL proof used the local Docker PostgreSQL 16 instance exposed only at
`127.0.0.1:15432`. Each run created a random isolated schema, created its own tables and delay
trigger, and dropped the schema in `finally`. A post-test catalog query returned zero remaining
`round3_%` schemas.

## Root Causes And Fixes

### 1. JSON legacy unmatched assignment

Root cause: `assign_unmatched_record()` called `update_unmatched_record()` before reading and
validating the unmatched terminal. The update advanced the review version, wrote an update audit,
and refreshed summary before `ensure_task_for_terminal()` could create a placeholder task.

Fix: assignment now locates the record in the existing active authoritative transaction or
existing team state without calling the state-initializing accessor. It validates the terminal with
the shared formal-identity validator before update, task creation, assignment, summary, audit, or
persistence mutation. `00000000`, `未关联终端`, `manual-*`, and `unmatched-*` therefore produce a
controlled HTTP 400 / repository `ValueError` with the complete state and persistence bytes intact.

The raw-state lookup is intentional: `state_for_team()` adds `summary.team_id`, which would itself
violate the requirement that rejection occur before any summary mutation.

### 2. PostgreSQL concurrent task materialization

Root cause: `_ensure_task_for_terminal()` performed query-then-insert without serializing the real
`(team_id, terminal)` identity. Concurrent finalizations for different meter keys could both see no
task and then collide or create split task identity.

Fix: a stable signed 64-bit key derived from SHA-256 of the namespaced `(team_id, terminal)` tuple
is passed to `pg_advisory_xact_lock()` before the task query. Finalization lock order is now formal
meter identity, then terminal task identity. Other helper callers acquire only the terminal lock,
so no path reverses that order.

The integration test runs two real `finalize_unmatched_match()` calls for the same terminal and
different meter keys. A temporary PostgreSQL trigger sleeps before task insert to make the old race
deterministic. Both finalizations now succeed, one task exists, and both materialized groups point
to that task. Futures have 15-second timeouts and the database has statement/lock timeouts.

### 3. Release truth semantic parsing

Root cause: version periods were treated as sentence boundaries, version context stopped at blank
paragraphs, conjunctions such as `and` / `并于` did not create semantic clauses, and contractions or
intervening adverbs escaped negation. The claim vocabulary also omitted live-production and Chinese
completion forms.

Fix: the parser now normalizes contractions, protects periods inside version tokens, splits
English/Chinese semantic conjunctions and punctuation, and carries explicit version context across
the complete prose stream. Negation and future/conditional language are evaluated per clause.
Affirmative patterns include `is now live in production` and `生产部署已完成`.

Markdown table rows are excluded from prose scanning so an empty `Deployed source commit` evidence
label is not a claim. Conditional rollback prose using before/after/until/once remains non-
affirmative. Structured status fields continue to be parsed separately.

### 4. Forged release archives

Root cause: `verify-client-release.py` accepted a missing manifest `Version`, conditionally skipped
static version checks, and checked only that the V3.0.80 release record filename existed. Packaged
AGENTS markers and release truth were not parsed.

Fix: package verification now requires a semantic manifest version, requires the Vue title and JS
assets to contain that version, and requires it to equal the packaged V3.0.80 candidate marker. It
loads `verify_release_sop.py` as the shared truth parser, reconciles English/Chinese deployed and
candidate markers, verifies the release-record header, rejects unsupported deployment claims, and
requires the record to remain pending before deployment.

Forged ZIP tests cover missing manifest version, static mismatch, contradictory AGENTS markers,
deployed status without evidence, clause/paragraph affirmative prose bypasses, and a valid pending
control archive.

## RED Evidence

All binding RED runs were executed before their implementation changes.

1. Legacy assign repository and real HTTP middleware:

   `.\.venv\Scripts\python.exe -m pytest v2-api/tests/test_local_simulation.py v2-api/tests/test_api.py -k "legacy_assign_rejects_placeholder_terminal" -q`

   Result: `8 failed, 262 deselected, 1 warning in 3.38s`. Repository calls did not raise and HTTP
   returned 200 for all four placeholder terminal classes.

2. Release semantic clauses:

   `.\.venv\Scripts\python.exe -m pytest scripts/test_verify_release_sop.py -k "clause_scoped_and_cross_line or semantic_clause_parser" -q`

   Result: `8 failed, 7 passed, 142 deselected in 0.16s`. Conjunction, Chinese conjunction,
   cross-blank-line, live-production, Chinese-completion, contraction, adverbial-negation, and
   future controls exposed the gaps.

3. Forged package verification:

   `.\.venv\Scripts\python.exe -m pytest scripts/test_verify_client_release.py -q`

   Result: `6 failed, 3 passed in 0.15s`. Missing manifest version, contradictory markers,
   unsupported deployed record, and three affirmative-prose archives were accepted.

4. Real PostgreSQL concurrency:

   `$env:ROUND3_POSTGRES_TEST_URL='postgresql+psycopg://module_manager:module_manager_password@127.0.0.1:15432/module_manager_v3_local'; .\.venv\Scripts\python.exe -m pytest v2-api/tests/test_round3_postgres_concurrency.py -q`

   Valid race result: `1 failed in 2.00s`. One worker raised
   `FinalizationIdentityConflict` caused by `uq_tasks_team_legacy_id`, proving both transactions had
   attempted first task creation. An earlier setup-only run hit project/team FK ordering before the
   race; the fixture was corrected to flush Team first and was not counted as finding RED evidence.

5. Gate-discovered parser false positives:

   `.\.venv\Scripts\python.exe -m pytest scripts/test_verify_release_sop.py -k "semantic_clause_parser" -q`

   Result: `2 failed, 6 passed, 151 deselected in 0.13s` for the empty deployed-source table label
   and conditional rollback prose. Both were fixed before final release-gate verification.

## GREEN Evidence

- Legacy JSON repository plus real FastAPI: `8 passed, 262 deselected, 1 warning in 2.55s`.
- Real PostgreSQL concurrent finalization: `1 passed in 1.54s`.
- Final adversarial release parser focus: `17 passed, 142 deselected in 0.06s`.
- Forged package suite: `9 passed in 0.08s`.
- Final complete release/package tests: `168 passed in 0.40s`.
- Core backend modules plus PostgreSQL integration: `375 passed, 1 warning in 122.41s`.
- Full `v2-api/tests` with the local PostgreSQL URL set: `513 passed, 1 warning in 131.26s`.
- `scripts/verify_security_hardening.py`: `[OK] security hardening static checks passed`.
- `scripts/verify_release_sop.py`: `[OK] release SOP files and references are consistent`.
- `scripts/verify_project_board_unmatched_review.js`: `project board unmatched review checks passed`.
- `scripts/verify-client-release.py --help`: exit 0.
- `scripts/verify_vue_migration_gate.py --strict-native`: passed; 7 registered pages, 0 legacy
  bridge pages.
- `npm run build` in `v2-web`: passed; `vue-tsc --noEmit` and Vite transformed 1889 modules.
- `git diff --check 94bdadc..HEAD`: exit 0 after the implementation commit.
- Generated `v2-api/app/static/vue` assets were restored; path-specific Git status was empty.
- Local PostgreSQL cleanup query: `0` schemas matching `round3_%`.

## Changed Files

- `.superpowers/sdd/final-review-round-3-findings.md`
- `.superpowers/sdd/final-review-round-3-fix-report.md`
- `scripts/test_verify_client_release.py`
- `scripts/test_verify_release_sop.py`
- `scripts/verify-client-release.py`
- `scripts/verify_release_sop.py`
- `v2-api/app/services/local_simulation.py`
- `v2-api/app/services/state_repository.py`
- `v2-api/tests/test_api.py`
- `v2-api/tests/test_local_simulation.py`
- `v2-api/tests/test_round3_postgres_concurrency.py`

## Self-Review

- Mutation ordering: invalid legacy terminals are rejected before task, unmatched, summary, audit,
  authoritative-transaction commit, or persistence-file mutation.
- HTTP proof: tests pass through production authentication and `persist_local_test_state`; they do
  not bypass middleware or call only a route function.
- Lock identity and order: the task lock uses only canonical team and terminal identity; formal
  finalization retains meter lock first and terminal lock second. No new reverse acquisition path
  was introduced.
- PostgreSQL isolation: the test URL is required explicitly, asserts PostgreSQL and localhost, uses
  a random schema, has timeout guards, and drops all test objects on success or failure.
- Release truth: version periods survive clause splitting; explicit version context crosses blank
  lines; negation/future handling remains clause-local; table labels are not prose.
- Package truth: manifest, static assets, AGENTS markers, record version, pending status, and
  deployment evidence are checked as one fail-closed contract using the shared parser.
- Baseline: AGENTS remains deployed V3.0.79 / candidate V3.0.80, and the V3.0.80 record remains
  pending. No affirmative deployment statement was added.
- Scope: no production access, package, deploy, baseline advance, unrelated revert, database
  migration, or generated static-asset commit occurred.

## Residual Risk

- PostgreSQL advisory keys use a signed 64-bit SHA-256 prefix; collision risk is theoretical and
  negligible, but advisory locks rely on application writers using `_ensure_task_for_terminal()`.
  Direct manual SQL can bypass application coordination.
- The real concurrency proof covers PostgreSQL 16 in the local Docker topology with two workers.
  It does not simulate production latency or a large worker fleet; production was intentionally not
  accessed.
- The integration test is opt-in outside this review via `ROUND3_POSTGRES_TEST_URL`; this review's
  focused, relevant-module, and full backend runs all set it, so the test executed rather than
  skipped.
- The backend suite reports the existing Starlette `httpx` deprecation warning.
- The frontend build reports existing Rollup annotation and large-chunk warnings; type checking and
  the production build still succeed.
