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

