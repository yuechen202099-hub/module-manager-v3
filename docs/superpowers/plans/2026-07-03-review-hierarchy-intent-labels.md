# Review Hierarchy Intent Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the review workbench show the same device hierarchy intent labels that construction uses, so reviewers can distinguish main-device evidence, accessory evidence, accessory replacement confirmation, conditional follow-up evidence, photo evidence, and KPI evidence.

**Architecture:** Keep the existing review hierarchy sections and add a small intent-label layer in both `ReviewView.vue` and the actual menu-facing `TaskHallView.vue`. The label helper maps existing `relationRole`, `requiredWhen`, and KPI-like keys to reviewer-facing labels; templates render Element Plus tags beside the existing role tags.

**Tech Stack:** Vue 3, TypeScript, Element Plus, Node-based static guard scripts, Vite build.

---

### Task 1: Add Review Intent Guard

**Files:**
- Create: `scripts/verify_vue_review_hierarchy_intent_labels.js`

- [x] **Step 1: Write the failing guard**

The guard reads `v2-web/src/views/ReviewView.vue` and requires these tokens: `function reviewEvidenceIntentLabel`, `function reviewEvidenceIntentType`, `platform-review-intent-tag`, `审阅证据意图`, `主设备本体`, `任务对象下的附属设备`, `附属设备确认`, `条件补采`, `照片证据`, `KPI资料`, and field/photo template usages.

- [x] **Step 2: Run guard to verify it fails**

Run: `node scripts\verify_vue_review_hierarchy_intent_labels.js`

Expected: `[FAIL] review view must compute evidence intent labels`

### Task 2: Render Review Intent Labels

**Files:**
- Modify: `v2-web/src/views/ReviewView.vue`
- Modify: `v2-web/src/views/TaskHallView.vue`

- [x] **Step 1: Add helper functions**

Add `reviewEvidenceIntentLabel()` / `reviewEvidenceIntentType()` and `platformReviewEvidenceIntentLabel()` / `platformReviewEvidenceIntentType()` near the existing relation-role helpers. Map `replacement_device` to `主设备本体`, `old_device` and `accessory_new_device` to `任务对象下的附属设备`, `accessory_replace_confirm` to `附属设备确认`, `evidence_photo` to `照片证据`, conditional `requiredWhen` items to `条件补采`, and KPI-like supporting keys to `KPI资料`.

- [x] **Step 2: Render the tag on field rows**

Add an `ElTag` with `class="platform-review-intent-tag"` and `title="审阅证据意图"` after the existing role tag in both review surfaces.

- [x] **Step 3: Render the tag on photo rows**

Add the same tag after the photo slot role tag, using `slot` as the helper argument in both review surfaces.

- [x] **Step 4: Add focused styling**

Add `.platform-review-intent-tag` beside `.platform-review-role-tag` styling in both review surfaces.

### Task 3: Document And Verify

**Files:**
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Create: `docs/reports/pm-platform-review-hierarchy-intent-labels-2026-07-03.md`

- [x] **Step 1: Run focused guards**

Run:

```powershell
node scripts\verify_vue_review_hierarchy_intent_labels.js
node scripts\verify_vue_review_hierarchy_sections.js
node scripts\verify_vue_review_required_evidence_gate.js
```

Expected: all print `[OK]`.

- [x] **Step 2: Run frontend build**

Run: `pnpm --dir v2-web build`

Expected: build exits `0`.

- [x] **Step 3: Browser smoke**

Open `/review?project_id=draft-project` on the local preview server, select a platform review work order, and verify visible tags include `主设备本体`, `任务对象下的附属设备`, `附属设备确认`, `条件补采`, `照片证据`, and `KPI资料` when the selected work order includes KPI evidence.

- [x] **Step 4: Safety checks**

Run `git diff --check` and `git status --short -- .env data uploads v2-api/data v2-api/app/static/uploads`.
