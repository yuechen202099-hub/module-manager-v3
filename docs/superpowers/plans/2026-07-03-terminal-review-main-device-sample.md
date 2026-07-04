# Terminal Review Main Device Sample Plan

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `V3.0.77`

## Objective

Make terminal replacement review verifiable as a real local sample, not only as a field-schema preset.

The sample must prove:

- `new_terminal_no` enters review as `replacement_device`.
- old terminal/device recovery enters review as `old_device`.
- communication module and SIM replacement confirmations enter review as `accessory_replace_confirm`.
- old/new communication module and SIM fields keep `required_when`.
- old-device recovery and module evidence photos remain review evidence.
- the real `/task-hall` workbench renders a `主设备更换` section.

## Scope

- Add an idempotent terminal external-completed review sample to `scripts/seed-platform-terminal-demo.py`.
- Wire `scripts/start-platform-local.ps1` so local starts include the terminal review sample.
- Add a focused guard: `scripts/verify_platform_terminal_review_sample.py`.
- Keep all data local and development-only.

## Safety

- The seed refuses non-local environments unless explicitly forced.
- The local start script still sets `APP_ENV=local`, `DEMO_AUTH_ENABLED=true`, `STATE_BACKEND=json`, and `STORAGE_BACKEND=local`.
- No production `.env`, OSS, PostgreSQL, uploads, tag, version number, or deployment path is touched.

## Rollback

- Revert:
  - `scripts/seed-platform-terminal-demo.py`
  - `scripts/start-platform-local.ps1`
  - `scripts/verify_platform_local_start_script.py`
  - `scripts/verify_platform_terminal_review_sample.py`
- Delete local ignored sample state under `data` if a clean local demo state is desired.
