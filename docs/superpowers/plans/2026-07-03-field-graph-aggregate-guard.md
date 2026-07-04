# Field Graph Aggregate Guard Plan

Date: 2026-07-03

## Context

The backend now rejects project field schemas that try to keep more than one aggregate field. The graphical field designer should show this rule before save, so operators do not discover it only after a backend 400 response.

## Scope

- Add a visible aggregate-readiness card to the field graph.
- Keep only one active aggregate slot: `aggregate_field`.
- Stop custom child fields from offering `aggregate` as a relation role.
- Add save-time validation before creating a draft project or saving draft field configuration.
- Keep this package UI-only plus source/build verification: no database, OSS, production data, version, tag, or deployment changes.

## Implementation

1. Add a red frontend verifier for aggregate guard wiring.
2. Extend `FieldGraphDesigner.vue` with aggregate guard issues and a `聚合口径` readiness card.
3. Filter relation role options so only the aggregate node can use `aggregate`.
4. Extend `ProjectsView.vue` save validation with `aggregateFieldSaveIssues`.
5. Run source guards, frontend build, browser smoke, and safety checks.

## Rollback

Revert:

- `v2-web/src/components/project-fields/FieldGraphDesigner.vue` aggregate guard changes.
- `v2-web/src/views/ProjectsView.vue` `aggregateFieldSaveIssues` changes.
- `scripts/verify_vue_field_graph_aggregate_guard.js`.

Regenerate frontend static assets from the previous build if this package has already been built. No database rollback is required.
