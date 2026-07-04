# Terminal Accessory Confirmation Gate

## Goal

Make the device replacement hierarchy harder to misconfigure in the visual field graph:

- Module replacement stays modeled as accessory equipment replaced under one unchanged task object.
- Terminal replacement stays modeled as main-device replacement plus explicit accessory replacement confirmation.
- Accessory devices under terminal replacement must not be flattened directly under the task object.

## Scope

- Add a field-detail hierarchy hint in the graphical field designer.
- Add a frontend readiness issue when terminal replacement has unconditional accessory new-device fields.
- Add a project save gate message before the request reaches backend validation.
- Keep backend production data, PostgreSQL, OSS, `.env`, official version numbers, tags, and deployment untouched.

## Implementation Steps

1. Add a failing verification script for terminal accessory confirmation visibility and save gating.
2. Update `FieldGraphDesigner.vue` with selected-field hierarchy hints and a specific terminal flat-accessory issue.
3. Update `ProjectsView.vue` save-time hierarchy validation with a specific terminal accessory confirmation message.
4. Run focused Vue hierarchy verification, backend hierarchy verification, build, browser smoke, diff check, and sensitive path scan.

## Verification Commands

```powershell
node scripts/verify_vue_terminal_accessory_confirmation_gate.js
node scripts/verify_vue_device_hierarchy_config.js
node scripts/verify_vue_device_replacement_hierarchy_mode.js
node scripts/verify_vue_field_graph_hierarchy_save_gate.js
node scripts/verify_vue_replacement_hierarchy_template_apply.js
python scripts/verify_platform_device_replacement_hierarchy_mode.py
python scripts/verify_platform_single_aggregate_device_hierarchy_guard.py
pnpm --dir v2-web build
git diff --check
```
