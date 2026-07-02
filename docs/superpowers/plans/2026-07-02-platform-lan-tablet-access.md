# Platform LAN Tablet Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the local platform viewable from a tablet on the same LAN while keeping the default start mode local-only and production-safe.

**Architecture:** Extend the existing local PowerShell start script with an explicit host parameter. Keep `127.0.0.1` as the default, allow `0.0.0.0` only when requested, print a LAN URL for operators, and guard the script contract with a Python verification script and report.

**Tech Stack:** PowerShell local start script, Python guard script, local HTTP smoke checks.

---

### Task 1: Guard The Local Start Contract

**Files:**
- Modify: `scripts/verify_platform_local_start_script.py`
- Modify: `scripts/start-platform-local.ps1`

- [x] **Step 1: Observe RED**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_platform_local_start_script.py
```

Observed: failed because the old contract still required hard-coded `--host 127.0.0.1`.

- [x] **Step 2: Update the contract**

Require:

- default `HostAddress` is `127.0.0.1`,
- `HostAddress` is restricted to `127.0.0.1` or `0.0.0.0`,
- uvicorn uses `--host $HostAddress`,
- LAN URL is printed only when `-HostAddress 0.0.0.0` is passed,
- no OSS, PostgreSQL URL, or production branch token is embedded.

### Task 2: Validate LAN Access

**Files:**
- Modify: `scripts/start-platform-local.ps1`
- Create: `docs/reports/pm-platform-lan-tablet-access-2026-07-02.md`
- Modify: `docs/PM_PLATFORM_TEAM_DEVELOPMENT.md`
- Modify: `docs/reports/pm-platform-full-flow-evaluation-2026-06-30.md`

- [x] **Step 1: Restart in LAN mode**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-platform-local.ps1 -Port 52131 -HostAddress 0.0.0.0 -Restart
```

- [x] **Step 2: Verify local and LAN URLs**

Run:

```powershell
Invoke-WebRequest http://127.0.0.1:52131/platform-projects
Invoke-WebRequest http://192.168.50.162:52131/platform-projects
```

Observed: both returned HTTP 200 with page content.

- [x] **Step 3: Record operator instructions**

Tablet URL for this LAN session:

```text
http://192.168.50.162:52131/platform-projects
```

Safety note: use only on trusted private LAN/Wi-Fi. No production deployment or public exposure is included.
