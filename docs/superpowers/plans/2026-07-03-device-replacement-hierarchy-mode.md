# Device Replacement Hierarchy Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make device replacement hierarchy modes explicit so module replacement is shown as accessory replacement under the task object, while terminal replacement is shown as main-device replacement with accessory replacement confirmation.

**Architecture:** Reuse existing `relationRole`, `parentKey`, and `requiredWhen` schema fields. Add read-only hierarchy mode summaries in the field graph and readiness evidence; do not add persistence, migrations, archive writes, or production data changes.

**Tech Stack:** Vue 3 + TypeScript + Element Plus frontend, FastAPI platform readiness service, Node/Python guard scripts.

---

## Files

- Modify: `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
  - Add hierarchy mode classification and cards.
  - Show module replacement and terminal replacement semantics as explicit visual rules.
- Modify: `v2-api/app/services/platform/readiness.py`
  - Add readiness evidence fields for replacement hierarchy mode.
  - Keep existing blocker logic compatible.
- Create: `scripts/verify_vue_device_replacement_hierarchy_mode.js`
  - Guard frontend mode cards and labels.
- Create: `scripts/verify_platform_device_replacement_hierarchy_mode.py`
  - Guard backend readiness evidence for module and terminal modes.
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
  - Record this execution package.
- Create: `docs/reports/pm-platform-device-replacement-hierarchy-mode-2026-07-03.md`
  - Summarize changes, verification, risk, and rollback.

## Tasks

### Task 1: Frontend Guard

- [ ] Create `scripts/verify_vue_device_replacement_hierarchy_mode.js`.
- [ ] Require `FieldGraphDesigner.vue` to contain:
  - `replacementHierarchyModeCards`
  - `deviceReplacementHierarchyMode`
  - `accessory_under_task_object`
  - `main_device_with_accessory_confirmation`
  - `任务对象下更换附属设备`
  - `主设备更换后确认附属设备`
  - `更换层级`
  - `field-replacement-mode-cards`
- [ ] Run the guard and confirm it fails before frontend implementation.

### Task 2: Backend Guard

- [ ] Create `scripts/verify_platform_device_replacement_hierarchy_mode.py`.
- [ ] Build one module-style schema with `accessory_new_device` under `meter_no` and no `replacement_device`.
- [ ] Build one terminal-style schema with `replacement_device`, `old_device`, and `accessory_replace_confirm` under `terminal_no`.
- [ ] Assert readiness evidence returns:
  - `replacement_hierarchy_mode = accessory_under_task_object` for module replacement.
  - `replacement_hierarchy_mode = main_device_with_accessory_confirmation` for terminal replacement.
  - `requires_accessory_confirmation = true` for terminal replacement.
- [ ] Run the guard and confirm it fails before backend implementation.

### Task 3: Frontend Implementation

- [ ] Add `deviceReplacementHierarchyMode()` to classify schemas from existing field roles.
- [ ] Add `replacementHierarchyModeCards` computed values.
- [ ] Render compact mode cards above existing relationship summary.
- [ ] Keep existing drag/drop behavior unchanged.
- [ ] Run the frontend guard and existing field graph guards.

### Task 4: Backend Implementation

- [ ] Add `_device_replacement_hierarchy_mode()` to `readiness.py`.
- [ ] Include mode evidence inside `_device_hierarchy_check()`.
- [ ] Keep existing failed-action behavior unchanged.
- [ ] Run the backend guard and existing readiness guards.

### Task 5: Verification And Handoff

- [ ] Run focused frontend/backend guard scripts.
- [ ] Run `pnpm --dir v2-web build`.
- [ ] Refresh the local browser preview and verify the hierarchy mode labels are visible.
- [ ] Run `git diff --check`.
- [ ] Run sensitive path status check for `.env`, `data`, `uploads`, `v2-api/data`, and `v2-api/app/static/uploads`.
- [ ] Update team development log and write the report.

## Safety

- No `.env`, `data`, `uploads`, OSS, PostgreSQL, tag, official version, or deployment change.
- No migration and no production data write.
- Rollback is removing the mode cards, readiness evidence additions, guard scripts, report row, and rebuilt static assets.
