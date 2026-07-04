# Project Board Device Hierarchy Map Plan

Date: 2026-07-03
Branch: `pm-platform/production-3.0.77-sync`
Baseline: `production/V3/3.0.77` / `V3.0.77`

## Objective

Carry the configured field hierarchy into `/project-board` so the cockpit shows how a project work order is organized, not only flat KPI counts.

The visible map must distinguish:

- one active aggregate field,
- the task object and core task details,
- main-device replacement for terminal-replacement projects,
- accessory-device replacement/confirmation under the task object,
- conditional accessory follow-up fields controlled by `required_when`,
- photo evidence slots.

This preserves the business distinction:

- module replacement: replace an accessory device under one task object,
- terminal replacement: replace the main terminal and confirm whether accessory devices also change.

## Scope

Frontend:

- Refine `ProjectBoardView.vue` field hierarchy columns.
- Classify `replacement_device` as main-device replacement.
- Classify `old_device` as a main old device only when the schema also has a main `replacement_device`; otherwise keep it in the accessory layer.
- Classify `accessory_replace_confirm` and unconditional `accessory_new_device` as accessory confirmation/replacement.
- Classify `required_when` accessory fields as conditional follow-up collection.
- Show each field's parent label and conditional rule in the node.

Verification:

- Strengthen `scripts/verify_vue_project_board_field_hierarchy_map.js` first so it fails without the new hierarchy.
- Run related hierarchy guards and frontend build.
- Browser-smoke `/project-board?project_id=draft-project` with the terminal replacement demo.

## Data Safety

- No production `.env`, data, uploads, OSS object, PostgreSQL row, version number, tag, or deployment path is touched.
- Local browser validation uses the already-running development service with `STATE_BACKEND=json`.
- Frontend build regenerates local static Vue assets under `v2-api/app/static/vue`.

## Rollback

- Revert `v2-web/src/views/ProjectBoardView.vue`.
- Revert `scripts/verify_vue_project_board_field_hierarchy_map.js`.
- Rebuild frontend assets if the generated static files need to match the previous source state.
- No data rollback is required because this package is presentation-only.
