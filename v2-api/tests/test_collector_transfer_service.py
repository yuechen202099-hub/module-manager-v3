from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects import postgresql
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
    CollectorMeterItem,
    CollectorPhoto,
    CollectorRequirement,
    CollectorScanEvent,
    CollectorTransferRun,
    CollectorTransferTerminal,
    CollectorWorkbenchItem,
    GroupBarcodeVerification,
    GroupStatus,
    MaterialGroup,
    PhysicalCollector,
    Photo,
    Project,
    ProjectStatus,
    Team,
    Task,
    TaskStatus,
    TotalCatalogRow,
    User,
)
from app.services.collector_transfer import (
    CollectorAllocationConflictError,
    CollectorPhotoConflictError,
    CollectorSnapshotChangedError,
    CollectorWorkbenchIncompleteError,
    PostgresCollectorTransferService,
    TerminalNotFoundError,
    TerminalSourceChangedError,
    _photo_snapshot,
    meter_sources_from_groups,
)
from app.services import photo_barcode_check
from app.services.state_repository import PostgresStateRepository


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
        team_id=collector.team_id,
        project_id=collector.project_id,
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


def set_manual_classification_confirmation(
    session: Session,
    group: MaterialGroup,
) -> None:
    """Represent a manual confirmation of the group's current active-photo evidence."""
    session.flush()
    photos = list(
        session.scalars(
            select(Photo)
            .where(
                Photo.group_id == group.id,
                Photo.is_active.is_(True),
            )
            .order_by(Photo.sort_order, Photo.id)
        ).all()
    )
    raw_data = dict(group.raw_data or {})
    raw_data["classification_manual_confirmation"] = {
        "actor": "fixture-admin",
        "confirmed_at": "2026-08-27T12:00:00+08:00",
        "acknowledged_anomalies": False,
        "anomalies": [],
        "photo_snapshot": [
            {
                "photo_id": str(photo.legacy_id or photo.id),
                "category": str(photo.category or "unclassified"),
                "sha256": str(photo.sha256 or ""),
            }
            for photo in photos
        ],
    }
    group.raw_data = raw_data


def clear_manual_classification_confirmation(group: MaterialGroup) -> None:
    """Represent a group whose current classification has not been manually confirmed."""
    raw_data = dict(group.raw_data or {})
    raw_data.pop("classification_manual_confirmation", None)
    group.raw_data = raw_data


def project_with_collector_requirement(
    session: Session,
    *,
    collector_no: str,
) -> tuple[Project, MaterialGroup]:
    project = session.scalar(select(Project).where(Project.team_id == "team-1"))
    group = MaterialGroup(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        terminal=f"T-{collector_no}",
        meter_match_key=f"M-{collector_no}",
        display_meter_no=f"M-{collector_no}",
        installation_address="项目库存测试地址",
        raw_data={"collector": collector_no},
    )
    session.add(group)
    session.commit()
    return project, group


def complete_project_collector_source(
    session: Session,
    *,
    collector_no: str,
) -> tuple[Project, MaterialGroup]:
    project, group = project_with_collector_requirement(session, collector_no=collector_no)
    source_photos = (
            Photo(
                team_id="team-1",
                group_id=group.id,
                sha256=uuid4().hex * 2,
                object_key=f"source/{collector_no}/module-meter.jpg",
                image_url=f"/source/{collector_no}/module-meter.jpg",
                category="module_meter",
                collector=collector_no,
                asset_no=f"MODULE-{collector_no}",
                is_active=True,
            ),
            Photo(
                team_id="team-1",
                group_id=group.id,
                sha256=uuid4().hex * 2,
                object_key=f"source/{collector_no}/after-box.jpg",
                image_url=f"/source/{collector_no}/after-box.jpg",
                category="after_box",
                collector=collector_no,
                is_active=True,
            ),
        )
    session.add_all(source_photos)
    session.flush()
    set_manual_classification_confirmation(session, group)
    session.commit()
    return project, group


def add_global_terminal_source(
    session: Session,
    *,
    project: Project,
    terminal_code: str,
    meter_no: str,
    collector_no: str,
    authoritative_address: str,
    snapshot_address: str = "资料组快照地址",
    raw_collector_no: str | None = None,
    legacy_id: str | None = None,
    status: GroupStatus = GroupStatus.APPROVED,
    barcode_status: str = "passed",
) -> MaterialGroup:
    """Create one complete source row using the real catalog/photo precedence contract."""
    catalog = TotalCatalogRow(
        id=uuid4(),
        team_id=project.team_id,
        project_id=project.id,
        terminal=terminal_code,
        original_meter_no=meter_no,
        meter_match_key=meter_no,
        installation_address=authoritative_address,
        raw_data={},
    )
    group = MaterialGroup(
        id=uuid4(),
        team_id=project.team_id,
        project_id=project.id,
        total_catalog_row_id=catalog.id,
        legacy_id=legacy_id or meter_no,
        terminal=terminal_code,
        meter_match_key=meter_no,
        display_meter_no=meter_no,
        installation_address=snapshot_address,
        status=status,
        photo_count=2,
        raw_data={
            "collector": raw_collector_no or collector_no,
            "module_asset_no": f"MODULE-{meter_no}",
        },
    )
    session.add_all((catalog, group))
    session.flush()
    source_photos = (
            Photo(
                id=uuid4(),
                team_id=project.team_id,
                group_id=group.id,
                sha256=uuid4().hex * 2,
                object_key=f"global/{group.id}/module-meter.jpg",
                image_url=f"/global/{group.id}/module-meter.jpg",
                category="module_meter",
                collector=collector_no,
                asset_no=f"MODULE-{meter_no}",
                sort_order=0,
                is_active=True,
            ),
            Photo(
                id=uuid4(),
                team_id=project.team_id,
                group_id=group.id,
                sha256=uuid4().hex * 2,
                object_key=f"global/{group.id}/after-box.jpg",
                image_url=f"/global/{group.id}/after-box.jpg",
                category="after_box",
                sort_order=1,
                is_active=True,
            ),
        )
    session.add_all(source_photos)
    session.add(
        GroupBarcodeVerification(
            id=uuid4(),
            team_id=project.team_id,
            group_id=group.id,
            status=barcode_status,
            meter_matched=barcode_status in {"passed", "manual_confirmed"},
            module_matched=barcode_status in {"passed", "manual_confirmed"},
            collector_matched=barcode_status in {"passed", "manual_confirmed"},
            recognition_source="test",
        )
    )
    session.flush()
    set_manual_classification_confirmation(session, group)
    return group


def add_unconstructed_global_terminal_source(
    session: Session,
    *,
    project: Project,
    terminal_code: str,
    meter_no: str,
    authoritative_address: str,
    legacy_id: str | None = None,
) -> MaterialGroup:
    catalog = TotalCatalogRow(
        id=uuid4(),
        team_id=project.team_id,
        project_id=project.id,
        terminal=terminal_code,
        original_meter_no=meter_no,
        meter_match_key=meter_no,
        installation_address=authoritative_address,
        raw_data={},
    )
    group = MaterialGroup(
        id=uuid4(),
        team_id=project.team_id,
        project_id=project.id,
        total_catalog_row_id=catalog.id,
        legacy_id=legacy_id or meter_no,
        terminal=terminal_code,
        meter_match_key=meter_no,
        display_meter_no=meter_no,
        installation_address=f"旧-{authoritative_address}",
        status=GroupStatus.UNREVIEWED,
        photo_count=0,
        raw_data={},
    )
    session.add_all((catalog, group))
    session.flush()
    return group


def stored_photo(sha256_value: str) -> dict[str, object]:
    return {
        "sha256": sha256_value,
        "storage_key": f"collector-inventory/{sha256_value}.jpg",
        "url": f"/static/uploads/collector-inventory/{sha256_value}.jpg",
        "storage_type": "local_upload",
        "content_type": "image/jpeg",
    }


@pytest.mark.parametrize(
    ("raw_data", "photo_values", "candidate", "expected"),
    [
        ({"collector": "RAW-1"}, [(0, " PHOTO-1 ", True)], "PHOTO-1", True),
        ({"collector": "RAW-1"}, [(0, "   ", True)], "RAW-1", True),
        ({"采集器": "0000123"}, [], "0000123", True),
        ({"采集器号": "中文-采集器"}, [], "中文-采集器", True),
        ({"construction_collector": "ALIAS-4"}, [], "ALIAS-4", True),
        ({"collector": "RAW-1"}, [(0, "INACTIVE", False)], "RAW-1", True),
        ({"collector": "RAW-1"}, [(0, "FIRST", True), (1, "SECOND", True)], "SECOND", False),
        ({"collector": "RAW-TAB"}, [(0, "\tPHOTO-TAB\n", True)], "PHOTO-TAB", True),
        ({"collector": "\tRAW-FALLBACK\r\n"}, [(0, "\t\n", True)], "RAW-FALLBACK", True),
        ({"collector": "RAW-1"}, [(0, "\nPHOTO\tINNER\t", True)], "PHOTO\tINNER", True),
    ],
)
def test_project_has_collector_number_preserves_precedence(
    db_session: Session,
    raw_data: dict[str, str],
    photo_values: list[tuple[int, str, bool]],
    candidate: str,
    expected: bool,
) -> None:
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    group = MaterialGroup(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        terminal=f"T-{uuid4().hex}",
        meter_match_key=f"M-{uuid4().hex}",
        display_meter_no=f"M-{uuid4().hex}",
        installation_address="有界采集器查询测试地址",
        raw_data=raw_data,
    )
    db_session.add(group)
    for sort_order, collector, is_active in photo_values:
        db_session.add(
            Photo(
                id=uuid4(),
                team_id="team-1",
                group_id=group.id,
                sha256=uuid4().hex * 2,
                object_key=f"source/{uuid4().hex}.jpg",
                collector=collector,
                sort_order=sort_order,
                is_active=is_active,
            )
        )
    db_session.commit()

    assert service(db_session)._project_has_collector_number(project.id, candidate) is expected


def test_project_has_collector_number_does_not_match_another_project(
    db_session: Session,
) -> None:
    source_project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    other_project = Project(
        id=uuid4(),
        team_id="team-1",
        code=f"P-{uuid4().hex[:8]}",
        name="另一项目",
        status=ProjectStatus.ACTIVE,
        settings={},
    )
    db_session.add(other_project)
    db_session.add(
        MaterialGroup(
            id=uuid4(),
            team_id="team-1",
            project_id=other_project.id,
            terminal="T-OTHER-PROJECT",
            meter_match_key="M-OTHER-PROJECT",
            display_meter_no="M-OTHER-PROJECT",
            installation_address="另一项目地址",
            raw_data={"collector": "PROJECT-ONLY"},
        )
    )
    db_session.commit()

    assert service(db_session)._project_has_collector_number(source_project.id, "PROJECT-ONLY") is False


def test_project_has_collector_number_does_not_match_another_team(
    db_session: Session,
) -> None:
    source_project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    foreign_project = Project(
        id=uuid4(),
        team_id="team-2",
        code=f"P-{uuid4().hex[:8]}",
        name="另一团队项目",
        status=ProjectStatus.ACTIVE,
        settings={},
    )
    db_session.add(Team(id="team-2", name="另一团队"))
    db_session.add(foreign_project)
    db_session.add(
        MaterialGroup(
            id=uuid4(),
            team_id="team-2",
            project_id=foreign_project.id,
            terminal="T-OTHER-TEAM",
            meter_match_key="M-OTHER-TEAM",
            display_meter_no="M-OTHER-TEAM",
            installation_address="另一团队地址",
            raw_data={"collector": "TEAM-ONLY"},
        )
    )
    db_session.commit()

    assert service(db_session)._project_has_collector_number(source_project.id, "TEAM-ONLY") is False


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


def test_non_direct_project_scan_leaves_no_business_rows(db_session: Session) -> None:
    """Catches persisting a server draft before a non-matching collector has a valid photo."""
    current_project_id = project_id(db_session)

    result = service(db_session).scan_inventory(
        project_id=str(current_project_id),
        collector_no=" POOL-001 ",
    )

    assert result["decision"] == "pool_needs_photo"
    assert result["collector_no"] == "POOL-001"
    assert db_session.scalar(select(func.count(PhysicalCollector.id))) == 0
    assert db_session.scalar(select(func.count(CollectorPhoto.id))) == 0
    assert db_session.scalar(select(func.count(CollectorScanEvent.id))) == 0
    assert db_session.scalar(select(func.count(AuditLog.id))) == 0


def test_direct_project_scan_without_photo_persists_only_confirmation(db_session: Session) -> None:
    """Catches asking for a website photo after the same-number physical was scanned in hand."""
    project, _group = project_with_collector_requirement(db_session, collector_no="DIRECT-001")

    result = service(db_session).scan_inventory(
        project_id=str(project.id),
        collector_no="DIRECT-001",
    )

    physical = db_session.scalar(select(PhysicalCollector))
    assert result["decision"] == "direct_reuse"
    assert result["requires_photo"] is False
    assert result["add_to_pool"] is False
    assert physical.project_id == project.id
    assert physical.pool_status == "direct"
    assert db_session.scalar(select(func.count(CollectorPhoto.id))) == 0
    assert db_session.scalar(select(func.count(CollectorScanEvent.id))) == 1


def test_non_direct_photo_atomically_creates_available_inventory(db_session: Session) -> None:
    """Catches saving only the barcode or leaving a photographed replacement unavailable."""
    current_project_id = project_id(db_session)

    result = service(db_session).register_inventory(
        project_id=str(current_project_id),
        collector_no="POOL-001",
        original_filename="POOL-001.jpg",
        stored=stored_photo("a1" * 32),
        byte_size=128,
    )

    physical = db_session.scalar(select(PhysicalCollector))
    photo = db_session.scalar(select(CollectorPhoto))
    assert result["pool_status"] == "available"
    assert physical.project_id == current_project_id
    assert physical.pool_status == "available"
    assert photo.project_id == current_project_id
    assert photo.physical_collector_id == physical.id
    assert db_session.scalar(select(func.count(CollectorScanEvent.id))) == 1


def test_project_inventory_same_number_and_photo_are_idempotent(db_session: Session) -> None:
    """Catches duplicate retries creating a second physical collector or collector photo."""
    current_project_id = project_id(db_session)
    first = service(db_session).register_inventory(
        project_id=str(current_project_id),
        collector_no="POOL-IDEMPOTENT",
        original_filename="POOL-IDEMPOTENT.jpg",
        stored=stored_photo("a2" * 32),
        byte_size=128,
    )

    second = service(db_session).register_inventory(
        project_id=str(current_project_id),
        collector_no="POOL-IDEMPOTENT",
        original_filename="retry.jpg",
        stored=stored_photo("a2" * 32),
        byte_size=128,
    )

    assert second["collector_id"] == first["collector_id"]
    assert second["photo"]["id"] == first["photo"]["id"]
    assert db_session.scalar(select(func.count(PhysicalCollector.id))) == 1
    assert db_session.scalar(select(func.count(CollectorPhoto.id))) == 1


def test_project_inventory_rejects_same_photo_for_another_collector(db_session: Session) -> None:
    """Catches one physical collector photo being admitted under two barcodes in one project."""
    current_project_id = project_id(db_session)
    service(db_session).register_inventory(
        project_id=str(current_project_id),
        collector_no="POOL-FIRST",
        original_filename="POOL-FIRST.jpg",
        stored=stored_photo("a3" * 32),
        byte_size=128,
    )

    with pytest.raises(CollectorPhotoConflictError, match="another physical collector"):
        service(db_session).register_inventory(
            project_id=str(current_project_id),
            collector_no="POOL-SECOND",
            original_filename="POOL-SECOND.jpg",
            stored=stored_photo("a3" * 32),
            byte_size=128,
        )

    db_session.rollback()
    assert db_session.scalar(select(func.count(PhysicalCollector.id))) == 1
    assert db_session.scalar(select(func.count(CollectorPhoto.id))) == 1


def test_project_inventory_rejects_a_second_active_photo_for_one_collector(
    db_session: Session,
) -> None:
    """Catches a retry with different image content bypassing the one-active-photo invariant."""
    current_project_id = project_id(db_session)
    service(db_session).register_inventory(
        project_id=str(current_project_id),
        collector_no="POOL-ONE-PHOTO",
        original_filename="first.jpg",
        stored=stored_photo("a4" * 32),
        byte_size=128,
    )

    with pytest.raises(CollectorPhotoConflictError, match="active photo"):
        service(db_session).register_inventory(
            project_id=str(current_project_id),
            collector_no="POOL-ONE-PHOTO",
            original_filename="second.jpg",
            stored=stored_photo("a5" * 32),
            byte_size=128,
        )

    db_session.rollback()
    assert db_session.scalar(select(func.count(CollectorPhoto.id))) == 1


def test_project_inventory_allows_same_number_and_photo_in_two_projects(
    db_session: Session,
) -> None:
    """Catches accidentally retaining team-wide barcode or SHA uniqueness."""
    first_project_id = project_id(db_session)
    second_project = Project(
        id=uuid4(),
        team_id="team-1",
        code=f"P-{uuid4().hex[:8]}",
        name="第二个项目",
        status=ProjectStatus.ACTIVE,
        settings={},
    )
    db_session.add(second_project)
    db_session.commit()

    first = service(db_session).register_inventory(
        project_id=str(first_project_id),
        collector_no="SAME-001",
        original_filename="same.jpg",
        stored=stored_photo("a6" * 32),
        byte_size=128,
    )
    second = service(db_session).register_inventory(
        project_id=str(second_project.id),
        collector_no="SAME-001",
        original_filename="same.jpg",
        stored=stored_photo("a6" * 32),
        byte_size=128,
    )

    assert first["collector_id"] != second["collector_id"]
    assert db_session.scalar(select(func.count(PhysicalCollector.id))) == 2
    assert db_session.scalar(select(func.count(CollectorPhoto.id))) == 2


@pytest.mark.parametrize("terminal_status", ["reserved", "used"])
def test_project_inventory_retry_never_demotes_consumed_status(
    db_session: Session,
    terminal_status: str,
) -> None:
    """Catches a repeated inventory upload returning consumed stock to the random pool."""
    current_project_id = project_id(db_session)
    sha256_value = ("a7" if terminal_status == "reserved" else "a8") * 32
    registered = service(db_session).register_inventory(
        project_id=str(current_project_id),
        collector_no=f"POOL-{terminal_status}",
        original_filename="terminal.jpg",
        stored=stored_photo(sha256_value),
        byte_size=128,
    )
    physical = db_session.get(PhysicalCollector, UUID(registered["collector_id"]))
    physical.pool_status = terminal_status
    db_session.commit()

    retried = service(db_session).register_inventory(
        project_id=str(current_project_id),
        collector_no=physical.collector_no,
        original_filename="retry.jpg",
        stored=stored_photo(sha256_value),
        byte_size=128,
    )

    assert retried["pool_status"] == terminal_status
    assert db_session.get(PhysicalCollector, physical.id).pool_status == terminal_status


def test_project_inventory_retry_never_demotes_direct_to_available(
    db_session: Session,
) -> None:
    """Catches a direct confirmation entering the random pool after source data later changes."""
    current_project_id = project_id(db_session)
    physical = PhysicalCollector(
        team_id="team-1",
        project_id=current_project_id,
        collector_no="DIRECT-PRESERVED",
        pool_status="direct",
    )
    db_session.add(physical)
    db_session.commit()
    photo = collector_photo(db_session, physical, sha256="b5" * 32)

    retried = service(db_session).register_inventory(
        project_id=str(current_project_id),
        collector_no=physical.collector_no,
        original_filename="retry.jpg",
        stored={
            "sha256": photo.sha256,
            "storage_key": photo.object_key,
            "storage_type": photo.storage_type,
        },
        byte_size=128,
    )

    assert retried["pool_status"] == "direct"
    assert db_session.get(PhysicalCollector, physical.id).pool_status == "direct"


