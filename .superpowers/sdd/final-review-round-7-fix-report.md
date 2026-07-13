# V3.0.80 Final Review Round 7 Fix Report

## Scope And Baseline

- Branch: `production/V3/3.0.80`
- Starting HEAD: `938574c30315a7b01af8e24ee0743dd32699c88e`
- Production remains `V3.0.79`; `V3.0.80` remains a pending candidate.
- No production backup, deployment, release-truth advancement, or production write was performed in this fix round.
- Findings: `.superpowers/sdd/final-review-round-7-findings.md`

## Root Causes And Fixes

### M1: deployment claim predicate grammar

The release parser matched the final deployment word but inspected only a narrow prefix grammar. Common affirmative forms such as `has gone live` and `already deployed` were missed, while perfect modal, future-perfect, adverbial-negation, and modal-adverb chains were treated as factual deployment.

The deployment predicate now recognizes common English live transitions without requiring a literal `production` suffix and recognizes Chinese completion markers including `already`. Its local prefix grammar consumes complete modal, perfect auxiliary, adverb, and negation chains before deciding whether the predicate is factual.

### M2: full Vue asset attestation

The runtime sidecar bound only the entry chunk. Imported chunks, CSS, HTML, and additional executable scripts could be changed without invalidating that digest.

The Vite post-bundle hook now emits a deterministic `assets` list in `version.json`. Every Vue output other than `version.json` is bound by relative path, byte size, and SHA-256. The package verifier requires the archive Vue file set to match that list exactly and validates every byte. `index.html` must contain exactly one script, and that script must be the external `type=module` entry.

The first end-to-end package attempt also exposed that JavaScript `localeCompare` and Python lexical ordering disagree for mixed-case paths. The builder now uses explicit code-point comparison, and a regression test forbids locale-dependent manifest ordering.

### M3: ZIP member safety

ZIP member names were normalized before validation, allowing absolute and traversal names to be stripped into apparently safe values. Symlink metadata and case-insensitive collisions were not inspected.

Every raw `ZipInfo` is now validated before reads or set conversion. The verifier rejects absolute, drive/colon, backslash, empty, dot, dot-dot, control-character, spelling-changing, symlink, duplicate, and case-colliding members.

### M4: recursive provider locator redaction

Audit redaction recognized only URL fields and storage/object/OSS keys. Equivalent provider fields using URI, link, path, name, S3, or COS tokens remained visible.

The classifier now requires a sensitive locator token (`url`, `uri`, `link`, `href`, `path`, `key`, `name`, or `bucket`) together with a photo/storage/provider qualifier (`raw`, `signed`, `presigned`, `source`, `image`, `photo`, `storage`, `object`, `oss`, `s3`, `cos`, `blob`, or `minio`). Bucket fields remain unconditionally secret. Business identifiers such as `candidate_key` and `project_id` remain visible. JSON, PostgreSQL persistence/response, and administrator HTTP response tests cover the new variants.

### M5: acceptance version contract

The acceptance script defaulted to `final-delivery-ready`, but the package builder accepts only semantic versions. Documentation and the smoke check also retained the obsolete demo package name.

The acceptance gate now defaults to an empty version, reads `v2-web/src/version.json`, validates its semantic version, and rejects an explicit mismatch before dependency installation or build work. Signoff documentation references the server package. The smoke check derives the same package name from the machine version source.

## RED Evidence

- M1/M5 focused source and forged-package selection: `13 failed, 288 deselected`.
- M2 stale imported chunk and extra script probes were accepted before the fix.
- M3 canonical path, symlink, and case-collision selection: `8 failed, 79 deselected`.
- M4 direct provider-variant probe: `1 failed, 1 warning`.
- Acceptance chain attempt 1: `818 passed, 3 skipped`, then failed because `smoke-client-demo.py` required the obsolete demo ZIP name.
- Acceptance chain attempt 2: `819 passed, 3 skipped`, smoke and build passed, then package verification failed because `localeCompare` ordering differed from Python lexical ordering.

## GREEN Evidence

- M1/M5 focused: `13 passed, 288 deselected`.
- M2 focused entry/asset/script selection: `5 passed, 82 deselected`.
- M3 focused unsafe ZIP selection: `8 passed, 79 deselected`.
- M4 direct, JSON, PostgreSQL persistence/response, and HTTP response: `5 passed, 1 warning`.
- Release and package tests: `301 passed, 1 intentional duplicate-ZIP warning`.
- Full backend with local PostgreSQL: `520 passed, 1 existing Starlette warning`.
- Full acceptance test phase: `819 passed, 3 skipped, 2 warnings`.
- Administrator release notes, unmatched review UI, security hardening, release SOP, and strict Vue migration gates passed.
- Vue build passed with `1890 modules transformed`; existing Rollup annotation and large-chunk warnings remain.
- End-to-end `run-client-acceptance-gate.ps1 -Version 3.0.80` passed through tests, demo smoke, Vue build, ZIP creation, and package verification.
- Verified temporary ZIP: `1416435` bytes, `121` required files, no forbidden cache/local files.

## Changed Files

- `docs/CLIENT_SIGNOFF_CHECKLIST.md`
- `scripts/run-client-acceptance-gate.ps1`
- `scripts/smoke-client-demo.py`
- `scripts/test_verify_client_release.py`
- `scripts/test_verify_release_sop.py`
- `scripts/verify-client-release.py`
- `scripts/verify_release_sop.py`
- `v2-api/app/services/unmatched_review.py`
- `v2-api/tests/test_api.py`
- `v2-api/tests/test_local_simulation.py`
- `v2-api/tests/test_state_repository.py`
- `v2-web/vite.config.ts`
- `.superpowers/sdd/final-review-round-7-findings.md`
- `.superpowers/sdd/final-review-round-7-fix-report.md`

## Cleanup And Release State

- Generated `v2-api/app/static/vue` output was restored to the starting HEAD after verification.
- Temporary staging and `module-manager-v2-server-3.0.80.zip` were removed before commit.
- `ops/releases/V3.0.80.md` remains pending with production evidence blank.
- Production remains `V3.0.79` until an independent review approves this commit and the controller performs backup, hash verification, deployment, and live checks.

All five Round 7 Medium findings are closed by local evidence. Independent Round 8 review is still required before release.
