# V3.2.11 Android scanner release gates report

## Files changed

- `v2-web/src/views/ConstructionView.vue`
- `v2-web/src/views/__tests__/ConstructionScannerAndroid.spec.ts`
- `scripts/verify-client-release.py`
- `scripts/verify_v3_2_11_release.py`
- `scripts/test_verify_client_release.py`
- `scripts/test_verify_v3_2_11_release.py`
- `scripts/build-client-release.ps1`

## RED evidence

1. `v2-web\\node_modules\\.bin\\vitest.cmd run --config tests/collector-transfer.vitest.config.ts src/views/__tests__/ConstructionScannerAndroid.spec.ts`
   - Failed as expected: the new close -> reopen regression asserted `oldControls.stop()` once but received zero calls. This demonstrates that the old ZXing promise could be accepted by the reopened dialog.
2. `.venv\\Scripts\\python.exe -m pytest scripts/test_verify_v3_2_11_release.py -q -k 'construction_android_scanner'`
   - Failed as expected: removing either Android scanner file did not create a V3.2.11 source failure, and replacing `decodeFromConstraints` was accepted.

## Implementation

- Added a monotonic construction-scanner session. Every `startScanner()` attempt begins a session; reset/close invalidates it.
- ZXing callbacks and asynchronously resolved controls now accept only the current open session. Stale controls are stopped immediately and never replace the current controls.
- Bound `ConstructionView.vue` and its Android scanner regression spec into V3.2.11 source checks, archive/package inputs, and build preflight inputs. The V3.2.11 verifier requires fallback/session markers and the regression test marker.

## GREEN evidence

1. `.venv\\Scripts\\python.exe -m pytest scripts/test_verify_v3_2_11_release.py -q`
   - `17 passed in 1.74s`.
2. `.venv\\Scripts\\python.exe -m pytest scripts/test_verify_client_release.py -q -k 'v3211 or V3211'`
   - `3 passed, 366 deselected in 0.70s`.
3. `v2-web\\node_modules\\.bin\\vitest.cmd run --config tests/collector-transfer.vitest.config.ts src/views/__tests__/ConstructionScannerAndroid.spec.ts`
   - `2 passed`.

## Commit

- Commit message: `fix: harden V3.2.11 Android scanner release gate`
- Commit hash: recorded in the task handoff after this report is committed.

## Concerns / remaining risks

- This is a focused hotfix verification set only; it does not run the full release/package build matrix.
- The session token prevents stale ZXing callbacks and controls from owning a reopened dialog; real Android hardware/browser camera compatibility still requires normal release smoke validation.
