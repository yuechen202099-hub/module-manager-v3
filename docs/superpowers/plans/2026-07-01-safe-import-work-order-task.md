# Safe Import Work Order Task Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert a confirmed platform import batch into a safe, auditable work-order creation task record without creating real business work orders yet.

**Architecture:** Extend the existing platform template service with a second persisted JSON store for import execution tasks. The task is created from an existing `batch-*` record, copies the batch summary and preview rows, marks zero created work orders, and exposes an explicit rollback strategy. The project API exposes create/read endpoints, and the project page adds a single follow-on action after “确认批次记录”.

**Tech Stack:** FastAPI, Python service functions, local JSON persistence, Vue 3 + Element Plus, existing `ImportJob` frontend mapping, pytest, Vite/pnpm build.

---

### Task 1: Backend Task Contract

**Files:**
- Modify: `v2-api/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Add a test after `test_project_template_import_batch_persists_confirmed_dry_run_record`:

```python
def test_project_import_batch_creates_safe_work_order_task_record() -> None:
    project = client.post(
        "/projects",
        json={
            "name": f"Terminal Work Order Task {uuid4()}",
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
            ["TT-TASK-001", "Area-01", "COMM-001"],
            ["TT-TASK-002", "Area-01", "COMM-002"],
        ]
    )
    batch = client.post(
        f"/projects/{project_id}/templates/external_completed/import-batches",
        data={"actor": "admin"},
        files={
            "file": (
                "external-completed-task.xlsx",
                workbook,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert batch.status_code == 200, batch.text
    batch_id = batch.json()["data"]["job_id"]

    response = client.post(
        f"/projects/{project_id}/import-batches/{batch_id}/work-order-tasks",
        json={"actor": "admin", "mode": "safe_record_only"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["job_id"].startswith("task-")
    assert payload["status"] == "planned"
    assert payload["project_id"] == project_id
    assert payload["batch_id"] == batch_id
    assert payload["progress"]["phase"] == "work_order_task_planned"
    assert payload["result"]["summary"]["total_rows"] == 2
    assert payload["result"]["summary"]["planned_work_orders"] == 2
    assert payload["result"]["summary"]["created_work_orders"] == 0
    assert payload["result"]["rollback"]["strategy"] == "delete_import_work_order_task_record"
    assert payload["result"]["rollback"]["created_work_orders"] == 0
    assert payload["result"]["preview_rows"][0]["primary_value"] == "TT-TASK-001"

    persisted = client.get(f"/projects/{project_id}/work-order-tasks/{payload['job_id']}")
    assert persisted.status_code == 200
    assert persisted.json()["data"]["job_id"] == payload["job_id"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py::test_project_import_batch_creates_safe_work_order_task_record -q
```

Expected: FAIL with `404 Not Found` because the endpoint does not exist.

### Task 2: Backend Service And Routes

**Files:**
- Modify: `v2-api/app/services/platform/templates.py`
- Modify: `v2-api/app/api/routes/projects.py`

- [ ] **Step 1: Implement minimal service functions**

Add a `platform-import-work-order-tasks.json` store beside `platform-import-batches.json`. Add:

```python
def create_import_work_order_task(project_id: str, batch_id: str, actor: str = "", mode: str = "safe_record_only") -> dict[str, Any]:
    batch = get_project_template_import_batch(project_id, batch_id)
    if mode != "safe_record_only":
        raise ValueError("Only safe_record_only mode is supported")
    ...
```

The returned record must use:
- `job_id`: `task-{uuid4().hex}`
- `status`: `planned`
- `progress.phase`: `work_order_task_planned`
- `summary.planned_work_orders`: batch `ready_rows`
- `summary.created_work_orders`: `0`
- `rollback.strategy`: `delete_import_work_order_task_record`

- [ ] **Step 2: Add FastAPI endpoints**

Add:

```python
@router.post("/{project_id}/import-batches/{batch_id}/work-order-tasks")
def create_import_work_order_task_route(...):
    ...

@router.get("/{project_id}/work-order-tasks/{task_id}")
def get_import_work_order_task_route(...):
    ...
```

- [ ] **Step 3: Run backend test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py::test_project_import_batch_creates_safe_work_order_task_record -q
```

Expected: PASS.

### Task 3: Frontend Task Entry

**Files:**
- Modify: `v2-web/src/api/services.ts`
- Modify: `v2-web/src/views/ProjectsView.vue`
- Modify: `scripts/verify_vue_work_item_schema_config.js`

- [ ] **Step 1: Add API service**

Add:

```ts
export async function createImportBatchWorkOrderTask(
  projectId: string,
  batchId: string,
  actor = currentActor(),
): Promise<ImportJob> {
  const job = await api<BackendImportJob>(
    `/projects/${projectId}/import-batches/${batchId}/work-order-tasks`,
    {
      method: 'POST',
      body: JSON.stringify({ actor, mode: 'safe_record_only' }),
    },
  )
  return mapImportJob(job)
}
```

- [ ] **Step 2: Add page state and button**

In `ProjectsView.vue`, add:
- `creatingWorkOrderTask`
- `workOrderTaskJob`
- `createWorkOrderTaskFromBatch()`
- A button labeled `生成工单任务`
- A result summary showing task id, planned rows, and created work orders `0`

- [ ] **Step 3: Extend verifier**

Add checks for:
- `createImportBatchWorkOrderTask`
- `/work-order-tasks`
- `createWorkOrderTaskFromBatch`
- `workOrderTaskJob`
- `生成工单任务`

### Task 4: Verification And Report

**Files:**
- Modify: `docs/reports/pm-platform-full-flow-evaluation-2026-06-30.md`

- [ ] **Step 1: Run focused verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py::test_project_template_validation_report_flags_excel_issues v2-api\tests\test_api.py::test_project_template_import_draft_previews_ready_rows_with_warnings v2-api\tests\test_api.py::test_project_template_import_batch_persists_confirmed_dry_run_record v2-api\tests\test_api.py::test_project_import_batch_creates_safe_work_order_task_record -q
node scripts\verify_vue_work_item_schema_config.js
pnpm --dir v2-web build
.\.venv\Scripts\python.exe scripts\verify_production_baseline.py
git status --short -- .env data v2-api/data v2-api/app/static/uploads
```

- [ ] **Step 2: Browser QA**

Open `http://127.0.0.1:52131/platform-projects`, verify:
- page renders with non-empty project table
- template menu still shows download and validate actions
- browser console has no app `error` or `warn`

- [ ] **Step 3: Report**

Append a report section named `2026-07-01 追加：安全工单任务记录` with:
- changed capability
- test commands and results
- production baseline
- sensitive-path check
- rollback strategy
- remaining risk before real work-order creation
