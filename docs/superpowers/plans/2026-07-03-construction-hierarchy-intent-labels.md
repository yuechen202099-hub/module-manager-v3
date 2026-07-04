# Construction Hierarchy Intent Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show construction operators whether each collection item is a main device, an accessory under the task object, an accessory confirmation, a conditional follow-up, or photo evidence.

**Architecture:** Reuse existing frontend schema fields: `relationRole`, `requiredWhen`, and active construction/photo slots. Add read-only intent labels in `ConstructionView.vue`; do not change collection submission rules, review status, persistence, PostgreSQL, OSS, or production data.

**Tech Stack:** Vue 3 + TypeScript + Element Plus, Node guard scripts, Vite build verification.

---

## Files

- Modify: `v2-web/src/views/ConstructionView.vue`
  - Add intent label/type helpers.
  - Show intent labels in site checklist cards.
  - Show intent labels beside construction fields and photo slots.
- Create: `scripts/verify_vue_construction_hierarchy_intent_labels.js`
  - Guard visible intent labels and helper wiring.
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
  - Record this execution package.
- Create: `docs/reports/pm-platform-construction-hierarchy-intent-labels-2026-07-03.md`
  - Summarize changes, verification, risk, and rollback.

## Tasks

### Task 1: Frontend Guard

- [ ] Create `scripts/verify_vue_construction_hierarchy_intent_labels.js`.
- [ ] Require `ConstructionView.vue` to contain:
  - `constructionCollectionIntentLabel`
  - `constructionCollectionIntentType`
  - `construction-intent-tag`
  - `施工采集意图`
  - `主设备本体`
  - `任务对象下的附属设备`
  - `附属设备确认`
  - `条件补采`
- [ ] Run the guard and confirm it fails before implementation.

### Task 2: Construction UI

- [ ] Add intent fields to `SiteChecklistItem`.
- [ ] Populate field/photo checklist items with intent labels.
- [ ] Render intent tags in both construction checklist blocks.
- [ ] Render intent tags beside field and photo role tags.
- [ ] Keep save, submit, scanner, conditional required, and missing-gap behavior unchanged.

### Task 3: Verification

- [ ] Run the new construction intent guard.
- [ ] Run existing construction hierarchy, conditional preview, required collection, and submit gap guards.
- [ ] Run `pnpm --dir v2-web build`.
- [ ] Browser-smoke `/construction?project_id=draft-project` or local construction route for the visible intent labels.
- [ ] Run `git diff --check`.
- [ ] Run sensitive path checks for `.env`, `data`, `uploads`, `v2-api/data`, and `v2-api/app/static/uploads`.

## Safety

- No production `.env`, data, uploads, OSS, PostgreSQL, migration, tag, version, release, or deployment change.
- Rollback removes the intent labels/helpers, guard script, report entry, and rebuilt Vue static assets.
