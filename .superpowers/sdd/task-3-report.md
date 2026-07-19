# V3.0.80 Task 3 Report: Version Truthfulness

## Scope

Implemented only the Task 3 version-truthfulness code and documentation work. No package was built for release distribution, no deployment or production connection was performed, no release directories were cleaned, and the deployed baseline was not advanced.

## RED

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest scripts\test_verify_release_sop.py -q
```

Output before the verifier implementation:

```text
2 failed
AttributeError: module 'verify_release_sop' has no attribute 'deployed_production_baseline'
AttributeError: module 'verify_release_sop' has no attribute 'release_record_claims_deployed_without_live_evidence'
```

Command after adding the verifier contract, before correcting the false baseline claim:

```powershell
.\.venv\Scripts\python.exe scripts\verify_release_sop.py
```

Output:

```text
[FAIL] AGENTS.md must define exactly one deployed production baseline marker
```

This demonstrated that the previous `V3.0.80` production-baseline wording could not satisfy the new deployed-baseline contract.

## GREEN

```powershell
.\.venv\Scripts\python.exe -m pytest scripts\test_verify_release_sop.py -q
```

```text
2 passed in 0.01s
```

```powershell
.\.venv\Scripts\python.exe scripts\verify_release_sop.py
```

```text
[OK] release SOP files and references are consistent
```

Requested local verification stack:

```text
.\.venv\Scripts\python.exe -m pytest v2-api\tests -q
441 passed, 1 warning in 120.52s

npm --prefix v2-web run build
exit 0; Vue type-check and Vite build completed

node scripts\verify_project_board_unmatched_review.js
project board unmatched review checks passed

.\.venv\Scripts\python.exe scripts\verify_security_hardening.py
[OK] security hardening static checks passed

.\.venv\Scripts\python.exe scripts\verify_release_sop.py
[OK] release SOP files and references are consistent

