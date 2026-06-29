# Operations Platform Phase One Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first lightweight operations-platform layer: a real project overview API and Vue project page backed by modular backend services.

**Architecture:** Add backend platform modules around the existing replacement-project data without changing construction, review, export, OSS, or production database flows. The first module is read-only: it adapts `state_repository()` summary and task status into project progress, delivery, field, review, risk, and task-center summaries.

**Tech Stack:** FastAPI, Pydantic, existing state repository, Vue 3, TypeScript, Pinia, Element Plus, pytest, pnpm build.

---

## File Structure

- Create `v2-api/app/services/platform/__init__.py`: platform service package marker.
- Create `v2-api/app/services/platform/overview.py`: read-only adapter from existing replacement-project state to platform project overview.
- Modify `v2-api/app/api/routes/projects.py`: replace placeholder project list/detail endpoints with platform overview data.
- Modify `v2-api/tests/test_platform_overview.py`: verify platform service and `/projects` API response shape.
- Modify `v2-web/src/api/types.ts`: extend `Project` and add platform summary types.
- Modify `v2-web/src/api/services.ts`: make `fetchProjects()` call `/projects` instead of mocks.
- Modify `v2-web/src/views/ProjectsView.vue`: show real project progress, delivery, field, review, and risk summaries.

## Task 1: Backend Platform Overview Service

**Files:**
- Create: `v2-api/app/services/platform/__init__.py`
- Create: `v2-api/app/services/platform/overview.py`
- Test: `v2-api/tests/test_platform_overview.py`

- [ ] **Step 1: Write service unit tests**

Create `v2-api/tests/test_platform_overview.py` with:

```python
from app.services.platform.overview import build_replacement_project_overview


def test_build_replacement_project_overview_maps_summary_to_platform_fields():
    overview = build_replacement_project_overview(
        summary={
            "groups": 10,
            "reviewed_groups": 6,
            "exception_groups": 2,
            "unconstructed_groups": 3,
            "photo_rows_linked": 20,
        },
        task_status={
            "total": 4,
            "uploaded": 2,
            "reviewing": 1,
            "archived": 1,
            "avg_upload_rate": 0.5,
            "avg_review_rate": 0.6,
        },
    )

    assert overview["id"] == "replacement-project"
    assert overview["name"] == "更换模块项目"
    assert overview["stage"] == "施工中"
    assert overview["system_progress"] == 60
    assert overview["management_progress"] == 60
    assert overview["delivery"]["total_items"] == 4
    assert overview["field"]["exception_count"] == 2
    assert overview["review"]["reviewed_groups"] == 6
    assert overview["risks"]["total"] == 5
    assert overview["tasks"]["total"] == 4


def test_build_replacement_project_overview_marks_delivered_when_review_complete_and_no_risk():
    overview = build_replacement_project_overview(
        summary={
            "groups": 5,
            "reviewed_groups": 5,
            "exception_groups": 0,
            "unconstructed_groups": 0,
        },
        task_status={
            "total": 2,
            "uploaded": 2,
            "reviewing": 0,
            "archived": 2,
            "avg_upload_rate": 1,
            "avg_review_rate": 1,
        },
    )

    assert overview["stage"] == "待验收"
    assert overview["system_progress"] == 100
    assert overview["delivery"]["status"] == "ready"
    assert overview["risks"]["total"] == 0
```

- [ ] **Step 2: Run tests and confirm they fail**

Run: `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_overview.py -q`

Expected: fail because `app.services.platform.overview` does not exist.

- [ ] **Step 3: Add the service package**

Create `v2-api/app/services/platform/__init__.py`:

```python
"""Platform-level read models and adapters."""
```

- [ ] **Step 4: Implement platform overview adapter**

