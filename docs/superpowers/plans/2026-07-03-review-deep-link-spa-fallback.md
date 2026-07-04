# Review Deep Link SPA Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Direct browser visits to Vue review detail links such as `/review/g-001?project_id=draft-project` should load the Vue app instead of FastAPI 404.

**Architecture:** The Vue router already owns `review/:groupId`. The backend static entrypoint only needed one explicit FastAPI route that returns the same Vue production shell used by `/task-hall`, `/construction`, and `/project-board`, without widening API/static catch-all behavior.

**Tech Stack:** FastAPI static shell routing in `v2-api/app/main.py`, existing `v2-api/tests/test_api.py` Vue shell assertions, Vue 3 router in `v2-web/src/router/index.ts`.

---

### Task 1: Red Guard

**Files:**
- Modify: `v2-api/tests/test_api.py`

- [x] **Step 1: Add a failing test**

Add `test_review_detail_deep_link_serves_vue_shell` next to the existing direct workspace route tests:

```python
def test_review_detail_deep_link_serves_vue_shell() -> None:
    assert_vue_shell_response(client.get("/review/g-001?project_id=draft-project"))
```

- [x] **Step 2: Verify red**

Run:

```powershell
$env:PYTHONPATH='v2-api'; & "C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m pytest v2-api\tests\test_api.py::test_review_detail_deep_link_serves_vue_shell -q
```

Expected red result: response is `404 Not Found`.

### Task 2: Backend Fallback

**Files:**
- Modify: `v2-api/app/main.py`

- [x] **Step 1: Add the explicit review detail SPA route**

Add this route before `app.include_router(api_router)`:

```python
@app.get("/review/{group_id}")
def review_detail_page(group_id: str):
    return vue_index_response()
```

- [x] **Step 2: Verify green**

Run:

```powershell
$env:PYTHONPATH='v2-api'; & "C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m pytest v2-api\tests\test_api.py::test_review_detail_deep_link_serves_vue_shell -q
```

Expected green result: `1 passed`.

### Task 3: Regression Scope

**Files:**
- Read: `v2-web/src/components/project-fields/FieldGraphDesigner.vue`
- Read: `v2-web/src/views/ProjectsView.vue`
- Read: `scripts/verify_vue_device_replacement_hierarchy_mode.js`
- Read: `scripts/verify_platform_device_replacement_hierarchy_mode.py`

- [x] **Step 1: Verify adjacent Vue shell routes**

Run:

```powershell
$env:PYTHONPATH='v2-api'; & "C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m pytest v2-api\tests\test_api.py::test_direct_workspace_routes_redirect_to_app_shell v2-api\tests\test_api.py::test_task_hall_page_is_available v2-api\tests\test_api.py::test_construction_page_is_available -q
```

Expected result: `3 passed`.

- [x] **Step 2: Verify device replacement hierarchy rules**

Run:

```powershell
& "C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" scripts\verify_vue_device_replacement_hierarchy_mode.js
& "C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\verify_platform_device_replacement_hierarchy_mode.py
& "C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\verify_platform_device_relation_roles.py
& "C:\Users\Yuech\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe" scripts\verify_vue_field_graph_smart_drop.js
```

Expected result: all commands print `[OK]`, proving module replacement stays under the task object and terminal replacement requires main-device replacement plus accessory confirmation.