.\.venv\Scripts\python.exe scripts\verify-client-release.py --help
exit 0
```

The front-end build regenerated `v2-api/app/static/vue` assets; all generated asset changes were restored before review.

## Changed Files

- `AGENTS.md`: separates the deployed production baseline `V3.0.79` from release candidate `V3.0.80` with exact machine-checkable Chinese markers.
- `scripts/verify_release_sop.py`: parses the markers independently, requires a pending V3.0.80 release status, and rejects deployed claims with blank SHA256, backup directory, release directory, or public live-health evidence.
- `scripts/test_verify_release_sop.py`: focused regression coverage for independent markers and incomplete deployed records.
- `ops/releases/V3.0.80.md`: keeps status explicitly `pending` and leaves operational evidence blank.

## Commit

- Implementation commit: `f1d232a fix: enforce V3.0.80 release truthfulness`

## Self-Review

- The verifier matches exactly one deployed-baseline marker and exactly one candidate marker, so a generic version-string hit cannot substitute for either state.
- The deployed-evidence gate checks only records whose `Status` claims deployment, allowing the candidate record to remain pending with blank operational fields.
- Runtime and package version surfaces were not modified; they remain candidate `3.0.80`.

## Concerns

- `git diff --check 94bdadc..HEAD` currently fails on a pre-existing blank line at `docs/superpowers/plans/2026-07-13-v3-0-80-review-remediation.md:265`, which is outside Task 3 ownership. The Task 3 working diff passed `git diff --check`.
- Whole-branch approval, packaging, deployment, release retention, production health checks, and advancing the deployed baseline remain controller-owned.

## Review Remediation

The Task 3 review found that the first implementation read only the first `Status` field, accepted non-empty evidence without format validation, and required literal marker spelling.

### RED

```powershell
.\.venv\Scripts\python.exe -m pytest scripts\test_verify_release_sop.py -q
```

```text
14 failed, 2 passed
```

The failures covered normalized duplicate markers, multiple `Status`/`Deployment state` claims, shipped and Chinese deployed-status claims, invalid or placeholder evidence, and valid deployed records using non-`Status` fields.

Two additional adversarial RED checks then exposed health evidence with an embedded `TBD` placeholder and `.`/`..` path leaves:

```text
1 failed, 21 passed
2 failed, 22 passed
```

### GREEN

```powershell
.\.venv\Scripts\python.exe -m pytest scripts\test_verify_release_sop.py -q
.\.venv\Scripts\python.exe scripts\verify_release_sop.py
```

```text
24 passed in 0.04s
[OK] release SOP files and references are consistent
```

The verifier now normalizes marker labels, permits exactly one status-like assertion, recognizes deployed/shipped/released and Chinese equivalents in that assertion, rejects contradictory/multiple fields, and requires valid SHA256, backup/release paths, and successful public `sgcc.online/health` evidence for deployment claims.

### Remediation Commit

- `205ba9f fix: harden release truthfulness verifier`

No package, deployment, production connection, release cleanup, or deployed-baseline advancement occurred.

## V3.0.81 Task 3 Completion: Build Script Surface

### Supplemental RED

The prior Task 3 RED and targeted version/SOP RED coverage remained valid. The final strict SOP check reproduced the additional missing version surface before this change:

```powershell
.\.venv\Scripts\python.exe scripts\verify_release_sop.py
```

```text
[FAIL] Version update surface scripts/build-client-release.ps1 must match 3.0.81
```

Root cause: `scripts/build-client-release.ps1` still declared its default package version as `3.0.80`, while all other candidate surfaces and the strict release verifier required `3.0.81`.

### GREEN

Updated only the explicitly authorized `scripts/build-client-release.ps1` candidate surface:

- `[string]$Version = "3.0.81"`
- its semantic-version example now uses `3.0.81`

Fresh verification after the update:

```text
v2-api version tests: 5 passed, 139 deselected, 1 existing dependency deprecation warning
release SOP tests: 260 passed
scripts/verify_release_sop.py: [OK] release SOP files and references are consistent
git diff --check: exit 0; only expected Windows LF-to-CRLF warnings
```

### Final Scope And State

The only newly authorized file outside the original brief is `scripts/build-client-release.ps1`; all other Task 3 changes remain within the brief's Files list. `AGENTS.md` still states deployed production baseline `V3.0.80`, release candidate `V3.0.81`, and branch `production/V3/3.0.81`. `ops/releases/V3.0.81.md` still contains only `pending` or `not run` operational fields and rollback target `V3.0.80`.

### Final Commit

- Implementation commit SHA: `084cc23` (`chore: prepare V3.0.81 production release`)

### Final Concerns

- No package, production deployment, production health check, production reconciliation, or deployed-baseline advancement was performed; the V3.0.81 release record intentionally remains pending/not run.
- The focused API test emits the pre-existing Starlette/httpx deprecation warning. `git diff --check` emits only the repository's expected Windows LF-to-CRLF warnings.

## V3.0.81 Task 3: Version And Pending Release Record

### Modified Files

- `AGENTS.md`
- `v2-api/app/main.py`
- `v2-api/app/services/ops_status.py`
- `v2-api/pyproject.toml`
- `v2-api/tests/test_api.py`
- `v2-web/index.html`
- `v2-web/package.json`
- `v2-web/src/version.json`
- `v2-web/src/components/AppLayout.vue`
- `v2-web/src/constants/releaseNotes.ts`
- `RELEASE_MANIFEST.md`
- `ops/releases/V3.0.81.md`
- `scripts/verify_release_sop.py`
- `scripts/test_verify_release_sop.py`
- `scripts/build-client-release.ps1`

`v2-web/pnpm-lock.yaml` was inspected but has no root package-version field, so it required no semantic change.

### RED

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -k version -q
```

After making the system-status version test selectable by `-k version`, it failed as expected because runtime code returned `3.0.80` instead of `3.0.81`.

```powershell
.\.venv\Scripts\python.exe -m pytest scripts\test_verify_release_sop.py -q
```

This failed as expected before implementation because the candidate remained `V3.0.80` and `v2-web/src/version.json` remained `3.0.80`. A focused release-record test also failed before the pending-record gate existed, then exposed and covered the parser collision caused by a Chinese `发布` prose prefix.

