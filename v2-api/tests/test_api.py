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
    task = tasks_response.json()["data"]["items"][0]

    claim_response = client.post(f"/local-test/tasks/{task['id']}/claim", json={"reviewer": "api-test"})
    assert claim_response.status_code == 200
    assert claim_response.json()["data"]["claimed_by"] == "api-test"

    groups_response = client.get("/local-test/groups?limit=1")
    assert groups_response.status_code == 200
    group = groups_response.json()["data"]["items"][0]

    review_response = client.patch(
        f"/local-test/groups/{group['id']}/review",
        json={"status": "approved", "reviewer": "api-test", "note": "api smoke"},
    )
    assert review_response.status_code == 200
    assert review_response.json()["data"]["status"] == "approved"
