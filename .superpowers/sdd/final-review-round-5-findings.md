# V3.0.80 Final Review Round 5 Findings

Review range: `94bdadc..3688479`
Verdict: `BLOCK`

## Finding 1: conditional scope can hide real deployment claims (Medium)

The truth parser propagates any `can/could/may/might` condition across comma/conjunction boundaries. These cases are wrong:

- `Operators can log in, and V3.0.80 was deployed to production.` is not detected.
- `V3.0.80 has already gone live in production.` is not recognized.
- `V3.0.80 should be deployed tomorrow.` is incorrectly treated as deployed.

Split prose into atomic semantic clauses first. Only evaluate conditional/negative/future scope inside a clause that itself contains a deployment predicate. Unrelated capability statements must not suppress later deployment clauses. Recognize optional adverbs in `has/have already gone live in production`. Treat `should/must/ought to` and Chinese normative/future forms as non-affirmative. Put identical counterexamples in source and forged-ZIP suites.

## Finding 2: machine version sidecar is not bound to the actual Vue runtime (Medium)

The verifier checks source/runtime `version.json`, manifest, and title, but the Vue application still compiles `APP_VERSION` from an independent TypeScript literal. A stale V3.0.79 entry bundle plus V3.0.80 sidecars passes package verification.

Use one machine-readable source for both Vue runtime APP_VERSION and the copied runtime artifact. Emit a distinctive runtime build marker from application code that is guaranteed to remain in the entry bundle and is derived from the same version source. The package verifier must parse the exact entry-bundle marker and match it to source/runtime JSON, manifest, title, AGENTS candidate, and release record. An unrelated version string must not satisfy the check. Add a stale-bundle forged ZIP negative test.

## Required Verification

- Focused RED/GREEN for both findings.
- Full source parser and forged package tests.
- Vue typecheck/build proving JSON import/build marker works.
- Package build/verifier smoke, security/UI/release/Vue gates, full backend, and `git diff --check 94bdadc..HEAD`.
- No generated static asset commit; deployed/candidate markers remain V3.0.79/V3.0.80 pending.
