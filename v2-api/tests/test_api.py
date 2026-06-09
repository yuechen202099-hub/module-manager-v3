from fastapi.testclient import TestClient

from app.main import create_app


client = TestClient(create_app())


def assert_success_shape(payload: dict) -> None:
    assert "data" in payload
    assert payload["error"] is None
    assert isinstance(payload["request_id"], str)


def test_health_check() -> None:
    response = client.get("/health", headers={"x-request-id": "test-request"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "test-request"
    payload = response.json()
    assert payload["data"] == {"status": "ok"}
    assert payload["request_id"] == "test-request"


def test_project_routes_return_contract_shape() -> None:
    response = client.get("/projects")

    assert response.status_code == 200
    assert_success_shape(response.json())


def test_task_claim_placeholder_uses_contract_shape() -> None:
    response = client.post("/tasks/12/claim")

    assert response.status_code == 200
    payload = response.json()
    assert_success_shape(payload)
    assert payload["data"]["task_id"] == 12
    assert payload["data"]["status"] == "claimed"


def test_validation_error_uses_contract_shape() -> None:
    response = client.get("/tasks/not-an-int")

    assert response.status_code == 422
    payload = response.json()
    assert payload["data"] is None
    assert payload["error"]["code"] == "validation_error"
    assert isinstance(payload["request_id"], str)


def test_local_test_task_and_review_flow() -> None:
    client.post("/local-test/bootstrap")

    tasks_response = client.get("/local-test/tasks")
    assert tasks_response.status_code == 200
    task = next(item for item in tasks_response.json()["data"]["items"] if item["can_claim"])

    claim_response = client.post(f"/local-test/tasks/{task['id']}/claim", json={"reviewer": "api-test"})
    assert claim_response.status_code == 200
    assert claim_response.json()["data"]["claimed_by"] == "api-test"

    groups_response = client.get(f"/local-test/tasks/{task['id']}/groups?limit=1")
    assert groups_response.status_code == 200
    group = groups_response.json()["data"]["items"][0]

    review_response = client.patch(
        f"/local-test/groups/{group['id']}/review",
        json={"status": "approved", "reviewer": "api-test", "note": "api smoke"},
    )
    assert review_response.status_code == 200
    assert review_response.json()["data"]["status"] == "approved"

    photo_group = next(item for item in client.get(f"/local-test/tasks/{task['id']}/groups").json()["data"]["items"] if item["photos"])
    photo = photo_group["photos"][0]
    category_response = client.patch(
        f"/local-test/groups/{photo_group['id']}/photos/{photo['id']}/category",
        json={"category": "collector_barcode", "reviewer": "api-test"},
    )
    assert category_response.status_code == 200
    assert category_response.json()["data"]["category"] == "collector_barcode"


def test_task_hall_page_is_available() -> None:
    response = client.get("/task-hall")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "archivePhoto" in response.text
    assert "meta-grid" in response.text
    assert "data-action=\"stash\"" in response.text
    assert "renovation_count" in response.text
    assert 'id="openImport"' in response.text
    assert 'id="csvFile"' in response.text
    assert 'id="clearScan"' not in response.text
    assert 'id="claimFilter"' not in response.text
    assert 'id="completeFilter"' not in response.text
    assert "/claim-tasks" in response.text
    assert 'id="importPayload"' in response.text
    assert 'id="syncNow"' not in response.text
    assert 'id="scanFilter"' not in response.text


def test_project_board_page_is_available() -> None:
    response = client.get("/project-board")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "taskRows" in response.text
    assert "donutArc" in response.text
    assert "progressCarousel" in response.text
    assert "table-scroll" in response.text
    assert "/unmatched" in response.text
    assert "/claim-tasks?embedded=1" in response.text
    assert "totalRows" in response.text
    assert "stageRows" in response.text


def test_claim_tasks_page_is_available() -> None:
    response = client.get("/claim-tasks")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "claimedCount" in response.text
    assert "/local-test/tasks" in response.text


def test_unmatched_page_is_available() -> None:
    response = client.get("/unmatched")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "associateRecord" in response.text
    assert "/local-test/unmatched" in response.text


def test_catalog_routes_are_filterable() -> None:
    client.post("/local-test/bootstrap")

    response = client.get("/local-test/catalog/total?limit=5")
    filtered = client.get("/local-test/catalog/stage?query=350&limit=5")

    assert response.status_code == 200
    assert response.json()["data"]["total"] > 0
    assert len(response.json()["data"]["items"]) <= 5
    assert filtered.status_code == 200
    assert "items" in filtered.json()["data"]


def test_sync_config_page_is_available() -> None:
    response = client.get("/sync-config")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'id="payload"' in response.text


def test_clear_scan_data_route_resets_local_scan_state() -> None:
    client.post("/local-test/bootstrap")

    response = client.post("/local-test/scan/clear")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["summary"]["scan_rows"] == 0
    assert payload["summary"]["downloaded_photos"] == 0
    assert payload["summary"]["unclassified_photos"] == 0


def test_url_row_import_route_updates_local_tasks() -> None:
    client.post("/local-test/bootstrap")
    first_group = client.get("/local-test/groups?limit=1").json()["data"]["items"][0]
    client.post("/local-test/scan/clear")

    response = client.post(
        "/local-test/scan/import-url-rows",
        json={
            "rows": [
                {
                    "meter_no": first_group["meter_no"],
                    "terminal": first_group["terminal"],
                    "collector": "C-001",
                    "module_asset_no": "M-001",
                    "photo_urls": "https://example.test/1.jpg,https://example.test/2.jpg",
                }
            ]
        },
    )
    tasks = client.get("/local-test/tasks").json()["data"]["items"]

    assert response.status_code == 200
    assert response.json()["data"]["applied_records"] == 2
    assert any(task["can_claim"] for task in tasks)
