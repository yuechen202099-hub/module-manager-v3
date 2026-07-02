# Local Work Orders Dashboard Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reflect locally executed platform work orders in project overview and module summaries so imported projects no longer look empty after execution.

**Architecture:** Reuse the existing local `platform-work-orders.json` store created by the import execution flow. Add read-only summary helpers that count work orders by `project_id`, then have draft project overviews and module sections consume those counts. This keeps local platform work orders isolated from production business tables while making the project cockpit and module APIs show real imported progress.

**Tech Stack:** FastAPI project routes, Python platform catalog/template services, local JSON persistence, pytest, existing Vue project table mappings.

---

### Task 1: Backend Overview Contract

**Files:**
- Modify: `v2-api/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Add a test after `test_project_work_order_task_executes_idempotently_and_rolls_back_local_records`:

```python
def test_project_overview_counts_local_platform_work_orders_after_execution() -> None:
    project = client.post(
        "/projects",
        json={
            "name": f"Terminal Dashboard Counts {uuid4()}",
            "module_ids": ["progress", "delivery", "field", "review", "tasks", "risks"],
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
            ["TT-DASH-001", "Area-01", "COMM-001"],
            ["TT-DASH-002", "Area-02", "COMM-002"],
        ]
    )
    batch = client.post(
        f"/projects/{project_id}/templates/external_completed/import-batches",
        data={"actor": "admin"},
        files={
            "file": (
                "external-completed-dashboard.xlsx",
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
    executed = client.post(
        f"/projects/{project_id}/work-order-tasks/{task.json()['data']['job_id']}/execute",
        json={"actor": "admin", "mode": "local_platform_store"},
    )
    assert executed.status_code == 200, executed.text

    overview = client.get(f"/projects/{project_id}")
    assert overview.status_code == 200
    data = overview.json()["data"]
    assert data["total_groups"] == 2
    assert data["completed_groups"] == 0
    assert data["tasks"]["total"] == 2
    assert data["tasks"]["uploaded"] == 0
    assert data["field"]["unconstructed_groups"] == 2
    assert data["review"]["pending_groups"] == 2
    assert data["risks"]["unconstructed_groups"] == 2
    assert data["delivery"]["total_items"] == 2

    tasks = client.get(f"/projects/{project_id}/modules/tasks")
    assert tasks.status_code == 200
    assert tasks.json()["data"]["total"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py::test_project_overview_counts_local_platform_work_orders_after_execution -q
```

Expected: FAIL because draft project overview still reports zero local platform work orders.

### Task 2: Summary Helper And Catalog Integration

**Files:**
- Modify: `v2-api/app/services/platform/templates.py`
- Modify: `v2-api/app/services/platform/catalog.py`

- [ ] **Step 1: Add read-only work-order summary helper**

Add to `templates.py`:

```python
def summarize_platform_work_orders(project_id: str) -> dict[str, int]:
    ...
```

It must load `platform-work-orders.json`, count records matching `project_id`, and return:

```python
{
    "total": total,
    "uploaded": 0,
    "reviewing": 0,
    "archived": 0,
    "completed": 0,
    "exceptions": 0,
}
```

- [ ] **Step 2: Use summary in draft overview**

Update `_build_draft_project_overview` in `catalog.py` to:
- keep zero values for projects without local work orders
- set `total_groups` from summary total
- set `delivery.total_items` from summary total
- set `field.unconstructed_groups` from summary total
- set `review.pending_groups` from summary total
- set `risks.unconstructed_groups` from summary total
- set `tasks.total` from summary total

- [ ] **Step 3: Use overview for draft module sections**

Update `get_project_section` so draft projects return the section from `get_project_overview(project_id)` instead of `_empty_sections()[section]`.

### Task 3: Verification And Report

**Files:**
- Modify: `docs/reports/pm-platform-full-flow-evaluation-2026-06-30.md`

- [ ] **Step 1: Run verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest v2-api\tests\test_api.py::test_project_template_validation_report_flags_excel_issues v2-api\tests\test_api.py::test_project_template_import_draft_previews_ready_rows_with_warnings v2-api\tests\test_api.py::test_project_template_import_batch_persists_confirmed_dry_run_record v2-api\tests\test_api.py::test_project_import_batch_creates_safe_work_order_task_record v2-api\tests\test_api.py::test_project_work_order_task_executes_idempotently_and_rolls_back_local_records v2-api\tests\test_api.py::test_project_overview_counts_local_platform_work_orders_after_execution -q
.\.venv\Scripts\python.exe scripts\verify_production_baseline.py
git status --short -- .env data v2-api/data v2-api/app/static/uploads
```

- [ ] **Step 2: Browser QA**

Open `http://127.0.0.1:52131/platform-projects`, verify:
- project page renders
- existing template menu still works
- console has no app errors or warnings

- [ ] **Step 3: Report**

Append `2026-07-01 追加：本地平台工单接入项目概览` with changed capability, verification evidence, and remaining risk before construction/review workflow integration.