def test_project_inventory_list_is_project_scoped_and_filters_available_only(
    db_session: Session,
) -> None:
    """Catches list or pool candidates mixing direct/legacy rows or another project."""
    current_project_id = project_id(db_session)
    project_with_collector_requirement(db_session, collector_no="DIRECT-LIST")
    service(db_session).register_inventory(
        project_id=str(current_project_id),
        collector_no="DIRECT-LIST",
        original_filename="direct.jpg",
        stored=stored_photo("a9" * 32),
        byte_size=128,
    )
    service(db_session).register_inventory(
        project_id=str(current_project_id),
        collector_no="POOL-LIST",
        original_filename="pool.jpg",
        stored=stored_photo("b1" * 32),
        byte_size=128,
    )
    db_session.add(
        PhysicalCollector(
            team_id="team-1",
            project_id=current_project_id,
            collector_no="LEGACY-LIST",
            pool_status="awaiting_photo",
        )
    )
    other_project = Project(
        id=uuid4(),
        team_id="team-1",
        code=f"P-{uuid4().hex[:8]}",
        name="隔离项目",
        status=ProjectStatus.ACTIVE,
        settings={},
    )
    db_session.add(other_project)
    db_session.flush()
    db_session.add(
        PhysicalCollector(
            team_id="team-1",
            project_id=other_project.id,
            collector_no="OTHER-AVAILABLE",
            pool_status="available",
        )
    )
    db_session.commit()

    complete = service(db_session).list_inventory(project_id=str(current_project_id))
    available = service(db_session).list_inventory(
        project_id=str(current_project_id),
        status="available",
    )

    assert complete["total"] == 3
    assert complete["stats"] == {
        "direct": 1,
        "available": 1,
        "reserved": 0,
        "used": 0,
        "awaiting_photo": 1,
    }
    assert [item["collector_no"] for item in available["items"]] == ["POOL-LIST"]
    assert available["total"] == 1


def test_inventory_photo_region_scan_uses_the_current_project_photo(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches scanning a thumbnail, foreign photo, or whole image instead of the selected region."""
    current_project_id = project_id(db_session)
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=current_project_id,
        collector_no="OCR-WRONG",
        pool_status="available",
    )
    db_session.add(physical)
    db_session.commit()
    photo = collector_photo(db_session, physical, sha256="c1" * 32)
    observed: dict[str, object] = {}

    def scan(photo_payload, barcode_type, region):
        observed.update(
            photo=photo_payload,
            barcode_type=barcode_type,
            region=dict(region),
        )
        return {
            "barcode_type": "collector",
            "values": ["COLLECTOR-001"],
            "normalized_values": ["COLLECTOR-001"],
            "method": "barcode",
            "region": dict(region),
        }

    monkeypatch.setattr(photo_barcode_check, "scan_photo_region", scan)
    selected = {"x": 0.1, "y": 0.2, "width": 0.7, "height": 0.3}

    result = service(db_session).scan_inventory_photo_region(
        project_id=str(current_project_id),
        collector_id=str(physical.id),
        expected_collector_no="OCR-WRONG",
        expected_photo_sha256=photo.sha256,
        region=selected,
    )

    assert result["normalized_values"] == ["COLLECTOR-001"]
    assert observed["barcode_type"] == "collector"
    assert observed["region"] == selected
    assert observed["photo"] == {
        "id": str(photo.id),
        "image_url": "",
        "object_key": photo.object_key,
        "storage_type": "local_upload",
        "sha256": photo.sha256,
        "content_type": "",
    }


def test_inventory_photo_region_scan_rejects_a_stale_photo_snapshot(
    db_session: Session,
) -> None:
    """Catches a stale modal scanning a newly replaced collector photo."""
    current_project_id = project_id(db_session)
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=current_project_id,
        collector_no="OCR-WRONG",
        pool_status="available",
    )
    db_session.add(physical)
    db_session.commit()
    collector_photo(db_session, physical, sha256="c3" * 32)

    with pytest.raises(ValueError) as raised:
        service(db_session).scan_inventory_photo_region(
            project_id=str(current_project_id),
            collector_id=str(physical.id),
            expected_collector_no="OCR-WRONG",
            expected_photo_sha256="stale-photo-sha",
            region={"x": 0.1, "y": 0.2, "width": 0.7, "height": 0.3},
        )

    assert type(raised.value).__name__ == "CollectorInventorySnapshotChangedError"


def test_inventory_number_correction_reuses_the_photo_and_rematches_direct(
    db_session: Session,
) -> None:
    """Catches a corrected same-number collector remaining in the random replacement pool."""
    project, _group = project_with_collector_requirement(
        db_session,
        collector_no="DIRECT-CORRECTED",
    )
    actor_user(db_session)
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="OCR-WRONG",
        pool_status="available",
    )
    db_session.add(physical)
    db_session.commit()
    photo = collector_photo(db_session, physical, sha256="c2" * 32)
    selected = {"x": 0.12, "y": 0.22, "width": 0.66, "height": 0.24}

    result = service(db_session).correct_inventory_number(
        project_id=str(project.id),
        collector_id=str(physical.id),
        expected_collector_no="OCR-WRONG",
        expected_photo_sha256=photo.sha256,
        collector_no="DIRECT-CORRECTED",
        recognition_method="barcode",
        region=selected,
    )

    db_session.refresh(physical)
    db_session.refresh(photo)
    event = db_session.scalar(
        select(CollectorScanEvent)
        .where(CollectorScanEvent.physical_collector_id == physical.id)
        .order_by(CollectorScanEvent.created_at.desc(), CollectorScanEvent.id.desc())
    )
    audit = db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "collector_transfer.inventory_number_corrected",
            AuditLog.entity_id == physical.id,
        )
    )

    assert result["collector_no"] == "DIRECT-CORRECTED"
    assert result["decision"] == "direct_reuse"
    assert result["pool_status"] == "direct"
    assert physical.collector_no == "DIRECT-CORRECTED"
    assert physical.pool_status == "direct"
    assert photo.physical_collector_id == physical.id
    assert event.scanned_value == "DIRECT-CORRECTED"
    assert event.decision == "direct_reuse"
    assert audit.actor_username == "operator"
    assert audit.payload == {
        "before_collector_no": "OCR-WRONG",
        "after_collector_no": "DIRECT-CORRECTED",
        "before_pool_status": "available",
        "after_pool_status": "direct",
        "recognition_method": "barcode",
        "region": selected,
        "photo_id": str(photo.id),
        "photo_sha256": photo.sha256,
    }


def test_inventory_number_correction_without_photo_requires_a_photo_for_pool(
    db_session: Session,
) -> None:
    """Catches a corrected non-matching collector entering the pool without evidence."""
    current_project_id = project_id(db_session)
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=current_project_id,
        collector_no="DIRECT-WRONG",
        pool_status="direct",
    )
    db_session.add(physical)
    db_session.commit()

    result = service(db_session).correct_inventory_number(
        project_id=str(current_project_id),
        collector_id=str(physical.id),
        expected_collector_no="DIRECT-WRONG",
        expected_photo_sha256="",
        collector_no="POOL-CORRECTED",
        recognition_method="manual",
        region=None,
    )

    db_session.refresh(physical)
    assert result["requires_photo"] is True
    assert result["pool_status"] == "awaiting_photo"
    assert physical.collector_no == "POOL-CORRECTED"
    assert physical.pool_status == "awaiting_photo"


@pytest.mark.parametrize("pool_status", ["reserved", "used"])
def test_inventory_number_correction_blocks_consumed_collectors(
    db_session: Session,
    pool_status: str,
) -> None:
    """Catches editing an allocated collector without first rolling its assignment back."""
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project_id(db_session),
        collector_no=f"LOCKED-{pool_status}",
        pool_status=pool_status,
    )
    db_session.add(physical)
    db_session.commit()

    with pytest.raises(ValueError, match="rollback") as raised:
        service(db_session).correct_inventory_number(
            project_id=str(physical.project_id),
            collector_id=str(physical.id),
            expected_collector_no=physical.collector_no,
            expected_photo_sha256="",
            collector_no=f"CORRECTED-{pool_status}",
            recognition_method="manual",
            region=None,
        )

    assert type(raised.value).__name__ == "CollectorInventoryAssignmentLockedError"
    db_session.refresh(physical)
    assert physical.collector_no == f"LOCKED-{pool_status}"


def test_inventory_number_correction_blocks_active_direct_assignment(
    db_session: Session,
) -> None:
    """Catches a reserved direct assignment staying editable because its pool status remains direct."""
    run = transfer_run(db_session)
    terminal = transfer_terminal(db_session, run)
    direct_requirement = requirement(
        db_session,
        run,
        terminal,
        collector_no="DIRECT-ASSIGNED",
        status="direct_ready",
    )
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=run.project_id,
        collector_no="DIRECT-ASSIGNED",
        pool_status="direct",
    )
    db_session.add(physical)
    db_session.commit()
    photo = collector_photo(db_session, physical, sha256="d1" * 32)
    db_session.add(
        CollectorAssignment(
            id=uuid4(),
            run_id=run.id,
            team_id="team-1",
            requirement_id=direct_requirement.id,
            physical_collector_id=physical.id,
            collector_photo_id=photo.id,
            assignment_mode="direct",
            status="reserved",
            assigned_by_username="operator",
        )
    )
    db_session.commit()

    listed = service(db_session).list_inventory(project_id=str(run.project_id))
    listed_item = next(
        item for item in listed["items"] if item["collector_id"] == str(physical.id)
    )
    assert listed_item["number_correction_locked"] is True

    with pytest.raises(ValueError, match="rollback") as raised:
        service(db_session).correct_inventory_number(
            project_id=str(run.project_id),
            collector_id=str(physical.id),
            expected_collector_no="DIRECT-ASSIGNED",
            expected_photo_sha256=photo.sha256,
            collector_no="DIRECT-CORRECTED",
            recognition_method="manual",
            region=None,
        )

    assert type(raised.value).__name__ == "CollectorInventoryAssignmentLockedError"
    db_session.refresh(physical)
    assert physical.collector_no == "DIRECT-ASSIGNED"


def test_inventory_number_correction_blocks_active_assignmentless_direct_workbench(
    db_session: Session,
) -> None:
    """Catches renumbering a direct-ready physical while its workbench still claims the old number."""
    run = transfer_run(db_session)
    run.stats = {"workflow_kind": "global_terminal_workbench", "superseded": False}
    terminal = transfer_terminal(db_session, run)
    direct_requirement = requirement(
        db_session,
        run,
        terminal,
        collector_no="DIRECT-WORKBENCH",
        status="direct_ready",
    )
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=run.project_id,
        collector_no="DIRECT-WORKBENCH",
        pool_status="direct",
    )
    db_session.add_all(
        [
            physical,
            CollectorWorkbenchItem(
                id=uuid4(),
                run_id=run.id,
                terminal_id=terminal.id,
                team_id="team-1",
                item_kind="collector_removal",
                source_key=str(direct_requirement.id),
                requirement_id=direct_requirement.id,
                assignment_id=None,
                status="pending",
                sort_order=0,
            ),
        ]
    )
    db_session.commit()

    with pytest.raises(ValueError, match="rollback") as raised:
        service(db_session).correct_inventory_number(
            project_id=str(run.project_id),
            collector_id=str(physical.id),
            expected_collector_no="DIRECT-WORKBENCH",
            expected_photo_sha256="",
            collector_no="DIRECT-CORRECTED",
            recognition_method="manual",
            region=None,
        )

    assert type(raised.value).__name__ == "CollectorInventoryAssignmentLockedError"
    db_session.refresh(physical)
    assert physical.collector_no == "DIRECT-WORKBENCH"


def test_inventory_number_correction_does_not_lock_the_duplicate_target_row(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches A-to-B and B-to-A corrections deadlocking on each other's target row."""
    current_project_id = project_id(db_session)
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=current_project_id,
        collector_no="SOURCE-NO",
        pool_status="available",
    )
    db_session.add(physical)
    db_session.commit()
    original_scalar = db_session.scalar

    def reject_target_row_lock(statement, *args, **kwargs):
        sql = str(statement.compile(dialect=postgresql.dialect()))
        if (
            "physical_collectors.id !=" in sql
            and getattr(statement, "_for_update_arg", None) is not None
        ):
            raise RuntimeError("duplicate target row lock requested")
        return original_scalar(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "scalar", reject_target_row_lock)

    result = service(db_session).correct_inventory_number(
        project_id=str(current_project_id),
        collector_id=str(physical.id),
        expected_collector_no="SOURCE-NO",
        expected_photo_sha256="",
        collector_no="TARGET-NO",
        recognition_method="manual",
        region=None,
    )

    assert result["collector_no"] == "TARGET-NO"


def test_inventory_number_correction_rejects_stale_or_duplicate_targets(
    db_session: Session,
) -> None:
    """Catches stale pages overwriting newer numbers or silently merging two physical devices."""
    current_project_id = project_id(db_session)
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=current_project_id,
        collector_no="CURRENT-NO",
        pool_status="available",
    )
    duplicate = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=current_project_id,
        collector_no="DUPLICATE-NO",
        pool_status="available",
    )
    db_session.add_all([physical, duplicate])
    db_session.commit()

    with pytest.raises(ValueError, match="changed") as stale:
        service(db_session).correct_inventory_number(
            project_id=str(current_project_id),
            collector_id=str(physical.id),
            expected_collector_no="STALE-NO",
            expected_photo_sha256="",
            collector_no="NEW-NO",
            recognition_method="manual",
            region=None,
        )
    with pytest.raises(ValueError, match="already exists") as duplicate_error:
        service(db_session).correct_inventory_number(
            project_id=str(current_project_id),
            collector_id=str(physical.id),
            expected_collector_no="CURRENT-NO",
            expected_photo_sha256="",
            collector_no="DUPLICATE-NO",
            recognition_method="manual",
            region=None,
        )

    assert type(stale.value).__name__ == "CollectorInventorySnapshotChangedError"
    assert type(duplicate_error.value).__name__ == "CollectorInventoryNumberConflictError"
    db_session.refresh(physical)
    assert physical.collector_no == "CURRENT-NO"


def test_archived_project_inventory_request_has_zero_side_effects(db_session: Session) -> None:
    """Catches archived projects accepting new inventory after being taken out of service."""
    project = db_session.get(Project, project_id(db_session))
    project.status = ProjectStatus.ARCHIVED
    project.archived_at = datetime.now(UTC)
    db_session.commit()

    with pytest.raises(KeyError):
        service(db_session).register_inventory(
            project_id=str(project.id),
            collector_no="ARCHIVED-001",
            original_filename="archived.jpg",
            stored=stored_photo("b2" * 32),
            byte_size=128,
        )

    assert db_session.scalar(select(func.count(PhysicalCollector.id))) == 0
    assert db_session.scalar(select(func.count(CollectorPhoto.id))) == 0


def test_cross_team_and_unknown_projects_have_zero_inventory_side_effects(
    db_session: Session,
) -> None:
    """Catches authenticated team scope being bypassed by a caller-supplied project ID."""
    db_session.add(Team(id="team-2", name="另一个团队"))
    foreign_project = Project(
        id=uuid4(),
        team_id="team-2",
        code=f"P-{uuid4().hex[:8]}",
        name="其他团队项目",
        status=ProjectStatus.ACTIVE,
        settings={},
    )
    db_session.add(foreign_project)
    db_session.commit()

    for rejected_project_id in (foreign_project.id, uuid4()):
        with pytest.raises(KeyError):
            service(db_session).scan_inventory(
                project_id=str(rejected_project_id),
                collector_no="FORBIDDEN-001",
            )

    assert db_session.scalar(select(func.count(PhysicalCollector.id))) == 0
    assert db_session.scalar(select(func.count(CollectorPhoto.id))) == 0
    assert db_session.scalar(select(func.count(CollectorScanEvent.id))) == 0


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


