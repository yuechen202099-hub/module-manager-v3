from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.routes import groups as group_routes
from app.main import create_app
from app.models import GroupStatus, PhotoUploadStatus
from app.services import data_center as data_center_service
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
    categories: list[str] | None = None,
) -> dict:
    updated = (
        updated_at
        if updated_at is not None
        else (datetime(2026, 7, 23, 10, 0, tzinfo=UTC) + timedelta(minutes=index)).isoformat()
    )
    resolved_categories = categories or ["before_box", "module_meter", "after_box", "collector_barcode"]
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
                "archive_status": archive_status,
                "image_url": f"https://example.test/signed/{index}/{slot}.jpg?token=secret",
                "ocr_candidates": ["hidden"],
                "binary_content": "hidden",
                "is_active": True,
            }
            for slot, category in enumerate(resolved_categories, start=1)
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
    assert "nulls last" in compiled[1]
    assert "legacy_id desc" in compiled[1] or "material_groups.id desc" in compiled[1]


def test_json_data_center_updated_sort_keeps_empty_times_last() -> None:
    from app.schemas.data_center import DataCenterQuery

    rows = [
        data_center_service.group_row(_group(1, updated_at="")),
        data_center_service.group_row(_group(2, updated_at="2026-07-23T10:00:00+00:00")),
        data_center_service.group_row(_group(3, updated_at="2026-07-23T11:00:00+00:00")),
    ]

    desc = data_center_service.page_rows(rows, DataCenterQuery(data_type="group", sort="updated_desc"))["items"]
    asc = data_center_service.page_rows(rows, DataCenterQuery(data_type="group", sort="updated_asc"))["items"]

    assert [row["id"] for row in desc] == ["group-003", "group-002", "group-001"]
    assert [row["id"] for row in asc] == ["group-002", "group-003", "group-001"]


def test_json_data_center_bounded_selection_keeps_only_requested_window() -> None:
    from app.schemas.data_center import DataCenterQuery

    retained_sizes: list[int] = []
    query = DataCenterQuery(data_type="group", page=3, page_size=20, sort="updated_desc")

    page = data_center_service.select_bounded_page(
        (_group(index) for index in range(1, 1001)),
        query,
        data_center_service.group_row,
        on_retained_size=retained_sizes.append,
    )

    assert page["total"] == 1000
    assert len(page["items"]) == 20
    assert max(retained_sizes) <= 60
    assert [row["id"] for row in page["items"][:3]] == ["group-960", "group-959", "group-958"]


def test_postgres_data_center_sql_uses_active_photo_archive_and_required_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    repo.list_data_center_rows(
        DataCenterQuery(
            data_type="group",
            archive_status="archived",
            classification_status="complete",
            sort="updated_asc",
        )
    )

    compiled = " ".join(
        str(statement.compile(compile_kwargs={"literal_binds": True})).lower()
        for statement in session.statements
    )
    assert "photos.archive_status" in compiled
    assert "photos.category" in compiled
    assert "photo_count >= 4" not in compiled
    assert "raw_data ->> 'archive_status'" not in compiled
    assert "nulls last" in compiled


def test_postgres_data_center_row_mapping_preserves_sql_derived_statuses() -> None:
    row = repository.PostgresStateRepository._data_center_row_from_mapping(
        {
            "kind": "group",
            "legacy_id": "sql-derived-001",
            "terminal": "T-01",
            "meter_no": "M-001",
            "meter_match_key": "001",
            "address": "Address",
            "collector": "C-001",
            "module_asset_no": "MOD-001",
            "construction_collector": "CC-001",
            "construction_module_asset_no": "CM-001",
            "installer": "installer-a",
            "photo_count": 4,
            "classification_status": "complete",
            "construction_status": "completed",
            "archive_status": "archived",
            "barcode_status": "passed",
            "exception_status": "",
            "updated_at": "2026-07-23T10:00:00+00:00",
            "raw_data": {},
        }
    )

    assert row["classification_status"] == "complete"
    assert row["archive_status"] == "archived"


