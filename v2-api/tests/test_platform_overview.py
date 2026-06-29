from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.services.platform.adapters.replacement import build_replacement_project_overview as build_adapter_overview
from app.services.platform.catalog import (
    ProjectNotFound,
    get_project_overview,
    get_project_section,
    list_project_definitions,
)
from app.services.platform.delivery import build_delivery_summary
from app.services.platform.field import build_field_summary
from app.services.platform.overview import build_replacement_project_overview
from app.services.platform.progress import build_progress_summary
from app.services.platform.projects import build_project_overview
from app.services.platform.review import build_review_summary
from app.services.platform.risks import build_risk_summary
from app.services.platform.tasks import build_task_summary


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


def test_platform_progress_module_calculates_stage_and_progress():
    progress = build_progress_summary(
        groups=10,
        reviewed_groups=6,
        risk_total=5,
        unconstructed_groups=3,
        reviewing_tasks=1,
    )

    assert progress["stage"] == "审阅中"
    assert progress["system_progress"] == 60
    assert progress["management_progress"] == 60
    assert progress["management_locked"] is False


def test_platform_summary_modules_keep_independent_boundaries():
    tasks = build_task_summary(
        {
            "total": 4,
            "uploaded": 2,
            "reviewing": 1,
            "archived": 1,
            "avg_upload_rate": 0.5,
            "avg_review_rate": 0.6,
        }
    )
    field = build_field_summary(photo_rows_linked=20, unconstructed_groups=3, exception_groups=2)
    review = build_review_summary(groups=10, reviewed_groups=6, progress=60)
    risks = build_risk_summary(exception_groups=2, unconstructed_groups=3, delivery_ready=False)
    delivery = build_delivery_summary(progress=60, risk_total=risks["total"])

    assert tasks["upload_rate"] == 50
    assert field["exception_count"] == 2
    assert review["pending_groups"] == 4
    assert risks["delivery_blockers"] == 5
    assert delivery["completed_items"] == 2


def test_project_module_builds_overview_envelope_from_focused_summaries():
    overview = build_project_overview(
        project_id="demo-project",
        name="演示项目",
        status="active",
        progress={"stage": "施工中", "system_progress": 60, "management_progress": 60, "management_locked": False},
        total_groups=10,
        completed_groups=6,
        exception_groups=2,
        tasks={"total": 4},
        delivery={"status": "preparing"},
        field={"exception_count": 2},
        review={"pending_groups": 4},
        risks={"total": 5},
        updated_at="2026-06-29T00:00:00+00:00",
    )

    assert overview["id"] == "demo-project"
    assert overview["name"] == "演示项目"
    assert overview["stage"] == "施工中"
    assert overview["delivery"]["status"] == "preparing"
    assert overview["risks"]["total"] == 5


def test_replacement_adapter_matches_public_overview_facade():
    summary = {"groups": 5, "reviewed_groups": 5, "exception_groups": 0, "unconstructed_groups": 0}
    task_status = {"total": 2, "uploaded": 2, "reviewing": 0, "archived": 2, "avg_upload_rate": 1, "avg_review_rate": 1}

    adapter_overview = build_adapter_overview(summary=summary, task_status=task_status)
    facade_overview = build_replacement_project_overview(summary=summary, task_status=task_status)

    adapter_overview["updated_at"] = "stable"
    facade_overview["updated_at"] = "stable"
    assert adapter_overview == facade_overview


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
    assert overview["stage"] == "审阅中"
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


@pytest.mark.parametrize(
    ("section", "expected_keys"),
    [
        ("progress", {"stage", "system_progress", "management_progress", "management_locked"}),
        ("delivery", {"status", "total_items", "completed_items"}),
        ("field", {"photo_rows_linked", "unconstructed_groups", "exception_count"}),
        ("review", {"reviewed_groups", "review_rate", "pending_groups"}),
        ("risks", {"total", "field_exceptions", "delivery_blockers"}),
        ("tasks", {"total", "uploaded", "reviewing", "archived"}),
    ],
)
def test_project_module_endpoints_return_focused_sections(section, expected_keys):
    client = TestClient(app)
    response = client.get(f"/projects/replacement-project/{section}")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert set(payload).issuperset(expected_keys)


def test_project_module_endpoints_reject_unknown_project():
    client = TestClient(app)
    response = client.get("/projects/unknown-project/progress")

    assert response.status_code == 404
