# PM Platform Field Graph Designer Design

## Goal

Move project field configuration from a text-heavy row form toward a graphical hierarchy editor that a non-technical operations user can understand.

The first MVP must make these relationships visible and adjustable:

- Project aggregate field, such as station area or line.
- Project primary field, such as terminal, electric meter, or user.
- Child business fields under the primary or aggregate field.
- Initial import fields.
- Field construction collection fields.
- Required photo evidence.
- Platform-required KPI and traceability fields.

## Product Principle

Each project has unique business fields, but most engineering projects share a small structural pattern:

`project -> aggregate object -> primary object -> child fields and evidence`

Examples:

- Terminal replacement: station area -> terminal -> old device, communication module, SIM card, photos.
- Meter module replacement: station area -> electric meter -> module, collector, photos.
- Station area line-loss inspection: station area -> master meter and users -> inspection fields, photos, exceptions.

The user should configure the structure by looking at the field tree first, then editing details.

## MVP Scope

The first implementation stays inside the existing project field schema model.

It will not add a database migration and will not change import/export contracts. It will reuse:

- `primaryField`
- `aggregateField`
- `customFields`
- `parentKey`
- `source`
- `captureMethod`
- `dataType`
- `required`
- `kpiEnabled`

## Interface Design

Add a new component under the existing field configuration dialog:

`v2-web/src/components/project-fields/FieldGraphDesigner.vue`

The component shows:

1. A left visual hierarchy area.
2. A right selected-field details area.
3. Compact field chips grouped by role:
   - aggregate field
   - primary field
   - import fields
   - site collection fields
   - photo evidence
   - platform KPI fields

The hierarchy should start with the aggregate field at the top, then primary field, then child fields. Child fields can be reassigned by drag-and-drop to either the aggregate field or primary field. The existing row form remains below as a precision fallback for the MVP.

The selected-field details area is editable for draft projects. It updates the same reactive form fields as the row editor:

- field label
- field key
- field source
- capture method
- data type
- required flag

The graph also shows a template binding preview:

- Initial import template: primary field, aggregate field, and import-source fields.
- External completed template: initial import fields plus site collection fields and photo evidence fields.
- Site required checklist: required site-collection fields that the construction side must collect.

The preview does not create a separate construction template. It explains how the existing downloadable templates will be shaped by the field schema.

## Interaction Rules

- Draft projects can edit the field graph.
- Non-draft projects can view the graph but cannot change it.
- Primary and aggregate fields cannot be dragged or deleted in the graph.
- Custom fields can be dragged to change `parentKey`.
- Selecting a node updates the detail panel.
- Changing source, capture method, type, or required state in the graph updates the same reactive schema form used by the existing row editor.
- Adding and removing fields remains available through the existing form actions for the MVP.

## Data Flow

`ProjectsView.vue` owns the reactive `schemaForm`.

`FieldGraphDesigner.vue` receives:

- `primaryField`
- `aggregateField`
- `customFields`
- `platformRequiredFields`
- `editable`

The component emits:

- `update-parent` with `{ fieldIndex, parentKey }`
- `update-field` with `{ type, fieldIndex, updates }`

No API changes are required. Save continues through `workspace.updateProjectWorkItemSchema(project.id, buildWorkItemSchemaPayload(schemaForm))`.

## Verification

Add a frontend guard script:

`scripts/verify_vue_project_field_graph_designer.js`

It should check:

- `FieldGraphDesigner.vue` exists.
- `ProjectsView.vue` imports and renders the component.
- The component contains visual hierarchy tokens:
  - `字段关系图`
  - `聚合字段`
  - `主字段`
  - `导入字段`
  - `现场采集`
  - `照片证据`
  - `平台必备`
- The component supports drag/drop and emits `update-parent`.
- The component emits `update-field` and shows editable detail controls for selected draft fields.
- The existing save flow still calls `buildWorkItemSchemaPayload(schemaForm)`.

Run:

- `node scripts/verify_vue_project_field_graph_designer.js`
- `pnpm --dir v2-web build`
- Browser check on `/platform-projects`, open field configuration, confirm the hierarchy appears and no console error is emitted.

## Rollback

Rollback is UI-only:

1. Remove `FieldGraphDesigner.vue`.
2. Remove the import and component usage from `ProjectsView.vue`.
3. Remove `scripts/verify_vue_project_field_graph_designer.js`.
4. Keep the existing row-based field editor unchanged.

No data migration rollback is needed because the MVP writes the same field schema structure as before.