def test_postgres_data_center_row_mapping_uses_authoritative_sql_barcode_status() -> None:
    row = repository.PostgresStateRepository._data_center_row_from_mapping(
        {
            "kind": "group",
            "legacy_id": "sql-barcode-001",
            "terminal": "T-01",
            "meter_no": "M-001",
            "meter_match_key": "001",
            "address": "Address",
            "collector": "C-001",
            "module_asset_no": "MOD-001",
            "construction_collector": "CC-001",
            "construction_module_asset_no": "CM-001",
            "installer": "installer-a",
            "photo_count": 4,
            "classification_status": "complete",
            "construction_status": "completed",
            "archive_status": "archived",
            "barcode_status": "ineligible",
            "exception_status": "",
            "updated_at": "2026-07-23T10:00:00+00:00",
            "raw_data": {
                "barcode_verification": {"status": "passed", "result": {"missing_fields": []}},
                "group_barcode_check_status": "passed",
            },
        }
    )

    assert row["barcode_status"] == "ineligible"
    assert row["barcode_progress"]["status"] == "ineligible"


def test_postgres_data_center_list_filters_counts_and_returns_authoritative_barcode_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            return 1

        def execute(self, statement):
            self.statements.append(statement)
            return ScalarResult(
                [
                    {
                        "kind": "group",
                        "legacy_id": "sql-barcode-001",
                        "terminal": "T-01",
                        "meter_no": "M-001",
                        "meter_match_key": "001",
                        "address": "Address",
                        "collector": "C-001",
                        "module_asset_no": "MOD-001",
                        "construction_collector": "CC-001",
                        "construction_module_asset_no": "CM-001",
                        "installer": "installer-a",
                        "photo_count": 4,
                        "classification_status": "complete",
                        "construction_status": "completed",
                        "archive_status": "archived",
                        "barcode_status": "ineligible",
                        "exception_status": "",
                        "updated_at": "2026-07-23T10:00:00+00:00",
                        "raw_data": {
                            "barcode_verification": {"status": "passed", "result": {"missing_fields": []}},
                            "group_barcode_check_status": "passed",
                        },
                    }
                ]
            )

    session = RecordingSession()
    repo = repository.PostgresStateRepository()
    monkeypatch.setattr(repo, "_session", lambda: session)
    monkeypatch.setattr(local_simulation, "current_team_id", lambda: "demo-team")

    page = repo.list_data_center_rows(DataCenterQuery(data_type="group", barcode_status="ineligible"))

    compiled = [
        str(statement.compile(compile_kwargs={"literal_binds": True})).lower()
        for statement in session.statements
    ]
    assert "data_center_rows.barcode_status = 'ineligible'" in compiled[0]
    assert "data_center_rows.barcode_status = 'ineligible'" in compiled[1]
    assert page["total"] == 1
    assert page["items"][0]["barcode_status"] == "ineligible"


def test_postgres_data_center_detail_derives_statuses_after_loading_photos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id = uuid4()
    group = _model_group(group_id, legacy_id="detail-001", photo_count=4)
    photos = [
        _model_photo(group_id, "p1", "before_box", "archived"),
        _model_photo(group_id, "p2", "before_box", "archived"),
        _model_photo(group_id, "p3", "before_box", "archived"),
        _model_photo(group_id, "p4", "before_box", "pending"),
    ]

    class ScalarRows:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

    class DetailSession:
        def __init__(self):
            self.scalar_calls = 0
            self.scalars_calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def get(self, *_args, **_kwargs):
            return None

        def scalar(self, *_args, **_kwargs):
            self.scalar_calls += 1
            return group if self.scalar_calls == 1 else None

        def scalars(self, *_args, **_kwargs):
            self.scalars_calls += 1
            return ScalarRows(photos if self.scalars_calls == 1 else [])

    repo = repository.PostgresStateRepository()
    monkeypatch.setattr(repo, "_session", lambda: DetailSession())
    monkeypatch.setattr(local_simulation, "current_team_id", lambda: "demo-team")

    detail = repo.get_data_center_detail(kind="group", item_id="detail-001")

    assert detail is not None
    assert detail["classification_status"] == "incomplete"
    assert detail["archive_status"] == "pending"
    assert len(detail["photos"]) == 4