def test_project_meter_projection_preserves_full_orm_parity_without_loading_source_entities(
    db_session: Session,
) -> None:
    """Catches selected-column projection changing precedence/snapshots or hydrating source ORM rows."""
    current_project_id = project_id(db_session)
    blank_group = MaterialGroup(
        id=UUID("a0000000-0000-0000-0000-000000000001"),
        team_id="team-1",
        project_id=current_project_id,
        terminal=" ",
        meter_match_key="PROJECTION-BLANK",
        display_meter_no="",
        installation_address="空终端地址",
        raw_data={"collector": "RAW-COLLECTOR", "module_asset_no": "RAW-MODULE"},
    )
    photographed_group = MaterialGroup(
        id=UUID("a0000000-0000-0000-0000-000000000002"),
        team_id="team-1",
        project_id=current_project_id,
        terminal="T-002",
        meter_match_key="PROJECTION-PHOTO",
        display_meter_no="M-002",
        installation_address="照片优先地址",
        raw_data={"collector": "RAW-SHOULD-LOSE"},
    )
    missing_group = MaterialGroup(
        id=UUID("a0000000-0000-0000-0000-000000000003"),
        team_id="team-1",
        project_id=current_project_id,
        terminal="T-003",
        meter_match_key="PROJECTION-MISSING",
        display_meter_no="M-003",
        installation_address="诊断地址",
        raw_data={},
    )
    local_module = Photo(
        id=UUID("b0000000-0000-0000-0000-000000000001"),
        team_id="team-1",
        group_id=blank_group.id,
        sha256="1" * 64,
        object_key="source/local-module.jpg",
        image_url="/source/local-module.jpg",
        storage_type="local_upload",
        storage_key="source/local-module.jpg",
        content_type="image/jpeg",
        category="module_meter",
        collector=" ",
        asset_no=" ",
        sort_order=0,
        is_active=True,
    )
    local_after = Photo(
        id=UUID("b0000000-0000-0000-0000-000000000002"),
        team_id="team-1",
        group_id=blank_group.id,
        sha256="2" * 64,
        object_key="source/local-after.jpg",
        image_url="/source/local-after.jpg",
        category="after_box",
        collector="",
        sort_order=1,
        is_active=True,
    )
    inactive = Photo(
        id=UUID("b0000000-0000-0000-0000-000000000003"),
        team_id="team-1",
        group_id=blank_group.id,
        sha256="3" * 64,
        object_key="source/inactive.jpg",
        category="before_box",
        collector="INACTIVE-MUST-NOT-WIN",
        sort_order=-1,
        is_active=False,
    )
    oss_module = Photo(
        id=UUID("b0000000-0000-0000-0000-000000000004"),
        team_id="team-1",
        group_id=photographed_group.id,
        sha256="4" * 64,
        object_key="source/oss-module.jpg",
        storage_type="oss",
        storage_bucket="evidence-bucket",
        storage_key="project/oss-module.jpg",
        content_type="image/jpeg",
        category="module_meter",
        collector="",
        asset_no="MODULE-PHOTO",
        sort_order=0,
        is_active=True,
    )
    oss_after = Photo(
        id=UUID("b0000000-0000-0000-0000-000000000005"),
        team_id="team-1",
        group_id=photographed_group.id,
        sha256="5" * 64,
        object_key="source/oss-after.jpg",
        storage_type="oss",
        storage_bucket="evidence-bucket",
        storage_key="project/oss-after.jpg",
        category="after_box",
        collector="PHOTO-COLLECTOR",
        sort_order=1,
        is_active=True,
    )
    reference_groups = (blank_group, photographed_group, missing_group)
    reference_photos = (local_module, local_after, inactive, oss_module, oss_after)
    db_session.add_all((*reference_groups, *reference_photos))
    db_session.commit()
    expected_projection = meter_sources_from_groups(reference_groups, reference_photos)
    expected_snapshots = {
        str(local_module.id): {
            "id": str(local_module.id),
            "image_url": "/source/local-module.jpg",
            "object_key": "source/local-module.jpg",
            "storage_type": "local_upload",
            "storage_key": "source/local-module.jpg",
            "storage_bucket": "",
            "sha256": "1" * 64,
            "content_type": "image/jpeg",
        },
        str(oss_module.id): {
            "id": str(oss_module.id),
            "image_url": "",
            "object_key": "source/oss-module.jpg",
            "storage_type": "oss",
            "storage_key": "project/oss-module.jpg",
            "storage_bucket": "evidence-bucket",
            "sha256": "4" * 64,
            "content_type": "image/jpeg",
        },
    }
    loaded_source_entities: list[object] = []
    recorded_selects: list[str] = []

    def record_loaded(_session: Session, instance: object) -> None:
        if isinstance(instance, (MaterialGroup, Photo)):
            loaded_source_entities.append(instance)

    def record_sql(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            recorded_selects.append(statement)

    with Session(db_session.bind) as projection_session:
        event.listen(projection_session, "loaded_as_persistent", record_loaded)
        event.listen(db_session.bind, "before_cursor_execute", record_sql)
        try:
            projection, photos = service(projection_session)._project_meter_projection(current_project_id)
        finally:
            event.remove(db_session.bind, "before_cursor_execute", record_sql)
            event.remove(projection_session, "loaded_as_persistent", record_loaded)

    source_selects = [
        statement
        for statement in recorded_selects
        if "FROM MATERIAL_GROUPS" in statement.upper() or "FROM PHOTOS" in statement.upper()
    ]
    assert projection == expected_projection
    assert projection.diagnostics == (
        {"group_id": str(blank_group.id), "code": "terminal_missing", "message": "终端地址码为空"},
        {"group_id": str(blank_group.id), "code": "meter_missing", "message": "meter_missing"},
        {"group_id": str(missing_group.id), "code": "collector_missing", "message": "collector_missing"},
        {"group_id": str(missing_group.id), "code": "module_missing", "message": "module_missing"},
        {"group_id": str(missing_group.id), "code": "module_meter_photo_missing", "message": "module_meter_photo_missing"},
        {"group_id": str(missing_group.id), "code": "after_box_photo_missing", "message": "after_box_photo_missing"},
    )
    photos_by_id = {str(photo.id): photo for photo in photos}
    assert _photo_snapshot(photos_by_id[str(local_module.id)]) == expected_snapshots[str(local_module.id)]
    assert _photo_snapshot(photos_by_id[str(oss_module.id)]) == expected_snapshots[str(oss_module.id)]
    assert loaded_source_entities == []
    assert len(source_selects) == 2
    assert "ORDER BY MATERIAL_GROUPS.TERMINAL, MATERIAL_GROUPS.DISPLAY_METER_NO, MATERIAL_GROUPS.ID" in source_selects[0].upper()
    assert "JOIN MATERIAL_GROUPS ON PHOTOS.GROUP_ID = MATERIAL_GROUPS.ID" in source_selects[1].upper()
    assert "ORDER BY PHOTOS.GROUP_ID, PHOTOS.SORT_ORDER, PHOTOS.ID" in source_selects[1].upper()
    assert not any("GROUP_ID IN (" in statement.upper() for statement in source_selects)


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


class _ProjectInventoryNumberConflictSession:
    def __init__(self, winner: SimpleNamespace) -> None:
        self.winner = winner
        self.physical_lookup_count = 0
        self.added: list[object] = []
        self.flush_count = 0
        self.commit_count = 0

    def scalar(self, statement: object) -> object | None:
        statement_text = str(statement)
        if "physical_collectors.collector_no" in statement_text:
            self.physical_lookup_count += 1
            return self.winner if self.physical_lookup_count > 1 else None
        return None

    def add(self, record: object) -> None:
        self.added.append(record)

    def flush(self) -> None:
        self.flush_count += 1
        if self.flush_count == 1:
            raise IntegrityError("duplicate project collector", {}, RuntimeError("unique constraint"))

    def begin_nested(self) -> _NestedTransaction:
        return _NestedTransaction()

    def commit(self) -> None:
        self.commit_count += 1


class _ProjectInventoryPhotoConflictSession:
    def __init__(self, winner_photo: SimpleNamespace) -> None:
        self.winner_photo = winner_photo
        self.sha_lookup_count = 0
        self.added: list[object] = []
        self.flush_count = 0
        self.commit_count = 0

    def scalar(self, statement: object) -> object | None:
        statement_text = str(statement)
        if "collector_photos.sha256" in statement_text:
            self.sha_lookup_count += 1
            return self.winner_photo if self.sha_lookup_count > 1 else None
        return None

    def add(self, record: object) -> None:
        self.added.append(record)

    def flush(self) -> None:
        self.flush_count += 1
        if self.flush_count == 1:
            raise IntegrityError("duplicate project photo", {}, RuntimeError("unique constraint"))

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


def test_project_inventory_registration_recovers_number_uniqueness_race(
    monkeypatch,
) -> None:
    """Catches a concurrent first registration surfacing a raw unique-constraint failure."""
    project = SimpleNamespace(id=UUID("22222222-2222-2222-2222-222222222222"))
    winner = SimpleNamespace(
        id=UUID("33333333-3333-3333-3333-333333333333"),
        collector_no="POOL-RACE",
        pool_status="available",
        last_scanned_at=None,
    )
    session = _ProjectInventoryNumberConflictSession(winner)
    transfer = PostgresCollectorTransferService(
        session=session,
        team_id="team-1",
        actor="operator",
    )
    monkeypatch.setattr(transfer, "_project", lambda _project_id: project)
    monkeypatch.setattr(
        transfer,
        "_project_has_collector_number",
        lambda _project_id, _collector_no: False,
    )
    monkeypatch.setattr(transfer, "_actor_user_id", lambda: None)
    monkeypatch.setattr(transfer, "_audit", lambda **_payload: None)

    result = transfer.register_inventory(
        project_id=str(project.id),
        collector_no="POOL-RACE",
        original_filename="POOL-RACE.jpg",
        stored=stored_photo("b3" * 32),
        byte_size=128,
    )

    assert result["collector_id"] == str(winner.id)
    assert result["pool_status"] == "available"
    assert session.commit_count == 1


def test_project_inventory_registration_recovers_same_collector_photo_race(
    monkeypatch,
) -> None:
    """Catches a concurrent identical upload surfacing a raw project-SHA uniqueness error."""
    project = SimpleNamespace(id=UUID("22222222-2222-2222-2222-222222222222"))
    physical = SimpleNamespace(
        id=UUID("33333333-3333-3333-3333-333333333333"),
        collector_no="POOL-PHOTO-RACE",
        pool_status="available",
        last_scanned_at=None,
    )
    winner_photo = SimpleNamespace(
        id=UUID("44444444-4444-4444-4444-444444444444"),
        physical_collector_id=physical.id,
        sha256="b4" * 32,
        object_key="collector-inventory/winner.jpg",
        image_url="/static/uploads/collector-inventory/winner.jpg",
        storage_type="local_upload",
        content_type="image/jpeg",
    )
    session = _ProjectInventoryPhotoConflictSession(winner_photo)
    transfer = PostgresCollectorTransferService(
        session=session,
        team_id="team-1",
        actor="operator",
    )
    monkeypatch.setattr(transfer, "_project", lambda _project_id: project)
    monkeypatch.setattr(
        transfer,
        "_project_has_collector_number",
        lambda _project_id, _collector_no: False,
    )
    monkeypatch.setattr(
        transfer,
        "_locked_project_physical_collector",
        lambda **_payload: physical,
    )
    monkeypatch.setattr(transfer, "_actor_user_id", lambda: None)
    monkeypatch.setattr(transfer, "_audit", lambda **_payload: None)

    result = transfer.register_inventory(
        project_id=str(project.id),
        collector_no=physical.collector_no,
        original_filename="POOL-PHOTO-RACE.jpg",
        stored=stored_photo("b4" * 32),
        byte_size=128,
    )

    assert result["photo"]["id"] == str(winner_photo.id)
    assert result["collector_id"] == str(physical.id)
    assert session.commit_count == 1


def test_create_run_binds_same_project_direct_inventory_without_assignment_photo(
    db_session: Session,
) -> None:
    """Catches using a direct assignment/photo instead of the scanned physical collector itself."""
    project, _group = complete_project_collector_source(
        db_session,
        collector_no="DIRECT-BIND",
    )
    physical = PhysicalCollector(
        team_id="team-1",
        project_id=project.id,
        collector_no="DIRECT-BIND",
        pool_status="direct",
    )
    db_session.add(physical)
    db_session.commit()
    retained_photo = collector_photo(db_session, physical, sha256="b6" * 32)

    created = service(db_session).create_run(project_id=str(project.id), name="直接绑定")

    assignment = db_session.scalar(select(CollectorAssignment))
    required = db_session.scalar(select(CollectorRequirement))
    removal_item = db_session.scalar(
        select(CollectorWorkbenchItem).where(CollectorWorkbenchItem.requirement_id == required.id)
    )
    assert assignment is None
    assert required.status == "direct_ready"
    assert removal_item is not None
    assert removal_item.assignment_id is None
    assert db_session.get(PhysicalCollector, physical.id).pool_status == "direct"
    assert db_session.get(CollectorPhoto, retained_photo.id) is not None
    assert db_session.scalar(select(func.count(CollectorWorkbenchItem.id))) == 2
    assert created["direct_match_count"] == 1
    assert created["assignment_count"] == 0


def test_create_run_scale_preserves_multiterminal_snapshots_requirements_and_direct_binding(
    db_session: Session,
) -> None:
    """Catches the streamed source path changing run rows, deduplication, snapshots, workbench, or direct binding."""
    current_project_id = project_id(db_session)

    def add_complete_group(
        *,
        terminal: str,
        meter_no: str,
        collector_no: str,
        storage_prefix: str,
    ) -> tuple[MaterialGroup, Photo, Photo]:
        group = MaterialGroup(
            id=uuid4(),
            team_id="team-1",
            project_id=current_project_id,
            terminal=terminal,
            meter_match_key=f"KEY-{meter_no}",
            display_meter_no=meter_no,
            installation_address=f"地址-{terminal}",
            raw_data={"collector": collector_no},
        )
        module = Photo(
            id=uuid4(),
            team_id="team-1",
            group_id=group.id,
            sha256=uuid4().hex * 2,
            object_key=f"{storage_prefix}/module.jpg",
            image_url=f"/{storage_prefix}/module.jpg",
            storage_type="oss",
            storage_bucket="run-snapshot-bucket",
            storage_key=f"{storage_prefix}/module.jpg",
            content_type="image/jpeg",
            category="module_meter",
            collector=collector_no,
            asset_no=f"MODULE-{meter_no}",
            sort_order=0,
            is_active=True,
        )
        after = Photo(
            id=uuid4(),
            team_id="team-1",
            group_id=group.id,
            sha256=uuid4().hex * 2,
            object_key=f"{storage_prefix}/after.jpg",
            image_url=f"/{storage_prefix}/after.jpg",
            storage_type="local_upload",
            storage_key=f"{storage_prefix}/after.jpg",
            content_type="image/jpeg",
            category="after_box",
            collector=collector_no,
            sort_order=1,
            is_active=True,
        )
        db_session.add_all((group, module, after))
        return group, module, after

    first, first_module, first_after = add_complete_group(
        terminal="T-SHARED",
        meter_no="M-001",
        collector_no="C-SHARED",
        storage_prefix="run-scale/first",
    )
    second, _second_module, _second_after = add_complete_group(
        terminal="T-SHARED",
        meter_no="M-002",
        collector_no="C-SHARED",
        storage_prefix="run-scale/second",
    )
    direct_group, _direct_module, _direct_after = add_complete_group(
        terminal="T-DIRECT",
        meter_no="M-003",
        collector_no="C-DIRECT",
        storage_prefix="run-scale/direct",
    )
    direct = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=current_project_id,
        collector_no="C-DIRECT",
        pool_status="direct",
    )
    db_session.add(direct)
    db_session.commit()
    direct_photo = collector_photo(db_session, direct, sha256="d0" * 32)

    created = service(db_session).create_run(project_id=str(current_project_id), name="规模路径一致性")
    run_id = UUID(str(created["id"]))
    requirements = db_session.scalars(
        select(CollectorRequirement).where(CollectorRequirement.run_id == run_id)
    ).all()
    meter_items = db_session.scalars(
        select(CollectorMeterItem).where(CollectorMeterItem.run_id == run_id)
    ).all()
    assignments = db_session.scalars(
        select(CollectorAssignment).where(CollectorAssignment.run_id == run_id)
    ).all()

    assert {key: created[key] for key in (
        "terminal_count",
        "meter_count",
        "collector_requirement_count",
        "blocked_terminal_count",
        "direct_match_count",
        "assignment_count",
    )} == {
        "terminal_count": 2,
        "meter_count": 3,
        "collector_requirement_count": 2,
        "blocked_terminal_count": 0,
        "direct_match_count": 1,
        "assignment_count": 0,
    }
    assert sorted(requirement.original_collector_no for requirement in requirements) == [
        "C-DIRECT",
        "C-SHARED",
    ]
    assert len(meter_items) == 3
    assert {item.source_group_id for item in meter_items} == {first.id, second.id, direct_group.id}
    assert db_session.scalar(
        select(func.count(CollectorWorkbenchItem.id)).where(CollectorWorkbenchItem.run_id == run_id)
    ) == 4
    direct_requirement = next(
        requirement for requirement in requirements if requirement.original_collector_no == "C-DIRECT"
    )
    direct_item = db_session.scalar(
        select(CollectorWorkbenchItem).where(
            CollectorWorkbenchItem.requirement_id == direct_requirement.id
        )
    )
    assert assignments == []
    assert direct_item is not None and direct_item.assignment_id is None
    assert db_session.get(CollectorPhoto, direct_photo.id) is not None

    first_item = next(item for item in meter_items if item.source_group_id == first.id)
    expected_module_snapshot = {
        "id": str(first_module.id),
        "image_url": "/run-scale/first/module.jpg",
        "object_key": "run-scale/first/module.jpg",
        "storage_type": "oss",
        "storage_key": "run-scale/first/module.jpg",
        "storage_bucket": "run-snapshot-bucket",
        "sha256": first_module.sha256,
        "content_type": "image/jpeg",
    }
    expected_after_snapshot = {
        "id": str(first_after.id),
        "image_url": "/run-scale/first/after.jpg",
        "object_key": "run-scale/first/after.jpg",
        "storage_type": "local_upload",
        "storage_key": "run-scale/first/after.jpg",
        "storage_bucket": "",
        "sha256": first_after.sha256,
        "content_type": "image/jpeg",
    }
    assert first_item.module_meter_photo_snapshot == expected_module_snapshot
    assert first_item.after_box_photo_snapshot == expected_after_snapshot

    first_module.storage_key = "mutated/module.jpg"
    first_after.storage_key = "mutated/after.jpg"
    db_session.commit()
    db_session.expire(first_item)
    assert first_item.module_meter_photo_snapshot == expected_module_snapshot
    assert first_item.after_box_photo_snapshot == expected_after_snapshot


def test_create_run_makes_same_number_without_photo_directly_rephoto_ready(
    db_session: Session,
) -> None:
    """Catches leaving a scanned same-number physical blocked on a nonexistent website photo."""
    project, _group = complete_project_collector_source(
        db_session,
        collector_no="DIRECT-PENDING",
    )
    direct = PhysicalCollector(
        team_id="team-1",
        project_id=project.id,
        collector_no="DIRECT-PENDING",
        pool_status="direct",
    )
    replacement = PhysicalCollector(
        team_id="team-1",
        project_id=project.id,
        collector_no="POOL-SHOULD-NOT-BIND",
        pool_status="available",
    )
    db_session.add_all((direct, replacement))
    db_session.commit()
    collector_photo(db_session, replacement, sha256="b7" * 32)

    created = service(db_session).create_run(project_id=str(project.id), name="待补直绑照片")
    allocated = service(db_session).allocate(run_id=created["id"])

    required = db_session.scalar(select(CollectorRequirement))
    removal_item = db_session.scalar(
        select(CollectorWorkbenchItem).where(CollectorWorkbenchItem.requirement_id == required.id)
    )
    assert required.status == "direct_ready"
    assert removal_item is not None
    assert removal_item.assignment_id is None
    assert allocated["assignment_count"] == 0
    assert db_session.scalar(select(func.count(CollectorAssignment.id))) == 0
    assert db_session.get(PhysicalCollector, replacement.id).pool_status == "available"


def test_allocate_never_reads_available_inventory_from_another_project(
    db_session: Session,
) -> None:
    """Catches team-wide pool selection consuming another current project's collector."""
    run = transfer_run(db_session)
    requirement(db_session, run, transfer_terminal(db_session, run), collector_no="ORIGINAL-A")
    other_project = Project(
        id=uuid4(),
        team_id="team-1",
        code=f"P-{uuid4().hex[:8]}",
        name="项目 B",
        status=ProjectStatus.ACTIVE,
        settings={},
    )
    db_session.add(other_project)
    db_session.flush()
    foreign = PhysicalCollector(
        team_id="team-1",
        project_id=other_project.id,
        collector_no="POOL-B",
        pool_status="available",
    )
    db_session.add(foreign)
    db_session.commit()
    collector_photo(db_session, foreign, sha256="b8" * 32)

    with pytest.raises(PoolInsufficientError) as raised:
        service(db_session).allocate(run_id=str(run.id))

    db_session.rollback()
    assert raised.value.available == 0
    assert db_session.scalar(select(func.count(CollectorAssignment.id))) == 0
    assert db_session.get(PhysicalCollector, foreign.id).pool_status == "available"


def test_allocate_rejects_photo_with_mismatched_project_ownership(
    db_session: Session,
) -> None:
    """Catches a corrupt cross-project photo being accepted as allocation evidence."""
    run = transfer_run(db_session)
    requirement(db_session, run, transfer_terminal(db_session, run), collector_no="ORIGINAL-A")
    other_project = Project(
        id=uuid4(),
        team_id="team-1",
        code=f"P-{uuid4().hex[:8]}",
        name="项目 B",
        status=ProjectStatus.ACTIVE,
        settings={},
    )
    db_session.add(other_project)
    db_session.flush()
    physical = PhysicalCollector(
        team_id="team-1",
        project_id=run.project_id,
        collector_no="CORRUPT-PHOTO-PROJECT",
        pool_status="available",
    )
    db_session.add(physical)
    db_session.flush()
    db_session.add(
        CollectorPhoto(
            team_id="team-1",
            project_id=other_project.id,
            physical_collector_id=physical.id,
            sha256="b9" * 32,
            original_filename="corrupt.jpg",
            object_key="collector-inventory/corrupt.jpg",
            storage_type="local_upload",
            is_active=True,
        )
    )
    db_session.commit()

    with pytest.raises(CollectorAllocationConflictError, match="project"):
        service(db_session).allocate(run_id=str(run.id))

    db_session.rollback()
    assert db_session.scalar(select(func.count(CollectorAssignment.id))) == 0