Create `v2-api/app/services/platform/overview.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _number(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _percent(value: float) -> int:
    return max(0, min(100, round(value * 100)))


def _stage(progress: int, risk_total: int, unconstructed: int, reviewing: int) -> str:
    if progress >= 100 and risk_total == 0:
        return "待验收"
    if reviewing > 0:
        return "审阅中"
    if unconstructed > 0:
        return "施工中"
    if progress > 0:
        return "交付准备"
    return "准备中"


def build_replacement_project_overview(
    *,
    summary: dict[str, Any],
    task_status: dict[str, Any],
) -> dict[str, Any]:
    groups = _number(summary.get("groups"))
    reviewed_groups = _number(summary.get("reviewed_groups"))
    exception_groups = _number(summary.get("exception_groups"))
    unconstructed_groups = _number(summary.get("unconstructed_groups"))
    photo_rows_linked = _number(summary.get("photo_rows_linked"))
    task_total = _number(task_status.get("total"))
    uploaded_tasks = _number(task_status.get("uploaded"))
    reviewing_tasks = _number(task_status.get("reviewing"))
    archived_tasks = _number(task_status.get("archived"))
    upload_rate = float(task_status.get("avg_upload_rate") or 0)
    review_rate = float(task_status.get("avg_review_rate") or 0)
    progress = _percent(reviewed_groups / groups) if groups else _percent(review_rate)
    risk_total = exception_groups + unconstructed_groups
    stage = _stage(progress, risk_total, unconstructed_groups, reviewing_tasks)
    delivery_ready = progress >= 100 and risk_total == 0

    return {
        "id": "replacement-project",
        "name": "更换模块项目",
        "status": "active",
        "stage": stage,
        "system_progress": progress,
        "management_progress": progress,
        "management_locked": False,
        "total_groups": groups,
        "completed_groups": reviewed_groups,
        "exception_groups": exception_groups,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "tasks": {
            "total": task_total,
            "uploaded": uploaded_tasks,
            "reviewing": reviewing_tasks,
            "archived": archived_tasks,
            "upload_rate": _percent(upload_rate),
            "review_rate": _percent(review_rate),
        },
        "delivery": {
            "status": "ready" if delivery_ready else "preparing",
            "total_items": 4,
            "completed_items": 4 if delivery_ready else max(0, min(3, progress // 30)),
            "latest_record": "",
        },
        "field": {
            "photo_rows_linked": photo_rows_linked,
            "unconstructed_groups": unconstructed_groups,
            "exception_count": exception_groups,
        },
        "review": {
            "reviewed_groups": reviewed_groups,
            "review_rate": progress,
            "pending_groups": max(groups - reviewed_groups, 0),
        },
        "risks": {
            "total": risk_total,
            "field_exceptions": exception_groups,
            "unconstructed_groups": unconstructed_groups,
            "delivery_blockers": 0 if delivery_ready else risk_total,
        },
    }
```

- [ ] **Step 5: Run service tests and confirm they pass**

Run: `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_overview.py -q`

Expected: `2 passed`.

## Task 2: Projects API Uses Platform Overview

**Files:**
- Modify: `v2-api/app/api/routes/projects.py`
- Test: `v2-api/tests/test_platform_overview.py`

- [ ] **Step 1: Add API tests**

Append to `v2-api/tests/test_platform_overview.py`:

```python
from fastapi.testclient import TestClient

from app.main import app


def test_projects_list_returns_replacement_platform_project():
    client = TestClient(app)
    response = client.get("/projects")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == "replacement-project"
    assert "delivery" in payload["items"][0]
    assert "risks" in payload["items"][0]


def test_project_detail_returns_platform_project():
    client = TestClient(app)
    response = client.get("/projects/replacement-project")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["id"] == "replacement-project"
    assert "tasks" in payload
```

- [ ] **Step 2: Run API tests and confirm detail route fails**

Run: `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_overview.py -q`

Expected: fail because current detail route expects `project_id: int`.

- [ ] **Step 3: Implement API route adapter**

Replace `v2-api/app/api/routes/projects.py` with:

```python
from fastapi import APIRouter, HTTPException, Request

from app.core.responses import ok
from app.schemas.project import ProjectCreate
from app.services.platform.overview import build_replacement_project_overview
from app.services.state_repository import state_repository

router = APIRouter(prefix="/projects")


def _replacement_overview():
    repository = state_repository()
    summary_payload = repository.summary()
    task_status = repository.task_status()
    return build_replacement_project_overview(
        summary=summary_payload.get("summary", {}),
        task_status=task_status,
    )


@router.get("")
def list_projects(request: Request):
    item = _replacement_overview()
    return ok(request, {"total": 1, "items": [item]})


@router.post("")
def create_project(payload: ProjectCreate, request: Request):
    return ok(request, {"id": "draft", "name": payload.name, "description": payload.description, "status": "draft"})


@router.get("/{project_id}")
def get_project(project_id: str, request: Request):
    if project_id != "replacement-project":
        raise HTTPException(status_code=404, detail="Project not found")
    return ok(request, _replacement_overview())
```

- [ ] **Step 4: Run API tests and confirm they pass**

Run: `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_overview.py -q`

Expected: `4 passed`.

## Task 3: Frontend Project Overview Integration