def test_postgres_data_center_detail_excludes_invalid_upload_photos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_id = uuid4()
    group = _model_group(group_id, legacy_id="detail-valid-photos", photo_count=5)
    photos = [
        _model_photo(group_id, "p1", "before_box", "archived"),
        _model_photo(group_id, "p2", "module_meter", "archived"),
        _model_photo(group_id, "p3", "after_box", "archived"),
        _model_photo(group_id, "p4", "collector_barcode", "archived"),
        _model_photo(group_id, "p5", "before_box", "pending", upload_status=PhotoUploadStatus.INVALID),
    ]

    class ScalarRows:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

    class DetailSession:
        def __init__(self):
            self.scalar_calls = 0
            self.scalars_calls = 0
            self.photo_statements = []

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def get(self, *_args, **_kwargs):
            return None

        def scalar(self, *_args, **_kwargs):
            self.scalar_calls += 1
            return group if self.scalar_calls == 1 else None

        def scalars(self, statement, *_args, **_kwargs):
            self.scalars_calls += 1
            if self.scalars_calls == 1:
                self.photo_statements.append(statement)
                return ScalarRows(photos)
            return ScalarRows([])

    session = DetailSession()
    repo = repository.PostgresStateRepository()
    monkeypatch.setattr(repo, "_session", lambda: session)
    monkeypatch.setattr(local_simulation, "current_team_id", lambda: "demo-team")

    detail = repo.get_data_center_detail(kind="group", item_id="detail-valid-photos")

    assert detail is not None
    assert detail["photo_count"] == 4
    assert [photo["id"] for photo in detail["photos"]] == ["p1", "p2", "p3", "p4"]
    assert detail["classification_status"] == "complete"
    assert detail["archive_status"] == "archived"
    compiled = str(session.photo_statements[0].compile(compile_kwargs={"literal_binds": True})).lower()
    assert "photos.upload_status != 'invalid'" in compiled


def _model_group(group_id, *, legacy_id: str, photo_count: int):
    from types import SimpleNamespace

    return SimpleNamespace(
        id=group_id,
        team_id="demo-team",
        legacy_id=legacy_id,
        legacy_task_id=1,
        task_id=None,
        display_meter_no="M-001",
        meter_match_key="001",
        terminal="T-01",
        installation_address="Address",
        status=GroupStatus.APPROVED,
        photo_count=photo_count,
        reviewer="",
        reviewed_at=None,
        review_note="",
        exception_note="",
        exception_reasons=[],
        has_archive_blocker=False,
        raw_data={},
    )


def _model_photo(
    group_id,
    legacy_id: str,
    category: str,
    archive_status: str,
    *,
    upload_status: PhotoUploadStatus = PhotoUploadStatus.UPLOADED,
):
    from types import SimpleNamespace

    return SimpleNamespace(
        id=uuid4(),
        team_id="demo-team",
        legacy_id=legacy_id,
        group_id=group_id,
        source=None,
        barcode="",
        collector="",
        asset_no="",
        creator="",
        image_url=f"https://example.test/{legacy_id}.jpg",
        image_file_id=None,
        source_url="",
        source_file_id=None,
        storage_type="",
        storage_bucket="",
        storage_key="",
        sha256="a" * 64,
        original_filename="",
        upload_status=upload_status,
        category=category,
        archive_status=archive_status,
        archive_filename="",
        sort_order=0,
        raw_data={"category": category, "archive_status": archive_status},
    )
