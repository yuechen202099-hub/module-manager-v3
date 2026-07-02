# Local Work Order Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute a planned platform work-order task into local platform work-order records with idempotency and rollback, without touching production business tables, OSS, or PostgreSQL data.

**Architecture:** Add a third platform JSON store, `platform-work-orders.json`, beside existing import batch and work-order task stores. Executing a `task-*` reads preview rows from the task result, creates one local platform work-order record per planned row, updates the task status to `completed`, and records generated work-order ids. Re-executing the same task is idempotent and returns the already-created records; rollback deletes only records created by that task and marks the task `rolled_back`.

**Tech Stack:** FastAPI routes, Python platform template service, local JSON persistence, Vue 3 + Element Plus, existing frontend `ImportJob` mapping, pytest, Vite/pnpm build.

---

### Task 1: Backend Execution Contract

**Files:**
- Modify: `v2-api/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Add a test after `test_project_import_batch_creates_safe_work_order_task_record`:

```python
def test_project_work_order_task_executes_idempotently_and_rolls_back_local_records() -> None:
    project = client.post(
        "/projects",
        json={
            "name": f"Terminal Execute Work Orders {uuid4()}",
            "module_ids": ["field", "review"],
            "work_item_schema": {
                "primary_field": {"key": "terminal_no", "label": "Terminal", "source": "import", "required": True},
                "aggregate_field": {"key": "area_no", "label": "Area", "source": "import", "required": True},
                "custom_fields": [
                    {
                        "key": "communication_module_no",
                        "label": "Communication Module",
                        "data_type": "text",
                        "source": "field_collection",
                        "capture_method": "scan",
                        "required": True,
                    },
                ],
            },
        },
    )
    assert project.status_code == 200
    project_id = project.json()["data"]["id"]
    workbook = build_api_workbook(
        [
            ["Terminal", "Area", "Communication Module"],
            ["TT-EXEC-001", "Area-01", "COMM-001"],
            ["TT-EXEC-002", "Area-01", "COMM-002"],
        ]
    )
    batch = client.post(
        f"/projects/{project_id}/templates/external_completed/import-batches",
        data={"actor": "admin"},
        files={
            "file": (
                "external-completed-exec.xlsx",
                workbook,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert batch.status_code == 200, batch.text
    task = client.post(
        f"/projects/{project_id}/import-batches/{batch.json()['data']['job_id']}/work-order-tasks",
        json={"actor": "admin", "mode": "safe_record_only"},
    )
    assert task.status_code == 200, task.text
    task_id = task.json()["data"]["job_id"]

    executed = client.post(
        f"/projects/{project_id}/work-order-tasks/{task_id}/execute",
        json={"actor": "admin", "mode": "local_platform_store"},
    )

    assert executed.status_code == 200, executed.text
    payload = executed.json()["data"]
    assert payload["job_id"] == task_id
    assert payload["status"] == "completed"
    assert payload["progress"]["phase"] == "work_orders_created"
    assert payload["result"]["summary"]["created_work_orders"] == 2
    assert payload["result"]["rollback"]["strategy"] == "delete_platform_work_orders_by_task"
    created_ids = payload["result"]["created_work_order_ids"]
    assert len(created_ids) == 2
    assert created_ids[0].startswith("wo-")

    repeated = client.post(
        f"/projects/{project_id}/work-order-tasks/{task_id}/execute",
        json={"actor": "admin", "mode": "local_platform_store"},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["data"]["result"]["created_work_order_ids"] == created_ids

    rollback = client.post(
        f"/projects/{project_id}/work-order-tasks/{task_id}/rollback",
        json={"actor": "admin"},
    )
    assert rollback.status_code == 200, rollback.text
    rolled_back = rollback.json()["data"]
    assert rolled_back["status"] == "rolled_back"
    assert rolled_back["progress"]["phase"] == "work_orders_rolled_back"
    assert rolled_back["result"]["summary"]["created_work_orders"] == 0
    assert rolled_back["result"]["rollback"]["deleted_work_orders"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py::test_project_work_order_task_executes_idempotently_and_rolls_back_local_records -q
```

Expected: FAIL with `404 Not Found` because execution and rollback endpoints do not exist.

### Task 2: Backend Service And Routes

**Files:**
- Modify: `v2-api/app/services/platform/templates.py`
- Modify: `v2-api/app/api/routes/projects.py`

- [ ] **Step 1: Add local work-order store**

Add `_PLATFORM_WORK_ORDERS` and a store path helper that writes to `platform-work-orders.json`, next to the existing stores.

- [ ] **Step 2: Add execution service**

Add:

```python
def execute_import_work_order_task(project_id: str, task_id: str, actor: str = "", mode: str = "local_platform_store") -> dict[str, Any]:
    ...
```

Rules:
- allow only `local_platform_store`
- if the task is already `completed`, return it unchanged
- if the task was `rolled_back`, reject with `ValueError`
- create one `wo-*` record per preview row
- set task `status=completed`
- set `progress.phase=work_orders_created`
- set `created_work_orders` to count of local records

- [ ] **Step 3: Add rollback service**

Add:

```python
def rollback_import_work_order_task(project_id: str, task_id: str, actor: str = "") -> dict[str, Any]:
    ...
```

Rules:
- delete only work orders whose `source_task_id` equals the task id
- set task `status=rolled_back`
- set `progress.phase=work_orders_rolled_back`
- set `created_work_orders=0`
- record `deleted_work_orders`

- [ ] **Step 4: Add routes**

Add:

```python
@router.post("/{project_id}/work-order-tasks/{task_id}/execute")
def execute_import_work_order_task_route(...):
    ...

@router.post("/{project_id}/work-order-tasks/{task_id}/rollback")
def rollback_import_work_order_task_route(...):
    ...
```

### Task 3: Frontend Execution And Rollback

**Files:**
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/views/ProjectsView.vue`
- Modify: `scripts/verify_vue_work_item_schema_config.js`

- [ ] **Step 1: Add service functions**

Add:

```ts
export async function executeImportWorkOrderTask(projectId: string, taskId: string, actor = currentActor()): Promise<ImportJob>
export async function rollbackImportWorkOrderTask(projectId: string, taskId: string, actor = currentActor()): Promise<ImportJob>
```

- [ ] **Step 2: Add sequential buttons**

After `生成工单任务`, show:
- `执行创建工单`
- `回滚工单任务`

Keep them inside the same import dialog, enabled only when the task state allows the next action.

### Task 4: Verification And Report

**Files:**
- Modify: `docs/reports/pm-platform-full-flow-evaluation-2026-06-30.md`

- [ ] **Step 1: Run verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py::test_project_template_validation_report_flags_excel_issues v2-api\tests\test_api.py::test_project_template_import_draft_previews_ready_rows_with_warnings v2-api\tests\test_api.py::test_project_template_import_batch_persists_confirmed_dry_run_record v2-api\tests\test_api.py::test_project_import_batch_creates_safe_work_order_task_record v2-api\tests\test_api.py::test_project_work_order_task_executes_idempotently_and_rolls_back_local_records -q
node scripts\verify_vue_work_item_schema_config.js
pnpm --dir v2-web build
.\.venv\Scripts\python.exe scripts\verify_production_baseline.py
git status --short -- .env data v2-api/data v2-api/app/static/uploads
```

- [ ] **Step 2: Browser QA**

Open `http://127.0.0.1:52131/platform-projects`, verify:
- project page renders
- template menu still exposes download/validate
- console has no app errors or warnings

- [ ] **Step 3: Report**

Append `2026-07-01 追加：本地平台工单执行与回滚` with changed capability, verification, rollback path, and remaining risk before production database migration.
