from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from uuid import UUID, uuid4

from openpyxl import Workbook
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import main as main_module
from app.api.routes import collector_transfer as routes
from app.core import security
from app.database import Base
from app.domain.collector_transfer import PoolInsufficientError
from app.models import (
    AuditLog,
    CollectorAssignment,
    CollectorImportRow,
    CollectorMeterItem,
    CollectorPhoto,
    CollectorRequirement,
    CollectorScanEvent,
    CollectorTransferRun,
    CollectorTransferTerminal,
    CollectorWorkbenchItem,
    MaterialGroup,
    PhysicalCollector,
    Photo,
    Project,
    ProjectStatus,
    Team,
    User,
)
from app.services.collector_transfer import (
    CollectorAllocationConflictError,
    CollectorPhotoConflictError,
    PostgresCollectorTransferService,
    collector_no_from_photo_filename,
    meter_sources_from_groups,
    read_collector_numbers_from_workbook,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(_type: JSONB, _compiler: object, **_kwargs: object) -> str:
    return "JSON"


@pytest.fixture
def db_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def register_uuid_function(connection, _connection_record) -> None:
        connection.create_function("gen_random_uuid", 0, lambda: uuid4().hex)

    Base.metadata.create_all(engine)
    session = Session(engine)
    try:
        session.add(Team(id="team-1", name="测试团队"))
        session.add(
            Project(
                id=uuid4(),
                team_id="team-1",
                code=f"P-{uuid4().hex[:8]}",
                name="测试项目",
                status=ProjectStatus.ACTIVE,
                settings={},
            )
        )
        session.commit()
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def project_id(session: Session) -> UUID:
    return session.scalar(select(Project.id).where(Project.team_id == "team-1"))


def transfer_run(session: Session, *, status: str = "inventory") -> CollectorTransferRun:
    run = CollectorTransferRun(
        id=uuid4(),
        team_id="team-1",
        project_id=project_id(session),
        name="盘点",
        status=status,
        stats={},
        diagnostics=[],
    )
    session.add(run)
    session.commit()
    return run


def transfer_terminal(session: Session, run: CollectorTransferRun, *, code: str = "T-001") -> CollectorTransferTerminal:
    terminal = CollectorTransferTerminal(
        id=uuid4(),
        run_id=run.id,
        team_id="team-1",
        terminal_code=code,
        installation_address="测试地址",
        status="ready",
        meter_count=1,
        collector_requirement_count=1,
        diagnostics=[],
    )
    session.add(terminal)
    session.commit()
    return terminal


def requirement(
    session: Session,
    run: CollectorTransferRun,
    terminal: CollectorTransferTerminal,
    *,
    collector_no: str = "C-001",
    status: str = "unmatched",
) -> CollectorRequirement:
    record = CollectorRequirement(
        id=uuid4(),
        run_id=run.id,
        terminal_id=terminal.id,
        team_id="team-1",
        original_collector_no=collector_no,
        status=status,
        sort_order=0,
        diagnostics=[],
    )
    session.add(record)
    session.commit()
    return record


def collector_photo(
    session: Session,
    collector: PhysicalCollector,
    *,
    sha256: str = "a" * 64,
) -> CollectorPhoto:
    photo = CollectorPhoto(
        id=uuid4(),
        team_id="team-1",
        physical_collector_id=collector.id,
        sha256=sha256,
        original_filename=f"{collector.collector_no}.jpg",
        object_key=f"collector-transfer/{collector.collector_no}.jpg",
        storage_type="local_upload",
        is_active=True,
    )
    session.add(photo)
    session.commit()
    return photo


def service(session: Session) -> PostgresCollectorTransferService:
    return PostgresCollectorTransferService(session=session, team_id="team-1", actor="operator")


def actor_user(session: Session, *, username: str = "operator") -> User:
    user = User(
        id=uuid4(),
        team_id="team-1",
        username=username,
        display_name=username,
        password_hash="test-only",
    )
    session.add(user)
    session.commit()
    return user


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


def test_module_source_ignores_after_box_asset_number_when_module_meter_is_blank() -> None:
    """Catches an unrelated evidence photo silently winning the module barcode fallback."""
    group = SimpleNamespace(
        id="group-asset-source",
        terminal="T-001",
        installation_address="测试地址",
        display_meter_no="METER-001",
        raw_data={"module_asset_no": "RAW-MODULE-001"},
    )
    photos = [
        SimpleNamespace(id="module", group_id="group-asset-source", category="module_meter", collector="C-001", asset_no="", is_active=True),
        SimpleNamespace(id="after", group_id="group-asset-source", category="after_box", collector="C-001", asset_no="AFTER-BOX-INCORRECT", is_active=True),
    ]

    projection = meter_sources_from_groups([group], photos)

    assert projection.sources[0].module_no == "RAW-MODULE-001"


def test_projection_preserves_a_blank_terminal_group_in_its_own_blocked_snapshot() -> None:
    """Catches silently combining or dropping blank-terminal groups instead of keeping a blocked meter item."""
    group = SimpleNamespace(
        id="group-blank",
        terminal=" ",
        installation_address="未知地址",
        display_meter_no="M-001",
        raw_data={"collector": "C-001"},
    )

    projection = meter_sources_from_groups([group], [])

    assert projection.sources[0].terminal_code == "__missing_terminal__:group-blank"
    assert projection.sources[0].group_id == "group-blank"
    assert projection.diagnostics[0] == {
        "group_id": "group-blank",
        "code": "terminal_missing",
        "message": "终端地址码为空",
    }


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


def test_excel_inventory_import_uses_simple_zero_fill_display_format_for_numeric_cells() -> None:
    """Catches a formatted numeric collector identifier silently losing its leading zeroes."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["采集器"])
    sheet.append([123])
    sheet["A2"].number_format = "000000"
    buffer = BytesIO()
    workbook.save(buffer)

    rows = read_collector_numbers_from_workbook(buffer.getvalue())

    assert rows == ((2, "000123"),)


def test_excel_inventory_import_rejects_unformatted_numeric_identifiers() -> None:
    """Catches a numeric cell being silently stringified when its display identity is ambiguous."""
    rows = read_collector_numbers_from_workbook(workbook_bytes(["采集器"], [[123]]))

    assert rows == ((2, ""),)


def test_excel_inventory_import_preserves_blank_rows_for_diagnostics() -> None:
    """Catches an empty collector cell disappearing before it can be persisted as invalid."""
    rows = read_collector_numbers_from_workbook(
        workbook_bytes(["采集器"], [["0000123"], [None], ["0000456"]])
    )

    assert rows == ((2, "0000123"), (3, ""), (4, "0000456"))


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
    monkeypatch.setattr(service, "_actor_user_id", lambda: None)
    monkeypatch.setattr(
        service,
        "_refresh_allocation_stats",
        lambda _run: {
            "assignment_count": 0,
            "active_assignment_count": 0,
            "direct_match_count": 0,
            "random_match_count": 0,
            "pool_available_count": 0,
        },
    )

    result = service.scan_collector(run_id=str(run.id), collector_no="000123")

    assert result["collector_id"] == str(winner.id)
    assert result["pool_status"] == "awaiting_photo"
    assert session.commit_count == 1


def test_real_database_create_run_keeps_each_blank_terminal_group_as_a_blocked_meter_item(
    db_session: Session,
) -> None:
    """Catches dropping source groups with blank terminals instead of preserving a separately blocked snapshot."""
    first = MaterialGroup(
        id=uuid4(),
        team_id="team-1",
        project_id=project_id(db_session),
        terminal=" ",
        meter_match_key="MISSING-TERMINAL-1",
        display_meter_no="M-001",
        installation_address="地址一",
        raw_data={"collector": "C-001"},
    )
    second = MaterialGroup(
        id=uuid4(),
        team_id="team-1",
        project_id=project_id(db_session),
        terminal="",
        meter_match_key="MISSING-TERMINAL-2",
        display_meter_no="M-002",
        installation_address="地址二",
        raw_data={"collector": "C-002"},
    )
    db_session.add_all((first, second))
    db_session.commit()

    result = service(db_session).create_run(project_id=str(project_id(db_session)), name="空终端")

    terminals = db_session.scalars(
        select(CollectorTransferTerminal).where(CollectorTransferTerminal.run_id == UUID(str(result["id"])))
    ).all()
    meter_items = db_session.scalars(
        select(CollectorMeterItem).where(CollectorMeterItem.run_id == UUID(str(result["id"])))
    ).all()
    assert len(terminals) == 2
    assert {terminal.status for terminal in terminals} == {"blocked"}
    assert len({terminal.terminal_code for terminal in terminals}) == 2
    assert {item.source_group_id for item in meter_items} == {first.id, second.id}


def test_real_database_missing_final_module_number_blocks_run_and_allocation(
    db_session: Session,
) -> None:
    """Catches a blank final module barcode leaving its terminal allocatable."""
    group = MaterialGroup(
        id=uuid4(),
        team_id="team-1",
        project_id=project_id(db_session),
        terminal="T-MODULE-MISSING",
        meter_match_key="MODULE-MISSING-1",
        display_meter_no="000000000123",
        installation_address="模块号缺失地址",
        raw_data={"collector": "C-MODULE-MISSING"},
    )
    db_session.add(group)
    db_session.flush()
    db_session.add_all(
        (
            Photo(
                team_id="team-1",
                group_id=group.id,
                sha256="1" * 64,
                object_key="source/module-missing/module-meter.jpg",
                image_url="/source/module-meter.jpg",
                category="module_meter",
                collector="C-MODULE-MISSING",
                asset_no="",
                is_active=True,
            ),
            Photo(
                team_id="team-1",
                group_id=group.id,
                sha256="2" * 64,
                object_key="source/module-missing/after-box.jpg",
                image_url="/source/after-box.jpg",
                category="after_box",
                collector="C-MODULE-MISSING",
                is_active=True,
            ),
        )
    )
    db_session.commit()

    created = service(db_session).create_run(
        project_id=str(project_id(db_session)),
        name="模块缺失阻断",
    )

    assert [item["code"] for item in created["diagnostics"]] == ["module_missing"]
    run_id = UUID(str(created["id"]))
    terminal = db_session.scalar(
        select(CollectorTransferTerminal).where(CollectorTransferTerminal.run_id == run_id)
    )
    required = db_session.scalar(
        select(CollectorRequirement).where(CollectorRequirement.run_id == run_id)
    )
    assert terminal.status == "blocked"
    assert required.status == "blocked"
    with pytest.raises(ValueError, match="批次存在资料阻断") as raised:
        service(db_session).allocate(run_id=str(run_id))
    assert raised.type.__name__ == "CollectorRunBlockedError"


def test_workbench_install_photos_are_immutable_run_snapshots(
    db_session: Session,
) -> None:
    """Catches source-photo invalidation or storage edits changing an existing run's evidence."""
    group = MaterialGroup(
        id=uuid4(),
        team_id="team-1",
        project_id=project_id(db_session),
        terminal="T-SNAPSHOT",
        meter_match_key="SNAPSHOT-1",
        display_meter_no="000000000456",
        installation_address="快照地址",
        raw_data={"collector": "C-SNAPSHOT"},
    )
    db_session.add(group)
    db_session.flush()
    source_photos = (
        Photo(
            team_id="team-1",
            group_id=group.id,
            sha256="3" * 64,
            object_key="source/snapshot/module-meter.jpg",
            image_url="/source/snapshot/module-meter.jpg",
            storage_type="local_upload",
            storage_key="source/snapshot/module-meter.jpg",
            category="module_meter",
            collector="C-SNAPSHOT",
            asset_no="MODULE-SNAPSHOT",
            is_active=True,
        ),
        Photo(
            team_id="team-1",
            group_id=group.id,
            sha256="4" * 64,
            object_key="source/snapshot/after-box.jpg",
            image_url="/source/snapshot/after-box.jpg",
            storage_type="local_upload",
            storage_key="source/snapshot/after-box.jpg",
            category="after_box",
            collector="C-SNAPSHOT",
            is_active=True,
        ),
    )
    db_session.add_all(source_photos)
    db_session.commit()
    transfer = service(db_session)
    created = transfer.create_run(project_id=str(project_id(db_session)), name="快照验证")
    terminal_id = db_session.scalar(
        select(CollectorTransferTerminal.id).where(
            CollectorTransferTerminal.run_id == UUID(str(created["id"]))
        )
    )
    before = transfer.terminal_workbench(
        run_id=str(created["id"]),
        terminal_id=str(terminal_id),
    )["items"][0]["photos"]

    for source in source_photos:
        source.is_active = False
        source.image_url = "/source/mutated.jpg"
        source.storage_key = "source/mutated.jpg"
        source.object_key = "source/mutated.jpg"
    db_session.commit()

    after = transfer.terminal_workbench(
        run_id=str(created["id"]),
        terminal_id=str(terminal_id),
    )["items"][0]["photos"]
    assert after == before
    assert [slot["photo"]["storage_key"] for slot in after] == [
        "source/snapshot/module-meter.jpg",
        "source/snapshot/after-box.jpg",
    ]


def test_real_database_scan_returns_each_direct_and_pool_decision(
    db_session: Session,
) -> None:
    """Catches the scan service bypassing the persisted same-number or replacement-pool state machine."""
    run = transfer_run(db_session)
    no_photo_requirement = requirement(db_session, run, transfer_terminal(db_session, run, code="T-001"), collector_no="C-001")
    reusable_requirement = requirement(db_session, run, transfer_terminal(db_session, run, code="T-002"), collector_no="C-002")
    reusable_collector = PhysicalCollector(
        id=uuid4(), team_id="team-1", collector_no="C-002", pool_status="awaiting_photo"
    )
    db_session.add(reusable_collector)
    db_session.commit()
    collector_photo(db_session, reusable_collector)

    needs_photo = service(db_session).scan_collector(run_id=str(run.id), collector_no="C-001")
    reusable = service(db_session).scan_collector(run_id=str(run.id), collector_no="C-002")
    pool = service(db_session).scan_collector(run_id=str(run.id), collector_no="C-999")

    assert needs_photo["decision"] == "direct_needs_photo"
    assert needs_photo["requires_photo"] is True
    assert reusable["decision"] == "direct_reuse"
    assert reusable["add_to_pool"] is False
    assert pool["decision"] == "pool_needs_photo"
    assert pool["pool_status"] == "awaiting_photo"
    assert db_session.get(CollectorRequirement, no_photo_requirement.id).status == "direct_pending_photo"
    assert db_session.get(CollectorRequirement, reusable_requirement.id).status == "direct_ready"
    assert db_session.scalar(select(func.count(AuditLog.id))) == 3


@pytest.mark.parametrize(("assignment_status", "physical_status", "requirement_status"), [("reserved", "reserved", "assigned"), ("used", "used", "used")])
def test_real_database_rescan_never_demotes_existing_assignment_state(
    db_session: Session,
    assignment_status: str,
    physical_status: str,
    requirement_status: str,
) -> None:
    """Catches a repeat scan rewriting reserved or used allocation state into a direct assignment state."""
    run = transfer_run(db_session)
    terminal = transfer_terminal(db_session, run)
    required = requirement(db_session, run, terminal, status=requirement_status)
    physical = PhysicalCollector(
        id=uuid4(), team_id="team-1", collector_no="C-001", pool_status=physical_status
    )
    db_session.add(physical)
    db_session.commit()
    photo = collector_photo(db_session, physical)
    assigned = CollectorAssignment(
        id=uuid4(), run_id=run.id, team_id="team-1", requirement_id=required.id,
        physical_collector_id=physical.id, collector_photo_id=photo.id, assignment_mode="random", status=assignment_status,
    )
    db_session.add(assigned)
    db_session.commit()

    result = service(db_session).scan_collector(run_id=str(run.id), collector_no="C-001")

    db_session.refresh(physical)
    db_session.refresh(required)
    db_session.refresh(assigned)
    assert result["pool_status"] == physical_status
    assert physical.pool_status == physical_status
    assert required.status == requirement_status
    assert assigned.assignment_mode == "random"
    assert assigned.status == assignment_status


def _route_session_factory(session: Session):
    return sessionmaker(bind=session.get_bind(), expire_on_commit=False)


def _route_auth_headers(*, team_id: str = "team-1", username: str = "admin-a") -> dict[str, str]:
    token = security.create_access_token(
        {
            "sub": username,
            "username": username,
            "roles": ["admin"],
            "team_id": team_id,
        }
    )
    return {"Authorization": f"bearer {token}"}


def test_saved_image_registration_scope_includes_inactive_database_ownership(
    db_session: Session,
    monkeypatch,
) -> None:
    """Catches cleanup deleting an object still owned by an inactive/soft-invalid photo row."""
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        collector_no="C-INACTIVE",
        pool_status="available",
    )
    db_session.add(physical)
    db_session.commit()
    photo = collector_photo(db_session, physical, sha256="d" * 64)
    photo.is_active = False
    db_session.commit()
    monkeypatch.setattr(routes, "SessionLocal", _route_session_factory(db_session))

    assert routes.saved_image_is_registered(
        team_id="team-1",
        stored={"sha256": "d" * 64, "storage_key": photo.object_key},
    ) is True
    assert routes.saved_image_is_registered(
        team_id="team-2",
        stored={"sha256": "d" * 64, "storage_key": photo.object_key},
    ) is False
    assert routes.saved_image_is_registered(
        team_id="team-1",
        stored={"sha256": "e" * 64, "storage_key": photo.object_key},
    ) is False
    assert routes.saved_image_is_registered(
        team_id="team-1",
        stored={"sha256": "d" * 64, "storage_key": "collector-transfer/other.jpg"},
    ) is False