def test_workbench_completion_rejects_mismatched_inventory_project(
    db_session: Session,
) -> None:
    """Catches completion consuming evidence whose photo belongs to another project."""
    run = transfer_run(db_session)
    terminal = transfer_terminal(db_session, run)
    required = requirement(db_session, run, terminal, status="assigned")
    other_project = Project(
        id=uuid4(),
        team_id="team-1",
        code=f"P-{uuid4().hex[:8]}",
        name="项目 B",
        status=ProjectStatus.ACTIVE,
        settings={},
    )
    db_session.add(other_project)
    db_session.flush()
    physical = PhysicalCollector(
        team_id="team-1",
        project_id=run.project_id,
        collector_no="WORKBENCH-CORRUPT",
        pool_status="reserved",
    )
    db_session.add(physical)
    db_session.flush()
    photo = CollectorPhoto(
        team_id="team-1",
        project_id=other_project.id,
        physical_collector_id=physical.id,
        sha256="c1" * 32,
        original_filename="corrupt.jpg",
        object_key="collector-inventory/workbench-corrupt.jpg",
        storage_type="local_upload",
        is_active=True,
    )
    db_session.add(photo)
    db_session.flush()
    assigned = CollectorAssignment(
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

    with pytest.raises(CollectorAllocationConflictError, match="project"):
        service(db_session).set_workbench_item_status(item_id=str(item.id), completed=True)

    db_session.rollback()
    assert db_session.get(CollectorAssignment, assigned.id).status == "reserved"
    assert db_session.get(PhysicalCollector, physical.id).pool_status == "reserved"
    with pytest.raises(CollectorAllocationConflictError, match="project"):
        service(db_session).rollback_assignment(assignment_id=str(assigned.id))

    db_session.rollback()
    assert db_session.get(CollectorAssignment, assigned.id).status == "reserved"


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
        id=uuid4(),
        team_id="team-1",
        project_id=run.project_id,
        collector_no="C-002",
        pool_status="awaiting_photo",
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
        id=uuid4(),
        team_id="team-1",
        project_id=run.project_id,
        collector_no="C-001",
        pool_status=physical_status,
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
        project_id=project_id(db_session),
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
        project_id=str(physical.project_id),
        stored={"sha256": "d" * 64, "storage_key": photo.object_key},
    ) is True
    assert routes.saved_image_is_registered(
        team_id="team-2",
        project_id=str(physical.project_id),
        stored={"sha256": "d" * 64, "storage_key": photo.object_key},
    ) is False
    assert routes.saved_image_is_registered(
        team_id="team-1",
        project_id=str(uuid4()),
        stored={"sha256": "d" * 64, "storage_key": photo.object_key},
    ) is False
    assert routes.saved_image_is_registered(
        team_id="team-1",
        project_id=str(physical.project_id),
        stored={"sha256": "e" * 64, "storage_key": photo.object_key},
    ) is False
    assert routes.saved_image_is_registered(
        team_id="team-1",
        project_id=str(physical.project_id),
        stored={"sha256": "d" * 64, "storage_key": "collector-transfer/other.jpg"},
    ) is False


def test_single_photo_reuse_deletes_the_new_unreferenced_saved_object(
    db_session: Session,
    monkeypatch,
) -> None:
    """Catches successful SHA reuse leaking the newly saved object whose key was not persisted."""
    current_project_id = project_id(db_session)
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=current_project_id,
        collector_no="C-REUSE",
        pool_status="available",
    )
    db_session.add(physical)
    db_session.commit()
    old_photo = collector_photo(db_session, physical, sha256="f" * 64)
    new_key = "collector-inventory/new-upload-C-REUSE.jpg"
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
        "/collector-transfer/inventory",
        headers=_route_auth_headers(),
        data={"project_id": str(current_project_id), "collector_no": physical.collector_no},
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
        id=uuid4(),
        team_id="team-1",
        project_id=run.project_id,
        collector_no="C-001",
        pool_status=physical_status,
    )
    db_session.add(physical)
    db_session.commit()
    photo = collector_photo(db_session, physical)
    assigned = CollectorAssignment(
        id=uuid4(), run_id=run.id, team_id="team-1", requirement_id=required.id,
        physical_collector_id=physical.id, collector_photo_id=photo.id, assignment_mode="random", status=assignment_status,
    )
    event = CollectorScanEvent(
        id=uuid4(), run_id=run.id, team_id="team-1", project_id=run.project_id, physical_collector_id=physical.id,
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
    first = PhysicalCollector(
        id=uuid4(), team_id="team-1", project_id=run.project_id, collector_no="C-FIRST", pool_status="available"
    )
    second = PhysicalCollector(
        id=uuid4(), team_id="team-1", project_id=run.project_id, collector_no="C-SECOND", pool_status="awaiting_photo"
    )
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
    current_project_id = project_id(db_session)
    first = PhysicalCollector(
        id=uuid4(), team_id="team-1", project_id=current_project_id, collector_no="C-DB-1", pool_status="available"
    )
    second = PhysicalCollector(
        id=uuid4(), team_id="team-1", project_id=current_project_id, collector_no="C-DB-2", pool_status="awaiting_photo"
    )
    db_session.add_all((first, second))
    db_session.commit()
    collector_photo(db_session, first, sha256="8" * 64)
    duplicate = CollectorPhoto(
        id=uuid4(),
        team_id="team-1",
        project_id=current_project_id,
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
        project_id=project_id(db_session),
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
        project_id=second_run.project_id,
        collector_no="C-SHA-TEAM-2",
        pool_status="awaiting_photo",
    )
    db_session.add_all((second_run, second))
    db_session.flush()
    db_session.add(
        CollectorScanEvent(
            run_id=second_run.id,
            team_id="team-2",
            project_id=second_run.project_id,
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


def test_direct_scan_refreshes_and_returns_transactional_run_totals(db_session: Session) -> None:
    """Catches a direct assignment leaving direct and active-assignment totals stale."""
    run = transfer_run(db_session)
    terminal = transfer_terminal(db_session, run)
    requirement(db_session, run, terminal, collector_no="C-DIRECT-STATS")
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=run.project_id,
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
        project_id=run.project_id,
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
        project_id=run.project_id,
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
        project_id=run.project_id,
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
    physical = PhysicalCollector(
        id=uuid4(), team_id="team-1", project_id=run.project_id, collector_no="C-999", pool_status="available"
    )
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
    physical = PhysicalCollector(
        id=uuid4(), team_id="team-1", project_id=run.project_id, collector_no="C-999", pool_status="available"
    )
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
        project_id=run.project_id,
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


def test_global_terminal_candidates_keep_project_identity_and_aggregate_real_source_rules(
    db_session: Session,
) -> None:
    """Catches cross-project merging or candidate counts drifting from source precedence."""
    project_a = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    project_a.code = "P-SOUTH"
    project_a.name = "城南项目"
    project_b = Project(
        id=uuid4(),
        team_id="team-1",
        code="P-NORTH",
        name="城北项目",
        status=ProjectStatus.ACTIVE,
        settings={},
    )
    db_session.add(project_b)
    group_a1 = add_global_terminal_source(
        db_session,
        project=project_a,
        terminal_code=" T-001 ",
        meter_no="000000000001",
        collector_no="PHOTO-DIRECT",
        raw_collector_no="RAW-IGNORED",
        authoritative_address="权威-A",
        snapshot_address="旧地址-A1",
    )
    add_global_terminal_source(
        db_session,
        project=project_a,
        terminal_code="T-001",
        meter_no="000000000002",
        collector_no="PHOTO-DIRECT",
        raw_collector_no="RAW-IGNORED-2",
        authoritative_address="权威-A",
        snapshot_address="旧地址-A2",
    )
    add_global_terminal_source(
        db_session,
        project=project_b,
        terminal_code="T-001",
        meter_no="000000000003",
        collector_no="MISSING-B",
        authoritative_address="权威-B",
    )
    db_session.add(
        PhysicalCollector(
            id=uuid4(),
            team_id="team-1",
            project_id=project_a.id,
            collector_no="PHOTO-DIRECT",
            pool_status="direct",
        )
    )
    pool_collector = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project_b.id,
        collector_no="POOL-B",
        pool_status="available",
    )
    db_session.add(pool_collector)
    db_session.commit()
    collector_photo(db_session, pool_collector, sha256="b" * 64)

    page = service(db_session).list_global_terminals(query="T-001")

    assert {(row["project_id"], row["terminal_code"]) for row in page["items"]} == {
        (str(project_a.id), "T-001"),
        (str(project_b.id), "T-001"),
    }
    assert all(row["needs_disambiguation"] for row in page["items"])
    by_project = {row["project_id"]: row for row in page["items"]}
    candidate_a = by_project[str(project_a.id)]
    candidate_b = by_project[str(project_b.id)]
    assert candidate_a["installation_address"] == "权威-A"
    assert candidate_a["meter_count"] == 2
    assert candidate_a["collector_count"] == 1
    assert candidate_a["physical_count"] == 1
    assert candidate_a["missing_count"] == 0
    assert candidate_a["workflow_state"] == "ready"
    assert candidate_a["selectable"] is True
    assert candidate_b["meter_count"] == 1
    assert candidate_b["collector_count"] == 1
    assert candidate_b["physical_count"] == 0
    assert candidate_b["missing_count"] == 1
    assert candidate_b["pool_available_count"] == 1
    assert candidate_b["workflow_state"] == "needs_replacement"
    assert len(candidate_a["source_revision"]) == 64

    original_revision = candidate_a["source_revision"]
    source_photo = db_session.scalar(
        select(Photo).where(
            Photo.group_id == group_a1.id,
            Photo.category == "module_meter",
        )
    )
    source_photo.sha256 = "f" * 64
    db_session.commit()
    refreshed = service(db_session).list_global_terminals(query="T-001")
    refreshed_a = next(row for row in refreshed["items"] if row["project_id"] == str(project_a.id))
    assert refreshed_a["source_revision"] != original_revision


def test_global_terminal_candidates_include_mixed_construction_review_counts(
    db_session: Session,
) -> None:
    """Catches an unconstructed meter hiding a terminal or blocking its constructed review queue."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="MIXED-001",
        meter_no="M-READY",
        collector_no="C-SHARED",
        authoritative_address="混合终端地址",
        legacy_id="g-ready",
        status=GroupStatus.APPROVED,
    )
    review_group = add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="MIXED-001",
        meter_no="M-REVIEW",
        collector_no="C-SHARED",
        authoritative_address="混合终端地址",
        legacy_id="g-review",
        status=GroupStatus.UNREVIEWED,
    )
    clear_manual_classification_confirmation(review_group)
    catalog = TotalCatalogRow(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        terminal="MIXED-001",
        original_meter_no="M-UNBUILT",
        meter_match_key="M-UNBUILT",
        installation_address="混合终端地址",
        raw_data={},
    )
    unbuilt = MaterialGroup(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        total_catalog_row_id=catalog.id,
        legacy_id="g-unbuilt",
        terminal="MIXED-001",
        meter_match_key="M-UNBUILT",
        display_meter_no="M-UNBUILT",
        installation_address="旧混合终端地址",
        status=GroupStatus.UNREVIEWED,
        photo_count=0,
        raw_data={},
    )
    db_session.add_all((catalog, unbuilt))
    db_session.commit()

    candidate = service(db_session).list_global_terminals(
        query="MIXED-001",
        include_blocked=True,
    )["items"][0]

    assert candidate["constructed_meter_count"] == 2
    assert candidate["unconstructed_meter_count"] == 1
    assert candidate["review_ready_count"] == 1
    assert candidate["review_required_count"] == 1
    assert candidate["workflow_state"] == "needs_review"
    assert candidate["selectable"] is True
    assert candidate["terminal_code"] == "MIXED-001"
    assert candidate["terminal_key"] != "MIXED-001"


def test_automatic_approved_group_without_manual_marker_keeps_review_pending_and_opens_rephoto(
    db_session: Session,
) -> None:
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    group = add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="AUTO-APPROVED-NO-MARKER",
        meter_no="AUTO-APPROVED-METER",
        collector_no="AUTO-APPROVED-COLLECTOR",
        authoritative_address="自动审批不解锁地址",
        status=GroupStatus.APPROVED,
    )
    group.raw_data = {
        key: value
        for key, value in dict(group.raw_data or {}).items()
        if key != "classification_manual_confirmation"
    }
    db_session.commit()

    candidate = service(db_session).list_global_terminals(
        query="AUTO-APPROVED-NO-MARKER",
        include_blocked=True,
    )["items"][0]
    opened = service(db_session).open_review_workbench_terminal(
        terminal_key_value=candidate["terminal_key"],
        source_revision=candidate["source_revision"],
    )

    assert candidate["review_ready_count"] == 0
    assert candidate["review_required_count"] == 1
    assert opened["workflow_state"] == "needs_review"
    assert opened["rephoto"] is not None
    assert len(opened["rephoto"]["meter_install_items"]) == 1
    assert opened["meters"][0]["classification_manually_confirmed"] is False
    assert opened["meters"][0]["classification_manual_confirmation"] is None


def test_multi_address_terminal_stays_selectable_for_pending_review(
    db_session: Session,
) -> None:
    """Catches legitimate per-meter addresses blocking one terminal's review queue."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="MULTI-ADDRESS-001",
        meter_no="M-READY",
        collector_no="C-SHARED",
        authoritative_address="一号楼 101 室",
        legacy_id="g-ready",
        status=GroupStatus.APPROVED,
    )
    review_group = add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="MULTI-ADDRESS-001",
        meter_no="M-REVIEW",
        collector_no="C-SHARED",
        authoritative_address="二号楼 202 室",
        legacy_id="g-review",
        status=GroupStatus.UNREVIEWED,
        barcode_status="pending",
    )
    clear_manual_classification_confirmation(review_group)
    db_session.commit()

    default_page = service(db_session).list_global_terminals(
        query="MULTI-ADDRESS-001",
    )

    assert [item["terminal_code"] for item in default_page["items"]] == [
        "MULTI-ADDRESS-001"
    ]

    candidate = service(db_session).list_global_terminals(
        query="MULTI-ADDRESS-001",
        include_blocked=True,
    )["items"][0]

    assert candidate["workflow_state"] == "needs_review"
    assert candidate["selectable"] is True
    assert candidate["review_ready_count"] == 1
    assert candidate["review_required_count"] == 1
    assert set(candidate["installation_address"].split("、")) == {
        "一号楼 101 室",
        "二号楼 202 室",
    }

    opened = service(db_session).open_review_workbench_terminal(
        terminal_key_value=candidate["terminal_key"],
        source_revision=candidate["source_revision"],
    )

    assert opened["workflow_state"] == "needs_review"
    assert [row["group_id"] for row in opened["meters"]] == ["g-ready", "g-review"]
    assert {code for row in opened["review_blockers"] for code in row["codes"]} == {
        "review_not_approved",
        "barcode_verification_required",
    }


def test_global_terminal_candidates_block_conflicts_and_bound_filters(
    db_session: Session,
) -> None:
    """Catches team leaks, leading-zero collapse, blocked leakage, and unbounded pages."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    project.code = "P-LOCAL"
    project.name = "本地项目"
    add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="000000",
        meter_no="CONFLICT-1",
        collector_no="CONFLICT-C1",
        authoritative_address="",
        snapshot_address="",
    )
    add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="000123",
        meter_no="LEADING-1",
        collector_no="LEADING-C1",
        authoritative_address="前导零地址",
    )
    add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="123",
        meter_no="PLAIN-1",
        collector_no="PLAIN-C1",
        authoritative_address="普通地址",
    )
    db_session.add(Team(id="team-2", name="其他团队"))
    foreign_project = Project(
        id=uuid4(),
        team_id="team-2",
        code="P-FOREIGN",
        name="其他团队项目",
        status=ProjectStatus.ACTIVE,
        settings={},
    )
    db_session.add(foreign_project)
    add_global_terminal_source(
        db_session,
        project=foreign_project,
        terminal_code="FOREIGN-ONLY",
        meter_no="FOREIGN-1",
        collector_no="FOREIGN-C1",
        authoritative_address="外部团队地址",
    )
    db_session.commit()

    first_default_page = service(db_session).list_global_terminals(page_size=1)
    assert [row["terminal_code"] for row in first_default_page["items"]] == ["000123"]
    assert first_default_page["total"] == 2

    default_page = service(db_session).list_global_terminals(page_size=999)
    assert default_page["page_size"] == 100
    assert all(row["workflow_state"] != "blocked" for row in default_page["items"])
    assert all(row["terminal_code"] != "FOREIGN-ONLY" for row in default_page["items"])

    blocked_page = service(db_session).list_global_terminals(
        state="blocked",
        include_blocked=True,
    )
    assert [row["terminal_code"] for row in blocked_page["items"]] == ["000000"]
    assert blocked_page["items"][0]["workflow_state"] == "blocked"
    assert blocked_page["items"][0]["selectable"] is False
    assert {item["code"] for item in blocked_page["items"][0]["diagnostics"]} == {
        "installation_address_missing"
    }

    leading = service(db_session).list_global_terminals(query="000123")
    assert [row["terminal_code"] for row in leading["items"]] == ["000123"]
    assert leading["items"][0]["terminal_key"] != service(db_session).list_global_terminals(
        query="普通地址"
    )["items"][0]["terminal_key"]


def test_review_workbench_open_keeps_review_pending_and_creates_constructed_rephoto_run(
    db_session: Session,
) -> None:
    """Catches pending classification hiding already constructed re-photo material."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="REVIEW-MIXED-001",
        meter_no="M-READY",
        collector_no="C-SHARED",
        authoritative_address="统一打开混合地址",
        legacy_id="g-ready",
        status=GroupStatus.APPROVED,
    )
    review_group = add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="REVIEW-MIXED-001",
        meter_no="M-REVIEW",
        collector_no="C-SHARED",
        authoritative_address="统一打开混合地址",
        legacy_id="g-review",
        status=GroupStatus.UNREVIEWED,
    )
    clear_manual_classification_confirmation(review_group)
    add_unconstructed_global_terminal_source(
        db_session,
        project=project,
        terminal_code="REVIEW-MIXED-001",
        meter_no="M-UNBUILT",
        authoritative_address="统一打开混合地址",
        legacy_id="g-unbuilt",
    )
    db_session.commit()
    candidate = service(db_session).list_global_terminals(
        query="REVIEW-MIXED-001",
        include_blocked=True,
    )["items"][0]
    before = db_session.scalar(select(func.count(CollectorTransferRun.id)))

    result = service(db_session).open_review_workbench_terminal(
        terminal_key_value=candidate["terminal_key"],
        source_revision=candidate["source_revision"],
    )

    assert result["workflow_state"] == "needs_review"
    assert result["rephoto"] is not None
    assert len(result["rephoto"]["meter_install_items"]) == 2
    assert result["constructed_meter_count"] == 2
    assert result["unconstructed_meter_count"] == 1
    assert [row["group_id"] for row in result["meters"]] == [
        "g-ready",
        "g-review",
        "g-unbuilt",
    ]
    assert db_session.scalar(select(func.count(CollectorTransferRun.id))) == before + 1


