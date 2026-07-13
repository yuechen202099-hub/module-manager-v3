# V3.0.80 Final Review Round 5 Fix Report

Date: 2026-07-14
Branch: `production/V3/3.0.80`
Baseline: `36884794ec66a41fb8ae9a4a06a7e50f78765203`
Production baseline: `V3.0.79`
Candidate: `V3.0.80` pending
Deployment: not performed

## Scope And Result

Both Round 5 Medium findings are closed:

1. Release truth parsing now isolates modal, normative, negative, and future language to atomic semantic clauses. Only a leading explicit antecedent such as `if`, `unless`, `若`, or `除非` can carry conditional scope to a following clause. Unrelated capability prose no longer hides a later deployment assertion, optional adverbs in `has/have already gone live` are recognized, and English/Chinese normative or future claims remain non-affirmative.
2. `v2-web/src/version.json` is the single Vue machine version source. `APP_VERSION` imports it, Vite emits the runtime `version.json` from it, and application entry code retains an exact `__MODULE_MANAGER_VUE_ENTRY_VERSION__:<semver>:__END__` marker. Package verification parses the one module entry referenced by `index.html`, reads only that bundle's exact marker, and reconciles it with source/runtime JSON, manifest, title, AGENTS candidate markers, and the release record.

No production system, production database, deployment marker, or live state was accessed or changed.

## Root Causes

### Finding 1

`semantic_claim_clauses()` used one broad `can/could/may/might/if/unless` predicate both to classify a clause and to open cross-clause conditional scope. A capability statement therefore contaminated later independent clauses. The deployment regex also required `has gone live` with no intervening adverb, while `should` and `must` were not classified as non-affirmative.

The fix separates same-clause modal classification from cross-clause antecedent detection. Cross-clause scope opens only when an atomic clause begins with an explicit condition. The self-review added the adversarial control `Operators can log in if authorized, and V3.0.80 was deployed to production.` to prove that an unrelated trailing condition also cannot suppress the deployment claim.

### Finding 2

The old `v2-web/public/version.json` sidecar was copied independently while `APP_VERSION` remained a TypeScript literal. The package verifier trusted source/runtime sidecars and never followed the actual Vue entry script, so a stale `V3.0.79` entry bundle could pass beside `V3.0.80` metadata.

The fix moves the canonical artifact into importable Vue source, derives both UI and build outputs from it, and places a distinctive marker in application entry code. The verifier uses `HTMLParser`, requires exactly one local module entry under `/vue/`, rejects ambiguous/traversal paths, requires exactly one semantic marker in that referenced bundle, and ignores marker-like content in unrelated chunks.

### Verification Chain Finding

The first package build exposed an existing false-green in the smoke chain: the smoke verifier uploaded fake JPEG/PNG bytes that the hardened upload validator correctly rejected, and the PowerShell builder did not propagate the failed Python exit code. The smoke fixture now generates valid 8x8 images, and a RED/GREEN test requires package construction to throw when smoke fails.

## RED Evidence

### Initial source parser and Vue binding RED

```powershell
.\.venv\Scripts\python.exe -m pytest scripts/test_verify_release_sop.py -k round5 -q
```

Result: `5 failed, 3 passed, 191 deselected in 0.15s`.

Failures proved:

- unrelated `can` scope hid a real deployment claim;
- `has already gone live` was missed;
- `should` and `must` deployment prose was treated as affirmative;
- the importable single version source and entry marker did not exist.

### Initial forged package RED

```powershell
.\.venv\Scripts\python.exe -m pytest scripts/test_verify_client_release.py -k "round5 or stale_entry" -q
```

Result: `5 failed, 3 passed, 43 deselected in 0.28s`.

The stale `V3.0.79` referenced entry bundle passed even with only ordinary or unrelated-chunk `V3.0.80` decoys, and the same parser counterexamples failed through forged ZIP verification.

### Self-review atomic-clause RED

```powershell
.\.venv\Scripts\python.exe -m pytest scripts/test_verify_release_sop.py -k atomic_clauses -q
.\.venv\Scripts\python.exe -m pytest scripts/test_verify_client_release.py -k atomic_affirmative -q
```

Each suite produced `1 failed, 2 passed`; the shared failure was the unrelated trailing `if authorized` condition suppressing an independent deployment clause.

### Package smoke propagation RED

```powershell
.\.venv\Scripts\python.exe -m pytest scripts/test_verify_client_release.py -k builder_stops -q
```

Result: `1 failed, 51 deselected in 0.08s`; the builder had no `$LASTEXITCODE` guard after smoke execution.

The first real package build also reproduced the stale smoke fixture as HTTP 400: `smoke-a.jpg has unsupported image bytes`.

## GREEN Evidence

### Focused GREEN