def test_single_photo_reuse_deletes_the_new_unreferenced_saved_object(
    db_session: Session,
    monkeypatch,
) -> None:
    """Catches successful SHA reuse leaking the newly saved object whose key was not persisted."""
    run = transfer_run(db_session)
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        collector_no="C-REUSE",
        pool_status="available",
    )
    db_session.add(physical)
    db_session.commit()
    old_photo = collector_photo(db_session, physical, sha256="f" * 64)
    service(db_session).scan_collector(run_id=str(run.id), collector_no=physical.collector_no)
    new_key = "collector-transfer/new-upload-C-REUSE.jpg"
    deleted: list[str] = []
    monkeypatch.setattr(routes, "SessionLocal", _route_session_factory(db_session))
    monkeypatch.setattr(
        routes,
        "save_image_bytes",
        lambda **_kwargs: {
            "url": f"/static/uploads/{new_key}",
            "sha256": old_photo.sha256,
            "storage_type": "local_upload",
            "storage_key": new_key,
            "content_type": "image/jpeg",
            "created_new": True,
        },
    )
    monkeypatch.setattr(
        routes,
        "delete_saved_image",
        lambda stored: deleted.append(str(stored["storage_key"])),
    )
    client = TestClient(main_module.create_app())

    response = client.post(
        f"/collector-transfer/runs/{run.id}/collectors/{physical.id}/photo",
        headers=_route_auth_headers(),
        files={"file": ("C-REUSE.jpg", b"same-image-content", "image/jpeg")},
    )

    assert response.status_code == 200
    assert deleted == [new_key]
    with _route_session_factory(db_session)() as verification:
        photos = verification.scalars(
            select(CollectorPhoto).where(CollectorPhoto.physical_collector_id == physical.id)
        ).all()
        assert len(photos) == 1
        assert photos[0].object_key == old_photo.object_key