### GREEN

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py -k version -q
```

`5 passed, 139 deselected, 1 warning`

```powershell
.\.venv\Scripts\python.exe -m pytest scripts\test_verify_release_sop.py -q
```

`260 passed`

The version and release-record tests confirm deployed baseline `V3.0.80`, candidate `V3.0.81`, the maintenance branch `production/V3/3.0.81`, the machine-readable runtime version, and a pending-only V3.0.81 record with rollback target `V3.0.80`.

```powershell
.\.venv\Scripts\python.exe scripts\verify_release_sop.py
```

Failed: `Version update surface scripts/build-client-release.ps1 must match 3.0.81`.

### Self Review

`git diff --check` passed for the current task diff. The deployed baseline remains `V3.0.80`; the new release note is titled `未匹配长条码候选修复` and states that long barcodes can match existing data groups, while a unique candidate is preselected but still requires administrator confirmation. `ops/releases/V3.0.81.md` contains only pending/not-run operational status and no deployment evidence.

### Commit

Commit SHA: not created. The required SOP verification is failing, so no incomplete candidate commit was made.

### Concern

`scripts/build-client-release.ps1` has `[string]$Version = "3.0.80"`. It is outside the Task 3 brief's allowed Files list, but the strict verifier correctly requires it to match `3.0.81`. Updating that script requires its owner or explicit permission; weakening the verifier would hide a real candidate-version mismatch.

## Final Parser Normalization Remediation

The full-width dot bypass showed that delimiter-by-delimiter regex expansion could not provide a reliable parser boundary.

### RED

```powershell
.\.venv\Scripts\python.exe -m pytest scripts\test_verify_release_sop.py -q
```

```text
16 failed, 117 passed
```

The failures were the full-width-dot and bracket label variants across unbulleted, `-`, `*`, and `+` marker/status forms.

### GREEN

```powershell
.\.venv\Scripts\python.exe -m pytest scripts\test_verify_release_sop.py -q
.\.venv\Scripts\python.exe scripts\verify_release_sop.py
.\.venv\Scripts\python.exe -m py_compile scripts\verify_release_sop.py scripts\test_verify_release_sop.py
```

```text
133 passed in 0.25s
[OK] release SOP files and references are consistent
```

The parser now uses `unicodedata.normalize('NFKC')`, removes one optional Markdown bullet, matches known labels by normalized case-insensitive prefix, and strips decorative suffix separators only after a label match. It requires nonempty values and retains the existing exact-one marker/status/evidence rules.

### Final Parser Commit

- `0f6a0e9 fix: normalize release verifier labels`

No package, deployment, production connection, release cleanup, or deployed-baseline advancement occurred.

## Second Re-Review Remediation

The second review identified that `+` and unbulleted semantic fields were ignored, decorative punctuation was not fully normalized, and evidence rows were reduced with last-write-wins behavior.

### RED

```powershell
.\.venv\Scripts\python.exe -m pytest scripts\test_verify_release_sop.py -q
```

```text
13 failed, 24 passed
```

The failures covered `+` version/status lines, unbulleted and punctuation-delimited fields, unbulleted evidence, and duplicate required evidence fields where a final valid row masked an earlier invalid or duplicate row.

### GREEN

```powershell
.\.venv\Scripts\python.exe -m pytest scripts\test_verify_release_sop.py -q
.\.venv\Scripts\python.exe scripts\verify_release_sop.py
.\.venv\Scripts\python.exe -m py_compile scripts\verify_release_sop.py scripts\test_verify_release_sop.py
```

```text
37 passed in 0.06s
[OK] release SOP files and references are consistent
```

The verifier now accepts `-`, `*`, `+`, and unbulleted semantic fields; canonicalizes ASCII/full-width decorative punctuation around labels; and keeps every required evidence occurrence. A deployment claim requires exactly one valid occurrence of each required evidence field, so duplicate, blank, malformed, placeholder, and conflicting rows all fail.

### Second Re-Review Commit

- `14236b6 fix: close release record parser bypasses`

No package, deployment, production connection, release cleanup, or deployed-baseline advancement occurred.
