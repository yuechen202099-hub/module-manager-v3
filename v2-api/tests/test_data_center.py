from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.routes import groups as group_routes
from app.main import create_app
from app.services import local_simulation
from app.services import state_repository as repository


client = TestClient(create_app())


def admin_headers() -> dict[str, str]:
    login = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    assert login.status_code == 200
    return {"Authorization": f"bearer {login.json()['data']['access_token']}"}


class RecordingRepository:
    def __init__(self) -> None:
        self.queries = []

    def list_data_center_rows(self, query):
        self.queries.append(query)
        return {
            "total": 0,
            "page": query.page,
            "page_size": query.page_size,
            "items": [],
        }

    def get_data_center_detail(self, *, kind: str, item_id: str):
        return {
            "kind": kind,
            "id": item_id,
            "photos": [{"id": "photo-1", "image_url": "https://example.test/photo.jpg"}],
            "audit": [{"action": "seed"}],
        }


@pytest.mark.parametrize("page_size", [20, 50, 100])
def test_data_center_accepts_supported_page_sizes(monkeypatch: pytest.MonkeyPatch, page_size: int) -> None:
    repo = RecordingRepository()
    monkeypatch.setattr(group_routes, "state_repository", lambda: repo)

    response = client.get(f"/groups/data-center?page=1&page_size={page_size}", headers=admin_headers())

    assert response.status_code == 200
    assert response.json()["data"]["page_size"] == page_size
    assert repo.queries[-1].page_size == page_size


@pytest.mark.parametrize("page_size", [1, 19, 21, 99, 101, 200])
def test_data_center_rejects_unsupported_page_sizes(monkeypatch: pytest.MonkeyPatch, page_size: int) -> None:
    monkeypatch.setattr(group_routes, "state_repository", lambda: RecordingRepository())

    response = client.get(f"/groups/data-center?page_size={page_size}", headers=admin_headers())

    assert response.status_code == 422


def test_data_center_route_requires_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(group_routes, "state_repository", lambda: RecordingRepository())

    assert client.get("/groups/data-center").status_code == 401


def _group(
    index: int,
    *,
    status: str = "approved",
    archive_status: str = "archived",
    barcode_status: str = "passed",
    installer: str = "张三",
    terminal: str = "T-01",
    updated_at: str | None = None,
) -> dict:
    updated = updated_at or (datetime(2026, 7, 23, 10, 0, tzinfo=UTC) + timedelta(minutes=index)).isoformat()
    categories = ["before_box", "module_meter", "after_box", "collector_barcode"]
    return {
        "id": f"group-{index:03d}",
        "task_id": index,
        "terminal": terminal,
        "meter_no": f"000123-{index:03d}",
        "meter_match_key": f"123-{index:03d}",
        "address": f"Address {index}",
        "status": status,
        "archive_status": archive_status,
        "installer": installer,
        "collector": f"C-{index:03d}",
        "module_asset_no": f"M-{index:03d}",
        "construction_collector": f"CC-{index:03d}",
        "construction_module_asset_no": f"CM-{index:03d}",
        "updated_at": updated,
        "barcode_verification": {
            "status": barcode_status,
            "result": {"missing_fields": [] if barcode_status == "passed" else ["module"]},
        },
        "photos": [
            {
                "id": f"group-{index:03d}-photo-{slot}",
                "category": category,
                "image_url": f"https://example.test/signed/{index}/{slot}.jpg?token=secret",
                "ocr_candidates": ["hidden"],
                "binary_content": "hidden",
                "is_active": True,
            }
            for slot, category in enumerate(categories, start=1)
        ],
    }


def test_json_data_center_combines_filters_with_stable_server_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.schemas.data_center import DataCenterQuery

    team_id = f"data-center-json-{uuid4()}"
    state = local_simulation.blank_state(team_id)
    matches = [_group(index, updated_at="2026-07-23T10:00:00+00:00") for index in range(1, 23)]
    state["groups"] = [
        *matches,
        _group(100, status="pending"),
        _group(101, archive_status="pending"),
        _group(102, barcode_status="unreadable"),
        _group(103, installer="李四"),
    ]
    monkeypatch.setitem(local_simulation._team_states, team_id, state)
    monkeypatch.setattr(local_simulation, "current_team_id", lambda: team_id)

    page = repository.JsonStateRepository().list_data_center_rows(
        DataCenterQuery(
            data_type="group",
            construction_status="completed",
            archive_status="archived",
            barcode_status="passed",
            classification_status="complete",
            installer="张三",
            query="000123",
            page=2,
            page_size=20,
            sort="updated_desc",
        )
    )

    assert page["total"] == 22
    assert len(page["items"]) == 2
    assert [row["id"] for row in page["items"]] == ["group-002", "group-001"]


def test_data_center_list_is_lightweight_and_detail_is_lazy_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.schemas.data_center import DataCenterQuery

    team_id = f"data-center-detail-{uuid4()}"
    state = local_simulation.blank_state(team_id)
    state["groups"] = [_group(1)]
    state["audit_events"] = [{"entity_type": "group", "entity_id": "group-001", "action": "seed"}]
    monkeypatch.setitem(local_simulation._team_states, team_id, state)
    monkeypatch.setattr(local_simulation, "current_team_id", lambda: team_id)
    repo = repository.JsonStateRepository()

    page = repo.list_data_center_rows(DataCenterQuery(data_type="group", page=1, page_size=20))
    row = page["items"][0]

    assert "photos" not in row
    assert "image_url" not in row
    assert "ocr_candidates" not in row
    assert "binary_content" not in row
    assert row["photo_count"] == 4

    detail = repo.get_data_center_detail(kind="group", item_id="group-001")
    assert detail is not None
    assert [photo["id"] for photo in detail["photos"]] == [
        "group-001-photo-1",
        "group-001-photo-2",
        "group-001-photo-3",
        "group-001-photo-4",
    ]
    assert detail["audit"] == [{"entity_type": "group", "entity_id": "group-001", "action": "seed"}]


def test_postgres_data_center_uses_count_and_bounded_stable_row_query(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.schemas.data_center import DataCenterQuery

    class ScalarResult:
        def __init__(self, values):
            self._values = values

        def all(self):
            return self._values

    class RecordingSession:
        def __init__(self):
            self.statements = []

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def scalar(self, statement):
            self.statements.append(statement)
            return 0

        def execute(self, statement):
            self.statements.append(statement)
            return ScalarResult([])

    session = RecordingSession()
    repo = repository.PostgresStateRepository()
    monkeypatch.setattr(repo, "_session", lambda: session)
    monkeypatch.setattr(local_simulation, "current_team_id", lambda: "demo-team")

    page = repo.list_data_center_rows(DataCenterQuery(page=2, page_size=50, sort="updated_desc"))

    assert page["total"] == 0
    assert len(session.statements) == 2
    compiled = [
        str(statement.compile(compile_kwargs={"literal_binds": True})).lower()
        for statement in session.statements
    ]
    assert "count" in compiled[0]
    assert "limit 50" in compiled[1]
    assert "offset 50" in compiled[1]
    assert "order by" in compiled[1]
    assert "updated_at desc" in compiled[1]
    assert "legacy_id desc" in compiled[1] or "material_groups.id desc" in compiled[1]
