# Device Hierarchy Contract Notes

## Goal

Lock the operator-facing device hierarchy contract into backend readiness and the graphical field designer:

- Module replacement means the task object stays unchanged and accessory equipment is replaced under that task object.
- Terminal replacement means the main device is replaced first, then accessory equipment replacement is confirmed.
- Conditional accessory collection remains driven by `required_when`.

## Scope

- Add read-only backend readiness evidence under `device_hierarchy.evidence.hierarchy_contract`.
- Show the backend contract in the field graph readiness echo when a saved schema is inspected.
- Add regression guards for the backend evidence and frontend visible block.
- Do not create migrations, tags, releases, deployments, OSS writes, PostgreSQL writes, or production data edits.

## Implementation Steps

1. Add a failing backend regression test for operator contract evidence.
2. Add backend `hierarchy_contract` evidence to `_device_hierarchy_check`.
3. Add a failing Vue static guard for visible backend contract notes.
4. Render `后端层级口径` in `FieldGraphDesigner.vue`.
5. Run hierarchy verification, frontend build, browser smoke, diff check, and sensitive path scan.

## Verification Commands

```powershell
python -m pytest v2-api/tests/test_platform_project_readiness.py -q
python scripts/verify_platform_device_replacement_hierarchy_mode.py
python scripts/verify_platform_single_aggregate_device_hierarchy_guard.py
node scripts/verify_vue_device_hierarchy_contract_notes.js
node scripts/verify_vue_device_replacement_hierarchy_mode.js
node scripts/verify_vue_terminal_accessory_confirmation_gate.js
node scripts/verify_vue_field_graph_backend_readiness_echo.js
pnpm --dir v2-web build
```
