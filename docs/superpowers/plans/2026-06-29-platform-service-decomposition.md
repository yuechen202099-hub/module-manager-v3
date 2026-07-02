# Platform Service Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the first operations-platform overview service into focused backend modules while keeping the existing `/projects` API response unchanged.

**Architecture:** Keep `app.services.platform.overview.build_replacement_project_overview()` as the public facade used by routes and frontend code. Move the actual read-model builders into focused modules: tasks, progress, delivery, field, review, risks, projects, and adapters/replacement. This is a refactor with no production data writes and no API behavior change.

**Tech Stack:** FastAPI service layer, Python 3.12, pytest.

---

## File Structure

- Create `v2-api/app/services/platform/utils.py`: shared numeric normalization helpers.
- Create `v2-api/app/services/platform/tasks.py`: task-center summary builder.
- Create `v2-api/app/services/platform/progress.py`: system/management progress and stage calculation.
- Create `v2-api/app/services/platform/delivery.py`: delivery capability summary builder.
- Create `v2-api/app/services/platform/field.py`: field construction data summary builder.
- Create `v2-api/app/services/platform/review.py`: review summary builder.
- Create `v2-api/app/services/platform/risks.py`: risk summary builder.
- Create `v2-api/app/services/platform/projects.py`: project identity and envelope builder.
- Create `v2-api/app/services/platform/adapters/__init__.py`: adapter package marker.
- Create `v2-api/app/services/platform/adapters/replacement.py`: adapter from current replacement-project repository data to platform overview.
- Modify `v2-api/app/services/platform/overview.py`: thin facade that delegates to the replacement adapter.
- Modify `v2-api/tests/test_platform_overview.py`: add module-boundary tests and keep API regression tests.

## Task 1: Add Module Boundary Tests

**Files:**
- Modify: `v2-api/tests/test_platform_overview.py`

- [ ] **Step 1: Add failing imports and focused tests**

Append tests that import these new functions:

```python
from app.services.platform.delivery import build_delivery_summary
from app.services.platform.field import build_field_summary
from app.services.platform.progress import build_progress_summary
from app.services.platform.review import build_review_summary
from app.services.platform.risks import build_risk_summary
from app.services.platform.tasks import build_task_summary
```

Add tests:

```python
def test_platform_progress_module_calculates_stage_and_progress():
    progress = build_progress_summary(groups=10, reviewed_groups=6, risk_total=5, unconstructed_groups=3, reviewing_tasks=1)
    assert progress["stage"] == "审阅中"
    assert progress["system_progress"] == 60
    assert progress["management_progress"] == 60
    assert progress["management_locked"] is False


def test_platform_summary_modules_keep_independent_boundaries():
    tasks = build_task_summary({"total": 4, "uploaded": 2, "reviewing": 1, "archived": 1, "avg_upload_rate": 0.5, "avg_review_rate": 0.6})
    field = build_field_summary(photo_rows_linked=20, unconstructed_groups=3, exception_groups=2)
    review = build_review_summary(groups=10, reviewed_groups=6, progress=60)
    risks = build_risk_summary(exception_groups=2, unconstructed_groups=3, delivery_ready=False)
    delivery = build_delivery_summary(progress=60, risk_total=risks["total"])

    assert tasks["upload_rate"] == 50
    assert field["exception_count"] == 2
    assert review["pending_groups"] == 4
    assert risks["delivery_blockers"] == 5
    assert delivery["completed_items"] == 2
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_overview.py -q
```

Expected: fails because the new platform modules do not exist.

## Task 2: Split Focused Platform Modules

**Files:**
- Create: `v2-api/app/services/platform/utils.py`
- Create: `v2-api/app/services/platform/tasks.py`
- Create: `v2-api/app/services/platform/progress.py`
- Create: `v2-api/app/services/platform/delivery.py`
- Create: `v2-api/app/services/platform/field.py`
- Create: `v2-api/app/services/platform/review.py`
- Create: `v2-api/app/services/platform/risks.py`

- [ ] **Step 1: Implement shared helpers**

Create `utils.py`:

```python
from __future__ import annotations

from typing import Any


def number(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def percent(value: float) -> int:
    return max(0, min(100, round(value * 100)))
```

- [ ] **Step 2: Implement task summary**

Create `tasks.py` with `build_task_summary(task_status: dict[str, Any]) -> dict[str, Any]`.

- [ ] **Step 3: Implement progress summary**

Create `progress.py` with `build_progress_summary(...) -> dict[str, Any]` and stage rules matching existing behavior.

- [ ] **Step 4: Implement delivery, field, review, and risks summaries**

Create the remaining summary files with one public builder per file.

- [ ] **Step 5: Run tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_overview.py -q
```

Expected: module tests pass or now fail only because `overview.py` has not delegated to the new adapter yet.

## Task 3: Add Replacement Adapter and Facade

**Files:**
- Create: `v2-api/app/services/platform/projects.py`
- Create: `v2-api/app/services/platform/adapters/__init__.py`
- Create: `v2-api/app/services/platform/adapters/replacement.py`
- Modify: `v2-api/app/services/platform/overview.py`

- [ ] **Step 1: Create project envelope builder**

Create `projects.py` with `build_project_overview(...)` accepting the focused summaries and returning the current platform overview shape.

- [ ] **Step 2: Create replacement adapter**

Create `adapters/replacement.py` with `build_replacement_project_overview(summary, task_status)`.

- [ ] **Step 3: Replace overview facade**

Change `overview.py` to import and re-export:

```python
from app.services.platform.adapters.replacement import build_replacement_project_overview

__all__ = ["build_replacement_project_overview"]
```

- [ ] **Step 4: Run regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_overview.py -q
```

Expected: all tests pass.

## Task 4: Verification and Commit

**Files:**
- Verify all modified and new backend files.

- [ ] **Step 1: Run release checks**

Run:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_release_sop.py
.\.venv\Scripts\python.exe .\scripts\verify_vue_migration_gate.py --strict-native
```

Expected: both pass.

- [ ] **Step 2: Inspect Git status**

Run:

```powershell
git status -sb
git diff --stat
```

Expected: only the new plan, platform service modules, and platform tests changed.

- [ ] **Step 3: Commit**

Run:

```powershell
git add docs/superpowers/plans/2026-06-29-platform-service-decomposition.md v2-api/app/services/platform v2-api/tests/test_platform_overview.py
git commit -m "refactor: split platform overview services"
```

Expected: commit created on `feat/operations-platform-phase-one`.

## Self-Review

- Spec coverage: covers the requested backend decomposition by separating projects, progress, tasks, delivery, field, review, risks, and adapters.
- Placeholder scan: no implementation step depends on unspecified files or future decisions.
- Type consistency: all public builders return dictionaries matching the existing API response shape, preserving frontend compatibility.