def test_review_workbench_open_all_unconstructed_is_zero_write(
    db_session: Session,
) -> None:
    """Catches allocating collector or re-photo rows for a terminal with no construction."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    add_unconstructed_global_terminal_source(
        db_session,
        project=project,
        terminal_code="NO-CONSTRUCTION-001",
        meter_no="M-NONE",
        authoritative_address="未施工地址",
        legacy_id="g-none",
    )
    db_session.commit()
    candidate = service(db_session).list_global_terminals(
        query="NO-CONSTRUCTION-001",
        include_blocked=True,
    )["items"][0]
    before = db_session.scalar(select(func.count(CollectorTransferRun.id)))

    result = service(db_session).open_review_workbench_terminal(
        terminal_key_value=candidate["terminal_key"],
        source_revision=candidate["source_revision"],
    )

    assert result["workflow_state"] == "no_construction"
    assert result["rephoto"] is None
    assert result["meters"][0]["construction_state"] == "unconstructed"
    assert db_session.scalar(select(func.count(CollectorTransferRun.id))) == before


def test_review_workbench_open_ready_terminal_creates_and_reuses_one_snapshot(
    db_session: Session,
) -> None:
    """Catches duplicate hidden runs for an unchanged fully reviewed terminal."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="REVIEW-READY-001",
        meter_no="M-READY",
        collector_no="C-READY",
        authoritative_address="统一打开就绪地址",
        legacy_id="g-ready",
    )
    db_session.commit()
    candidate = service(db_session).list_global_terminals(
        query="REVIEW-READY-001",
        include_blocked=True,
    )["items"][0]
    before = db_session.scalar(select(func.count(CollectorTransferRun.id)))

    first = service(db_session).open_review_workbench_terminal(
        terminal_key_value=candidate["terminal_key"],
        source_revision=candidate["source_revision"],
    )
    reopened = service(db_session).open_review_workbench_terminal(
        terminal_key_value=candidate["terminal_key"],
        source_revision=candidate["source_revision"],
    )

    assert first["rephoto"] is not None
    assert reopened["rephoto"]["run_id"] == first["rephoto"]["run_id"]
    assert first["source_revision"] == candidate["source_revision"]
    assert db_session.scalar(select(func.count(CollectorTransferRun.id))) == before + 1


def test_review_workbench_open_rejects_another_team_terminal_key(
    db_session: Session,
) -> None:
    """Catches treating the opaque key as authorization across team boundaries."""
    db_session.add(Team(id="team-2", name="另一团队"))
    foreign_project = Project(
        id=uuid4(),
        team_id="team-2",
        code="P-FOREIGN-REVIEW",
        name="外部审阅项目",
        status=ProjectStatus.ACTIVE,
        settings={},
    )
    db_session.add(foreign_project)
    add_global_terminal_source(
        db_session,
        project=foreign_project,
        terminal_code="FOREIGN-REVIEW-001",
        meter_no="M-FOREIGN",
        collector_no="C-FOREIGN",
        authoritative_address="外部审阅地址",
    )
    db_session.commit()
    foreign_service = PostgresCollectorTransferService(
        session=db_session,
        team_id="team-2",
        actor="foreign",
    )
    foreign_candidate = foreign_service.list_global_terminals(
        query="FOREIGN-REVIEW-001",
        include_blocked=True,
    )["items"][0]

    with pytest.raises(TerminalNotFoundError):
        service(db_session).open_review_workbench_terminal(
            terminal_key_value=foreign_candidate["terminal_key"],
            source_revision=foreign_candidate["source_revision"],
        )


def test_review_workbench_unconstructed_change_does_not_supersede_snapshot(
    db_session: Session,
) -> None:
    """Catches unrelated unconstructed edits invalidating a reviewed re-photo snapshot."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="UNBUILT-CHANGE-001",
        meter_no="M-READY",
        collector_no="C-READY",
        authoritative_address="未施工变更地址",
    )
    unbuilt = add_unconstructed_global_terminal_source(
        db_session,
        project=project,
        terminal_code="UNBUILT-CHANGE-001",
        meter_no="M-UNBUILT",
        authoritative_address="未施工变更地址",
    )
    db_session.commit()
    candidate = service(db_session).list_global_terminals(
        query="UNBUILT-CHANGE-001",
        include_blocked=True,
    )["items"][0]
    first = service(db_session).open_review_workbench_terminal(
        terminal_key_value=candidate["terminal_key"],
        source_revision=candidate["source_revision"],
    )
    unbuilt.display_meter_no = "M-UNBUILT-CHANGED"
    unbuilt.status = GroupStatus.REJECTED
    unbuilt.exception_note = "未施工资料说明变更"
    unbuilt.raw_data = {"collector": "C-IGNORED"}
    db_session.commit()

    reopened = service(db_session).open_review_workbench_terminal(
        terminal_key_value=candidate["terminal_key"],
        source_revision=candidate["source_revision"],
    )

    assert reopened["source_revision"] == candidate["source_revision"]
    assert reopened["rephoto"]["run_id"] == first["rephoto"]["run_id"]
    assert reopened["rephoto"]["source_changed"] is False


def test_review_workbench_constructed_change_supersedes_untouched_snapshot(
    db_session: Session,
) -> None:
    """Catches reusing an untouched snapshot after constructed photo evidence changes."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    group = add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="REVIEW-SUPERSEDE-001",
        meter_no="M-READY",
        collector_no="C-READY",
        authoritative_address="统一刷新地址",
    )
    db_session.commit()
    candidate = service(db_session).list_global_terminals(
        query="REVIEW-SUPERSEDE-001",
        include_blocked=True,
    )["items"][0]
    first = service(db_session).open_review_workbench_terminal(
        terminal_key_value=candidate["terminal_key"],
        source_revision=candidate["source_revision"],
    )
    source_photo = db_session.scalar(
        select(Photo).where(
            Photo.group_id == group.id,
            Photo.category == "module_meter",
        )
    )
    source_photo.sha256 = "e" * 64
    set_manual_classification_confirmation(db_session, group)
    db_session.commit()
    changed_candidate = service(db_session).list_global_terminals(
        query="REVIEW-SUPERSEDE-001",
        include_blocked=True,
    )["items"][0]

    changed = service(db_session).open_review_workbench_terminal(
        terminal_key_value=changed_candidate["terminal_key"],
        source_revision=changed_candidate["source_revision"],
    )

    old_run = db_session.get(CollectorTransferRun, UUID(first["rephoto"]["run_id"]))
    assert changed["rephoto"]["run_id"] != first["rephoto"]["run_id"]
    assert old_run.stats["superseded"] is True
    assert old_run.stats["superseded_by_run_id"] == changed["rephoto"]["run_id"]


def test_review_workbench_constructed_change_preserves_progressed_snapshot(
    db_session: Session,
) -> None:
    """Catches replacing historical completed rows after constructed evidence changes."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    group = add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="REVIEW-PROGRESS-001",
        meter_no="M-READY",
        collector_no="C-READY",
        authoritative_address="统一进度地址",
    )
    db_session.commit()
    candidate = service(db_session).list_global_terminals(
        query="REVIEW-PROGRESS-001",
        include_blocked=True,
    )["items"][0]
    first = service(db_session).open_review_workbench_terminal(
        terminal_key_value=candidate["terminal_key"],
        source_revision=candidate["source_revision"],
    )
    meter_item_id = db_session.scalar(
        select(CollectorWorkbenchItem.id).where(
            CollectorWorkbenchItem.run_id == UUID(first["rephoto"]["run_id"]),
            CollectorWorkbenchItem.item_kind == "meter_install",
        )
    )
    service(db_session).set_workbench_item_status(
        item_id=str(meter_item_id),
        completed=True,
    )
    source_photo = db_session.scalar(
        select(Photo).where(
            Photo.group_id == group.id,
            Photo.category == "after_box",
        )
    )
    source_photo.sha256 = "d" * 64
    set_manual_classification_confirmation(db_session, group)
    db_session.commit()
    changed_candidate = service(db_session).list_global_terminals(
        query="REVIEW-PROGRESS-001",
        include_blocked=True,
    )["items"][0]

    preserved = service(db_session).open_review_workbench_terminal(
        terminal_key_value=changed_candidate["terminal_key"],
        source_revision=changed_candidate["source_revision"],
    )

    assert preserved["rephoto"]["run_id"] == first["rephoto"]["run_id"]
    assert preserved["rephoto"]["source_changed"] is True
    assert preserved["rephoto"]["meter_install_items"][0]["status"] == "completed"


def mutation_fingerprint(session: Session) -> dict[str, object]:
    """Return all business rows a rejected workbench mutation could change."""
    session.flush()
    return {
        "runs": [
            tuple(row)
            for row in session.execute(
                select(
                    CollectorTransferRun.id,
                    CollectorTransferRun.status,
                    CollectorTransferRun.stats,
                ).order_by(CollectorTransferRun.id)
            ).tuples()
        ],
        "requirements": [
            tuple(row)
            for row in session.execute(
                select(
                    CollectorRequirement.id,
                    CollectorRequirement.original_collector_no,
                    CollectorRequirement.status,
                    CollectorRequirement.diagnostics,
                ).order_by(CollectorRequirement.id)
            ).tuples()
        ],
        "assignments": [
            tuple(row)
            for row in session.execute(
                select(
                    CollectorAssignment.id,
                    CollectorAssignment.status,
                    CollectorAssignment.used_at,
                ).order_by(CollectorAssignment.id)
            ).tuples()
        ],
        "physicals": [
            tuple(row)
            for row in session.execute(
                select(
                    PhysicalCollector.id,
                    PhysicalCollector.pool_status,
                ).order_by(PhysicalCollector.id)
            ).tuples()
        ],
        "items": [
            tuple(row)
            for row in session.execute(
                select(
                    CollectorWorkbenchItem.id,
                    CollectorWorkbenchItem.status,
                    CollectorWorkbenchItem.assignment_id,
                ).order_by(CollectorWorkbenchItem.id)
            ).tuples()
        ],
        "terminals": [
            tuple(row)
            for row in session.execute(
                select(
                    CollectorTransferTerminal.id,
                    CollectorTransferTerminal.status,
                    CollectorTransferTerminal.completed_item_count,
                    CollectorTransferTerminal.collector_requirement_count,
                ).order_by(CollectorTransferTerminal.id)
            ).tuples()
        ],
        "audit_count": session.scalar(select(func.count(AuditLog.id))),
    }


def test_review_gate_compiles_postgres_valid_outer_join_lock_shape(
    db_session: Session,
) -> None:
    """Catches a nullable TotalCatalogRow outer join being locked as a PostgreSQL target."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="POSTGRES-LOCK-SHAPE",
        meter_no="POSTGRES-LOCK-SHAPE-METER",
        collector_no="POSTGRES-LOCK-SHAPE-COLLECTOR",
        authoritative_address="PostgreSQL lock shape address",
    )
    db_session.commit()
    statements: list[str] = []

    def capture_postgres_shape(orm_execute_state) -> None:
        statements.append(
            str(orm_execute_state.statement.compile(dialect=postgresql.dialect()))
        )

    event.listen(db_session, "do_orm_execute", capture_postgres_shape)
    try:
        service(db_session)._terminal_review_bundle(
            project_id=project.id,
            terminal_code="POSTGRES-LOCK-SHAPE",
            lock_groups=True,
        )
    finally:
        event.remove(db_session, "do_orm_execute", capture_postgres_shape)

    locking_statements = [item for item in statements if "FOR UPDATE" in item]
    assert any(
        "FROM material_groups" in item and "FOR UPDATE OF material_groups" in item
        for item in locking_statements
    ), locking_statements
    assert any(
        "FROM total_catalog_rows" in item
        and "FOR UPDATE OF total_catalog_rows" in item
        for item in locking_statements
    )
    assert not any(
        "LEFT OUTER JOIN total_catalog_rows" in item for item in locking_statements
    )


@pytest.mark.parametrize(
    "operation",
    ["replace_missing", "rollback", "refresh", "complete_meter", "complete_collector"],
)
def test_every_collector_mutation_allows_pending_review_when_source_is_unchanged(
    db_session: Session,
    operation: str,
) -> None:
    """Catches review-only state changes re-locking valid re-photo operations."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    group = add_global_terminal_source(
        db_session,
        project=project,
        terminal_code=f"REVIEW-GATE-{operation}",
        meter_no=f"M-{operation}",
        collector_no=f"C-{operation}",
        authoritative_address="审阅复检地址",
    )
    pool = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no=f"POOL-{operation}",
        pool_status="available",
    )
    db_session.add(pool)
    db_session.commit()
    collector_photo(db_session, pool, sha256=uuid4().hex * 2)
    candidate = service(db_session).list_global_terminals(
        query=f"REVIEW-GATE-{operation}",
        include_blocked=True,
    )["items"][0]
    opened = service(db_session).open_review_workbench_terminal(
        terminal_key_value=candidate["terminal_key"],
        source_revision=candidate["source_revision"],
    )
    rephoto = opened["rephoto"]
    terminal_id = rephoto["terminal"]["id"]
    assignment_id: str | None = None
    item_id: str | None = None
    if operation in {"rollback", "complete_collector"}:
        replacement = service(db_session).replace_terminal_missing(
            terminal_id=terminal_id
        )
        assignment_id = replacement["assignments"][0]["assignment_id"]
        detail = service(db_session).global_terminal_detail(terminal_id=terminal_id)
        item_id = detail["collector_items"][0]["workbench_item_id"]
    elif operation == "complete_meter":
        item_id = rephoto["meter_install_items"][0]["workbench_item_id"]

    clear_manual_classification_confirmation(group)
    group.status = GroupStatus.UNREVIEWED
    db_session.commit()
    before = mutation_fingerprint(db_session)

    if operation == "replace_missing":
        service(db_session).replace_terminal_missing(terminal_id=terminal_id)
    elif operation == "rollback":
        service(db_session).rollback_assignment(assignment_id=assignment_id)
    elif operation == "refresh":
        service(db_session).refresh_global_terminal(terminal_id=terminal_id)
    else:
        service(db_session).set_workbench_item_status(
            item_id=item_id,
            completed=True,
        )

    assert mutation_fingerprint(db_session) != before


@pytest.mark.parametrize(
    "operation",
    ["replace_missing", "rollback", "refresh", "complete_meter", "complete_collector"],
)
def test_every_collector_mutation_rejects_source_changed_active_photo_without_writes(
    db_session: Session,
    operation: str,
) -> None:
    """Catches every mutation accepting an old snapshot after an active source SHA changes."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    group = add_global_terminal_source(
        db_session,
        project=project,
        terminal_code=f"SOURCE-GATE-{operation}",
        meter_no=f"SOURCE-M-{operation}",
        collector_no=f"SOURCE-C-{operation}",
        authoritative_address="源图复检地址",
    )
    pool = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no=f"SOURCE-POOL-{operation}",
        pool_status="available",
    )
    db_session.add(pool)
    db_session.commit()
    collector_photo(db_session, pool, sha256=uuid4().hex * 2)
    candidate = service(db_session).list_global_terminals(
        query=f"SOURCE-GATE-{operation}",
        include_blocked=True,
    )["items"][0]
    opened = service(db_session).open_review_workbench_terminal(
        terminal_key_value=candidate["terminal_key"],
        source_revision=candidate["source_revision"],
    )
    rephoto = opened["rephoto"]
    assert rephoto is not None
    terminal_id = rephoto["terminal"]["id"]
    assignment_id: str | None = None
    item_id: str | None = None
    if operation in {"rollback", "complete_collector"}:
        replacement = service(db_session).replace_terminal_missing(
            terminal_id=terminal_id
        )
        assignment_id = replacement["assignments"][0]["assignment_id"]
        detail = service(db_session).global_terminal_detail(terminal_id=terminal_id)
        item_id = detail["collector_items"][0]["workbench_item_id"]
    elif operation == "complete_meter":
        item_id = rephoto["meter_install_items"][0]["workbench_item_id"]

    source_photo = db_session.scalar(
        select(Photo)
        .where(Photo.group_id == group.id, Photo.is_active.is_(True))
        .order_by(Photo.sort_order, Photo.id)
    )
    assert source_photo is not None
    source_photo.sha256 = uuid4().hex * 2
    set_manual_classification_confirmation(db_session, group)
    db_session.commit()
    before = mutation_fingerprint(db_session)

    with pytest.raises(TerminalSourceChangedError):
        if operation == "replace_missing":
            service(db_session).replace_terminal_missing(terminal_id=terminal_id)
        elif operation == "rollback":
            service(db_session).rollback_assignment(assignment_id=assignment_id)
        elif operation == "refresh":
            service(db_session).refresh_global_terminal(terminal_id=terminal_id)
        else:
            service(db_session).set_workbench_item_status(
                item_id=item_id,
                completed=True,
            )

    assert mutation_fingerprint(db_session) == before


def test_final_approval_updates_review_state_without_gating_rephoto(
    db_session: Session,
    monkeypatch,
) -> None:
    """Catches classification status suppressing otherwise complete re-photo material."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    terminal_code = "FINAL-APPROVAL-001"
    add_global_terminal_source(
        db_session,
        project=project,
        terminal_code=terminal_code,
        meter_no="FINAL-APPROVAL-M-1",
        collector_no="FINAL-APPROVAL-C-1",
        authoritative_address="最终审批解锁地址",
    )
    final_group = add_global_terminal_source(
        db_session,
        project=project,
        terminal_code=terminal_code,
        meter_no="FINAL-APPROVAL-M-2",
        collector_no="FINAL-APPROVAL-C-2",
        authoritative_address="最终审批解锁地址",
        status=GroupStatus.UNREVIEWED,
    )
    review_task = Task(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        legacy_id=9001,
        terminal=terminal_code,
        title="Final approval review task",
        status=TaskStatus.DRAFT,
        review_claimed_by="terminal-reviewer",
        raw_data={},
    )
    final_group.legacy_task_id = review_task.legacy_id
    clear_manual_classification_confirmation(final_group)
    db_session.add(review_task)
    db_session.commit()
    candidate = service(db_session).list_global_terminals(
        query=terminal_code,
        include_blocked=True,
    )["items"][0]
    locked = service(db_session).open_review_workbench_terminal(
        terminal_key_value=candidate["terminal_key"],
        source_revision=candidate["source_revision"],
    )

    assert locked["workflow_state"] == "needs_review"
    assert locked["review_required_count"] == 1
    assert locked["rephoto"] is not None
    assert len(locked["rephoto"]["meter_install_items"]) == 2

    repository = PostgresStateRepository()
    monkeypatch.setattr(
        "app.services.state_repository.local_simulation.current_team_id",
        lambda: "team-1",
    )
    monkeypatch.setattr(
        repository,
        "_session",
        lambda: Session(bind=db_session.get_bind(), expire_on_commit=False),
    )
    monkeypatch.setattr(
        repository,
        "_enqueue_delivery_cache_after_commit",
        lambda *_args, **_kwargs: None,
    )
    persisted = repository.review_group(
        final_group.legacy_id,
        "approved",
        "terminal-reviewer",
        note="final constructed meter approved",
    )
    db_session.expire_all()
    reviewed_but_unconfirmed = service(db_session).open_review_workbench_terminal(
        terminal_key_value=candidate["terminal_key"],
    )

    assert persisted["status"] == "approved"
    approved_group = db_session.get(MaterialGroup, final_group.id)
    assert approved_group.reviewer == "terminal-reviewer"
    assert approved_group.reviewed_at is not None
    assert reviewed_but_unconfirmed["review_required_count"] == 1
    assert reviewed_but_unconfirmed["rephoto"] is not None
    assert reviewed_but_unconfirmed["rephoto"]["run_id"] == locked["rephoto"]["run_id"]

    set_manual_classification_confirmation(db_session, approved_group)
    db_session.commit()
    unlocked = service(db_session).open_review_workbench_terminal(
        terminal_key_value=candidate["terminal_key"],
    )

    assert unlocked["review_required_count"] == 0
    assert unlocked["workflow_state"] in {"needs_replacement", "pool_shortage", "ready"}
    assert unlocked["rephoto"] is not None
    assert len(unlocked["rephoto"]["meter_install_items"]) == 2


def test_repeated_rollback_remains_idempotent_while_review_is_pending(
    db_session: Session,
) -> None:
    """Catches review-only state turning an idempotent rollback into an error."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    group = add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="REPEATED-ROLLBACK-REVIEW",
        meter_no="REPEATED-ROLLBACK-METER",
        collector_no="REPEATED-ROLLBACK-ORIGINAL",
        authoritative_address="Repeated rollback review address",
    )
    pool = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="REPEATED-ROLLBACK-POOL",
        pool_status="available",
    )
    db_session.add(pool)
    db_session.commit()
    collector_photo(db_session, pool, sha256=uuid4().hex * 2)
    candidate = service(db_session).list_global_terminals(
        query="REPEATED-ROLLBACK-REVIEW",
    )["items"][0]
    opened = service(db_session).open_review_workbench_terminal(
        terminal_key_value=candidate["terminal_key"],
        source_revision=candidate["source_revision"],
    )
    replacement = service(db_session).replace_terminal_missing(
        terminal_id=opened["rephoto"]["terminal"]["id"]
    )
    assignment_id = replacement["assignments"][0]["assignment_id"]
    service(db_session).rollback_assignment(assignment_id=assignment_id)
    clear_manual_classification_confirmation(group)
    group.status = GroupStatus.UNREVIEWED
    db_session.commit()
    before = mutation_fingerprint(db_session)

    result = service(db_session).rollback_assignment(assignment_id=assignment_id)

    assert result["status"] == "rolled_back"
    assert mutation_fingerprint(db_session) == before