| Command | Exact result |
| --- | --- |
| source Round 5 parser excluding Vue binding | `7 passed, 192 deselected in 0.06s` |
| forged-ZIP Round 5 parser | `7 passed, 44 deselected in 0.13s` |
| source Vue binding | `1 passed, 198 deselected in 0.02s` |
| stale referenced entry bundle | `1 passed, 50 deselected in 0.16s` |
| final source atomic-clause selection | `3 passed, 197 deselected in 0.06s` |
| final forged-ZIP atomic-clause selection | `3 passed, 50 deselected in 0.20s` |
| smoke exit propagation gate | `1 passed, 51 deselected in 0.02s` |
| standalone client smoke | PASS, ending `Client demo smoke check passed.` |

### Complete Suites

| Command | Exact result |
| --- | --- |
| `pytest scripts/test_verify_release_sop.py -q` | `200 passed in 0.43s` |
| `pytest scripts/test_verify_client_release.py -q` | `53 passed in 0.44s` |
| `pytest v2-api/tests -q` with `ROUND3_POSTGRES_TEST_URL` and `ROUND4_POSTGRES_TEST_URL` set to localhost PostgreSQL 16 | `515 passed, 1 warning in 131.74s` |

The backend warning is the existing FastAPI `TestClient` Starlette/httpx deprecation warning. The Round 3/4 PostgreSQL tests executed against `127.0.0.1:15432`; they did not skip and cleaned their isolated schemas.

### Build, Package, And Gates

| Command | Result |
| --- | --- |
| `npm exec vue-tsc -- --noEmit` | PASS, exit 0 |
| `npm run build` | PASS, 1890 modules transformed, built in 4.59s |
| built artifact inspection | `{"version":"3.0.80"}`, entry `/vue/assets/index-CY0DTNPp.js`, marker count `1`, marker version `3.0.80` |
| `scripts/build-client-release.ps1 -Version 3.0.80` | PASS with valid client smoke; final local ZIP built |
| `verify-client-release.py <local ZIP>` | PASS, `1,409,066` bytes and `121` required files |
| `python scripts/verify_security_hardening.py` | `[OK] security hardening static checks passed` |
| `python scripts/verify_release_sop.py` | `[OK] release SOP files and references are consistent` |
| `node scripts/verify_project_board_unmatched_review.js` | `project board unmatched review checks passed` |
| `python scripts/verify_vue_migration_gate.py --strict-native` | PASS, 7 registered pages and 0 legacy bridge pages |

Vite emitted only the existing Rollup pure-annotation and large-chunk warnings. The generated package folder/ZIP and all generated/untracked `v2-api/app/static/vue` files were deleted; tracked static assets were restored.

## Changed Files

- `.superpowers/sdd/final-review-round-5-findings.md`
- `.superpowers/sdd/final-review-round-5-fix-report.md`
- `docs/sop/02-production-branch-versioning.md`
- `docs/sop/05-release-package-and-hash.md`
- `scripts/build-client-release.ps1`
- `scripts/smoke-client-demo.py`
- `scripts/test_verify_client_release.py`
- `scripts/test_verify_release_sop.py`
- `scripts/verify-client-release.py`
- `scripts/verify_release_sop.py`
- `v2-web/public/version.json` (removed)
- `v2-web/src/version.json` (canonical source)
- `v2-web/src/constants/releaseNotes.ts`
- `v2-web/src/main.ts`
- `v2-web/src/vite-env.d.ts`
- `v2-web/tsconfig.node.json`
- `v2-web/vite.config.ts`

## Commit

This report is included in the single Round 5 commit. Its exact SHA is reported after commit creation in the final task response; a Git commit cannot contain its own final hash without changing that hash.

## Self-review

- Confirmed capability and explicit-condition scope are separate, including the extra trailing-`if` adversarial case.
- Confirmed prior Round 4 controls still pass, including leading `if/unless` and Chinese antecedents that must suppress conditional deployment prose.
- Confirmed the package verifier reads only the `index.html`-referenced entry and rejects missing, ambiguous, external, query-bearing, traversal, non-JavaScript, or multiply marked entries.
- Confirmed UI `APP_VERSION`, emitted sidecar, and entry marker derive from the same JSON source.
- Confirmed production markers remain `V3.0.79` deployed and `V3.0.80` pending candidate.
- Confirmed no backend transaction code changed and no generated static/package artifact is part of the intended commit.

## Residual Risk

- The release prose parser remains deliberately rule-based. Unusual grammar outside the tested English/Chinese forms could require another explicit pattern, but the specified Round 5 cases and additional atomic-scope adversary are covered in both source and forged-ZIP suites.
- The Vue build retains pre-existing large-chunk and third-party pure-annotation warnings; no new build error or runtime marker ambiguity was observed.
- No deployment or live production verification was performed, by instruction. `V3.0.80` remains a pending candidate and this report does not assert release readiness beyond the requested local evidence.
