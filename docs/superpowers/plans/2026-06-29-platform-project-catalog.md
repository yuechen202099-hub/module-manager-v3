# Platform Project Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight platform project catalog so project routes no longer hard-code `replacement-project` directly.

**Architecture:** Introduce `app.services.platform.catalog` as the read-only registry for platform project definitions and adapter dispatch. The first catalog entry remains `replacement-project` and uses the existing replacement adapter/state repository. The public API stays compatible: `/projects`, `/projects/{id}`, and module section endpoints return the same payloads, but route code asks the catalog for project data.

**Tech Stack:** FastAPI, Python 3.12, existing platform services, pytest.

---

## File Structure

- Create `v2-api/app/services/platform/catalog.py`: project definition dataclass, project list, overview loading, section loading, and `ProjectNotFound` error.
- Modify `v2-api/app/api/routes/projects.py`: delegate project lookup and section lookup to catalog.
- Modify `v2-api/tests/test_platform_overview.py`: add catalog tests and keep API behavior regression tests.

## Task 1: Add Catalog Tests

**Files:**
- Modify: `v2-api/tests/test_platform_overview.py`

- [ ] **Step 1: Add failing catalog imports and tests**

Import:

```python
import pytest

from app.services.platform.catalog import (
    ProjectNotFound,
    get_project_overview,
    get_project_section,
    list_project_definitions,
)
```

Add tests:

```python
def test_platform_catalog_lists_replacement_project_definition():
    definitions = list_project_definitions()
    assert [item["id"] for item in definitions] == ["replacement-project"]
    assert definitions[0]["name"] == "更换模块项目"
    assert definitions[0]["status"] == "active"


def test_platform_catalog_loads_project_overview_and_sections():
    overview = get_project_overview("replacement-project")
    progress = get_project_section("replacement-project", "progress")
    tasks = get_project_section("replacement-project", "tasks")

    assert overview["id"] == "replacement-project"
    assert progress["stage"] == overview["stage"]
    assert tasks["total"] == overview["tasks"]["total"]


def test_platform_catalog_rejects_unknown_project_and_section():
    with pytest.raises(ProjectNotFound):
        get_project_overview("unknown-project")
    with pytest.raises(KeyError):
        get_project_section("replacement-project", "unknown-section")
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_overview.py -q
```

Expected: fail because `app.services.platform.catalog` does not exist.

## Task 2: Implement Catalog Service

**Files:**
- Create: `v2-api/app/services/platform/catalog.py`

- [ ] **Step 1: Add project definition and error**

Create a frozen dataclass `ProjectDefinition` with `id`, `name`, `status`, and `adapter`.

- [ ] **Step 2: Register the replacement project**

Register one entry:

```python
ProjectDefinition(
    id="replacement-project",
    name="更换模块项目",
    status="active",
    adapter="replacement",
)
```

- [ ] **Step 3: Add overview and section accessors**

Implement:

```python
list_project_definitions() -> list[dict[str, str]]
get_project_overview(project_id: str) -> dict[str, Any]
get_project_section(project_id: str, section: str) -> dict[str, Any]
```

`get_project_overview()` should use `get_state_repository()` and `build_replacement_project_overview()` for the replacement adapter.

- [ ] **Step 4: Run tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_overview.py -q
```

Expected: catalog tests pass while route code is still unchanged.

## Task 3: Delegate Routes to Catalog

**Files:**
- Modify: `v2-api/app/api/routes/projects.py`

- [ ] **Step 1: Replace route helper functions**

Import `ProjectNotFound`, `get_project_overview`, `get_project_section`, and `list_project_overviews`.

- [ ] **Step 2: Update list/detail routes**

`GET /projects` should return all catalog project overviews.

`GET /projects/{project_id}` should return catalog overview.

- [ ] **Step 3: Update section routes**

Each section endpoint should call `get_project_section(project_id, section_name)`.

- [ ] **Step 4: Run tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_platform_overview.py -q
```

Expected: all tests pass and unknown projects still return 404.

## Task 4: Verification and Commit

**Files:**
- Verify all modified files.

- [ ] **Step 1: Run release gates**

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

Expected: only plan, catalog, projects route, and platform tests changed.

- [ ] **Step 3: Commit**

Run:

```powershell
git add docs/superpowers/plans/2026-06-29-platform-project-catalog.md v2-api/app/services/platform/catalog.py v2-api/app/api/routes/projects.py v2-api/tests/test_platform_overview.py
git commit -m "feat: add platform project catalog"
```

Expected: commit created on `feat/operations-platform-phase-one`.

## Self-Review

- Spec coverage: introduces the first multi-project extension point without changing runtime storage.
- Placeholder scan: no TBD or deferred behavior.
- Type consistency: catalog accessors return the existing overview and section dictionary shapes used by the frontend.
