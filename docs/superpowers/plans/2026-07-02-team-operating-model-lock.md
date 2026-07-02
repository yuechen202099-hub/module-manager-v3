# Team Operating Model Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock the PM platform multi-agent team setting into repository documentation and a repeatable guard so future context compression or thread handoff does not lose the development rhythm.

**Architecture:** Treat this as a Codex Integrator and QA work package. The team memory document is the human-readable source of truth, and `scripts/verify_pm_platform_team_operating_model.py` is the automated guard that checks required team, review, safety, and next-execution terms.

**Tech Stack:** Markdown documentation, Python guard script, existing Git safety checks.

---

## File Structure

- Create: `scripts/verify_pm_platform_team_operating_model.py`
  - Checks that the team memory document and this plan preserve the fixed team contract, subagent dispatch packet, two-stage review gate, backend/frontend split, next execution queue, and production safety boundaries.
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
  - Adds the context-stable team setting requested by the user, including visual workflow, dispatch template, review gates, split contracts, and next package queue.
- Create: `docs/superpowers/plans/2026-07-02-team-operating-model-lock.md`
  - Records the execution plan and observed red-green verification for this documentation lock.

### Task 1: Add Team Operating Guard

**Files:**
- Create: `scripts/verify_pm_platform_team_operating_model.py`

- [x] **Step 1: Write the guard script**

Create a Python script that reads `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md` and this plan, then requires these terms:

```text
Agent Dispatch Packet Template
Two-Stage Review Gate
Spec compliance review
Code quality review
Backend Team Split Contract
Frontend Team Split Contract
Next Execution Queue
No production database migration may start without explicit user approval.
no tag, no deploy, no official version bump
```

- [x] **Step 2: Run the guard before updating the document**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_pm_platform_team_operating_model.py
```

Observed RED:

```text
[FAIL] team memory missing required content: Agent Dispatch Packet Template, Two-Stage Review Gate, Spec compliance review, Code quality review, Backend Team Split Contract, Frontend Team Split Contract, Next Execution Queue, No production database migration may start without explicit user approval., no tag, no deploy, no official version bump
```

### Task 2: Lock Team Memory

**Files:**
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`

- [ ] **Step 1: Add the subagent dispatch packet template**

Add a section named `Agent Dispatch Packet Template` requiring every specialist package to declare objective, owner role, allowed files, forbidden files, baseline, verification, migration note, rollback note, and output format.

- [ ] **Step 2: Add the two-stage review gate**

Add a section named `Two-Stage Review Gate` requiring:

```text
Spec compliance review
Code quality review
```

The first review confirms product and plan fit. The second review checks implementation quality, data safety, and verification evidence.

- [ ] **Step 3: Add team split contracts**

Add `Backend Team Split Contract` and `Frontend Team Split Contract` so backend and frontend subagents know their boundaries before touching shared files.

- [ ] **Step 4: Add next execution queue**

Add `Next Execution Queue` with the currently safe order:

```text
1. Keep PR/patch handoff ready.
2. Refresh production baseline before new code work.
3. Wait for explicit user approval before Alembic or PostgreSQL migration.
4. After migration approval, add persistence-backed contract tests before production reads.
```

### Task 3: Verify And Record

**Files:**
- Verify: `scripts/verify_pm_platform_team_operating_model.py`
- Verify: `scripts/verify_pm_platform_handoff_package.py`

- [ ] **Step 1: Run the team operating guard**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_pm_platform_team_operating_model.py
```

Expected:

```text
[OK] PM platform team operating model is locked
```

- [ ] **Step 2: Run the existing handoff guard**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_pm_platform_handoff_package.py
```

Expected:

```text
[OK] PM platform PR/patch handoff package is consistent
```

- [ ] **Step 3: Check protected data paths**

Run:

```powershell
git status --short -- .env data v2-api/data v2-api/app/static/uploads uploads
```

Expected: no output.

## Self-Review

- Spec coverage: The plan records the user's requested team development setting, context recovery rule, multi-agent split, review gate, and execution order.
- Placeholder scan: No step uses TBD, TODO, or an unspecified command.
- Type consistency: The guard, plan, and team-memory section names use the same exact strings.
