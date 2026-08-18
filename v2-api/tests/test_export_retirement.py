import pytest
from fastapi.testclient import TestClient

from app.api.routes import exports, local_test
from app.main import create_app
from app.services.export_retirement import RETIREMENT_MESSAGE, is_retired_export_path


RETIRED_PATHS = (
    "/exports",
    "/exports/terminal-readiness?page=1&page_size=20",
    "/exports/jobs",
    "/local-test/export-manifest/final-delivery",
    "/local-test/unmatched/export",
    "/local-test/photo-barcode/review-groups/export",
)
RETIRED_METHODS = ("GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE")


@pytest.mark.parametrize("method", RETIRED_METHODS)
@pytest.mark.parametrize("path", RETIRED_PATHS)
def test_retired_exports_return_410_before_auth_or_validation(method: str, path: str) -> None:
    response = TestClient(create_app()).request(method, path, content=b"{")
    assert response.status_code == 410
    if method != "HEAD":
        assert response.json() == {"detail": RETIREMENT_MESSAGE}


def test_retirement_gate_does_not_touch_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode():
        raise AssertionError("repository must not be accessed")

    monkeypatch.setattr(local_test, "state_repository", explode)
    monkeypatch.setattr(exports, "state_repository", explode)
    assert TestClient(create_app()).get("/exports/terminal-readiness").status_code == 410
    assert TestClient(create_app()).get("/local-test/unmatched/export").status_code == 410


def test_export_router_is_not_registered() -> None:
    pending = list(create_app().routes)
    registered_paths = set()
    while pending:
        route = pending.pop()
        if hasattr(route, "path"):
            registered_paths.add(route.path)
        pending.extend(getattr(route, "routes", ()))
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            pending.extend(original_router.routes)
    assert not any(path == "/exports" or path.startswith("/exports/") for path in registered_paths)


def test_nearby_non_export_route_is_not_retired() -> None:
    assert is_retired_export_path("/local-test/unmatched") is False
    assert is_retired_export_path("/project-board") is False
