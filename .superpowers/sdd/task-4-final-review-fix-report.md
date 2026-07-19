# V3.0.81 Whole-Branch Important Fix Report

## Result

- Status: DONE
- Implementation commit SHA: `6278c5b232c41b9c27257a95fdf66224dc03ec9b`
- Scope: the four authorized verifier/test scripts only; this report is committed separately.
- Release state preserved: V3.0.80 remains deployed and V3.0.81 remains pending.

## Root Cause

1. Pending-candidate prose detection associated affirmative deployment prose with the most recently seen version token. A valid rollback marker could therefore make a later unversioned deployment claim appear to describe V3.0.80, and complete forged evidence then passed.
2. The dynamic deployed-baseline refactor replaced V3.0.80's exact full-lifecycle status check with a weaker test for any deployment verb plus four evidence fields.
3. The direct SOP rejected equal deployed/candidate markers, while the archive verifier hard-coded V3.0.80 as the only deployed baseline and always treated V3.0.81 as pending.

## RED Evidence

### Important 1: Complete Forged Evidence Bypass

Command:

```powershell
python -m pytest -q scripts/test_verify_release_sop.py::test_rejects_pending_candidate_with_unversioned_deployment_claim_and_complete_evidence scripts/test_verify_client_release.py::test_archive_rejects_pending_candidate_with_unversioned_claim_and_complete_evidence
```

Observed before implementation: exit code `1`; `2 failed in 0.19s`. Both SOP and archive tests reported `Failed: DID NOT RAISE AssertionError`, proving that pending lifecycle fields plus an unversioned affirmative claim and complete valid evidence bypassed both boundaries.

### Important 2: Deployed Lifecycle Completeness

Command:

```powershell
python -m pytest -q scripts/test_verify_release_sop.py::test_deployed_lifecycle_rejects_bare_deployed_status scripts/test_verify_client_release.py::test_archive_rejects_bare_deployed_baseline_status
```

Observed before implementation: exit code `1`; `2 failed in 0.21s`. Both tests reported `Failed: DID NOT RAISE AssertionError`; the archive verifier printed its normal `[OK]` lines while accepting a bare `Status: deployed` baseline.

### Important 3: Equal Post-Deploy Markers

Command:

```powershell
python -m pytest -q scripts/test_verify_release_sop.py::test_post_deploy_equal_markers_validate_one_deployed_record scripts/test_verify_client_release.py::test_archive_accepts_equal_post_deploy_markers_as_one_deployed_record
```

Observed before implementation: exit code `1`; `2 failed in 0.21s`. The SOP test failed because the single-record lifecycle dispatcher did not exist; the archive test failed with `Packaged AGENTS.md deployed production baseline must remain V3.0.80`.

## Changes

### Shared SOP Truth Rules

- Added a whole-record affirmative deployment-prose predicate that reuses the existing clause parser and deployment claim detector without requiring version-token association.
- Pending status combined with any affirmative deployment claim now fails before evidence completeness can affect the result.
- Restored the exact deployed lifecycle status `reviewed, packaged, deployed, and verified in production` for every dynamic deployed baseline.
- Added `validate_release_lifecycle_records()`, which validates deployed and candidate versions in marker order and deduplicates equal versions so the post-deploy V3.0.81 record is checked once as deployed.

### Archive Boundary

- The archive verifier now loads packaged release records and delegates both deployed-baseline and candidate validation to the shared SOP lifecycle dispatcher.
- Removed the hard-coded V3.0.80 deployed-baseline restriction while retaining the package-version-to-candidate contract.
- The current V3.0.80/V3.0.81 archive path still validates V3.0.80 as fully deployed and V3.0.81 as fully pending.

### Regression Coverage

- Added direct SOP and archive tests for complete forged evidence with unversioned deployment prose.
- Added direct SOP and archive negative tests for bare deployed status and positive controls for the complete lifecycle status.
- Added direct SOP and archive tests for equal V3.0.81 deployed/candidate markers.
- Updated the archive fixture so packaged V3.0.80 is a truthful complete deployed baseline and pending V3.0.81 includes the full pending lifecycle fields.

## GREEN Evidence

```powershell
.\.venv\Scripts\python.exe -m pytest -q scripts/test_verify_release_sop.py::test_rejects_pending_candidate_with_unversioned_deployment_claim_and_complete_evidence scripts/test_verify_client_release.py::test_archive_rejects_pending_candidate_with_unversioned_claim_and_complete_evidence scripts/test_verify_release_sop.py::test_deployed_lifecycle_rejects_bare_deployed_status scripts/test_verify_release_sop.py::test_deployed_lifecycle_accepts_complete_status scripts/test_verify_client_release.py::test_archive_rejects_bare_deployed_baseline_status scripts/test_verify_client_release.py::test_archive_accepts_complete_deployed_baseline_status scripts/test_verify_release_sop.py::test_post_deploy_equal_markers_validate_one_deployed_record scripts/test_verify_client_release.py::test_archive_accepts_equal_post_deploy_markers_as_one_deployed_record
```

Output: `8 passed in 0.30s`.

```powershell
.\.venv\Scripts\python.exe -m pytest scripts -q
```

Output: `462 passed, 1 warning in 2.49s`.

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_release_sop.py
```

Output: `[OK] release SOP files and references are consistent`.

```powershell
.\.venv\Scripts\python.exe -m py_compile scripts\verify_release_sop.py scripts\test_verify_release_sop.py scripts\verify-client-release.py scripts\test_verify_client_release.py
```

Output: exit code `0`.

```powershell
git diff --check
```

Output: exit code `0`; only expected Windows LF-to-CRLF working-copy warnings were emitted.

## Self-Review

- The implementation commit contains only the four authorized scripts.
- `AGENTS.md`, current release records, release manifest, and product files were not modified.
- Deployment-claim regexes, conditional/negation handling, and all four live-evidence validators were left intact; the new predicate strengthens coverage by removing version-token dependence.
- The package verifier and direct SOP now share one lifecycle dispatcher and one truth parser.
- Equal markers validate one record once through `dict.fromkeys`, with the deployed-baseline branch taking precedence.

## Attention Items

- The single pytest warning is the existing intentional duplicate-ZIP-member negative fixture (`test_archive_rejects_duplicate_entry_bundle_members`); it does not mask a failure.
- Git reports expected LF-to-CRLF working-copy conversion warnings on Windows; `git diff --check` reports no diff errors.
- No unresolved Important findings remain.