def test_completion_updates_terminal_count_with_autoflush_disabled(
    db_session: Session,
) -> None:
    """Catches completion counting the pre-update item state in PostgreSQL-style sessions."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="AUTOFLUSH-COMPLETION-COUNT",
        meter_no="AUTOFLUSH-COMPLETION-METER",
        collector_no="AUTOFLUSH-COMPLETION-ORIGINAL",
        authoritative_address="Autoflush completion count address",
    )
    pool = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="AUTOFLUSH-COMPLETION-POOL",
        pool_status="available",
    )
    db_session.add(pool)
    db_session.commit()
    collector_photo(db_session, pool, sha256=uuid4().hex * 2)
    candidate = service(db_session).list_global_terminals(
        query="AUTOFLUSH-COMPLETION-COUNT",
    )["items"][0]
    opened = service(db_session).open_review_workbench_terminal(
        terminal_key_value=candidate["terminal_key"],
        source_revision=candidate["source_revision"],
    )
    terminal_id = opened["rephoto"]["terminal"]["id"]
    replacement = service(db_session).replace_terminal_missing(terminal_id=terminal_id)
    item_id = service(db_session).global_terminal_detail(terminal_id=terminal_id)[
        "collector_items"
    ][0]["workbench_item_id"]
    db_session.autoflush = False
    try:
        service(db_session).set_workbench_item_status(item_id=item_id, completed=True)
    finally:
        db_session.autoflush = True

    terminal = db_session.get(CollectorTransferTerminal, UUID(terminal_id))
    assert terminal.completed_item_count == 1
    assert terminal.status == "in_progress"


def test_open_global_terminal_creates_one_terminal_snapshot_and_reuses_revision(
    db_session: Session,
) -> None:
    """Catches global open creating a project-wide run or duplicating an unchanged snapshot."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="OPEN-001",
        meter_no="OPEN-METER-1",
        collector_no="OPEN-COLLECTOR-1",
        authoritative_address="打开终端地址",
    )
    add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="OTHER-001",
        meter_no="OTHER-METER-1",
        collector_no="OTHER-COLLECTOR-1",
        authoritative_address="其他终端地址",
    )
    db_session.commit()
    candidate = service(db_session).list_global_terminals(query="OPEN-001")["items"][0]

    opened = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code=" OPEN-001 ",
        source_revision=candidate["source_revision"],
        terminal_key_value=candidate["terminal_key"],
    )

    run = db_session.get(CollectorTransferRun, UUID(opened["run_id"]))
    terminals = db_session.scalars(
        select(CollectorTransferTerminal).where(
            CollectorTransferTerminal.run_id == run.id
        )
    ).all()
    assert opened["snapshot_reused"] is False
    assert opened["source_changed"] is False
    assert run.stats["workflow_kind"] == "global_terminal_workbench"
    assert run.stats["source_revision"] == candidate["source_revision"]
    assert run.stats["source_terminal_code"] == "OPEN-001"
    assert len(terminals) == 1
    assert terminals[0].terminal_code == "OPEN-001"
    assert db_session.scalar(
        select(func.count(CollectorMeterItem.id)).where(
            CollectorMeterItem.run_id == run.id
        )
    ) == 1

    reopened = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="OPEN-001",
        source_revision=candidate["source_revision"],
        terminal_key_value=candidate["terminal_key"],
    )
    assert reopened["run_id"] == opened["run_id"]
    assert reopened["workbench_terminal_id"] == opened["workbench_terminal_id"]
    assert reopened["snapshot_reused"] is True


def test_open_global_terminal_keeps_only_safe_constructed_sources(
    db_session: Session,
) -> None:
    """Catches legacy diagnostics blocking valid constructed evidence from opening."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    safe_group = add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="OPEN-SAFE-ONLY-001",
        meter_no="M-SAFE",
        collector_no="C-SAFE",
        authoritative_address="安全施工地址",
    )
    add_unconstructed_global_terminal_source(
        db_session,
        project=project,
        terminal_code="OPEN-SAFE-ONLY-001",
        meter_no="M-UNCONSTRUCTED",
        authoritative_address="安全施工地址",
    )
    add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="OPEN-SAFE-ONLY-001",
        meter_no="M-MISSING-COLLECTOR",
        collector_no="",
        authoritative_address="安全施工地址",
    )
    missing_photo_group = add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="OPEN-SAFE-ONLY-001",
        meter_no="M-MISSING-PHOTO",
        collector_no="C-MISSING-PHOTO",
        authoritative_address="安全施工地址",
    )
    missing_photo = db_session.scalar(
        select(Photo).where(
            Photo.group_id == missing_photo_group.id,
            Photo.category == "after_box",
        )
    )
    missing_photo.is_active = False
    db_session.commit()
    candidate = service(db_session).list_global_terminals(
        query="OPEN-SAFE-ONLY-001",
        include_blocked=True,
    )["items"][0]

    opened = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="OPEN-SAFE-ONLY-001",
        source_revision=candidate["source_revision"],
        terminal_key_value=candidate["terminal_key"],
    )

    meter_items = list(
        db_session.scalars(
            select(CollectorMeterItem).where(
                CollectorMeterItem.run_id == UUID(opened["run_id"])
            )
        )
    )
    assert [item.source_group_id for item in meter_items] == [safe_group.id]


def test_open_global_terminal_supersedes_untouched_snapshot_after_source_change(
    db_session: Session,
) -> None:
    """Catches stale untouched snapshots being reused after selected photo evidence changes."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    group = add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="REFRESH-001",
        meter_no="REFRESH-METER-1",
        collector_no="REFRESH-COLLECTOR-1",
        authoritative_address="自动刷新地址",
    )
    db_session.commit()
    first_candidate = service(db_session).list_global_terminals(query="REFRESH-001")["items"][0]
    first = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="REFRESH-001",
        source_revision=first_candidate["source_revision"],
        terminal_key_value=first_candidate["terminal_key"],
    )
    source_photo = db_session.scalar(
        select(Photo).where(
            Photo.group_id == group.id,
            Photo.category == "module_meter",
        )
    )
    source_photo.sha256 = "e" * 64
    db_session.commit()
    changed_candidate = service(db_session).list_global_terminals(query="REFRESH-001")["items"][0]

    changed = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="REFRESH-001",
        source_revision=changed_candidate["source_revision"],
        terminal_key_value=changed_candidate["terminal_key"],
    )

    old_run = db_session.get(CollectorTransferRun, UUID(first["run_id"]))
    assert changed["run_id"] != first["run_id"]
    assert changed["snapshot_reused"] is False
    assert changed["source_changed"] is False
    assert old_run.stats["superseded"] is True
    assert old_run.stats["superseded_by_run_id"] == changed["run_id"]


def test_open_global_terminal_preserves_progressed_snapshot_after_source_change(
    db_session: Session,
) -> None:
    """Catches source refresh silently replacing a snapshot with completed re-photo progress."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    group = add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="PROGRESSED-001",
        meter_no="PROGRESSED-METER-1",
        collector_no="PROGRESSED-COLLECTOR-1",
        authoritative_address="进度保护地址",
    )
    db_session.commit()
    candidate = service(db_session).list_global_terminals(query="PROGRESSED-001")["items"][0]
    opened = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="PROGRESSED-001",
        source_revision=candidate["source_revision"],
        terminal_key_value=candidate["terminal_key"],
    )
    item_id = db_session.scalar(
        select(CollectorWorkbenchItem.id).where(
            CollectorWorkbenchItem.run_id == UUID(opened["run_id"]),
            CollectorWorkbenchItem.item_kind == "meter_install",
        )
    )
    service(db_session).set_workbench_item_status(
        item_id=str(item_id),
        completed=True,
    )
    source_photo = db_session.scalar(
        select(Photo).where(
            Photo.group_id == group.id,
            Photo.category == "after_box",
        )
    )
    source_photo.sha256 = "d" * 64
    db_session.commit()
    changed_candidate = service(db_session).list_global_terminals(query="PROGRESSED-001")["items"][0]

    preserved = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="PROGRESSED-001",
        source_revision=changed_candidate["source_revision"],
        terminal_key_value=changed_candidate["terminal_key"],
    )

    old_run = db_session.get(CollectorTransferRun, UUID(opened["run_id"]))
    assert preserved["run_id"] == opened["run_id"]
    assert preserved["snapshot_reused"] is True
    assert preserved["source_changed"] is True
    assert preserved["current_source_revision"] == changed_candidate["source_revision"]
    assert not old_run.stats.get("superseded", False)
    assert db_session.get(CollectorWorkbenchItem, item_id).status == "completed"


def test_global_terminal_detail_projects_present_missing_and_replaced_collectors(
    db_session: Session,
) -> None:
    """Catches the workbench hiding missing requirements or treating direct items as photo-backed replacements."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    for meter_no, collector_no in (
        ("DETAIL-METER-1", "DIRECT-001"),
        ("DETAIL-METER-2", "MISSING-001"),
        ("DETAIL-METER-3", "ORIGINAL-001"),
    ):
        add_global_terminal_source(
            db_session,
            project=project,
            terminal_code="DETAIL-001",
            meter_no=meter_no,
            collector_no=collector_no,
            authoritative_address="详情测试地址",
        )
    direct = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="DIRECT-001",
        pool_status="direct",
    )
    replacement = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="POOL-REPLACED-001",
        pool_status="available",
    )
    spare = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="POOL-SPARE-001",
        pool_status="available",
    )
    db_session.add_all((direct, replacement, spare))
    db_session.commit()
    replacement_photo = collector_photo(db_session, replacement, sha256="c" * 64)
    collector_photo(db_session, spare, sha256="a" * 64)
    candidate = service(db_session).list_global_terminals(query="DETAIL-001")["items"][0]
    opened = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="DETAIL-001",
        source_revision=candidate["source_revision"],
        terminal_key_value=candidate["terminal_key"],
    )
    run_id = UUID(opened["run_id"])
    terminal_id = UUID(opened["workbench_terminal_id"])
    replaced_requirement = db_session.scalar(
        select(CollectorRequirement).where(
            CollectorRequirement.run_id == run_id,
            CollectorRequirement.original_collector_no == "ORIGINAL-001",
        )
    )
    replacement.pool_status = "reserved"
    replaced_requirement.status = "assigned"
    assignment = CollectorAssignment(
        id=uuid4(),
        run_id=run_id,
        team_id="team-1",
        requirement_id=replaced_requirement.id,
        physical_collector_id=replacement.id,
        collector_photo_id=replacement_photo.id,
        assignment_mode="random",
        status="reserved",
    )
    db_session.add(assignment)
    db_session.flush()
    db_session.add(
        CollectorWorkbenchItem(
            id=uuid4(),
            run_id=run_id,
            terminal_id=terminal_id,
            team_id="team-1",
            item_kind="collector_removal",
            source_key=str(replaced_requirement.id),
            requirement_id=replaced_requirement.id,
            assignment_id=assignment.id,
            status="pending",
            sort_order=20,
        )
    )
    db_session.commit()

    detail = service(db_session).global_terminal_detail(
        terminal_id=str(terminal_id)
    )

    assert len(detail["meter_install_items"]) == 3
    assert all(
        [slot["slot"] for slot in row["photos"]]
        == ["module_meter", "after_box"]
        for row in detail["meter_install_items"]
    )
    assert [row["physical_state"] for row in detail["collector_items"]] == [
        "present",
        "missing",
        "replaced",
    ]
    present, missing, replaced = detail["collector_items"]
    assert present["final_collector_no"] == "DIRECT-001"
    assert present["capture_strategy"] == "live_physical"
    assert present["photo"] is None
    assert present["assignment_id"] is None
    assert missing["workbench_item_id"] is None
    assert missing["final_collector_no"] is None
    assert missing["capture_strategy"] == "unavailable"
    assert replaced["final_collector_no"] == "POOL-REPLACED-001"
    assert replaced["collector_barcode"] == "POOL-REPLACED-001"
    assert replaced["capture_strategy"] == "screen_photo"
    assert replaced["assignment_id"] == str(assignment.id)
    assert replaced["photo"]["sha256"] == "c" * 64
    assert detail["pool_summary"] == {
        "required": 1,
        "available": 1,
        "shortage": 0,
    }


def test_global_terminal_detail_reuses_authorized_source_photo_for_present_collector(
    db_session: Session,
) -> None:
    """Catches a photo-free confirmed collector hiding its matching constructed source photo."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    first_group = add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="PRESENT-SOURCE-001",
        meter_no="PRESENT-SOURCE-METER-1",
        collector_no="PRESENT-SOURCE-COLLECTOR",
        authoritative_address="实物采集器来源地址",
    )
    second_group = add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="PRESENT-SOURCE-001",
        meter_no="PRESENT-SOURCE-METER-2",
        collector_no="PRESENT-SOURCE-COLLECTOR",
        authoritative_address="实物采集器来源地址",
    )
    first_source_photo = Photo(
        id=uuid4(),
        team_id="team-1",
        group_id=first_group.id,
        sha256="d" * 64,
        object_key=f"global/{first_group.id}/collector-primary.jpg",
        image_url=f"/global/{first_group.id}/collector-primary.jpg",
        category="collector_barcode",
        sort_order=2,
        is_active=True,
    )
    db_session.add_all(
        (
            Photo(
                id=uuid4(),
                team_id="team-1",
                group_id=first_group.id,
                sha256="a" * 64,
                object_key=f"global/{first_group.id}/collector-inactive.jpg",
                image_url=f"/global/{first_group.id}/collector-inactive.jpg",
                category="collector_barcode",
                sort_order=0,
                is_active=False,
            ),
            first_source_photo,
            Photo(
                id=uuid4(),
                team_id="team-1",
                group_id=first_group.id,
                sha256="e" * 64,
                object_key=f"global/{first_group.id}/collector-secondary.jpg",
                image_url=f"/global/{first_group.id}/collector-secondary.jpg",
                category="collector_barcode",
                sort_order=3,
                is_active=True,
            ),
            Photo(
                id=uuid4(),
                team_id="team-1",
                group_id=second_group.id,
                sha256="f" * 64,
                object_key=f"global/{second_group.id}/collector-other-group.jpg",
                image_url=f"/global/{second_group.id}/collector-other-group.jpg",
                category="collector_barcode",
                sort_order=0,
                is_active=True,
            ),
        )
    )
    db_session.commit()

    scanned = service(db_session).scan_inventory(
        project_id=str(project.id),
        collector_no="PRESENT-SOURCE-COLLECTOR",
    )
    candidate = service(db_session).list_global_terminals(
        query="PRESENT-SOURCE-001"
    )["items"][0]
    opened = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="PRESENT-SOURCE-001",
        source_revision=candidate["source_revision"],
        terminal_key_value=candidate["terminal_key"],
    )

    first = service(db_session).global_terminal_detail(
        terminal_id=opened["workbench_terminal_id"]
    )
    second = service(db_session).global_terminal_detail(
        terminal_id=opened["workbench_terminal_id"]
    )

    present = first["collector_items"][0]
    physical = db_session.get(PhysicalCollector, UUID(scanned["collector_id"]))
    assert present["physical_state"] == "present"
    assert present["photo"]["id"] == str(first_source_photo.id)
    assert present["photo"]["sha256"] == "d" * 64
    assert second["collector_items"] == first["collector_items"]
    assert present["assignment_id"] is None
    assert physical.pool_status == "direct"
    assert db_session.scalar(select(func.count(CollectorPhoto.id))) == 0
    assert first["pool_summary"] == {"required": 0, "available": 0, "shortage": 0}


def test_global_terminal_detail_reconciles_late_direct_inventory_once(
    db_session: Session,
) -> None:
    """Catches a same-number physical scan after snapshot creation remaining missing or duplicating work items."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="LATE-DIRECT-001",
        meter_no="LATE-DIRECT-METER",
        collector_no="LATE-DIRECT-COLLECTOR",
        authoritative_address="后补实物地址",
    )
    db_session.commit()
    candidate = service(db_session).list_global_terminals(query="LATE-DIRECT-001")["items"][0]
    opened = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="LATE-DIRECT-001",
        source_revision=candidate["source_revision"],
        terminal_key_value=candidate["terminal_key"],
    )
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="LATE-DIRECT-COLLECTOR",
        pool_status="direct",
    )
    db_session.add(physical)
    db_session.commit()

    first = service(db_session).global_terminal_detail(
        terminal_id=opened["workbench_terminal_id"]
    )
    second = service(db_session).global_terminal_detail(
        terminal_id=opened["workbench_terminal_id"]
    )

    requirement_row = db_session.scalar(
        select(CollectorRequirement).where(
            CollectorRequirement.run_id == UUID(opened["run_id"])
        )
    )
    assert first["collector_items"][0]["physical_state"] == "present"
    assert second["collector_items"] == first["collector_items"]
    assert requirement_row.status == "direct_ready"
    assert db_session.scalar(
        select(func.count(CollectorWorkbenchItem.id)).where(
            CollectorWorkbenchItem.requirement_id == requirement_row.id
        )
    ) == 1
    assert db_session.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.action == "collector_workbench.direct_bound"
        )
    ) == 1


