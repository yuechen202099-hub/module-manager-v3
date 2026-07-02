# PM Platform PR Patch Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the current PM platform branch into a reviewable PR/patch handoff without touching production data, version numbers, tags, or deployment targets.

**Architecture:** Treat this as an Ops And Release work package. The branch remains on `pm-platform/project-drafts`; the handoff records the production baseline, changed-file groups, feature scope, verification evidence, risks, migration notes, rollback plan, and production safety checks.

**Tech Stack:** Git, Python guard script, existing backend pytest tests, existing Vue guard scripts, pnpm frontend build.

---

## File Structure

- Create: `scripts/verify_pm_platform_handoff_package.py`
  - Validates that the handoff report, PR body draft, team memory, and plan contain the required safety and delivery sections.
  - Checks sensitive paths are clean through Git before the handoff can be accepted.
- Create: `scripts/verify_pm_platform_team_operating_model.py`
  - Validates that the Team Operating Model Lock, agent dispatch packet, two-stage review gate, backend/frontend split, and next execution queue are preserved.
- Create: `docs/reports/pm-platform-pr-patch-handoff-2026-07-02.md`
  - Human handoff report for PR or patch review.
  - Includes baseline commit, changed-file groups, feature summary, verification evidence, risks, migration notes, rollback plan, and production safety notes.
- Create: `docs/reports/pm-platform-pr-body-2026-07-02.md`
  - Draft PR body that can be copied into GitHub when the user chooses PR creation.
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
  - Records the current team setting, current active package, and next-step queue for context recovery.

### Task 1: Confirm Baseline And Safety State

**Files:**
- Read: Git metadata
- Read: sensitive path status

- [x] **Step 1: Confirm active feature branch**

Run:

```powershell
& 'C:/Users/Yuech/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe' branch --show-current
```

Expected:

```text
pm-platform/project-drafts
```

- [x] **Step 2: Confirm baseline and current commits**

Run:

```powershell
& 'C:/Users/Yuech/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe' rev-parse HEAD
& 'C:/Users/Yuech/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe' rev-parse origin/production/V3/3.0.71
& 'C:/Users/Yuech/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe' merge-base HEAD origin/production/V3/3.0.71
& 'C:/Users/Yuech/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe' rev-parse "v3.0.71^{commit}"
```

Expected:

```text
8035f3247b5f2aaf579747fe4d71ae25fe2211e5
862659e0e6599367e7dbb164659b7ccd147c2574
862659e0e6599367e7dbb164659b7ccd147c2574
825f88092701df5ac6e3caf41b29d146f6a4d536
```

- [x] **Step 3: Confirm protected data paths are clean**

Run:

```powershell
& 'C:/Users/Yuech/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe' status --short -- .env data v2-api/data v2-api/app/static/uploads uploads
```

Expected: no output.

### Task 2: Add Handoff Guard

**Files:**
- Create: `scripts/verify_pm_platform_handoff_package.py`
- Verify: `docs/reports/pm-platform-pr-patch-handoff-2026-07-02.md`
- Verify: `docs/reports/pm-platform-pr-body-2026-07-02.md`
- Verify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

- [ ] **Step 1: Create the guard script**

Create `scripts/verify_pm_platform_handoff_package.py` with checks for required report headings, required baseline strings, required verifier names, required PR body sections, required team-memory status, and clean sensitive paths.

- [ ] **Step 2: Run the guard before creating the report**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_pm_platform_handoff_package.py
```

Expected: FAIL because the report and PR body draft do not exist yet.

### Task 3: Create PR/Patch Handoff Report

**Files:**
- Create: `docs/reports/pm-platform-pr-patch-handoff-2026-07-02.md`
- Create: `docs/reports/pm-platform-pr-body-2026-07-02.md`

- [ ] **Step 1: Write the handoff report**

The report must include these exact headings:

```markdown
## Baseline
## Changed File Groups
## Feature Summary
## Verification
## Risks
## Migration Notes
## Rollback Plan
## Production Safety
```

- [ ] **Step 2: Write the PR body draft**

The PR body must include these exact headings:

```markdown
## Summary
## Baseline
## Test Plan
## Migration / Rollback
## Risks
```

### Task 4: Verify The Package

**Files:**
- Verify: `scripts/verify_pm_platform_handoff_package.py`
- Verify: focused backend tests and frontend guards

- [ ] **Step 1: Run backend focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_contracts.py v2-api\tests\test_platform_persistence_status.py v2-api\tests\test_platform_postgres_design.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run backend guard scripts**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_platform_backend_contract_snapshot.py
.\.venv\Scripts\python.exe scripts\verify_platform_persistence_status.py
.\.venv\Scripts\python.exe scripts\verify_platform_postgres_design.py
.\.venv\Scripts\python.exe scripts\verify_pm_platform_team_operating_model.py
.\.venv\Scripts\python.exe scripts\verify_production_baseline.py
```

Expected: all scripts print `[OK]` style success output.

- [ ] **Step 3: Run frontend guard scripts**

Run:

```powershell
& 'C:/Users/Yuech/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' scripts\verify_vue_construction_checklist_consumption.js
& 'C:/Users/Yuech/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' scripts\verify_vue_project_field_graph_template_actions.js
& 'C:/Users/Yuech/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' scripts\verify_vue_project_workflow_module_toggles.js
& 'C:/Users/Yuech/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe' scripts\verify_vue_project_field_graph_designer.js
```

Expected: all scripts print `[OK]` style success output.

- [ ] **Step 4: Run frontend build**

Run:

```powershell
& 'C:/Users/Yuech/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pnpm.cmd' --dir v2-web build
```

Expected: build exits 0.

- [ ] **Step 5: Run the handoff guard**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_pm_platform_handoff_package.py
```

Expected:

```text
[OK] PM platform PR/patch handoff package is consistent
```

### Task 5: Update Team Memory

**Files:**
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

- [ ] **Step 1: Mark the active package**

Update `Team Memory Snapshot`, `Active Task Board`, and `Current execution package` so future agents know the PR/patch handoff package is prepared and the next risky step is the user-approved Alembic migration.

- [ ] **Step 2: Verify the handoff guard again**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_pm_platform_handoff_package.py
```

Expected:

```text
[OK] PM platform PR/patch handoff package is consistent
```

## Self-Review

- Spec coverage: The plan covers the requested team setting memory, production-following branch discipline, handoff report, verification evidence, migration/rollback notes, and production safety checks.
- Placeholder scan: No implementation step relies on `TBD`, `TODO`, or unspecified test commands.
- Type consistency: File names and command names are consistent across the plan, report, PR draft, and guard script.
