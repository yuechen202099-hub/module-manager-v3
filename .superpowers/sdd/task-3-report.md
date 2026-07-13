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