def test_global_terminal_detail_rejects_direct_physical_owned_by_another_terminal(
    db_session: Session,
) -> None:
    """Catches one same-number physical collector being claimed by two active hidden terminals."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    for terminal_code, meter_no in (
        ("OWNER-001", "OWNER-METER-1"),
        ("CLAIMANT-001", "CLAIMANT-METER-1"),
    ):
        add_global_terminal_source(
            db_session,
            project=project,
            terminal_code=terminal_code,
            meter_no=meter_no,
            collector_no="SHARED-DIRECT-001",
            authoritative_address=f"{terminal_code}地址",
        )
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="SHARED-DIRECT-001",
        pool_status="direct",
    )
    db_session.add(physical)
    db_session.commit()
    owner_candidate = service(db_session).list_global_terminals(query="OWNER-001")["items"][0]
    owner = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="OWNER-001",
        source_revision=owner_candidate["source_revision"],
        terminal_key_value=owner_candidate["terminal_key"],
    )
    physical.pool_status = "available"
    db_session.commit()
    claimant_candidate = service(db_session).list_global_terminals(query="CLAIMANT-001")["items"][0]
    claimant = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="CLAIMANT-001",
        source_revision=claimant_candidate["source_revision"],
        terminal_key_value=claimant_candidate["terminal_key"],
    )
    physical.pool_status = "direct"
    db_session.commit()

    with pytest.raises(ValueError, match="already claimed"):
        service(db_session).global_terminal_detail(
            terminal_id=claimant["workbench_terminal_id"]
        )

    owner_item = db_session.scalar(
        select(CollectorWorkbenchItem).where(
            CollectorWorkbenchItem.run_id == UUID(owner["run_id"]),
            CollectorWorkbenchItem.item_kind == "collector_removal",
        )
    )
    assert owner_item is not None


def test_direct_workbench_completion_and_undo_use_physical_without_assignment(
    db_session: Session,
) -> None:
    """Catches direct completion requiring a fake assignment/photo or failing to restore direct state on undo."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="DIRECT-COMPLETE-001",
        meter_no="DIRECT-COMPLETE-METER",
        collector_no="DIRECT-COMPLETE-COLLECTOR",
        authoritative_address="直接完成地址",
    )
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="DIRECT-COMPLETE-COLLECTOR",
        pool_status="direct",
    )
    db_session.add(physical)
    db_session.commit()
    candidate = service(db_session).list_global_terminals(query="DIRECT-COMPLETE-001")["items"][0]
    opened = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="DIRECT-COMPLETE-001",
        source_revision=candidate["source_revision"],
        terminal_key_value=candidate["terminal_key"],
    )
    requirement_row = db_session.scalar(
        select(CollectorRequirement).where(
            CollectorRequirement.run_id == UUID(opened["run_id"])
        )
    )
    item = db_session.scalar(
        select(CollectorWorkbenchItem).where(
            CollectorWorkbenchItem.requirement_id == requirement_row.id
        )
    )

    completed = service(db_session).set_workbench_item_status(
        item_id=str(item.id),
        completed=True,
    )
    db_session.refresh(requirement_row)
    db_session.refresh(physical)
    assert completed["status"] == "completed"
    assert requirement_row.status == "used"
    assert physical.pool_status == "used"
    assert db_session.scalar(select(func.count(CollectorAssignment.id))) == 0

    reopened = service(db_session).set_workbench_item_status(
        item_id=str(item.id),
        completed=False,
    )
    db_session.refresh(requirement_row)
    db_session.refresh(physical)
    assert reopened["status"] == "pending"
    assert requirement_row.status == "direct_ready"
    assert physical.pool_status == "direct"


def test_direct_workbench_completion_rejects_missing_physical_provenance(
    db_session: Session,
) -> None:
    """Catches a direct item completing after its same-number physical confirmation is invalidated."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="DIRECT-BROKEN-001",
        meter_no="DIRECT-BROKEN-METER",
        collector_no="DIRECT-BROKEN-COLLECTOR",
        authoritative_address="直接阻断地址",
    )
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="DIRECT-BROKEN-COLLECTOR",
        pool_status="direct",
    )
    db_session.add(physical)
    db_session.commit()
    candidate = service(db_session).list_global_terminals(query="DIRECT-BROKEN-001")["items"][0]
    opened = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="DIRECT-BROKEN-001",
        source_revision=candidate["source_revision"],
        terminal_key_value=candidate["terminal_key"],
    )
    item_id = db_session.scalar(
        select(CollectorWorkbenchItem.id).where(
            CollectorWorkbenchItem.run_id == UUID(opened["run_id"]),
            CollectorWorkbenchItem.item_kind == "collector_removal",
        )
    )
    physical.pool_status = "available"
    db_session.commit()

    with pytest.raises(CollectorWorkbenchIncompleteError, match="同号实物"):
        service(db_session).set_workbench_item_status(
            item_id=str(item_id),
            completed=True,
        )


def test_direct_workbench_undo_rejects_invalidated_physical_without_writes(
    db_session: Session,
) -> None:
    """Catches undo restoring an invalidated same-number physical to direct inventory."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="DIRECT-UNDO-BROKEN-001",
        meter_no="DIRECT-UNDO-BROKEN-METER",
        collector_no="DIRECT-UNDO-BROKEN-COLLECTOR",
        authoritative_address="直接撤销阻断地址",
    )
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="DIRECT-UNDO-BROKEN-COLLECTOR",
        pool_status="direct",
    )
    db_session.add(physical)
    db_session.commit()
    candidate = service(db_session).list_global_terminals(
        query="DIRECT-UNDO-BROKEN-001"
    )["items"][0]
    opened = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="DIRECT-UNDO-BROKEN-001",
        source_revision=candidate["source_revision"],
        terminal_key_value=candidate["terminal_key"],
    )
    requirement_row = db_session.scalar(
        select(CollectorRequirement).where(
            CollectorRequirement.run_id == UUID(opened["run_id"])
        )
    )
    item = db_session.scalar(
        select(CollectorWorkbenchItem).where(
            CollectorWorkbenchItem.requirement_id == requirement_row.id
        )
    )
    service(db_session).set_workbench_item_status(
        item_id=str(item.id),
        completed=True,
    )
    physical.pool_status = "available"
    db_session.commit()

    with pytest.raises(CollectorWorkbenchIncompleteError, match="同号实物"):
        service(db_session).set_workbench_item_status(
            item_id=str(item.id),
            completed=False,
        )

    db_session.refresh(item)
    db_session.refresh(requirement_row)
    db_session.refresh(physical)
    assert item.status == "completed"
    assert requirement_row.status == "used"
    assert physical.pool_status == "available"


def test_replace_terminal_missing_assigns_every_gap_once_and_retries_idempotently(
    db_session: Session,
) -> None:
    """Catches a terminal replacement allocating only part of its gaps or duplicating mappings on retry."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    for index in range(2):
        add_global_terminal_source(
            db_session,
            project=project,
            terminal_code="REPLACE-ATOMIC-001",
            meter_no=f"REPLACE-METER-{index + 1}",
            collector_no=f"ORIGINAL-{index + 1}",
            authoritative_address="原子替换地址",
        )
    pool = [
        PhysicalCollector(
            id=uuid4(),
            team_id="team-1",
            project_id=project.id,
            collector_no=f"POOL-ATOMIC-{index + 1}",
            pool_status="available",
        )
        for index in range(2)
    ]
    db_session.add_all(pool)
    db_session.commit()
    for index, physical in enumerate(pool):
        collector_photo(db_session, physical, sha256=f"{index + 1}" * 64)
    candidate = service(db_session).list_global_terminals(
        query="REPLACE-ATOMIC-001"
    )["items"][0]
    opened = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="REPLACE-ATOMIC-001",
        source_revision=candidate["source_revision"],
        terminal_key_value=candidate["terminal_key"],
    )

    first = service(db_session).replace_terminal_missing(
        terminal_id=opened["workbench_terminal_id"]
    )
    mapping_audit_count = db_session.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.action == "collector_workbench.terminal_replaced"
        )
    )
    second = service(db_session).replace_terminal_missing(
        terminal_id=opened["workbench_terminal_id"]
    )

    assignments = list(
        db_session.scalars(
            select(CollectorAssignment).where(
                CollectorAssignment.run_id == UUID(opened["run_id"])
            )
        )
    )
    requirements = list(
        db_session.scalars(
            select(CollectorRequirement).where(
                CollectorRequirement.run_id == UUID(opened["run_id"])
            )
        )
    )
    workbench_items = list(
        db_session.scalars(
            select(CollectorWorkbenchItem).where(
                CollectorWorkbenchItem.run_id == UUID(opened["run_id"]),
                CollectorWorkbenchItem.item_kind == "collector_removal",
            )
        )
    )
    assert first["required"] == 2
    assert first["assigned"] == 2
    assert len(first["assignments"]) == 2
    assert len({row["physical_collector_id"] for row in first["assignments"]}) == 2
    assert second["required"] == 0
    assert second["assigned"] == 0
    assert second["assignments"] == []
    assert len(assignments) == 2
    assert all(row.assignment_mode == "random" for row in assignments)
    assert all(row.status == "reserved" for row in assignments)
    assert all(row.status == "assigned" for row in requirements)
    assert all(row.pool_status == "reserved" for row in pool)
    assert len(workbench_items) == 2
    assert db_session.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.action == "collector_workbench.terminal_replaced"
        )
    ) == mapping_audit_count == 1


def test_replace_terminal_missing_pool_shortage_has_zero_business_writes(
    db_session: Session,
) -> None:
    """Catches pool shortage leaving a partial assignment, state change, work item, or audit."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    for index in range(2):
        add_global_terminal_source(
            db_session,
            project=project,
            terminal_code="REPLACE-SHORTAGE-001",
            meter_no=f"SHORTAGE-METER-{index + 1}",
            collector_no=f"SHORTAGE-ORIGINAL-{index + 1}",
            authoritative_address="池不足地址",
        )
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="SHORTAGE-POOL-1",
        pool_status="available",
    )
    db_session.add(physical)
    db_session.commit()
    collector_photo(db_session, physical, sha256="9" * 64)
    candidate = service(db_session).list_global_terminals(
        query="REPLACE-SHORTAGE-001"
    )["items"][0]
    opened = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="REPLACE-SHORTAGE-001",
        source_revision=candidate["source_revision"],
        terminal_key_value=candidate["terminal_key"],
    )
    run_id = UUID(opened["run_id"])
    terminal_id = UUID(opened["workbench_terminal_id"])

    def business_state() -> dict[str, object]:
        return {
            "requirements": list(
                db_session.execute(
                    select(CollectorRequirement.id, CollectorRequirement.status)
                    .where(CollectorRequirement.run_id == run_id)
                    .order_by(CollectorRequirement.id)
                ).tuples()
            ),
            "physicals": list(
                db_session.execute(
                    select(PhysicalCollector.id, PhysicalCollector.pool_status)
                    .where(PhysicalCollector.project_id == project.id)
                    .order_by(PhysicalCollector.id)
                ).tuples()
            ),
            "assignment_count": db_session.scalar(
                select(func.count(CollectorAssignment.id)).where(
                    CollectorAssignment.run_id == run_id
                )
            ),
            "removal_item_count": db_session.scalar(
                select(func.count(CollectorWorkbenchItem.id)).where(
                    CollectorWorkbenchItem.run_id == run_id,
                    CollectorWorkbenchItem.item_kind == "collector_removal",
                )
            ),
            "terminal_progress": db_session.execute(
                select(
                    CollectorTransferTerminal.status,
                    CollectorTransferTerminal.completed_item_count,
                ).where(CollectorTransferTerminal.id == terminal_id)
            ).one(),
            "replace_audit_count": db_session.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action == "collector_workbench.terminal_replaced"
                )
            ),
        }

    before = business_state()
    with pytest.raises(PoolInsufficientError) as raised:
        service(db_session).replace_terminal_missing(
            terminal_id=str(terminal_id)
        )
    after = business_state()

    assert raised.value.required == 2
    assert raised.value.available == 1
    assert after == before


def test_legacy_allocate_rejects_a_global_terminal_hidden_run(
    db_session: Session,
) -> None:
    """Catches the legacy run-wide allocator bypassing terminal-scoped atomic replacement."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="HIDDEN-ALLOCATE-001",
        meter_no="HIDDEN-ALLOCATE-METER",
        collector_no="HIDDEN-ALLOCATE-ORIGINAL",
        authoritative_address="隐藏运行地址",
    )
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="HIDDEN-ALLOCATE-POOL",
        pool_status="available",
    )
    db_session.add(physical)
    db_session.commit()
    collector_photo(db_session, physical, sha256="8" * 64)
    candidate = service(db_session).list_global_terminals(
        query="HIDDEN-ALLOCATE-001"
    )["items"][0]
    opened = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="HIDDEN-ALLOCATE-001",
        source_revision=candidate["source_revision"],
        terminal_key_value=candidate["terminal_key"],
    )

    with pytest.raises(ValueError, match="terminal-scoped"):
        service(db_session).allocate(run_id=opened["run_id"])

    assert db_session.scalar(
        select(func.count(CollectorAssignment.id)).where(
            CollectorAssignment.run_id == UUID(opened["run_id"])
        )
    ) == 0
    db_session.refresh(physical)
    assert physical.pool_status == "available"


def test_legacy_allocate_keeps_terminal_scoped_rejection_while_review_is_pending(
    db_session: Session,
) -> None:
    """Catches pending review changing the global workbench's terminal-scoped safety gate."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    group = add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="HIDDEN-ALLOCATE-REVIEW",
        meter_no="HIDDEN-ALLOCATE-REVIEW-METER",
        collector_no="HIDDEN-ALLOCATE-REVIEW-ORIGINAL",
        authoritative_address="隐藏运行审阅地址",
    )
    db_session.commit()
    candidate = service(db_session).list_global_terminals(
        query="HIDDEN-ALLOCATE-REVIEW"
    )["items"][0]
    opened = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="HIDDEN-ALLOCATE-REVIEW",
        source_revision=candidate["source_revision"],
        terminal_key_value=candidate["terminal_key"],
    )
    clear_manual_classification_confirmation(group)
    group.status = GroupStatus.UNREVIEWED
    db_session.commit()
    before = mutation_fingerprint(db_session)

    with pytest.raises(ValueError, match="terminal-scoped"):
        service(db_session).allocate(run_id=opened["run_id"])

    assert mutation_fingerprint(db_session) == before


def test_random_terminal_replacement_can_complete_undo_and_roll_back_to_missing(
    db_session: Session,
) -> None:
    """Catches rollback retaining an effective mapping, consumed pool state, or removal item."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="REPLACE-ROLLBACK-001",
        meter_no="REPLACE-ROLLBACK-METER",
        collector_no="REPLACE-ROLLBACK-ORIGINAL",
        authoritative_address="替换回滚地址",
    )
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="REPLACE-ROLLBACK-POOL",
        pool_status="available",
    )
    db_session.add(physical)
    db_session.commit()
    collector_photo(db_session, physical, sha256="7" * 64)
    candidate = service(db_session).list_global_terminals(
        query="REPLACE-ROLLBACK-001"
    )["items"][0]
    opened = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="REPLACE-ROLLBACK-001",
        source_revision=candidate["source_revision"],
        terminal_key_value=candidate["terminal_key"],
    )
    replacement = service(db_session).replace_terminal_missing(
        terminal_id=opened["workbench_terminal_id"]
    )
    assignment_id = replacement["assignments"][0]["assignment_id"]
    item = db_session.scalar(
        select(CollectorWorkbenchItem).where(
            CollectorWorkbenchItem.assignment_id == UUID(assignment_id)
        )
    )
    service(db_session).set_workbench_item_status(
        item_id=str(item.id),
        completed=True,
    )
    service(db_session).set_workbench_item_status(
        item_id=str(item.id),
        completed=False,
    )

    rolled_back = service(db_session).rollback_assignment(
        assignment_id=assignment_id
    )
    detail = service(db_session).global_terminal_detail(
        terminal_id=opened["workbench_terminal_id"]
    )

    assignment = db_session.get(CollectorAssignment, UUID(assignment_id))
    requirement_row = db_session.get(
        CollectorRequirement,
        assignment.requirement_id,
    )
    db_session.refresh(physical)
    assert rolled_back["status"] == "rolled_back"
    assert assignment.status == "rolled_back"
    assert requirement_row.status == "unmatched"
    assert physical.pool_status == "available"
    assert db_session.scalar(
        select(func.count(CollectorWorkbenchItem.id)).where(
            CollectorWorkbenchItem.assignment_id == assignment.id
        )
    ) == 0
    terminal = db_session.get(
        CollectorTransferTerminal,
        UUID(opened["workbench_terminal_id"]),
    )
    assert terminal.completed_item_count == 0
    assert terminal.status == "ready"
    assert detail["collector_items"][0]["physical_state"] == "missing"


def test_refresh_global_terminal_rejects_completed_progress_without_writes(
    db_session: Session,
) -> None:
    """Catches refresh silently superseding a snapshot after re-photography progress."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="REFRESH-COMPLETED-001",
        meter_no="REFRESH-COMPLETED-METER",
        collector_no="REFRESH-COMPLETED-COLLECTOR",
        authoritative_address="刷新完成门禁地址",
    )
    db_session.commit()
    candidate = service(db_session).list_global_terminals(
        query="REFRESH-COMPLETED-001"
    )["items"][0]
    opened = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="REFRESH-COMPLETED-001",
        source_revision=candidate["source_revision"],
        terminal_key_value=candidate["terminal_key"],
    )
    run_id = UUID(opened["run_id"])
    terminal_id = UUID(opened["workbench_terminal_id"])
    meter_item = db_session.scalar(
        select(CollectorWorkbenchItem).where(
            CollectorWorkbenchItem.run_id == run_id,
            CollectorWorkbenchItem.item_kind == "meter_install",
        )
    )
    service(db_session).set_workbench_item_status(
        item_id=str(meter_item.id),
        completed=True,
    )
    before_runs = db_session.scalar(
        select(func.count(CollectorTransferRun.id)).where(
            CollectorTransferRun.team_id == "team-1"
        )
    )
    old_run = db_session.get(CollectorTransferRun, run_id)
    old_stats = dict(old_run.stats or {})

    with pytest.raises(CollectorSnapshotChangedError, match="progress"):
        service(db_session).refresh_global_terminal(
            terminal_id=str(terminal_id)
        )

    db_session.refresh(old_run)
    db_session.refresh(meter_item)
    assert dict(old_run.stats or {}) == old_stats
    assert meter_item.status == "completed"
    assert db_session.scalar(
        select(func.count(CollectorTransferRun.id)).where(
            CollectorTransferRun.team_id == "team-1"
        )
    ) == before_runs


