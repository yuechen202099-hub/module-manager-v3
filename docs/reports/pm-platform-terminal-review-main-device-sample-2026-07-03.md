# PM Platform Terminal Review Main Device Sample

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `V3.0.77`

## Summary

The local terminal replacement demo now includes an idempotent external-completed review sample. This gives reviewers a real `/task-hall` work order with `主设备更换`, old-device recovery, accessory confirmations, conditional accessory fields, and photo evidence.

## Changed Files

- `scripts/seed-platform-terminal-demo.py`
- `scripts/start-platform-local.ps1`
- `scripts/verify_platform_local_start_script.py`
- `scripts/verify_platform_terminal_review_sample.py`
- `docs/superpowers/plans/2026-07-03-terminal-review-main-device-sample.md`
- `docs/reports/pm-platform-terminal-review-main-device-sample-2026-07-03.md`

## Verification

TDD red:

- `python scripts\verify_platform_terminal_review_sample.py`
  - Initial result: `[FAIL] terminal demo seed must expose seed_terminal_review_sample`
- `python scripts\verify_platform_local_start_script.py`
  - Initial result after guard update: `[FAIL] missing required snippet TERMINAL_REVIEW_SAMPLE: --with-review-sample`

Green:

- `python scripts\verify_platform_terminal_review_sample.py`
  - Result: `[OK] terminal review sample preserves main-device review hierarchy`
- `python scripts\verify_platform_local_start_script.py`
  - Result: `[OK] local platform start script is pinned to safe development paths.`
- `python scripts\verify_seed_terminal_demo_hierarchy_roles.py`
  - Result: `[OK] terminal demo seed preserves hierarchy relation roles`
- `python scripts\verify_platform_terminal_demo_seed.py`
  - Result: `[OK] terminal platform demo seed script is structurally safe.`
- `node scripts\verify_vue_review_hierarchy_sections.js`
  - Result: `[OK] Vue review hierarchy sections are wired.`
- `node scripts\verify_vue_device_hierarchy_config.js`
  - Result: `[OK] Vue device hierarchy configuration is represented.`
- `git diff --check -- scripts/seed-platform-terminal-demo.py scripts/verify_platform_terminal_review_sample.py scripts/verify_platform_local_start_script.py scripts/start-platform-local.ps1`
  - Result: no whitespace errors.

Local API verification:

- URL: `http://127.0.0.1:52137/projects/draft-project/review/work-orders`
- Result:
  - `total: 1`
  - `primary: TT-TERM-REVIEW-001`
  - `status: pending_review`
  - main device field: `new_terminal_no`, `relation_role: replacement_device`, `collected_value: NEW-TERM-001`
  - conditional field count: `4`

Browser smoke:

- URL: `http://127.0.0.1:52137/task-hall?project_id=draft-project`
- Result:
  - `platformCardCount: 1`
  - `platformDetail: 1`
  - `mainDeviceReplacement: 1`
  - `deviceReplacement: 1`
  - `accessoryConfirmation: 1`
  - `conditionalAccessory: 1`
  - `photoEvidence: 1`
  - `conditionHints: 5`
  - `roleTags: 12`
  - current `52137` console check found no relevant errors or warnings.

## Risk Notes

- This is local demo and verification data only.
- `scripts/start-platform-local.ps1` now creates the terminal review sample by default, but the seed is idempotent and remains local-only.
- No frontend source was changed in this package; the browser smoke validates the existing review hierarchy UI against the new terminal sample.

## Rollback Notes

- Code rollback: revert the changed files listed above.
- Local data rollback: remove ignored local demo JSON files under `data`, or start from a clean local workspace state.
- Production rollback: not applicable because no production write, migration, deployment, version bump, tag, OSS write, or PostgreSQL write occurred.