def test_batch_route_persists_one_diagnostic_per_excel_row_and_photo_input(
    db_session: Session,
    monkeypatch,
) -> None:
    """Catches blank rows, invalid filenames, or duplicate-number photos disappearing from diagnostics."""
    run = transfer_run(db_session)
    deleted: list[str] = []
    monkeypatch.setattr(routes, "SessionLocal", _route_session_factory(db_session))

    def save_photo(**kwargs):
        filename = str(kwargs["filename"])
        suffix = "jpg" if filename.endswith(".jpg") else "png"
        return {
            "url": f"/static/uploads/collector-transfer/{filename}",
            "sha256": ("a" if suffix == "jpg" else "b") * 64,
            "storage_type": "local_upload",
            "storage_key": f"collector-transfer/{filename}",
            "content_type": kwargs["content_type"],
            "created_new": True,
        }

    monkeypatch.setattr(routes, "save_image_bytes", save_photo)
    monkeypatch.setattr(
        routes,
        "delete_saved_image",
        lambda stored: deleted.append(str(stored["storage_key"])),
    )
    client = TestClient(main_module.create_app())

    response = client.post(
        f"/collector-transfer/runs/{run.id}/inventory/import",
        headers=_route_auth_headers(),
        files=[
            (
                "workbook",
                (
                    "collectors.xlsx",
                    workbook_bytes(["采集器"], [["000123"], [None]]),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            ),
            ("photos", ("folder/invalid.jpg", b"invalid-name", "image/jpeg")),
            ("photos", ("000123.jpg", b"first", "image/jpeg")),
            ("photos", ("000123.png", b"duplicate", "image/png")),
        ],
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["total"] == 5
    assert payload["inserted"] == 2
    assert payload["invalid"] == 2
    assert payload["reused"] == 1
    assert [(item["input_kind"], item["outcome"]) for item in payload["rows"]] == [
        ("excel", "inserted"),
        ("excel", "invalid"),
        ("photo", "invalid"),
        ("photo", "inserted"),
        ("photo", "reused"),
    ]
    with _route_session_factory(db_session)() as verification:
        persisted = verification.scalars(
            select(CollectorImportRow)
            .where(CollectorImportRow.run_id == run.id)
            .order_by(CollectorImportRow.row_number, CollectorImportRow.id)
        ).all()
        assert len(persisted) == 5
        assert [item.payload["input_kind"] for item in persisted] == [
            "excel",
            "excel",
            "photo",
            "photo",
            "photo",
        ]
    assert deleted == ["collector-transfer/000123.png"]


@pytest.mark.parametrize(("assignment_status", "physical_status", "requirement_status"), [("reserved", "reserved", "assigned"), ("used", "used", "used")])
def test_real_database_duplicate_photo_never_demotes_existing_assignment_state(
    db_session: Session,
    assignment_status: str,
    physical_status: str,
    requirement_status: str,
) -> None:
    """Catches an idempotent photo upload changing a reserved or used collector back to direct or available."""
    run = transfer_run(db_session)
    terminal = transfer_terminal(db_session, run)
    required = requirement(db_session, run, terminal, status=requirement_status)
    physical = PhysicalCollector(
        id=uuid4(), team_id="team-1", collector_no="C-001", pool_status=physical_status
    )
    db_session.add(physical)
    db_session.commit()
    photo = collector_photo(db_session, physical)
    assigned = CollectorAssignment(
        id=uuid4(), run_id=run.id, team_id="team-1", requirement_id=required.id,
        physical_collector_id=physical.id, collector_photo_id=photo.id, assignment_mode="random", status=assignment_status,
    )
    event = CollectorScanEvent(
        id=uuid4(), run_id=run.id, team_id="team-1", physical_collector_id=physical.id,
        requirement_id=required.id, scanned_value="C-001", decision="direct_reuse", requires_photo=False, add_to_pool=False,
    )
    db_session.add_all((assigned, event))
    db_session.commit()

    result = service(db_session).register_photo(
        run_id=str(run.id), collector_id=str(physical.id), original_filename="C-001.jpg",
        stored={"sha256": photo.sha256, "storage_key": photo.object_key, "storage_type": "local_upload"}, byte_size=12,
    )

    db_session.refresh(physical)
    db_session.refresh(required)
    assert result["pool_status"] == physical_status
    assert physical.pool_status == physical_status
    assert required.status == requirement_status
    assert db_session.scalar(select(func.count(CollectorPhoto.id))) == 1


def test_real_database_rejects_same_photo_sha_for_a_different_physical_collector(
    db_session: Session,
) -> None:
    """Catches cross-collector reuse before either pool state is mutated."""
    run = transfer_run(db_session)
    first = PhysicalCollector(id=uuid4(), team_id="team-1", collector_no="C-FIRST", pool_status="available")
    second = PhysicalCollector(id=uuid4(), team_id="team-1", collector_no="C-SECOND", pool_status="awaiting_photo")
    db_session.add_all((first, second))
    db_session.commit()
    existing = collector_photo(db_session, first, sha256="9" * 64)
    service(db_session).scan_collector(run_id=str(run.id), collector_no=second.collector_no)

    with pytest.raises(CollectorPhotoConflictError, match="another physical collector"):
        service(db_session).register_photo(
            run_id=str(run.id),
            collector_id=str(second.id),
            original_filename="C-SECOND.jpg",
            stored={
                "sha256": existing.sha256,
                "storage_key": "collector-transfer/C-SECOND-new.jpg",
                "storage_type": "local_upload",
            },
            byte_size=15,
        )

    db_session.rollback()
    assert db_session.scalar(select(func.count(CollectorPhoto.id))) == 1
    assert db_session.get(PhysicalCollector, second.id).pool_status == "awaiting_photo"


def test_sqlite_unique_backstop_rejects_cross_collector_photo_sha(db_session: Session) -> None:
    """Proves the database backstop covers concurrent service races."""
    first = PhysicalCollector(id=uuid4(), team_id="team-1", collector_no="C-DB-1", pool_status="available")
    second = PhysicalCollector(id=uuid4(), team_id="team-1", collector_no="C-DB-2", pool_status="awaiting_photo")
    db_session.add_all((first, second))
    db_session.commit()
    collector_photo(db_session, first, sha256="8" * 64)
    duplicate = CollectorPhoto(
        id=uuid4(),
        team_id="team-1",
        physical_collector_id=second.id,
        sha256="8" * 64,
        original_filename="C-DB-2.jpg",
        object_key="collector-transfer/C-DB-2.jpg",
        storage_type="local_upload",
        is_active=True,
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    assert db_session.scalar(select(func.count(CollectorPhoto.id))) == 1


def test_identical_collector_photo_sha_is_scoped_per_team(db_session: Session) -> None:
    """Catches another team's identical image blocking this team's photo registration."""
    transfer_run(db_session)
    first = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        collector_no="C-SHA-TEAM-1",
        pool_status="available",
    )
    db_session.add(first)
    db_session.commit()
    existing = collector_photo(db_session, first, sha256="7" * 64)

    db_session.add(Team(id="team-2", name="另一个团队"))
    second_project = Project(
        id=uuid4(),
        team_id="team-2",
        code=f"P-{uuid4().hex[:8]}",
        name="团队二项目",
        status=ProjectStatus.ACTIVE,
        settings={},
    )
    db_session.add(second_project)
    db_session.flush()
    second_run = CollectorTransferRun(
        id=uuid4(),
        team_id="team-2",
        project_id=second_project.id,
        name="团队二盘点",
        status="inventory",
        stats={},
        diagnostics=[],
    )
    second = PhysicalCollector(
        id=uuid4(),
        team_id="team-2",
        collector_no="C-SHA-TEAM-2",
        pool_status="awaiting_photo",
    )
    db_session.add_all((second_run, second))
    db_session.flush()
    db_session.add(
        CollectorScanEvent(
            run_id=second_run.id,
            team_id="team-2",
            physical_collector_id=second.id,
            scanned_value=second.collector_no,
            decision="pool_needs_photo",
            requires_photo=True,
            add_to_pool=True,
        )
    )
    db_session.commit()

    registered = PostgresCollectorTransferService(
        session=db_session,
        team_id="team-2",
        actor="operator-2",
    ).register_photo(
        run_id=str(second_run.id),
        collector_id=str(second.id),
        original_filename="C-SHA-TEAM-2.jpg",
        stored={
            "sha256": existing.sha256,
            "storage_key": "collector-transfer/team-2/C-SHA-TEAM-2.jpg",
            "storage_type": "local_upload",
            "content_type": "image/jpeg",
        },
        byte_size=10,
    )

    assert registered["collector_id"] == str(second.id)
    assert db_session.scalar(
        select(func.count(CollectorPhoto.id)).where(CollectorPhoto.sha256 == existing.sha256)
    ) == 2


def test_register_photo_requires_scan_provenance_in_the_same_run(db_session: Session) -> None:
    """Catches a collector scanned in run A being uploaded directly through run B."""
    run_a = transfer_run(db_session)
    run_b = transfer_run(db_session)
    scanned = service(db_session).scan_collector(run_id=str(run_a.id), collector_no="C-RUN-PROVENANCE")

    with pytest.raises(ValueError, match="当前批次.*扫码"):
        service(db_session).register_photo(
            run_id=str(run_b.id),
            collector_id=str(scanned["collector_id"]),
            original_filename="C-RUN-PROVENANCE.jpg",
            stored={
                "sha256": "6" * 64,
                "storage_key": "collector-transfer/C-RUN-PROVENANCE.jpg",
                "storage_type": "local_upload",
                "content_type": "image/jpeg",
            },
            byte_size=10,
        )

    db_session.rollback()
    assert db_session.scalar(select(func.count(CollectorPhoto.id))) == 0


def test_cross_run_photo_upload_has_stable_api_conflict_and_cleans_saved_file(
    db_session: Session,
    monkeypatch,
) -> None:
    """Catches an A-scan/B-upload returning a generic error or leaking its unregistered file."""
    run_a = transfer_run(db_session)
    run_b = transfer_run(db_session)
    scanned = service(db_session).scan_collector(run_id=str(run_a.id), collector_no="C-API-PROVENANCE")
    saved = {
        "url": "/static/uploads/collector-transfer/C-API-PROVENANCE.jpg",
        "sha256": "65" * 32,
        "storage_type": "local_upload",
        "storage_key": "collector-transfer/C-API-PROVENANCE.jpg",
        "content_type": "image/jpeg",
        "created_new": True,
    }
    deleted: list[str] = []
    monkeypatch.setattr(routes, "SessionLocal", _route_session_factory(db_session))
    monkeypatch.setattr(routes, "save_image_bytes", lambda **_kwargs: saved)
    monkeypatch.setattr(
        routes,
        "delete_saved_image",
        lambda stored: deleted.append(str(stored["storage_key"])),
    )

    response = TestClient(main_module.create_app()).post(
        f"/collector-transfer/runs/{run_b.id}/collectors/{scanned['collector_id']}/photo",
        headers=_route_auth_headers(username="constructor-a"),
        files={"file": ("C-API-PROVENANCE.jpg", b"cross-run", "image/jpeg")},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "scan_provenance_required"
    assert deleted == ["collector-transfer/C-API-PROVENANCE.jpg"]


def test_direct_scan_refreshes_and_returns_transactional_run_totals(db_session: Session) -> None:
    """Catches a direct assignment leaving direct and active-assignment totals stale."""
    run = transfer_run(db_session)
    terminal = transfer_terminal(db_session, run)
    requirement(db_session, run, terminal, collector_no="C-DIRECT-STATS")
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        collector_no="C-DIRECT-STATS",
        pool_status="awaiting_photo",
    )
    db_session.add(physical)
    db_session.commit()
    collector_photo(db_session, physical, sha256="5" * 64)

    scanned = service(db_session).scan_collector(
        run_id=str(run.id),
        collector_no=physical.collector_no,
    )

    assert scanned["stats"] == {
        "assignment_count": 1,
        "active_assignment_count": 1,
        "direct_match_count": 1,
        "random_match_count": 0,
        "pool_available_count": 0,
    }
    db_session.refresh(run)
    assert {key: run.stats[key] for key in scanned["stats"]} == scanned["stats"]


def test_pool_photo_allocate_and_rollback_each_refresh_run_totals(db_session: Session) -> None:
    """Catches pool admission, random allocation, or rollback returning stale derived totals."""
    run = transfer_run(db_session)
    terminal = transfer_terminal(db_session, run)
    requirement(db_session, run, terminal, collector_no="C-ORIGINAL-STATS")
    scanned = service(db_session).scan_collector(run_id=str(run.id), collector_no="C-POOL-STATS")
    assert scanned["stats"]["pool_available_count"] == 0

    registered = service(db_session).register_photo(
        run_id=str(run.id),
        collector_id=str(scanned["collector_id"]),
        original_filename="C-POOL-STATS.jpg",
        stored={
            "sha256": "a1" * 32,
            "storage_key": "collector-transfer/C-POOL-STATS.jpg",
            "storage_type": "local_upload",
            "content_type": "image/jpeg",
        },
        byte_size=10,
    )
    assert registered["stats"]["pool_available_count"] == 1
    assert registered["stats"]["assignment_count"] == 0

    allocated = service(db_session).allocate(run_id=str(run.id))
    assert allocated["stats"] == {
        "assignment_count": 1,
        "active_assignment_count": 1,
        "direct_match_count": 0,
        "random_match_count": 1,
        "pool_available_count": 0,
    }

    rolled_back = service(db_session).rollback_assignment(
        assignment_id=str(allocated["assignments"][0]["assignment_id"])
    )
    assert rolled_back["stats"] == {
        "assignment_count": 0,
        "active_assignment_count": 0,
        "direct_match_count": 0,
        "random_match_count": 0,
        "pool_available_count": 1,
    }
    db_session.refresh(run)
    assert {key: run.stats[key] for key in rolled_back["stats"]} == rolled_back["stats"]


@pytest.mark.parametrize("assignment_status", ["reserved", "used"])
def test_direct_assignment_rollback_never_admits_collector_to_random_pool(
    db_session: Session,
    assignment_status: str,
) -> None:
    """Catches direct rollback turning a photographed same-number collector into a pool candidate."""
    run = transfer_run(db_session)
    terminal = transfer_terminal(db_session, run)
    required = requirement(
        db_session,
        run,
        terminal,
        collector_no="C-DIRECT-ROLLBACK",
        status="used" if assignment_status == "used" else "direct_ready",
    )
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        collector_no="C-DIRECT-ROLLBACK",
        pool_status="used" if assignment_status == "used" else "direct",
    )
    db_session.add(physical)
    db_session.commit()
    photo = collector_photo(db_session, physical, sha256=("b" if assignment_status == "used" else "c") * 64)
    assigned = CollectorAssignment(
        id=uuid4(),
        run_id=run.id,
        team_id="team-1",
        requirement_id=required.id,
        physical_collector_id=physical.id,
        collector_photo_id=photo.id,
        assignment_mode="direct",
        status=assignment_status,
    )
    db_session.add(assigned)
    db_session.flush()
    db_session.add(
        CollectorWorkbenchItem(
            run_id=run.id,
            terminal_id=terminal.id,
            team_id="team-1",
            item_kind="collector_removal",
            source_key=str(required.id),
            requirement_id=required.id,
            assignment_id=assigned.id,
            status="completed" if assignment_status == "used" else "pending",
        )
    )
    db_session.commit()

    service(db_session).rollback_assignment(assignment_id=str(assigned.id))

    db_session.refresh(required)
    db_session.refresh(physical)
    assert required.status == "direct_ready"
    assert physical.pool_status == "direct"
    assert db_session.scalar(
        select(func.count(PhysicalCollector.id)).where(
            PhysicalCollector.id == physical.id,
            PhysicalCollector.pool_status == "available",
        )
    ) == 0
    reallocated = service(db_session).allocate(run_id=str(run.id))
    assert reallocated["assignment_count"] == 0
    assert db_session.scalar(
        select(func.count(CollectorAssignment.id)).where(
            CollectorAssignment.run_id == run.id,
            CollectorAssignment.status.in_(("reserved", "used")),
        )
    ) == 0


def test_undoing_only_completed_item_restores_ready_terminal(db_session: Session) -> None:
    """Catches an empty-progress terminal remaining in_progress after its only item is undone."""
    run = transfer_run(db_session)
    terminal = transfer_terminal(db_session, run)
    group = MaterialGroup(
        id=uuid4(),
        team_id="team-1",
        project_id=run.project_id,
        terminal=terminal.terminal_code,
        meter_match_key="UNDO-READY-1",
        display_meter_no="000000000789",
        installation_address="撤销地址",
        raw_data={},
    )
    db_session.add(group)
    db_session.flush()
    meter = CollectorMeterItem(
        run_id=run.id,
        terminal_id=terminal.id,
        team_id="team-1",
        source_group_id=group.id,
        meter_no="000000000789",
        meter_barcode="000000000789",
        module_no="MODULE-UNDO",
        module_barcode="MODULE-UNDO",
        module_meter_photo_snapshot={"id": str(uuid4()), "storage_key": "snapshots/module.jpg"},
        after_box_photo_snapshot={"id": str(uuid4()), "storage_key": "snapshots/after.jpg"},
        diagnostics=[],
    )
    db_session.add(meter)
    db_session.flush()
    item = CollectorWorkbenchItem(
        run_id=run.id,
        terminal_id=terminal.id,
        team_id="team-1",
        item_kind="meter_install",
        source_key=str(meter.id),
        meter_item_id=meter.id,
        status="pending",
    )
    db_session.add(item)
    db_session.commit()

    transfer = service(db_session)
    transfer.set_workbench_item_status(item_id=str(item.id), completed=True)
    transfer.set_workbench_item_status(item_id=str(item.id), completed=False)

    db_session.refresh(terminal)
    assert terminal.completed_item_count == 0
    assert terminal.status == "ready"


def test_direct_api_cannot_complete_meter_item_with_missing_server_evidence(
    db_session: Session,
    monkeypatch,
) -> None:
    """Catches bypassing meter barcode/two-photo completeness through the PATCH API."""
    run = transfer_run(db_session)
    terminal = transfer_terminal(db_session, run)
    group = MaterialGroup(
        id=uuid4(),
        team_id="team-1",
        project_id=run.project_id,
        terminal=terminal.terminal_code,
        meter_match_key="INVALID-COMPLETE-METER",
        display_meter_no="000000000901",
        installation_address="完整性地址",
        raw_data={},
    )
    db_session.add(group)
    db_session.flush()
    meter = CollectorMeterItem(
        run_id=run.id,
        terminal_id=terminal.id,
        team_id="team-1",
        source_group_id=group.id,
        meter_no="000000000901",
        meter_barcode="",
        module_no="MODULE-COMPLETE",
        module_barcode="MODULE-COMPLETE",
        module_meter_photo_snapshot={"id": str(uuid4()), "storage_key": "snapshots/module.jpg"},
        after_box_photo_snapshot={},
        diagnostics=[],
    )
    db_session.add(meter)
    db_session.flush()
    item = CollectorWorkbenchItem(
        run_id=run.id,
        terminal_id=terminal.id,
        team_id="team-1",
        item_kind="meter_install",
        source_key=str(meter.id),
        meter_item_id=meter.id,
        status="pending",
    )
    db_session.add(item)
    db_session.commit()
    monkeypatch.setattr(routes, "SessionLocal", _route_session_factory(db_session))

    response = TestClient(main_module.create_app()).patch(
        f"/collector-transfer/workbench/items/{item.id}",
        headers=_route_auth_headers(username="constructor-a"),
        json={"completed": True},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "workbench_incomplete"
    with _route_session_factory(db_session)() as verification:
        assert verification.get(CollectorWorkbenchItem, item.id).status == "pending"


def test_direct_api_cannot_complete_removal_with_inactive_bound_photo(
    db_session: Session,
    monkeypatch,
) -> None:
    """Catches completing a removal after its one required collector photo became invalid."""
    run = transfer_run(db_session)
    terminal = transfer_terminal(db_session, run)
    required = requirement(db_session, run, terminal, status="assigned")
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        collector_no="C-INACTIVE-EVIDENCE",
        pool_status="reserved",
    )
    db_session.add(physical)
    db_session.commit()
    photo = collector_photo(db_session, physical, sha256="d" * 64)
    photo.is_active = False
    assigned = CollectorAssignment(
        id=uuid4(),
        run_id=run.id,
        team_id="team-1",
        requirement_id=required.id,
        physical_collector_id=physical.id,
        collector_photo_id=photo.id,
        assignment_mode="random",
        status="reserved",
    )
    db_session.add(assigned)
    db_session.flush()
    item = CollectorWorkbenchItem(
        run_id=run.id,
        terminal_id=terminal.id,
        team_id="team-1",
        item_kind="collector_removal",
        source_key=str(required.id),
        requirement_id=required.id,
        assignment_id=assigned.id,
        status="pending",
    )
    db_session.add(item)
    db_session.commit()
    monkeypatch.setattr(routes, "SessionLocal", _route_session_factory(db_session))

    response = TestClient(main_module.create_app()).patch(
        f"/collector-transfer/workbench/items/{item.id}",
        headers=_route_auth_headers(username="constructor-a"),
        json={"completed": True},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "workbench_incomplete"
    with _route_session_factory(db_session)() as verification:
        assert verification.get(CollectorWorkbenchItem, item.id).status == "pending"


def test_direct_photo_assignment_persists_authenticated_operator_provenance(
    db_session: Session,
) -> None:
    """Catches direct capture/assignment rows losing the authenticated operator."""
    operator = actor_user(db_session)
    run = transfer_run(db_session)
    terminal = transfer_terminal(db_session, run)
    requirement(db_session, run, terminal, collector_no="C-DIRECT-ACTOR")
    transfer = service(db_session)
    scanned = transfer.scan_collector(run_id=str(run.id), collector_no="C-DIRECT-ACTOR")
    transfer.register_photo(
        run_id=str(run.id),
        collector_id=str(scanned["collector_id"]),
        original_filename="C-DIRECT-ACTOR.jpg",
        stored={
            "sha256": "e" * 64,
            "storage_key": "collector-transfer/C-DIRECT-ACTOR.jpg",
            "storage_type": "local_upload",
            "content_type": "image/jpeg",
        },
        byte_size=10,
    )

    assigned = db_session.scalar(
        select(CollectorAssignment).where(CollectorAssignment.run_id == run.id)
    )
    captured = db_session.scalar(
        select(CollectorPhoto).where(CollectorPhoto.physical_collector_id == assigned.physical_collector_id)
    )
    scan_event = db_session.scalar(
        select(CollectorScanEvent).where(CollectorScanEvent.run_id == run.id)
    )
    assert assigned.assigned_by_id == operator.id
    assert assigned.assigned_by_username == "operator"
    assert captured.captured_by_id == operator.id
    assert captured.captured_by_username == "operator"
    assert scan_event.actor_id == operator.id


def test_random_allocation_persists_operator_and_mapping_audit(db_session: Session) -> None:
    """Catches random assignments and audit rows retaining only an aggregate count."""
    operator = actor_user(db_session)
    run = transfer_run(db_session)
    terminal = transfer_terminal(db_session, run)
    required = requirement(db_session, run, terminal, collector_no="C-RANDOM-ORIGINAL")
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        collector_no="C-RANDOM-FINAL",
        pool_status="available",
    )
    db_session.add(physical)
    db_session.commit()
    collector_photo(db_session, physical, sha256="f" * 64)

    allocated = service(db_session).allocate(run_id=str(run.id))

    assigned = db_session.get(CollectorAssignment, UUID(allocated["assignments"][0]["assignment_id"]))
    audit = db_session.scalar(
        select(AuditLog)
        .where(
            AuditLog.team_id == "team-1",
            AuditLog.action == "collector_transfer.random_allocated",
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    )
    assert assigned.assigned_by_id == operator.id
    assert assigned.assigned_by_username == "operator"
    assert audit.actor_username == "operator"
    assert audit.payload["assigned_by"] == "operator"
    assert audit.payload["assignments"] == [
        {
            "assignment_id": str(assigned.id),
            "requirement_id": str(required.id),
            "original_collector_no": "C-RANDOM-ORIGINAL",
            "physical_collector_id": str(physical.id),
            "final_collector_no": "C-RANDOM-FINAL",
            "mode": "random",
        }
    ]


def test_workbench_completion_persists_authenticated_operator_provenance(
    db_session: Session,
) -> None:
    """Catches a completed workbench item omitting the authenticated completing operator."""
    operator = actor_user(db_session)
    run = transfer_run(db_session)
    terminal = transfer_terminal(db_session, run)
    group = MaterialGroup(
        id=uuid4(),
        team_id="team-1",
        project_id=run.project_id,
        terminal=terminal.terminal_code,
        meter_match_key="COMPLETE-ACTOR-1",
        display_meter_no="000000001111",
        installation_address="完成审计地址",
        raw_data={},
    )
    db_session.add(group)
    db_session.flush()
    meter = CollectorMeterItem(
        run_id=run.id,
        terminal_id=terminal.id,
        team_id="team-1",
        source_group_id=group.id,
        meter_no="000000001111",
        meter_barcode="000000001111",
        module_no="MODULE-ACTOR",
        module_barcode="MODULE-ACTOR",
        module_meter_photo_snapshot={"id": str(uuid4()), "storage_key": "snapshots/module-actor.jpg"},
        after_box_photo_snapshot={"id": str(uuid4()), "storage_key": "snapshots/after-actor.jpg"},
        diagnostics=[],
    )
    db_session.add(meter)
    db_session.flush()
    item = CollectorWorkbenchItem(
        run_id=run.id,
        terminal_id=terminal.id,
        team_id="team-1",
        item_kind="meter_install",
        source_key=str(meter.id),
        meter_item_id=meter.id,
        status="pending",
    )
    db_session.add(item)
    db_session.commit()

    service(db_session).set_workbench_item_status(item_id=str(item.id), completed=True)

    db_session.refresh(item)
    assert item.completed_by_id == operator.id
    assert item.completed_by_username == "operator"

def test_real_database_pool_shortage_leaves_no_allocation_side_effects(db_session: Session) -> None:
    """Catches a shortage that writes a partial assignment, state change, workbench item, or audit row."""
    run = transfer_run(db_session)
    terminal = transfer_terminal(db_session, run)
    required = requirement(db_session, run, terminal)

    with pytest.raises(PoolInsufficientError):
        service(db_session).allocate(run_id=str(run.id))

    db_session.rollback()
    assert db_session.get(CollectorRequirement, required.id).status == "unmatched"
    assert db_session.scalar(select(func.count(CollectorAssignment.id))) == 0
    assert db_session.scalar(select(func.count(CollectorWorkbenchItem.id))) == 0
    assert db_session.scalar(select(func.count(AuditLog.id))) == 0


def test_real_database_allocation_persists_and_retries_without_duplicate_audit(db_session: Session) -> None:
    """Catches random allocation changing on retry or appending duplicate assignments and audits."""
    run = transfer_run(db_session)
    terminal = transfer_terminal(db_session, run)
    required = requirement(db_session, run, terminal)
    physical = PhysicalCollector(id=uuid4(), team_id="team-1", collector_no="C-999", pool_status="available")
    db_session.add(physical)
    db_session.commit()
    collector_photo(db_session, physical)

    first = service(db_session).allocate(run_id=str(run.id))
    db_session.expire_all()
    second = service(db_session).allocate(run_id=str(run.id))

    assert first["assignment_count"] == 1
    assert second == {"run_id": str(run.id), "assignment_count": 1, "assignments": []}
    assert db_session.get(CollectorRequirement, required.id).status == "assigned"
    assert db_session.get(PhysicalCollector, physical.id).pool_status == "reserved"
    assert db_session.scalar(select(func.count(CollectorAssignment.id))) == 1
    assert db_session.scalar(select(func.count(CollectorWorkbenchItem.id))) == 1
    assert db_session.scalar(select(func.count(AuditLog.id))) == 1


def test_real_database_assignment_conflict_leaves_session_usable_and_reports_controlled_conflict(
    db_session: Session,
) -> None:
    """Catches allocation leaving PendingRollback after a unique assignment collision instead of returning a domain conflict."""
    run = transfer_run(db_session)
    terminal = transfer_terminal(db_session, run)
    required = requirement(db_session, run, terminal)
    physical = PhysicalCollector(id=uuid4(), team_id="team-1", collector_no="C-999", pool_status="available")
    db_session.add(physical)
    db_session.commit()
    photo = collector_photo(db_session, physical)
    conflicting_requirement = requirement(
        db_session, run, transfer_terminal(db_session, run, code="T-002"), collector_no="C-888", status="assigned"
    )
    db_session.add(
        CollectorAssignment(
            id=uuid4(), run_id=run.id, team_id="team-1", requirement_id=conflicting_requirement.id,
            physical_collector_id=physical.id, collector_photo_id=photo.id, assignment_mode="random", status="reserved",
        )
    )
    db_session.commit()

    with pytest.raises(CollectorAllocationConflictError):
        service(db_session).allocate(run_id=str(run.id))

    assert db_session.scalar(select(func.count(CollectorAssignment.id))) == 1
    assert db_session.get(CollectorRequirement, required.id).status == "unmatched"


@pytest.mark.parametrize(
    ("assignment_status", "physical_status", "requirement_status"),
    [("reserved", "reserved", "assigned"), ("used", "used", "used")],
)
def test_real_database_rescan_of_random_replacement_never_returns_pool_decision(
    db_session: Session,
    assignment_status: str,
    physical_status: str,
    requirement_status: str,
) -> None:
    """Catches a replacement whose physical number differs from the original being sent back to the pool."""
    run = transfer_run(db_session)
    terminal = transfer_terminal(db_session, run)
    required = requirement(
        db_session,
        run,
        terminal,
        collector_no="ORIGINAL-001",
        status=requirement_status,
    )
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        collector_no="REPLACEMENT-999",
        pool_status=physical_status,
    )
    db_session.add(physical)
    db_session.commit()
    photo = collector_photo(db_session, physical)
    assigned = CollectorAssignment(
        id=uuid4(),
        run_id=run.id,
        team_id="team-1",
        requirement_id=required.id,
        physical_collector_id=physical.id,
        collector_photo_id=photo.id,
        assignment_mode="random",
        status=assignment_status,
    )
    db_session.add(assigned)
    db_session.commit()

    result = service(db_session).scan_collector(run_id=str(run.id), collector_no="REPLACEMENT-999")

    event = db_session.scalar(
        select(CollectorScanEvent)
        .where(
            CollectorScanEvent.run_id == run.id,
            CollectorScanEvent.physical_collector_id == physical.id,
        )
        .order_by(CollectorScanEvent.created_at.desc(), CollectorScanEvent.id.desc())
    )
    db_session.refresh(physical)
    db_session.refresh(required)
    db_session.refresh(assigned)
    assert result["decision"] == "assignment_reuse"
    assert result["requires_photo"] is False
    assert result["add_to_pool"] is False
    assert result["pool_status"] == physical_status
    assert event.decision == "assignment_reuse"
    assert event.requires_photo is False
    assert event.add_to_pool is False
    assert physical.pool_status == physical_status
    assert required.status == requirement_status
    assert assigned.assignment_mode == "random"
    assert assigned.status == assignment_status
