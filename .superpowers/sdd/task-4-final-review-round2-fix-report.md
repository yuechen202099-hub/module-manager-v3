# V3.0.81 Whole-Branch Review Round 2 Fix Report

## Result

- Status: DONE
- Finding addressed: alternate Markdown lifecycle fields can no longer hide conflicting pending-candidate values.
- Scope: `scripts/verify_release_sop.py`, its direct tests, its packaged-archive boundary tests, and this report.
- Release state preserved: no release record, `AGENTS.md`, release manifest, or product file was modified.

## Root Cause

`candidate_release_record_is_pending()` used two local `re.findall()` expressions that only recognized the exact `- Label: value` form. The shared parser already normalized labels with NFKC and supported `-`, `*`, `+`, no bullet, decorative punctuation, and full-width punctuation, but the pending lifecycle uniqueness check did not use it. Because `verify-client-release.py` dynamically loads the packaged SOP parser, the same omission affected direct SOP and archive verification.

## RED Evidence

Direct SOP command:

```powershell
python -m pytest scripts/test_verify_release_sop.py -k "normalized_duplicate_lifecycle_field" -q
```

Observed before implementation: exit code `1`; `4 failed, 273 deselected`. Every case failed with `Failed: DID NOT RAISE AssertionError`.

Packaged-archive command:

```powershell
python -m pytest scripts/test_verify_client_release.py -k "normalized_duplicate_candidate_lifecycle_field" -q
```

Observed before implementation: exit code `1`; `4 failed, 189 deselected`. Every case failed with `Failed: DID NOT RAISE AssertionError`, and each archive printed its normal `[OK]` acceptance output.

The RED cases cover:

- `* Package: conflicting-value`
- `+ Local Verification: conflicting-value`
- unbulleted `Production Reconciliation: conflicting-value`
- `Production Reconciliation` with a full-width colon

## Single Fix

- Removed the two pending-lifecycle-only regular expressions.
- Built one label map from all required lifecycle fields.
- Collected recognized values by calling the existing `parse_known_label_value()` for every record line.
- Required exactly one value for every lifecycle field and compared that value with the expected state through the existing NFKC/casefold `normalize_text()` helper.
- Added no parser, regular expression, or archive-specific implementation path.

This applies uniformly to `Status`, `Local Verification`, `Package`, `Production Deployment`, `Production Reconciliation`, and `Rollback target`.

## GREEN Evidence

```powershell
python -m pytest scripts/test_verify_release_sop.py -k "normalized_duplicate_lifecycle_field" -q
```

Output: `4 passed, 273 deselected in 0.08s`.

```powershell
python -m pytest scripts/test_verify_client_release.py -k "normalized_duplicate_candidate_lifecycle_field" -q
```

Output: `4 passed, 189 deselected in 0.19s`.

Canonical direct/archive controls:

```powershell
python -m pytest scripts/test_verify_release_sop.py::test_accepts_pending_v3081_candidate_release_record scripts/test_verify_client_release.py::test_valid_pending_candidate_archive_passes_truthfulness_checks -q
```

Output: `2 passed in 0.06s`.

Both focused files:

```powershell
python -m pytest scripts/test_verify_release_sop.py scripts/test_verify_client_release.py -q
```

Output: `470 passed, 1 warning in 2.67s`.

Complete scripts suite:

```powershell
python -m pytest scripts -q
```

Output: `470 passed, 1 warning in 2.60s`.

Strict SOP:

```powershell
python scripts/verify_release_sop.py
```

Output: `[OK] release SOP files and references are consistent`.

Compilation:

```powershell
python -m py_compile scripts/verify_release_sop.py scripts/test_verify_release_sop.py scripts/verify-client-release.py scripts/test_verify_client_release.py
```

Output: exit code `0`.

Final whitespace validation:

```powershell
git diff --check
```

Output: exit code `0`; only expected Windows LF-to-CRLF working-copy warnings were emitted.

## Self-Review

- The implementation reuses the existing NFKC labeled-field parser and removes the parallel lifecycle regex collection.
- All six pending lifecycle fields are collected and checked for exactly one normalized expected value.
- Direct SOP and packaged-archive negative tests exercise the same shared implementation through their real boundaries.
- Existing canonical pending controls remain green.
- Affirmative deployment-prose detection, deployed lifecycle validation, live-evidence validation, and archive loading behavior were not weakened or modified.
- No current release record, `AGENTS.md`, release manifest, product source, or unrelated user change is present in the diff.

## Attention Items

- The one pytest warning is the existing intentional duplicate-ZIP-member fixture in `test_archive_rejects_duplicate_entry_bundle_members`; it does not mask a failure.
- Git emits the repository's expected LF-to-CRLF working-copy conversion warnings on Windows; `git diff --check` reports no diff errors.
- No unresolved Round 2 Important concern remains.
