# V3.0.80 Final Review Round 4 Findings

Review range: `94bdadc..bf92947`
Verdict: `BLOCK`

## Finding 1: PostgreSQL legacy unmatched assign accepts placeholder terminal (Medium)

The PostgreSQL legacy unmatched assignment path uses `record.terminal` without the shared formal identity validator. A local PostgreSQL 16 probe assigned `terminal=00000000`, advanced review version, persisted assignment, and wrote audit. Historical placeholder tasks can also be mutated.

Validate the PostgreSQL terminal before task lookup, payload update, audit staging, or commit. Add PostgreSQL repository and real `STATE_BACKEND=postgres` HTTP tests for `00000000`, `未关联终端`, `manual-*`, and `unmatched-*`. Assert record/version/task/audit are unchanged.

## Finding 2: release truth parser has conditional false positives and live synonym bypasses (Medium)

Current parser behavior:

- `could/may be deployed` and `can't be deployed` can be misclassified as deployed.
- `has gone live in production` is not recognized as an affirmative production claim.
- Conditional language can pass through full-document claim correlation.

Normalize contractions including `can't/cannot`. Treat `can/could/may/might/if/unless` and equivalent Chinese conditional language as non-affirmative at clause scope. Recognize `has/have gone live in production` and equivalent Chinese production-live/completion forms. Put every counterexample in both source parser and forged archive tests, with pure negative/pending/future controls.

## Finding 3: package version verification accepts ambiguous/forged markers (Medium)

The package verifier reads only the first manifest Version and accepts any JavaScript chunk containing the candidate version substring. These forged archives pass:

- Runtime `APP_VERSION='3.0.79'` plus an unrelated `3.0.80` string.
- Manifest containing both `Version: 3.0.80` and conflicting `Version: 3.0.79`.

Require exactly one semantic manifest Version. Read the runtime version from an unambiguous machine-readable artifact or exact build marker, not an arbitrary substring. Strictly reconcile manifest, Vue runtime/static marker, title, AGENTS candidate marker, and release record version/status. Add forged ZIP tests for duplicate/conflicting manifest versions and unrelated version strings.

## Required Verification

- Focused RED/GREEN for all three findings.
- Real localhost PostgreSQL repository and HTTP tests; no mock/skip accepted.
- Complete source parser and forged package suites.
- Full backend with PostgreSQL integration enabled, frontend build, security/UI/release gates, and `git diff --check 94bdadc..HEAD`.
- No generated static asset commit; production remains V3.0.79 and V3.0.80 remains pending.