def test_refresh_global_terminal_requires_random_rollback_then_supersedes_snapshot(
    db_session: Session,
) -> None:
    """Catches source changes blocking both refresh and rollback until review is current."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    source_group = add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="REFRESH-ASSIGNED-001",
        meter_no="REFRESH-ASSIGNED-METER",
        collector_no="REFRESH-ASSIGNED-ORIGINAL",
        authoritative_address="刷新分配门禁地址",
    )
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="REFRESH-ASSIGNED-POOL",
        pool_status="available",
    )
    db_session.add(physical)
    db_session.commit()
    collector_photo(db_session, physical, sha256="5" * 64)
    candidate = service(db_session).list_global_terminals(
        query="REFRESH-ASSIGNED-001"
    )["items"][0]
    opened = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="REFRESH-ASSIGNED-001",
        source_revision=candidate["source_revision"],
        terminal_key_value=candidate["terminal_key"],
    )
    replaced = service(db_session).replace_terminal_missing(
        terminal_id=opened["workbench_terminal_id"]
    )
    assignment_id = replaced["assignments"][0]["assignment_id"]
    source_photo = db_session.scalar(
        select(Photo).where(
            Photo.group_id == source_group.id,
            Photo.category == "after_box",
        )
    )
    source_photo.sha256 = "6" * 64
    set_manual_classification_confirmation(db_session, source_group)
    db_session.commit()
    old_run = db_session.get(CollectorTransferRun, UUID(opened["run_id"]))

    with pytest.raises(CollectorSnapshotChangedError, match="progress"):
        service(db_session).refresh_global_terminal(
            terminal_id=opened["workbench_terminal_id"]
        )

    db_session.refresh(old_run)
    assignment = db_session.get(CollectorAssignment, UUID(assignment_id))
    assert not old_run.stats.get("superseded", False)
    assert assignment.status == "reserved"
    with pytest.raises(TerminalSourceChangedError):
        service(db_session).rollback_assignment(assignment_id=assignment_id)

    db_session.refresh(assignment)
    db_session.refresh(physical)
    assert assignment.status == "reserved"
    assert physical.pool_status == "reserved"


def test_replace_terminal_missing_rejects_a_stale_source_snapshot_without_writes(
    db_session: Session,
) -> None:
    """Catches replacement consuming pool inventory against an outdated terminal source snapshot."""
    project = db_session.scalar(select(Project).where(Project.team_id == "team-1"))
    source_group = add_global_terminal_source(
        db_session,
        project=project,
        terminal_code="REPLACE-STALE-001",
        meter_no="REPLACE-STALE-METER",
        collector_no="REPLACE-STALE-ORIGINAL",
        authoritative_address="过期快照地址",
    )
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="REPLACE-STALE-POOL",
        pool_status="available",
    )
    db_session.add(physical)
    db_session.commit()
    collector_photo(db_session, physical, sha256="4" * 64)
    candidate = service(db_session).list_global_terminals(
        query="REPLACE-STALE-001"
    )["items"][0]
    opened = service(db_session).open_global_terminal(
        project_id=str(project.id),
        terminal_code="REPLACE-STALE-001",
        source_revision=candidate["source_revision"],
        terminal_key_value=candidate["terminal_key"],
    )
    source_photo = db_session.scalar(
        select(Photo).where(
            Photo.group_id == source_group.id,
            Photo.category == "after_box",
        )
    )
    source_photo.sha256 = "3" * 64
    set_manual_classification_confirmation(db_session, source_group)
    db_session.commit()

    with pytest.raises(CollectorSnapshotChangedError, match="source"):
        service(db_session).replace_terminal_missing(
            terminal_id=opened["workbench_terminal_id"]
        )

    db_session.refresh(physical)
    requirement_row = db_session.scalar(
        select(CollectorRequirement).where(
            CollectorRequirement.run_id == UUID(opened["run_id"])
        )
    )
    assert requirement_row.status == "unmatched"
    assert physical.pool_status == "available"
    assert db_session.scalar(
        select(func.count(CollectorAssignment.id)).where(
            CollectorAssignment.run_id == UUID(opened["run_id"])
        )
    ) == 0
    assert db_session.scalar(
        select(func.count(CollectorWorkbenchItem.id)).where(
            CollectorWorkbenchItem.run_id == UUID(opened["run_id"]),
            CollectorWorkbenchItem.item_kind == "collector_removal",
        )
    ) == 0


def open_manual_demand_terminal(
    session: Session,
    *,
    terminal_code: str,
) -> tuple[Project, dict[str, object]]:
    project = session.scalar(select(Project).where(Project.team_id == "team-1"))
    add_global_terminal_source(
        session,
        project=project,
        terminal_code=terminal_code,
        meter_no=f"{terminal_code}-METER",
        collector_no=f"{terminal_code}-SOURCE",
        authoritative_address="人工需求测试地址",
    )
    session.commit()
    candidate = service(session).list_global_terminals(query=terminal_code)["items"][0]
    opened = service(session).open_global_terminal(
        project_id=str(project.id),
        terminal_code=terminal_code,
        source_revision=candidate["source_revision"],
        terminal_key_value=candidate["terminal_key"],
    )
    return project, opened


def test_manual_demand_matches_unique_current_project_collectors_and_audits(
    db_session: Session,
) -> None:
    """Catches manual demand leaking opaque keys, crossing projects, or reusing one physical device."""
    project, opened = open_manual_demand_terminal(
        db_session,
        terminal_code="DEMAND-ATOMIC-001",
    )
    pool = [
        PhysicalCollector(
            id=uuid4(),
            team_id="team-1",
            project_id=project.id,
            collector_no=f"MANUAL-POOL-{index + 1}",
            pool_status="available",
        )
        for index in range(2)
    ]
    db_session.add_all(pool)
    db_session.commit()
    for index, physical in enumerate(pool):
        collector_photo(db_session, physical, sha256=f"{index + 5}" * 64)

    result = service(db_session).create_manual_demand(
        terminal_id=str(opened["workbench_terminal_id"]),
        quantity=2,
    )

    manual_requirements = list(
        db_session.scalars(
            select(CollectorRequirement)
            .where(CollectorRequirement.run_id == UUID(opened["run_id"]))
            .order_by(CollectorRequirement.sort_order, CollectorRequirement.id)
        )
    )[-2:]
    audit = db_session.scalar(
        select(AuditLog)
        .where(
            AuditLog.team_id == "team-1",
            AuditLog.action == "collector_workbench.manual_demand_added",
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    )
    detail = service(db_session).global_terminal_detail(
        terminal_id=str(opened["workbench_terminal_id"])
    )
    manual_items = [
        item
        for item in detail["collector_items"]
        if item["requirement_id"] in {str(row.id) for row in manual_requirements}
    ]

    assert result["required"] == result["assigned"] == 2
    assert {row["original_collector_no"] for row in result["assignments"]} == {"人工需求"}
    assert len({row["physical_collector_id"] for row in result["assignments"]}) == 2
    assert {row["physical_collector_id"] for row in result["assignments"]} == {
        str(row.id) for row in pool
    }
    assert len({row.original_collector_no for row in manual_requirements}) == 2
    assert all(row.original_collector_no.startswith("manual-demand:") for row in manual_requirements)
    assert all(
        row.diagnostics == [{"code": "manual_collector_demand", "label": "人工需求"}]
        for row in manual_requirements
    )
    assert {item["original_collector_no"] for item in manual_items} == {"人工需求"}
    assert audit is not None
    assert audit.project_id == project.id
    assert audit.payload["quantity"] == 2
    assert {row["original_collector_no"] for row in audit.payload["assignments"]} == {"人工需求"}
    assert all("manual-demand:" not in str(row) for row in result["assignments"])
    assert all("manual-demand:" not in str(row) for row in audit.payload["assignments"])


def test_manual_demand_pool_shortage_ignores_foreign_project_and_writes_nothing(
    db_session: Session,
) -> None:
    """Catches foreign-project inventory masking a shortage or partial manual-demand persistence."""
    project, opened = open_manual_demand_terminal(
        db_session,
        terminal_code="DEMAND-SHORT-001",
    )
    current = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="MANUAL-SHORTAGE-CURRENT",
        pool_status="available",
    )
    foreign_project = Project(
        id=uuid4(),
        team_id="team-1",
        code="P-MANUAL-FOREIGN",
        name="人工需求外部项目",
        status=ProjectStatus.ACTIVE,
        settings={},
    )
    foreign_pool = [
        PhysicalCollector(
            id=uuid4(),
            team_id="team-1",
            project_id=foreign_project.id,
            collector_no=f"MANUAL-SHORTAGE-FOREIGN-{index + 1}",
            pool_status="available",
        )
        for index in range(2)
    ]
    db_session.add_all([current, foreign_project, *foreign_pool])
    db_session.commit()
    collector_photo(db_session, current, sha256="a" * 64)
    for index, physical in enumerate(foreign_pool):
        collector_photo(db_session, physical, sha256=f"{index + 7}" * 64)
    before = mutation_fingerprint(db_session)

    with pytest.raises(PoolInsufficientError) as raised:
        service(db_session).create_manual_demand(
            terminal_id=str(opened["workbench_terminal_id"]),
            quantity=2,
        )

    assert raised.value.required == 2
    assert raised.value.available == 1
    assert mutation_fingerprint(db_session) == before


def test_manual_demand_rejects_non_positive_quantity_without_writes(
    db_session: Session,
) -> None:
    """Catches a zero or negative manual-demand quantity creating internal requirements."""
    _project, opened = open_manual_demand_terminal(
        db_session,
        terminal_code="DEMAND-VALID-001",
    )
    before = mutation_fingerprint(db_session)

    for quantity in (0, -1):
        with pytest.raises(ValueError, match="positive"):
            service(db_session).create_manual_demand(
                terminal_id=str(opened["workbench_terminal_id"]),
                quantity=quantity,
            )

    assert mutation_fingerprint(db_session) == before


def test_manual_demand_assignment_uses_existing_rollback_and_keeps_neutral_label(
    db_session: Session,
) -> None:
    """Catches manual requirements becoming unrollable or exposing their internal key after rollback."""
    project, opened = open_manual_demand_terminal(
        db_session,
        terminal_code="DEMAND-ROLLBACK-001",
    )
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="MANUAL-ROLLBACK-POOL",
        pool_status="available",
    )
    db_session.add(physical)
    db_session.commit()
    collector_photo(db_session, physical, sha256="b" * 64)
    created = service(db_session).create_manual_demand(
        terminal_id=str(opened["workbench_terminal_id"]),
        quantity=1,
    )
    assignment_id = created["assignments"][0]["assignment_id"]
    requirement_id = created["assignments"][0]["requirement_id"]

    rolled_back = service(db_session).rollback_assignment(
        assignment_id=assignment_id
    )
    detail = service(db_session).global_terminal_detail(
        terminal_id=str(opened["workbench_terminal_id"])
    )
    requirement_row = db_session.get(CollectorRequirement, UUID(requirement_id))
    manual_item = next(
        item
        for item in detail["collector_items"]
        if item["requirement_id"] == requirement_id
    )

    db_session.refresh(physical)
    assert rolled_back["status"] == "rolled_back"
    assert requirement_row.status == "unmatched"
    assert physical.pool_status == "available"
    assert manual_item["physical_state"] == "missing"
    assert manual_item["original_collector_no"] == "人工需求"
    assert "manual-demand:" not in str(manual_item)


def test_manual_demand_internal_key_is_independent_from_returned_requirement_id(
    db_session: Session,
) -> None:
    """Catches clients reconstructing the database-only key from a returned requirement id."""
    project, opened = open_manual_demand_terminal(
        db_session,
        terminal_code="DEMAND-OPAQUE-001",
    )
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="OPAQUE-SAFE-POOL",
        pool_status="available",
    )
    db_session.add(physical)
    db_session.commit()
    collector_photo(db_session, physical, sha256="c" * 64)

    created = service(db_session).create_manual_demand(
        terminal_id=str(opened["workbench_terminal_id"]),
        quantity=1,
    )
    requirement_id = UUID(created["assignments"][0]["requirement_id"])
    requirement_row = db_session.get(CollectorRequirement, requirement_id)

    assert requirement_row.original_collector_no != f"manual-demand:{requirement_id.hex}"


def test_manual_namespace_is_rejected_by_every_collector_number_input(
    db_session: Session,
) -> None:
    """Catches any public collector-number path admitting or looking up an internal key."""
    project, opened = open_manual_demand_terminal(
        db_session,
        terminal_code="DEMAND-INPUTS-001",
    )
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="INPUT-SAFE-POOL",
        pool_status="available",
    )
    db_session.add(physical)
    db_session.commit()
    photo = collector_photo(db_session, physical, sha256="d" * 64)
    reserved = "MaNuAl-DeMaNd:forged-input"
    region = {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5}
    before = mutation_fingerprint(db_session)

    with pytest.raises(ValueError, match="reserved"):
        service(db_session).scan_inventory(
            project_id=str(project.id),
            collector_no=reserved,
        )
    with pytest.raises(ValueError, match="reserved"):
        service(db_session).register_inventory(
            project_id=str(project.id),
            collector_no=reserved,
            original_filename="forged.jpg",
            stored={
                "sha256": "e" * 64,
                "storage_key": "collector-transfer/forged.jpg",
                "storage_type": "local_upload",
                "content_type": "image/jpeg",
            },
            byte_size=10,
        )
    with pytest.raises(ValueError, match="reserved"):
        service(db_session).scan_inventory_photo_region(
            project_id=str(project.id),
            collector_id=str(physical.id),
            expected_collector_no=reserved,
            expected_photo_sha256=photo.sha256,
            region=region,
        )
    with pytest.raises(ValueError, match="reserved"):
        service(db_session).correct_inventory_number(
            project_id=str(project.id),
            collector_id=str(physical.id),
            expected_collector_no=reserved,
            expected_photo_sha256=photo.sha256,
            collector_no="INPUT-SAFE-NEW",
            recognition_method="manual",
            region=None,
        )
    with pytest.raises(ValueError, match="reserved"):
        service(db_session).correct_inventory_number(
            project_id=str(project.id),
            collector_id=str(physical.id),
            expected_collector_no=physical.collector_no,
            expected_photo_sha256=photo.sha256,
            collector_no=reserved,
            recognition_method="manual",
            region=None,
        )
    with pytest.raises(ValueError, match="reserved"):
        service(db_session).scan_collector(
            run_id=str(opened["run_id"]),
            collector_no=reserved,
        )

    assert mutation_fingerprint(db_session) == before


def test_manual_internal_inventory_never_reconciles_or_surfaces_in_mappings(
    db_session: Session,
) -> None:
    """Catches legacy synthetic inventory appearing as a direct or random final collector number."""
    project, opened = open_manual_demand_terminal(
        db_session,
        terminal_code="DEMAND-ROUNDTRIP-001",
    )
    safe = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="ROUNDTRIP-SAFE-POOL",
        pool_status="available",
    )
    db_session.add(safe)
    db_session.commit()
    collector_photo(db_session, safe, sha256="f" * 64)
    created = service(db_session).create_manual_demand(
        terminal_id=str(opened["workbench_terminal_id"]),
        quantity=1,
    )
    assignment_id = created["assignments"][0]["assignment_id"]
    requirement_id = created["assignments"][0]["requirement_id"]
    service(db_session).rollback_assignment(assignment_id=assignment_id)
    requirement_row = db_session.get(CollectorRequirement, UUID(requirement_id))
    internal_key = requirement_row.original_collector_no
    safe.pool_status = "used"
    rogue = PhysicalCollector(
        id=UUID("00000000-0000-0000-0000-0000000000a1"),
        team_id="team-1",
        project_id=project.id,
        collector_no=internal_key,
        pool_status="direct",
    )
    db_session.add(rogue)
    db_session.commit()
    collector_photo(db_session, rogue, sha256="1" * 64)

    inventory = service(db_session).list_inventory(project_id=str(project.id))
    assert internal_key not in str(inventory)

    detail = service(db_session).global_terminal_detail(
        terminal_id=str(opened["workbench_terminal_id"])
    )
    manual_item = next(
        item
        for item in detail["collector_items"]
        if item["requirement_id"] == requirement_id
    )
    direct_audit_count = db_session.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.action == "collector_workbench.direct_bound",
            AuditLog.payload["requirement_id"].as_string() == requirement_id,
        )
    )

    assert manual_item["physical_state"] == "missing"
    assert manual_item["final_collector_no"] is None
    assert direct_audit_count == 0

    rogue.pool_status = "available"
    db_session.commit()
    with pytest.raises(PoolInsufficientError):
        service(db_session).create_manual_demand(
            terminal_id=str(opened["workbench_terminal_id"]),
            quantity=1,
        )

    replacement_physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="ROUNDTRIP-FRESH-POOL",
        pool_status="available",
    )
    db_session.add(replacement_physical)
    db_session.commit()
    collector_photo(db_session, replacement_physical, sha256="2" * 64)
    replacement = service(db_session).create_manual_demand(
        terminal_id=str(opened["workbench_terminal_id"]),
        quantity=1,
    )
    replacement_requirement_id = replacement["assignments"][0]["requirement_id"]
    audit = next(
        row
        for row in db_session.scalars(
            select(AuditLog).where(
                AuditLog.action == "collector_workbench.manual_demand_added"
            )
        ).all()
        if row.payload["assignments"][0]["requirement_id"]
        == replacement_requirement_id
    )

    assert replacement["assignments"][0]["final_collector_no"] == (
        replacement_physical.collector_no
    )
    assert "manual-demand:" not in str(replacement["assignments"])
    assert {
        assignment["final_collector_no"]
        for assignment in audit.payload["assignments"]
    } == {replacement_physical.collector_no}
    assert "manual-demand:" not in str(audit.payload["assignments"])


def test_manual_demand_reopens_completed_terminal_with_pending_work(
    db_session: Session,
) -> None:
    """Catches a completed terminal remaining completed after a new pending manual item is added."""
    project, opened = open_manual_demand_terminal(
        db_session,
        terminal_code="DEMAND-REOPEN-001",
    )
    meter_item = db_session.scalar(
        select(CollectorWorkbenchItem).where(
            CollectorWorkbenchItem.run_id == UUID(opened["run_id"]),
            CollectorWorkbenchItem.item_kind == "meter_install",
        )
    )
    service(db_session).set_workbench_item_status(
        item_id=str(meter_item.id),
        completed=True,
    )
    previous_total_count = service(db_session).global_terminal_detail(
        terminal_id=str(opened["workbench_terminal_id"])
    )["total_count"]
    terminal = db_session.get(
        CollectorTransferTerminal,
        UUID(opened["workbench_terminal_id"]),
    )
    assert terminal.status == "completed"
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="REOPEN-SAFE-POOL",
        pool_status="available",
    )
    db_session.add(physical)
    db_session.commit()
    collector_photo(db_session, physical, sha256="2" * 64)

    created = service(db_session).create_manual_demand(
        terminal_id=str(opened["workbench_terminal_id"]),
        quantity=1,
    )
    detail = service(db_session).global_terminal_detail(
        terminal_id=str(opened["workbench_terminal_id"])
    )
    manual_item = next(
        item
        for item in detail["collector_items"]
        if item["requirement_id"] == created["assignments"][0]["requirement_id"]
    )

    db_session.refresh(terminal)
    assert terminal.status == "in_progress"
    assert terminal.completed_item_count == 1
    assert detail["terminal"]["status"] == "in_progress"
    assert detail["completed_count"] == 1
    assert detail["total_count"] == previous_total_count + 1
    assert manual_item["status"] == "pending"
    assert db_session.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.action == "collector_transfer.workbench_item_completed"
        )
    ) == 1
    assert db_session.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.action == "collector_workbench.manual_demand_added"
        )
    ) == 1


def test_terminal_workbench_redacts_legacy_manual_namespace_assignment(
    db_session: Session,
) -> None:
    """Catches the run-scoped workbench exposing a database-only manual key as a barcode."""
    project, opened = open_manual_demand_terminal(
        db_session,
        terminal_code="DEMAND-LEGACY-WORKBENCH-001",
    )
    physical = PhysicalCollector(
        id=uuid4(),
        team_id="team-1",
        project_id=project.id,
        collector_no="LEGACY-WORKBENCH-SAFE",
        pool_status="available",
    )
    db_session.add(physical)
    db_session.commit()
    collector_photo(db_session, physical, sha256="4" * 64)
    created = service(db_session).create_manual_demand(
        terminal_id=str(opened["workbench_terminal_id"]),
        quantity=1,
    )
    requirement_id = created["assignments"][0]["requirement_id"]
    requirement = db_session.get(CollectorRequirement, UUID(requirement_id))
    physical.collector_no = requirement.original_collector_no
    db_session.commit()

    workbench = service(db_session).terminal_workbench(
        run_id=str(opened["run_id"]),
        terminal_id=str(opened["workbench_terminal_id"]),
    )
    removal_item = next(
        item for item in workbench["items"] if item["kind"] == "collector_removal"
    )
    detail = service(db_session).global_terminal_detail(
        terminal_id=str(opened["workbench_terminal_id"])
    )
    manual_item = next(
        item
        for item in detail["collector_items"]
        if item["requirement_id"] == requirement_id
    )

    assert removal_item["collector_no"] == ""
    assert removal_item["collector_barcode"] == ""
    assert "manual-demand:" not in str(workbench)
    assert manual_item["original_collector_no"] == "人工需求"
