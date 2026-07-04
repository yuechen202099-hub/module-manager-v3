# Create Project Field Graph Plan

Date: 2026-07-03

## Objective

Make the new-project draft dialog use the same graphical field relationship designer as the saved project field configuration dialog, so operators can see aggregate, task core, accessory device, evidence, and required-field relationships before creating a project.

## Scope

- Frontend only.
- Reuse `FieldGraphDesigner` in the create dialog.
- Keep the existing detailed field table as an advanced fallback below the visual graph.
- Do not change database schema, persistence backend, production data, OSS, version numbers, tags, or deployment.

## Behavior

- The create dialog shows a visual field graph bound to `createForm`.
- Drag/drop and selected-field edits update the create draft form.
- Template preview in the graph uses local draft field labels before the project exists.
- Template download/validation actions in the create dialog tell the operator to create the draft first.

## Verification

- `node scripts\verify_vue_project_field_graph_designer.js`
- `pnpm build`
- Browser smoke: open `/platform-projects`, click `新建项目`, confirm the field relationship graph appears in the create dialog.

## Migration Note

No migration. This package changes the frontend configuration experience only.

## Rollback Note

Remove the `FieldGraphDesigner` block from the create dialog and remove the create-dialog expectations from `scripts/verify_vue_project_field_graph_designer.js`.
