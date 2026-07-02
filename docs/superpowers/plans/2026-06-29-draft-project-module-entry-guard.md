# Draft Project Module Entry Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent draft platform projects from opening production-backed module pages until those modules have real draft adapters or empty-state pages.

**Architecture:** Keep persisted draft projects visible and selectable on the Projects page. Add a frontend entry guard in `ProjectsView.vue` so draft project module buttons show a clear "module pending access" message instead of routing to `/project-board`, `/construction`, `/task-hall`, or `/claim-tasks` with a draft `project_id`. Add a source-level verifier so future edits do not remove the guard accidentally.

**Tech Stack:** Vue 3, TypeScript, Element Plus, existing Node verification scripts, Vite build.

---

## File Structure

- Modify `v2-web/src/views/ProjectsView.vue`: guard draft project module entry and show a clear message.
- Create `scripts/verify_vue_draft_project_entry_guard.js`: verify the guard remains wired.
- Modify `scripts/verify-client-release.py`: include the new verifier as release-required project platform evidence.

## Task 1: Add Failing Guard Verifier

**Files:**
- Create: `scripts/verify_vue_draft_project_entry_guard.js`

- [ ] **Step 1: Write the failing verifier**

Create a Node script that reads `v2-web/src/views/ProjectsView.vue` and fails unless it finds:

- a draft project status branch in `openRoute`
- the message text `草稿项目模块待接入`
- no router navigation before that guard

- [ ] **Step 2: Run the verifier and confirm failure**

Run:

```powershell
node scripts\verify_vue_draft_project_entry_guard.js
```

Expected: FAIL because the guard does not exist yet.

## Task 2: Implement the Entry Guard

**Files:**
- Modify: `v2-web/src/views/ProjectsView.vue`

- [ ] **Step 1: Add guard to `openRoute`**

Before selecting the project and routing, check `project.status === 'draft'`. If true, show:

```ts
ElMessage.info('草稿项目模块待接入，先保留在项目列表中管理')
return
```

- [ ] **Step 2: Run the verifier and confirm pass**

Run:

```powershell
node scripts\verify_vue_draft_project_entry_guard.js
```

Expected: PASS.

## Task 3: Release Verification Wiring

**Files:**
- Modify: `scripts/verify-client-release.py`

- [ ] **Step 1: Require the new verifier script**

Add `scripts/verify_vue_draft_project_entry_guard.js` to the release verifier required-files list.

- [ ] **Step 2: Run release SOP verifier**

Run:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_release_sop.py
```

Expected: PASS.

## Task 4: Full Verification and Commit

**Files:**
- Verify all modified files and generated assets if build changes them.

- [ ] **Step 1: Run frontend verifier scripts**

Run:

```powershell
node scripts\verify_vue_draft_project_entry_guard.js
node scripts\verify_vue_project_module_metadata.js
node scripts\verify_vue_project_module_paths.js
```

Expected: all pass.

- [ ] **Step 2: Run focused backend and baseline checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_overview.py v2-api\tests\test_verify_production_baseline.py -q
.\.venv\Scripts\python.exe .\scripts\verify_production_baseline.py --fetch
```

Expected: all pass and current branch contains `origin/production/V3/3.0.69`.

- [ ] **Step 3: Run frontend build**

Run:

```powershell
cd v2-web
pnpm build
```

Expected: build passes. If static Vue assets change, include `v2-api/app/static/vue`.

- [ ] **Step 4: Commit**

```powershell
git add docs/superpowers/plans/2026-06-29-draft-project-module-entry-guard.md scripts/verify_vue_draft_project_entry_guard.js scripts/verify-client-release.py v2-web/src/views/ProjectsView.vue v2-api/app/static/vue
git commit -m "feat: guard draft project module entry"
```

## Self-Review

- Spec coverage: implements the next safe draft-project boundary without touching PostgreSQL, OSS, uploads, or core production business rules.
- Placeholder scan: no TBD or deferred implementation steps.
- Type consistency: uses the existing `Project.status` union and `ProjectsView.openRoute(project)` flow.
