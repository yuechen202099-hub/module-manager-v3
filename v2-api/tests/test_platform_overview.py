from app.services.platform.overview import build_replacement_project_overview
from fastapi.testclient import TestClient

from app.main import app


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
