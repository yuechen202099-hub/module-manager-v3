# Platform Production 3.0.77 Sync Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare the platform branch to follow `production/V3/3.0.77` without overwriting the current uncommitted platform work.

**Architecture:** Treat the current dirty worktree as authoritative WIP. Do not merge into it directly. First record production drift, dirty overlap, merge-tree conflict evidence, and a safe next-step sequence for snapshot, isolated sync, conflict resolution, rebuild, and verification.

**Tech Stack:** Git read-only inspection, existing production baseline verifier, handoff package verifier, documentation guard.

---

### Task 1: Confirm Production Drift

**Files:**
- Create: `docs/reports/pm-platform-production-3.0.77-sync-readiness-2026-07-02.md`
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Modify: `docs/reports/pm-platform-pr-patch-handoff-2026-07-02.md`
- Modify: `scripts/verify_pm_platform_handoff_package.py`

- [x] **Step 1: Fetch and inspect latest production**

Observed `origin/production/V3/3.0.77` at `4c05cc92a71e08a7eb5da6a25cef654271b4cfc5`.

- [x] **Step 2: Run production baseline verifier**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_production_baseline.py
```

Observed failure:

```text
[FAIL] Current ref HEAD does not contain production ref origin/production/V3/3.0.77 (4c05cc92a71e)
```

### Task 2: Measure Merge Risk

- [x] **Step 1: Count changed and overlapping paths**

Observed:

```text
production_changed=145
dirty=192
overlap=43
```

- [x] **Step 2: Identify hotspot overlap**

Hotspots include:

- `v2-api/app/api/routes/projects.py`
- `v2-web/src/api/services.ts`
- `v2-web/src/api/types.ts`
- `v2-web/src/views/ProjectsView.vue`
- generated Vue static assets

- [x] **Step 3: Preview merge conflicts**

`git merge-tree` reports `changed in both` for backend route/config/service files and frontend API/view files, plus generated asset churn.

### Task 3: Record Safe Sync Path

- [x] **Step 1: Do not merge into dirty worktree**

Decision: do not run `git merge` or `git rebase` in the current dirty worktree until WIP is protected.

- [x] **Step 2: Define next execution sequence**

1. Create a reviewable WIP snapshot or patch that excludes `.env`, `data`, uploads, dumps, secrets, and production artifacts.
2. Create an isolated sync workspace or clean branch based on `production/V3/3.0.77`.
3. Re-apply platform changes in controlled packages.
4. Resolve production security hardening conflicts first.
5. Rebuild Vue static assets from source after conflict resolution.
6. Rerun production baseline, focused backend/frontend guards, browser smoke, and sensitive-path checks.
