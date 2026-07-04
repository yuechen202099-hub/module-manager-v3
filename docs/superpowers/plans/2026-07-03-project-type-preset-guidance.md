# Project Type Preset Guidance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the create-project preset selector explain the selected project type's main field, aggregate field, and replacement hierarchy before the user configures or downloads templates.

**Architecture:** Keep guidance inside `ProjectsView.vue` because it owns the create-project form and preset application. Add a static verifier, then render a compact guidance panel under the preset selector.

**Tech Stack:** Vue 3, Element Plus, Node source verifier.

---

### Task 1: Guard

**Files:**
- Create: `scripts/verify_vue_project_type_preset_guidance.js`

- [ ] **Step 1: Write failing verifier**

Require `selectedProjectTypePresetGuidance`, `.preset-hierarchy-guidance`, terminal aggregate wording, one-active-aggregate wording, and module/terminal hierarchy wording in `ProjectsView.vue`.

- [ ] **Step 2: Run verifier red**

Run: `node scripts/verify_vue_project_type_preset_guidance.js`

Expected: fails before implementation.

### Task 2: UI Implementation

**Files:**
- Modify: `v2-web/src/views/ProjectsView.vue`

- [ ] **Step 1: Add `ProjectTypePresetGuidance` type**
- [ ] **Step 2: Add `selectedProjectTypePresetGuidance` computed value**
- [ ] **Step 3: Render `.preset-hierarchy-guidance` below project type preset selector**
- [ ] **Step 4: Add compact responsive styles**

### Task 3: Verification And Docs

**Files:**
- Create: `docs/reports/pm-platform-project-type-preset-guidance-2026-07-03.md`
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

- [ ] **Step 1: Run source guards**
- [ ] **Step 2: Run frontend build**
- [ ] **Step 3: Browser smoke: choose `更换终端` and verify the guidance text**
- [ ] **Step 4: Record migration, risk, and rollback notes**