**Files:**
- Modify: `v2-web/src/api/types.ts`
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/views/ProjectsView.vue`

- [ ] **Step 1: Extend frontend types**

Update `Project` in `v2-web/src/api/types.ts` to include:

```ts
export type Project = {
  id: string
  name: string
  status: 'active' | 'archived'
  stage?: string
  systemProgress?: number
  managementProgress?: number
  managementLocked?: boolean
  totalGroups: number
  completedGroups: number
  exceptionGroups: number
  updatedAt: string
  tasks?: {
    total: number
    uploaded: number
    reviewing: number
    archived: number
    uploadRate: number
    reviewRate: number
  }
  delivery?: {
    status: string
    totalItems: number
    completedItems: number
    latestRecord: string
  }
  field?: {
    photoRowsLinked: number
    unconstructedGroups: number
    exceptionCount: number
  }
  review?: {
    reviewedGroups: number
    reviewRate: number
    pendingGroups: number
  }
  risks?: {
    total: number
    fieldExceptions: number
    unconstructedGroups: number
    deliveryBlockers: number
  }
}
```

- [ ] **Step 2: Map `/projects` response**

Add a backend project type and mapper in `v2-web/src/api/services.ts`:

```ts
type BackendPlatformProject = {
  id: string
  name: string
  status?: string
  stage?: string
  system_progress?: number
  management_progress?: number
  management_locked?: boolean
  total_groups?: number
  completed_groups?: number
  exception_groups?: number
  updated_at?: string
  tasks?: Project['tasks']
  delivery?: {
    status?: string
    total_items?: number
    completed_items?: number
    latest_record?: string
  }
  field?: {
    photo_rows_linked?: number
    unconstructed_groups?: number
    exception_count?: number
  }
  review?: {
    reviewed_groups?: number
    review_rate?: number
    pending_groups?: number
  }
  risks?: {
    total?: number
    field_exceptions?: number
    unconstructed_groups?: number
    delivery_blockers?: number
  }
}

function mapProject(raw: BackendPlatformProject): Project {
  return {
    id: raw.id,
    name: raw.name,
    status: raw.status === 'archived' ? 'archived' : 'active',
    stage: raw.stage || '',
    systemProgress: Number(raw.system_progress || 0),
    managementProgress: Number(raw.management_progress || 0),
    managementLocked: Boolean(raw.management_locked),
    totalGroups: Number(raw.total_groups || 0),
    completedGroups: Number(raw.completed_groups || 0),
    exceptionGroups: Number(raw.exception_groups || 0),
    updatedAt: raw.updated_at || '',
    tasks: raw.tasks,
    delivery: raw.delivery ? {
      status: raw.delivery.status || '',
      totalItems: Number(raw.delivery.total_items || 0),
      completedItems: Number(raw.delivery.completed_items || 0),
      latestRecord: raw.delivery.latest_record || '',
    } : undefined,
    field: raw.field ? {
      photoRowsLinked: Number(raw.field.photo_rows_linked || 0),
      unconstructedGroups: Number(raw.field.unconstructed_groups || 0),
      exceptionCount: Number(raw.field.exception_count || 0),
    } : undefined,
    review: raw.review ? {
      reviewedGroups: Number(raw.review.reviewed_groups || 0),
      reviewRate: Number(raw.review.review_rate || 0),
      pendingGroups: Number(raw.review.pending_groups || 0),
    } : undefined,
    risks: raw.risks ? {
      total: Number(raw.risks.total || 0),
      fieldExceptions: Number(raw.risks.field_exceptions || 0),
      unconstructedGroups: Number(raw.risks.unconstructed_groups || 0),
      deliveryBlockers: Number(raw.risks.delivery_blockers || 0),
    } : undefined,
  }
}
```

Replace `fetchProjects()` with:

```ts
export async function fetchProjects(): Promise<Project[]> {
  const data = await api<{ items: BackendPlatformProject[] }>('/projects')
  return (data.items || []).map(mapProject)
}
```

- [ ] **Step 3: Render platform fields in ProjectsView**

Update `v2-web/src/views/ProjectsView.vue` so it calls `workspace.loadProjects()` on mount and displays progress, delivery, field, review, and risk columns.

- [ ] **Step 4: Build frontend**

Run: `pnpm build`

Expected: Vue TypeScript check and Vite build pass.

## Task 4: Verification and Commit

**Files:**
- Verify all modified files.

- [ ] **Step 1: Run targeted backend tests**

Run: `.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_overview.py -q`

Expected: pass.

- [ ] **Step 2: Run release and Vue gates**

Run:

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_release_sop.py
.\.venv\Scripts\python.exe .\scripts\verify_vue_migration_gate.py --strict-native
```

Expected: both pass.

- [ ] **Step 3: Inspect Git status**

Run:

```powershell
git status -sb
git diff --stat
```

Expected: only docs, platform service, projects API, platform test, frontend project files, and regenerated Vue static assets if build was run.

- [ ] **Step 4: Commit**

Run:

```powershell
git add docs/superpowers/specs/2026-06-29-operations-platform-phase-one-design.md docs/superpowers/plans/2026-06-29-operations-platform-phase-one.md v2-api/app/services/platform v2-api/app/api/routes/projects.py v2-api/tests/test_platform_overview.py v2-web/src/api/types.ts v2-web/src/api/services.ts v2-web/src/views/ProjectsView.vue v2-api/app/static/vue
git commit -m "feat: add operations platform overview"
```

Expected: commit created on `production/v3.0.35`.
