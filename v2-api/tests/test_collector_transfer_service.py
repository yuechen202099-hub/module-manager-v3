from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from uuid import UUID

from openpyxl import Workbook
from sqlalchemy.exc import IntegrityError

from app.services.collector_transfer import (
    PostgresCollectorTransferService,
    collector_no_from_photo_filename,
    meter_sources_from_groups,
    read_collector_numbers_from_workbook,
)


def test_existing_groups_project_to_only_the_two_confirmed_install_photo_slots() -> None:
    """Catches reintroducing before-box or collector photos into a meter install item."""
    group = SimpleNamespace(
        id="group-1",
        terminal="T-001",
        installation_address="聚丰园路95弄21号",
        display_meter_no="000012345678",
        raw_data={"采集器": "C-001"},
    )
    photos = [
        SimpleNamespace(id="before", group_id="group-1", category="before_box", collector="C-001", asset_no=None, is_active=True),
        SimpleNamespace(id="module", group_id="group-1", category="module_meter", collector="C-001", asset_no="A-001", is_active=True),
        SimpleNamespace(id="after", group_id="group-1", category="after_box", collector="C-001", asset_no=None, is_active=True),
    ]

    projection = meter_sources_from_groups([group], photos)

    assert projection.diagnostics == ()
    assert projection.sources[0].module_meter_photo_id == "module"
    assert projection.sources[0].after_box_photo_id == "after"
    assert projection.sources[0].module_no == "A-001"
    assert projection.sources[0].collector_no == "C-001"


def test_projection_reports_missing_terminal_and_does_not_merge_it_into_a_fake_terminal() -> None:
    """Catches silently combining all blank terminal groups into one terminal."""
    group = SimpleNamespace(
        id="group-blank",
        terminal=" ",
        installation_address="未知地址",
        display_meter_no="M-001",
        raw_data={"collector": "C-001"},
    )

    projection = meter_sources_from_groups([group], [])

    assert projection.sources == ()
    assert projection.diagnostics == (
        {"group_id": "group-blank", "code": "terminal_missing", "message": "终端地址码为空"},
    )


def workbook_bytes(headers: list[str], rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_excel_inventory_import_preserves_leading_zeroes_and_compatible_headers() -> None:
    """Catches numeric coercion or requiring only one exact customer spreadsheet header."""
    rows = read_collector_numbers_from_workbook(
        workbook_bytes(["编号", "扫码内容", "采集器"], [[1, "ignored", "0000123"], [2, "0000456", None]])
    )

    assert rows == ((2, "0000123"), (3, "0000456"))


def test_photo_filename_is_a_collector_number_not_a_storage_path() -> None:
    """Catches losing leading zeroes or accepting path traversal as a collector number."""
    assert collector_no_from_photo_filename("0000123.jpg") == "0000123"
    assert collector_no_from_photo_filename("../0000123.jpg") == ""


class _EmptyScalarResult:
    def all(self) -> list[object]:
        return []


class _NoWriteSession:
    def __init__(self) -> None:
        self.commit_count = 0

    def scalars(self, _statement: object) -> _EmptyScalarResult:
        return _EmptyScalarResult()

    def scalar(self, _statement: object) -> int:
        return 0

    def commit(self) -> None:
        self.commit_count += 1


def test_reallocating_an_already_allocated_run_returns_persisted_count_without_writes(
    monkeypatch,
) -> None:
    """Catches a retry overwriting the durable allocation summary or adding a second audit event."""
    run = SimpleNamespace(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        project_id=UUID("22222222-2222-2222-2222-222222222222"),
        status="allocated",
        stats={"assignment_count": 3},
    )
    session = _NoWriteSession()
    service = PostgresCollectorTransferService(session=session, team_id="team-1", actor="operator")
    audits: list[dict[str, object]] = []
    monkeypatch.setattr(service, "_run", lambda _run_id, lock=False: run)
    monkeypatch.setattr(service, "_audit", lambda **payload: audits.append(payload))

    result = service.allocate(run_id=str(run.id))

    assert result == {"run_id": str(run.id), "assignment_count": 3, "assignments": []}
    assert audits == []
    assert session.commit_count == 0


class _NestedTransaction:
    def __enter__(self) -> _NestedTransaction:
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> bool:
        return False


class _PhysicalCollectorConflictSession:
    def __init__(self, winner: SimpleNamespace) -> None:
        self._scalar_values = iter((None, winner, None, None, None, None))
        self.added: list[object] = []
        self.commit_count = 0

    def scalar(self, _statement: object) -> object | None:
        return next(self._scalar_values)

    def add(self, record: object) -> None:
        self.added.append(record)

    def flush(self) -> None:
        raise IntegrityError("duplicate collector", {}, RuntimeError("unique constraint"))

    def begin_nested(self) -> _NestedTransaction:
        return _NestedTransaction()

    def commit(self) -> None:
        self.commit_count += 1


def test_scan_recovers_the_physical_collector_that_won_a_unique_constraint_race(
    monkeypatch,
) -> None:
    """Catches leaking a database uniqueness error when a concurrent scan registered the same number first."""
    run = SimpleNamespace(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        project_id=UUID("22222222-2222-2222-2222-222222222222"),
    )
    winner = SimpleNamespace(
        id=UUID("33333333-3333-3333-3333-333333333333"),
        collector_no="000123",
        pool_status="awaiting_photo",
        last_scanned_at=None,
    )
    session = _PhysicalCollectorConflictSession(winner)
    service = PostgresCollectorTransferService(session=session, team_id="team-1", actor="operator")
    monkeypatch.setattr(service, "_run", lambda _run_id, lock=False: run)
    monkeypatch.setattr(service, "_audit", lambda **_payload: None)

    result = service.scan_collector(run_id=str(run.id), collector_no="000123")

    assert result["collector_id"] == str(winner.id)
    assert result["pool_status"] == "awaiting_photo"
    assert session.commit_count == 1
