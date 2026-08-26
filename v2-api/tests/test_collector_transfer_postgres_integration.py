"""Real PostgreSQL acceptance coverage for collector-transfer allocation.

Set COLLECTOR_TRANSFER_POSTGRES_TEST_URL only to a unique local disposable
database.  This test never discovers or uses a production connection.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from hashlib import sha256
from os import getenv
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.domain.collector_transfer import PoolInsufficientError
from app.models import (
    AuditLog,
    CollectorAssignment,
    CollectorPhoto,
    CollectorRequirement,
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
    TotalCatalogRow,
)
from app.services.collector_transfer import (
    CollectorAllocationConflictError,
    CollectorDirectConflictError,
    CollectorPhotoConflictError,
    CollectorWorkbenchIncompleteError,
    PostgresCollectorTransferService,
    TerminalReviewRequiredError,
    TerminalSourceChangedError,
)


@pytest.fixture()
def postgres_session_factory():
    database_url = getenv("COLLECTOR_TRANSFER_POSTGRES_TEST_URL", "").strip()
    if not database_url:
        pytest.skip("COLLECTOR_TRANSFER_POSTGRES_TEST_URL is required for local PostgreSQL acceptance")
    parsed = make_url(database_url)
    assert parsed.get_backend_name() == "postgresql"
    assert parsed.host in {"localhost", "127.0.0.1", "::1"}, "collector-transfer validation must stay local"
    assert parsed.database and parsed.database.startswith("collector_transfer_task7"), "use the Task 7 disposable database"
    engine = create_engine(database_url, pool_pre_ping=True, pool_size=5, max_overflow=0)
    try:
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        engine.dispose()


def seed_inventory_projects(session_factory, *, project_count: int) -> tuple[str, list[str]]:
    team_id = f"task7-inventory-{uuid4().hex}"
    with session_factory.begin() as session:
        session.add(Team(id=team_id, name="Task 7 inventory concurrency"))
        session.flush()
        projects = [
            Project(
                team_id=team_id,
                code=f"TASK7-INVENTORY-{uuid4().hex[:10]}",
                name=f"Task 7 inventory {index + 1}",
                status=ProjectStatus.ACTIVE,
            )
            for index in range(project_count)
        ]
        session.add_all(projects)
        session.flush()
        project_ids = [str(project.id) for project in projects]
    return team_id, project_ids


def register_inventory_once(
    session_factory,
    *,
    team_id: str,
    project_id: str,
    collector_no: str,
    photo_sha256: str,
    start: Barrier,
) -> tuple[str, str]:
    start.wait(timeout=10)
    with session_factory() as session:
        try:
            result = PostgresCollectorTransferService(
                session=session,
                team_id=team_id,
                actor="task7",
            ).register_inventory(
                project_id=project_id,
                collector_no=collector_no,
                original_filename=f"{collector_no}.jpg",
                stored={
                    "sha256": photo_sha256,
                    "storage_key": f"task7/{project_id}/{collector_no}.jpg",
                    "storage_type": "local_upload",
                    "content_type": "image/jpeg",
                },
                byte_size=128,
            )
            return "ok", str(result["collector_id"])
        except CollectorPhotoConflictError as exc:
            session.rollback()
            return "conflict", str(exc)
        except Exception as exc:  # assertion records any leaked database failure
            session.rollback()
            return "unexpected", f"{type(exc).__name__}: {exc}"


def test_real_postgres_concurrent_same_project_number_commits_one_inventory_row(
    postgres_session_factory,
) -> None:
    """Catches concurrent registration bypassing project collector-number uniqueness."""
    team_id, project_ids = seed_inventory_projects(
        postgres_session_factory,
        project_count=1,
    )
    start = Barrier(3)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            register_inventory_once,
            postgres_session_factory,
            team_id=team_id,
            project_id=project_ids[0],
            collector_no="TASK7-SAME-NUMBER",
            photo_sha256="a1" * 32,
            start=start,
        )
        second = executor.submit(
            register_inventory_once,
            postgres_session_factory,
            team_id=team_id,
            project_id=project_ids[0],
            collector_no="TASK7-SAME-NUMBER",
            photo_sha256="a2" * 32,
            start=start,
        )
        start.wait(timeout=10)
        outcomes = [first.result(timeout=15), second.result(timeout=15)]

    assert sorted(kind for kind, _detail in outcomes) == ["conflict", "ok"], outcomes
    with postgres_session_factory() as session:
        assert session.scalar(
            select(func.count(PhysicalCollector.id)).where(
                PhysicalCollector.team_id == team_id,
                PhysicalCollector.project_id == project_ids[0],
            )
        ) == 1
        assert session.scalar(
            select(func.count(CollectorPhoto.id)).where(
                CollectorPhoto.team_id == team_id,
                CollectorPhoto.project_id == project_ids[0],
            )
        ) == 1


def test_real_postgres_concurrent_same_photo_sha_commits_one_collector_binding(
    postgres_session_factory,
) -> None:
    """Catches one photo SHA being committed to two collectors in the same project."""
    team_id, project_ids = seed_inventory_projects(
        postgres_session_factory,
        project_count=1,
    )
    start = Barrier(3)
    shared_sha256 = "b1" * 32
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            register_inventory_once,
            postgres_session_factory,
            team_id=team_id,
            project_id=project_ids[0],
            collector_no="TASK7-SHA-A",
            photo_sha256=shared_sha256,
            start=start,
        )
        second = executor.submit(
            register_inventory_once,
            postgres_session_factory,
            team_id=team_id,
            project_id=project_ids[0],
            collector_no="TASK7-SHA-B",
            photo_sha256=shared_sha256,
            start=start,
        )
        start.wait(timeout=10)
        outcomes = [first.result(timeout=15), second.result(timeout=15)]

    assert sorted(kind for kind, _detail in outcomes) == ["conflict", "ok"], outcomes
    with postgres_session_factory() as session:
        assert session.scalar(
            select(func.count(PhysicalCollector.id)).where(
                PhysicalCollector.team_id == team_id,
                PhysicalCollector.project_id == project_ids[0],
            )
        ) == 1
        assert session.scalar(
            select(func.count(CollectorPhoto.id)).where(
                CollectorPhoto.team_id == team_id,
                CollectorPhoto.project_id == project_ids[0],
                CollectorPhoto.sha256 == shared_sha256,
            )
        ) == 1


def test_real_postgres_same_number_and_photo_sha_are_legal_across_projects(
    postgres_session_factory,
) -> None:
    """Catches project-scoped uniqueness accidentally remaining team-wide."""
    team_id, project_ids = seed_inventory_projects(
        postgres_session_factory,
        project_count=2,
    )
    start = Barrier(3)
    shared_sha256 = "c1" * 32
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                register_inventory_once,
                postgres_session_factory,
                team_id=team_id,
                project_id=project_id,
                collector_no="TASK7-CROSS-PROJECT",
                photo_sha256=shared_sha256,
                start=start,
            )
            for project_id in project_ids
        ]
        start.wait(timeout=10)
        outcomes = [future.result(timeout=15) for future in futures]

    assert [kind for kind, _detail in outcomes] == ["ok", "ok"], outcomes
    with postgres_session_factory() as session:
        physical_rows = list(
            session.scalars(
                select(PhysicalCollector).where(
                    PhysicalCollector.team_id == team_id,
                    PhysicalCollector.collector_no == "TASK7-CROSS-PROJECT",
                )
            )
        )
        photo_rows = list(
            session.scalars(
                select(CollectorPhoto).where(
                    CollectorPhoto.team_id == team_id,
                    CollectorPhoto.sha256 == shared_sha256,
                )
            )
        )

    assert {str(row.project_id) for row in physical_rows} == set(project_ids)
    assert {str(row.project_id) for row in photo_rows} == set(project_ids)


def seed_allocation_state(session_factory, *, pool_size: int) -> tuple[str, str, list[str]]:
    team_id = f"task7-collector-transfer-{uuid4().hex}"
    with session_factory.begin() as session:
        session.add(Team(id=team_id, name="Task 7 local PostgreSQL"))
        session.flush()
        project = Project(team_id=team_id, code=f"TASK7-{uuid4().hex[:10]}", name="Task 7", status=ProjectStatus.ACTIVE)
        session.add(project)
        session.flush()
        run = CollectorTransferRun(
            team_id=team_id,
            project_id=project.id,
            name="Task 7 concurrent allocation",
            status="inventory",
            source_snapshot_at=datetime.now(UTC),
            stats={},
            diagnostics=[],
        )
        session.add(run)
        session.flush()
        terminal = CollectorTransferTerminal(
            run_id=run.id,
            team_id=team_id,
            terminal_code="TASK7-T-001",
            installation_address="本地隔离验证地址",
            status="ready",
            meter_count=0,
            collector_requirement_count=1,
            diagnostics=[],
        )
        session.add(terminal)
        session.flush()
        requirement = CollectorRequirement(
            run_id=run.id,
            terminal_id=terminal.id,
            team_id=team_id,
            original_collector_no="ORIGINAL-TASK7",
            status="unmatched",
            sort_order=0,
            diagnostics=[],
        )
        session.add(requirement)
        for index in range(pool_size):
            physical = PhysicalCollector(
                team_id=team_id,
                project_id=project.id,
                collector_no=f"TASK7-POOL-{index + 1}",
                pool_status="available",
            )
            session.add(physical)
            session.flush()
            session.add(
                CollectorPhoto(
                    team_id=team_id,
                    project_id=project.id,
                    physical_collector_id=physical.id,
                    sha256=sha256(f"{team_id}:{index}".encode()).hexdigest(),
                    original_filename=f"TASK7-POOL-{index + 1}.jpg",
                    object_key=f"task7/TASK7-POOL-{index + 1}.jpg",
                    storage_type="local_upload",
                    is_active=True,
                )
            )
    return team_id, str(run.id), [str(requirement.id)]


def seed_partial_global_terminal_state(
    session_factory,
) -> tuple[str, str, str, str]:
    """Seed two requirements where one is replaced and the other remains missing."""
    team_id = f"task7-global-race-{uuid4().hex}"
    terminal_code = f"TASK7-GLOBAL-{uuid4().hex[:10]}"
    with session_factory.begin() as session:
        session.add(Team(id=team_id, name="Task 7 global terminal race"))
        session.flush()
        project = Project(
            team_id=team_id,
            code=f"TASK7-GLOBAL-{uuid4().hex[:10]}",
            name="Task 7 global terminal race",
            status=ProjectStatus.ACTIVE,
        )
        session.add(project)
        session.flush()
        project_id = str(project.id)
        for index in range(2):
            meter_no = f"TASK7-GLOBAL-METER-{index + 1}"
            collector_no = f"TASK7-GLOBAL-ORIGINAL-{index + 1}"
            catalog = TotalCatalogRow(
                id=uuid4(),
                team_id=team_id,
                project_id=project.id,
                terminal=terminal_code,
                original_meter_no=meter_no,
                meter_match_key=meter_no,
                installation_address="本地全局终端并发地址",
                raw_data={},
            )
            session.add(catalog)
            session.flush()
            group = MaterialGroup(
                id=uuid4(),
                team_id=team_id,
                project_id=project.id,
                total_catalog_row_id=catalog.id,
                legacy_id=f"task7-global-{index + 1}",
                terminal=terminal_code,
                meter_match_key=meter_no,
                display_meter_no=meter_no,
                installation_address="本地全局终端并发地址",
                status=GroupStatus.APPROVED,
                photo_count=2,
                raw_data={
                    "collector": collector_no,
                    "module_asset_no": f"TASK7-MODULE-{index + 1}",
                },
            )
            session.add(group)
            session.flush()
            session.add_all(
                (
                    Photo(
                        team_id=team_id,
                        group_id=group.id,
                        sha256=sha256(
                            f"{team_id}:source:{index}:module".encode()
                        ).hexdigest(),
                        object_key=f"task7/source/{group.id}/module.jpg",
                        image_url=f"/task7/source/{group.id}/module.jpg",
                        category="module_meter",
                        collector=collector_no,
                        asset_no=f"TASK7-MODULE-{index + 1}",
                        sort_order=0,
                        is_active=True,
                    ),
                    Photo(
                        team_id=team_id,
                        group_id=group.id,
                        sha256=sha256(
                            f"{team_id}:source:{index}:after".encode()
                        ).hexdigest(),
                        object_key=f"task7/source/{group.id}/after.jpg",
                        image_url=f"/task7/source/{group.id}/after.jpg",
                        category="after_box",
                        sort_order=1,
                        is_active=True,
                    ),
                )
            )
            session.add(
                GroupBarcodeVerification(
                    id=uuid4(),
                    team_id=team_id,
                    group_id=group.id,
                    status="passed",
                    meter_matched=True,
                    module_matched=True,
                    collector_matched=True,
                    recognition_source="task7",
                )
            )

    with session_factory() as session:
        opened = PostgresCollectorTransferService(
            session=session,
            team_id=team_id,
            actor="task7-seed",
        ).open_global_terminal(
            project_id=project_id,
            terminal_code=terminal_code,
        )
        run_id = opened["run_id"]
        terminal_id = opened["workbench_terminal_id"]
        run_uuid = UUID(run_id)
        terminal_uuid = UUID(terminal_id)
        project_uuid = UUID(project_id)

    with session_factory.begin() as session:
        requirements = list(
            session.scalars(
                select(CollectorRequirement)
                .where(CollectorRequirement.run_id == run_uuid)
                .order_by(CollectorRequirement.id)
            )
        )
        physicals: list[PhysicalCollector] = []
        photos: list[CollectorPhoto] = []
        for index in range(2):
            physical = PhysicalCollector(
                team_id=team_id,
                project_id=project_uuid,
                collector_no=f"TASK7-GLOBAL-POOL-{index + 1}",
                pool_status="reserved" if index == 0 else "available",
            )
            session.add(physical)
            session.flush()
            photo = CollectorPhoto(
                team_id=team_id,
                project_id=project_uuid,
                physical_collector_id=physical.id,
                sha256=sha256(f"{team_id}:pool:{index}".encode()).hexdigest(),
                original_filename=f"{physical.collector_no}.jpg",
                object_key=f"task7/pool/{physical.collector_no}.jpg",
                storage_type="local_upload",
                is_active=True,
            )
            session.add(photo)
            session.flush()
            physicals.append(physical)
            photos.append(photo)
        requirements[0].status = "assigned"
        assignment = CollectorAssignment(
            run_id=run_uuid,
            team_id=team_id,
            requirement_id=requirements[0].id,
            physical_collector_id=physicals[0].id,
            collector_photo_id=photos[0].id,
            assignment_mode="random",
            status="reserved",
            assigned_by_username="task7-seed",
        )
        session.add(assignment)
        session.flush()
        session.add(
            CollectorWorkbenchItem(
                run_id=run_uuid,
                terminal_id=terminal_uuid,
                team_id=team_id,
                item_kind="collector_removal",
                source_key=str(requirements[0].id),
                requirement_id=requirements[0].id,
                assignment_id=assignment.id,
                status="pending",
                sort_order=2,
            )
        )
        assignment_id = str(assignment.id)

    return team_id, terminal_id, assignment_id, run_id


def test_real_postgres_concurrent_allocation_is_stable_and_consumes_each_resource_once(postgres_session_factory) -> None:
    """Catches concurrent allocate calls duplicating one requirement or physical collector."""
    team_id, run_id, requirement_ids = seed_allocation_state(postgres_session_factory, pool_size=1)
    start = Barrier(3)

    def allocate_once() -> dict[str, object]:
        start.wait(timeout=10)
        with postgres_session_factory() as session:
            return PostgresCollectorTransferService(session=session, team_id=team_id, actor="task7").allocate(run_id=run_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(allocate_once)
        second = executor.submit(allocate_once)
        start.wait(timeout=10)
        outcomes = [first.result(timeout=15), second.result(timeout=15)]

    with postgres_session_factory() as session:
        assignments = list(session.scalars(select(CollectorAssignment).where(CollectorAssignment.run_id == run_id)))
        workbench_items = list(session.scalars(select(CollectorWorkbenchItem).where(CollectorWorkbenchItem.run_id == run_id)))
        requirements = list(session.scalars(select(CollectorRequirement).where(CollectorRequirement.id.in_(requirement_ids))))
        reserved = session.scalar(
            select(func.count(PhysicalCollector.id)).where(PhysicalCollector.team_id == team_id, PhysicalCollector.pool_status == "reserved")
        )

    assert sorted(
        (int(item["assignment_count"]), len(item["assignments"]))
        for item in outcomes
    ) == [(0, 0), (1, 1)]
    assert len(assignments) == 1
    assert len({row.requirement_id for row in assignments}) == 1
    assert len({row.physical_collector_id for row in assignments}) == 1
    assert [row.status for row in requirements] == ["assigned"]
    assert reserved == 1
    assert len(workbench_items) == 1


def test_real_postgres_two_runs_cannot_reserve_one_project_collector(
    postgres_session_factory,
) -> None:
    """Catches two runs concurrently reserving the same project inventory row."""
    team_id = f"task7-competing-runs-{uuid4().hex}"
    with postgres_session_factory.begin() as session:
        session.add(Team(id=team_id, name="Task 7 competing runs"))
        session.flush()
        project = Project(
            team_id=team_id,
            code=f"TASK7-RUNS-{uuid4().hex[:10]}",
            name="Task 7 competing runs",
            status=ProjectStatus.ACTIVE,
        )
        session.add(project)
        session.flush()
        physical = PhysicalCollector(
            team_id=team_id,
            project_id=project.id,
            collector_no="TASK7-ONE-PHYSICAL",
            pool_status="available",
        )
        session.add(physical)
        session.flush()
        session.add(
            CollectorPhoto(
                team_id=team_id,
                project_id=project.id,
                physical_collector_id=physical.id,
                sha256="d1" * 32,
                original_filename="TASK7-ONE-PHYSICAL.jpg",
                object_key="task7/TASK7-ONE-PHYSICAL.jpg",
                storage_type="local_upload",
                is_active=True,
            )
        )
        run_ids: list[str] = []
        requirement_ids: list[str] = []
        for index in range(2):
            run = CollectorTransferRun(
                team_id=team_id,
                project_id=project.id,
                name=f"Task 7 competing run {index + 1}",
                status="inventory",
                source_snapshot_at=datetime.now(UTC),
                stats={},
                diagnostics=[],
            )
            session.add(run)
            session.flush()
            terminal = CollectorTransferTerminal(
                run_id=run.id,
                team_id=team_id,
                terminal_code=f"TASK7-COMPETING-{index + 1}",
                installation_address="本地隔离验证地址",
                status="ready",
                meter_count=0,
                collector_requirement_count=1,
                diagnostics=[],
            )
            session.add(terminal)
            session.flush()
            requirement = CollectorRequirement(
                run_id=run.id,
                terminal_id=terminal.id,
                team_id=team_id,
                original_collector_no=f"ORIGINAL-{index + 1}",
                status="unmatched",
                sort_order=0,
                diagnostics=[],
            )
            session.add(requirement)
            session.flush()
            run_ids.append(str(run.id))
            requirement_ids.append(str(requirement.id))

    start = Barrier(3)

    def allocate_once(run_id: str) -> tuple[str, str]:
        start.wait(timeout=10)
        with postgres_session_factory() as session:
            try:
                result = PostgresCollectorTransferService(
                    session=session,
                    team_id=team_id,
                    actor="task7",
                ).allocate(run_id=run_id)
                return "ok", str(result["assignment_count"])
            except PoolInsufficientError as exc:
                session.rollback()
                return "insufficient", str(exc.available)
            except Exception as exc:  # assertion records any leaked database failure
                session.rollback()
                return "unexpected", f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(allocate_once, run_id) for run_id in run_ids]
        start.wait(timeout=10)
        outcomes = [future.result(timeout=15) for future in futures]

    assert sorted(kind for kind, _detail in outcomes) == ["insufficient", "ok"], outcomes
    with postgres_session_factory() as session:
        assignments = list(
            session.scalars(
                select(CollectorAssignment).where(
                    CollectorAssignment.run_id.in_(run_ids)
                )
            )
        )
        requirements = list(
            session.scalars(
                select(CollectorRequirement).where(
                    CollectorRequirement.id.in_(requirement_ids)
                )
            )
        )
        persisted_physical = session.scalar(
            select(PhysicalCollector).where(PhysicalCollector.id == physical.id)
        )

    assert len(assignments) == 1
    assert len({row.physical_collector_id for row in assignments}) == 1
    assert sorted(row.status for row in requirements) == ["assigned", "unmatched"]
    assert persisted_physical.pool_status == "reserved"


def test_real_postgres_pool_shortage_has_zero_allocation_side_effects(postgres_session_factory) -> None:
    """Catches a PostgreSQL shortage committing any partial allocation or audit row."""
    team_id, run_id, requirement_ids = seed_allocation_state(postgres_session_factory, pool_size=0)
    with postgres_session_factory() as session:
        service = PostgresCollectorTransferService(session=session, team_id=team_id, actor="task7")
        with pytest.raises(PoolInsufficientError):
            service.allocate(run_id=run_id)
        session.rollback()
        assert session.scalar(select(func.count(CollectorAssignment.id)).where(CollectorAssignment.run_id == run_id)) == 0
        assert session.scalar(select(func.count(CollectorWorkbenchItem.id)).where(CollectorWorkbenchItem.run_id == run_id)) == 0
        assert session.scalar(select(func.count(AuditLog.id)).where(AuditLog.team_id == team_id)) == 0
        assert session.scalar(select(CollectorRequirement.status).where(CollectorRequirement.id == requirement_ids[0])) == "unmatched"


def test_real_postgres_rolled_back_assignment_releases_requirement_and_collector(postgres_session_factory) -> None:
    """Catches a rollback that only changes the index status but leaves resources and workbench state consumed."""
    team_id, run_id, requirement_ids = seed_allocation_state(postgres_session_factory, pool_size=1)
    with postgres_session_factory() as session:
        service = PostgresCollectorTransferService(session=session, team_id=team_id, actor="task7-admin")
        allocated = service.allocate(run_id=run_id)
        assignment_id = allocated["assignments"][0]["assignment_id"]
        rolled_back = service.rollback_assignment(assignment_id=assignment_id)

    assert allocated["assignment_count"] == 1
    assert rolled_back == {
        "assignment_id": assignment_id,
        "run_id": run_id,
        "status": "rolled_back",
        "stats": {
            "active_assignment_count": 0,
            "assignment_count": 0,
            "direct_match_count": 0,
            "random_match_count": 0,
            "pool_available_count": 1,
        },
    }

    with postgres_session_factory() as session:
        assignment = session.get(CollectorAssignment, assignment_id)
        requirement = session.get(CollectorRequirement, requirement_ids[0])
        physical = session.scalar(select(PhysicalCollector).where(PhysicalCollector.team_id == team_id))
        workbench_items = list(session.scalars(select(CollectorWorkbenchItem).where(CollectorWorkbenchItem.run_id == run_id)))
        run = session.get(CollectorTransferRun, run_id)
        audit_actions = list(session.scalars(select(AuditLog.action).where(AuditLog.team_id == team_id)))

    assert assignment.status == "rolled_back"
    assert requirement.status == "unmatched"
    assert physical.pool_status == "available"
    assert workbench_items == []
    assert run.status == "inventory"
    assert run.stats["assignment_count"] == 0
    assert "collector_transfer.assignment_rolled_back" in audit_actions

    with postgres_session_factory() as session:
        result = PostgresCollectorTransferService(session=session, team_id=team_id, actor="task7").allocate(run_id=run_id)

    with postgres_session_factory() as session:
        assignments = list(
            session.scalars(select(CollectorAssignment).where(CollectorAssignment.run_id == run_id))
        )
        requirement = session.get(CollectorRequirement, requirement_ids[0])
        physical = session.scalar(select(PhysicalCollector).where(PhysicalCollector.team_id == team_id))

    assert result["assignment_count"] == 1
    assert len(assignments) == 2
    assert sorted(assignment.status for assignment in assignments) == ["reserved", "rolled_back"]
    assert sum(assignment.status in {"reserved", "used"} for assignment in assignments) == 1
    assert requirement.status == "assigned"
    assert physical.pool_status == "reserved"


def test_real_postgres_completion_and_rollback_share_deadlock_free_lock_order(
    postgres_session_factory,
) -> None:
    """Catches completion locking workbench-first while rollback locks assignment-first."""
    team_id, run_id, _requirement_ids = seed_allocation_state(postgres_session_factory, pool_size=1)
    with postgres_session_factory() as session:
        allocated = PostgresCollectorTransferService(
            session=session,
            team_id=team_id,
            actor="task7-admin",
        ).allocate(run_id=run_id)
        assignment_id = allocated["assignments"][0]["assignment_id"]
        workbench_item_id = str(
            session.scalar(
                select(CollectorWorkbenchItem.id).where(
                    CollectorWorkbenchItem.assignment_id == assignment_id
                )
            )
        )

    first_lock_barrier = Barrier(2)
    engine = postgres_session_factory.kw["bind"]

    def synchronize_inverted_first_locks(conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        normalized = " ".join(statement.lower().split())
        if "for update" not in normalized:
            return
        conn.info["collector_transfer_lock_count"] = int(
            conn.info.get("collector_transfer_lock_count", 0)
        ) + 1
        if conn.info["collector_transfer_lock_count"] != 1:
            return
        role = conn.info.get("collector_transfer_role")
        is_old_first_lock = (
            role == "complete" and "from collector_workbench_items" in normalized
        ) or (
            role == "rollback" and "from collector_assignments" in normalized
        )
        if is_old_first_lock:
            first_lock_barrier.wait(timeout=10)

    event.listen(engine, "after_cursor_execute", synchronize_inverted_first_locks)

    def run_operation(role: str) -> tuple[str, str]:
        with postgres_session_factory() as session:
            connection = session.connection()
            connection.info["collector_transfer_role"] = role
            connection.info["collector_transfer_lock_count"] = 0
            transfer = PostgresCollectorTransferService(
                session=session,
                team_id=team_id,
                actor=f"task7-{role}",
            )
            try:
                if role == "complete":
                    result = transfer.set_workbench_item_status(
                        item_id=workbench_item_id,
                        completed=True,
                    )
                else:
                    result = transfer.rollback_assignment(assignment_id=assignment_id)
                return "ok", str(result.get("status"))
            except KeyError:
                session.rollback()
                return "not_found", "404"
            except CollectorWorkbenchIncompleteError:
                session.rollback()
                return "conflict", "409"
            except Exception as exc:  # assertion below records any leaked database/deadlock failure
                session.rollback()
                return "unexpected", f"{type(exc).__name__}: {exc}"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            complete_future = executor.submit(run_operation, "complete")
            rollback_future = executor.submit(run_operation, "rollback")
            outcomes = [complete_future.result(timeout=20), rollback_future.result(timeout=20)]
    finally:
        event.remove(engine, "after_cursor_execute", synchronize_inverted_first_locks)

    assert all(kind != "unexpected" for kind, _detail in outcomes), outcomes
    assert {kind for kind, _detail in outcomes}.issubset({"ok", "not_found", "conflict"})


def test_real_postgres_concurrent_direct_claim_allows_one_hidden_terminal(
    postgres_session_factory,
) -> None:
    """Catches two terminal reconciliations claiming one direct physical after racing past ownership checks."""
    team_id = f"task7-direct-claim-{uuid4().hex}"
    with postgres_session_factory.begin() as session:
        session.add(Team(id=team_id, name="Task 7 direct claim"))
        session.flush()
        project = Project(
            team_id=team_id,
            code=f"TASK7-DIRECT-{uuid4().hex[:10]}",
            name="Task 7 direct claim",
            status=ProjectStatus.ACTIVE,
        )
        session.add(project)
        session.flush()
        physical = PhysicalCollector(
            team_id=team_id,
            project_id=project.id,
            collector_no="TASK7-SHARED-DIRECT",
            pool_status="direct",
        )
        session.add(physical)
        terminal_ids: list[str] = []
        for index in range(2):
            terminal_code = f"TASK7-DIRECT-T-{index + 1}"
            run = CollectorTransferRun(
                team_id=team_id,
                project_id=project.id,
                name=f"Task 7 direct run {index + 1}",
                status="inventory",
                stats={
                    "workflow_kind": "global_terminal_workbench",
                    "source_terminal_code": terminal_code,
                    "source_revision": f"revision-{index + 1}",
                    "superseded": False,
                },
                diagnostics=[],
            )
            session.add(run)
            session.flush()
            terminal = CollectorTransferTerminal(
                run_id=run.id,
                team_id=team_id,
                terminal_code=terminal_code,
                installation_address="并发直接实物地址",
                status="ready",
                meter_count=0,
                collector_requirement_count=1,
                diagnostics=[],
            )
            session.add(terminal)
            session.flush()
            session.add(
                CollectorRequirement(
                    run_id=run.id,
                    terminal_id=terminal.id,
                    team_id=team_id,
                    original_collector_no="TASK7-SHARED-DIRECT",
                    status="unmatched",
                    sort_order=0,
                    diagnostics=[],
                )
            )
            terminal_ids.append(str(terminal.id))

    start = Barrier(3)

    def reconcile_once(terminal_id: str) -> tuple[str, str]:
        start.wait(timeout=10)
        with postgres_session_factory() as session:
            transfer = PostgresCollectorTransferService(
                session=session,
                team_id=team_id,
                actor="task7-direct",
            )
            try:
                result = transfer.global_terminal_detail(
                    terminal_id=terminal_id
                )
                session.scalar(select(func.count(Team.id)))
                return "ok", str(result["collector_items"][0]["physical_state"])
            except CollectorDirectConflictError as exc:
                session.rollback()
                session.scalar(select(func.count(Team.id)))
                return "direct_conflict", str(exc)
            except Exception as exc:
                session.rollback()
                return "unexpected", f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(reconcile_once, terminal_id)
            for terminal_id in terminal_ids
        ]
        start.wait(timeout=10)
        outcomes = [future.result(timeout=20) for future in futures]

    assert sorted(kind for kind, _detail in outcomes) == [
        "direct_conflict",
        "ok",
    ], outcomes
    with postgres_session_factory() as session:
        direct_items = list(
            session.scalars(
                select(CollectorWorkbenchItem)
                .join(
                    CollectorRequirement,
                    CollectorRequirement.id
                    == CollectorWorkbenchItem.requirement_id,
                )
                .where(
                    CollectorWorkbenchItem.team_id == team_id,
                    CollectorWorkbenchItem.assignment_id.is_(None),
                    CollectorRequirement.original_collector_no
                    == "TASK7-SHARED-DIRECT",
                    CollectorRequirement.status == "direct_ready",
                )
            )
        )
        persisted_physical = session.scalar(
            select(PhysicalCollector).where(
                PhysicalCollector.team_id == team_id,
                PhysicalCollector.collector_no == "TASK7-SHARED-DIRECT",
            )
        )
        assignment_count = session.scalar(
            select(func.count(CollectorAssignment.id)).where(
                CollectorAssignment.team_id == team_id
            )
        )
        photo_count = session.scalar(
            select(func.count(CollectorPhoto.id)).where(
                CollectorPhoto.team_id == team_id
            )
        )

    assert len(direct_items) == 1
    assert persisted_physical.pool_status == "direct"
    assert assignment_count == 0
    assert photo_count == 0


def test_real_postgres_replace_and_rollback_share_canonical_lock_order(
    postgres_session_factory,
) -> None:
    """Catches terminal replacement and rollback deadlocking or leaving mixed resource states."""
    team_id, terminal_id, assignment_id, run_id = seed_partial_global_terminal_state(
        postgres_session_factory
    )
    start = Barrier(3)

    def run_operation(role: str) -> tuple[str, str]:
        start.wait(timeout=10)
        with postgres_session_factory() as session:
            transfer = PostgresCollectorTransferService(
                session=session,
                team_id=team_id,
                actor=f"task7-{role}",
            )
            try:
                if role == "replace":
                    result = transfer.replace_terminal_missing(
                        terminal_id=terminal_id
                    )
                    return "ok", str(result["assigned"])
                result = transfer.rollback_assignment(
                    assignment_id=assignment_id
                )
                return "ok", str(result["status"])
            except (
                CollectorAllocationConflictError,
                CollectorWorkbenchIncompleteError,
                PoolInsufficientError,
                KeyError,
            ) as exc:
                session.rollback()
                return "controlled", f"{type(exc).__name__}: {exc}"
            except Exception as exc:
                session.rollback()
                return "unexpected", f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=2) as executor:
        replace_future = executor.submit(run_operation, "replace")
        rollback_future = executor.submit(run_operation, "rollback")
        start.wait(timeout=10)
        outcomes = [
            replace_future.result(timeout=20),
            rollback_future.result(timeout=20),
        ]

    assert [kind for kind, _detail in outcomes] == ["ok", "ok"], outcomes
    with postgres_session_factory() as session:
        requirements = list(
            session.scalars(
                select(CollectorRequirement)
                .where(CollectorRequirement.run_id == UUID(run_id))
                .order_by(CollectorRequirement.id)
            )
        )
        physicals = list(
            session.scalars(
                select(PhysicalCollector)
                .where(PhysicalCollector.team_id == team_id)
                .order_by(PhysicalCollector.id)
            )
        )
        assignments = list(
            session.scalars(
                select(CollectorAssignment)
                .where(CollectorAssignment.run_id == UUID(run_id))
                .order_by(CollectorAssignment.id)
            )
        )
        removal_items = list(
            session.scalars(
                select(CollectorWorkbenchItem).where(
                    CollectorWorkbenchItem.run_id == UUID(run_id),
                    CollectorWorkbenchItem.item_kind == "collector_removal",
                )
            )
        )
        terminal = session.get(CollectorTransferTerminal, UUID(terminal_id))

    active = [row for row in assignments if row.status in {"reserved", "used"}]
    active_requirement_ids = {row.requirement_id for row in active}
    active_physical_ids = {row.physical_collector_id for row in active}
    assert len(active_requirement_ids) == len(active)
    assert len(active_physical_ids) == len(active)
    assert 1 <= len(active) <= 2
    assert next(
        row for row in assignments if str(row.id) == assignment_id
    ).status == "rolled_back"
    assert {
        row.id: row.status for row in requirements
    } == {
        row.id: ("assigned" if row.id in active_requirement_ids else "unmatched")
        for row in requirements
    }
    assert {
        row.id: row.pool_status for row in physicals
    } == {
        row.id: ("reserved" if row.id in active_physical_ids else "available")
        for row in physicals
    }
    assert {row.assignment_id for row in removal_items} == {row.id for row in active}
    assert terminal.completed_item_count == 0


def test_real_postgres_replace_and_complete_share_canonical_lock_order(
    postgres_session_factory,
) -> None:
    """Catches terminal replacement and completion deadlocking or losing either state transition."""
    team_id, terminal_id, assignment_id, run_id = seed_partial_global_terminal_state(
        postgres_session_factory
    )
    with postgres_session_factory() as session:
        workbench_item_id = str(
            session.scalar(
                select(CollectorWorkbenchItem.id).where(
                    CollectorWorkbenchItem.assignment_id == UUID(assignment_id)
                )
            )
        )
    start = Barrier(3)

    def run_operation(role: str) -> tuple[str, str]:
        start.wait(timeout=10)
        with postgres_session_factory() as session:
            transfer = PostgresCollectorTransferService(
                session=session,
                team_id=team_id,
                actor=f"task7-{role}",
            )
            try:
                if role == "replace":
                    result = transfer.replace_terminal_missing(
                        terminal_id=terminal_id
                    )
                    return "ok", str(result["assigned"])
                result = transfer.set_workbench_item_status(
                    item_id=workbench_item_id,
                    completed=True,
                )
                return "ok", str(result["status"])
            except (
                CollectorAllocationConflictError,
                CollectorWorkbenchIncompleteError,
                PoolInsufficientError,
                KeyError,
            ) as exc:
                session.rollback()
                return "controlled", f"{type(exc).__name__}: {exc}"
            except Exception as exc:
                session.rollback()
                return "unexpected", f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=2) as executor:
        replace_future = executor.submit(run_operation, "replace")
        complete_future = executor.submit(run_operation, "complete")
        start.wait(timeout=10)
        outcomes = [
            replace_future.result(timeout=20),
            complete_future.result(timeout=20),
        ]

    assert [kind for kind, _detail in outcomes] == ["ok", "ok"], outcomes
    with postgres_session_factory() as session:
        requirements = list(
            session.scalars(
                select(CollectorRequirement)
                .where(CollectorRequirement.run_id == UUID(run_id))
                .order_by(CollectorRequirement.id)
            )
        )
        physicals = list(
            session.scalars(
                select(PhysicalCollector)
                .where(PhysicalCollector.team_id == team_id)
                .order_by(PhysicalCollector.id)
            )
        )
        assignments = list(
            session.scalars(
                select(CollectorAssignment)
                .where(
                    CollectorAssignment.run_id == UUID(run_id),
                    CollectorAssignment.status.in_(("reserved", "used")),
                )
                .order_by(CollectorAssignment.id)
            )
        )
        removal_items = list(
            session.scalars(
                select(CollectorWorkbenchItem).where(
                    CollectorWorkbenchItem.run_id == UUID(run_id),
                    CollectorWorkbenchItem.item_kind == "collector_removal",
                )
            )
        )
        terminal = session.get(CollectorTransferTerminal, UUID(terminal_id))

    assert len(assignments) == 2
    assert len({row.requirement_id for row in assignments}) == 2
    assert len({row.physical_collector_id for row in assignments}) == 2
    assert sorted(row.status for row in assignments) == ["reserved", "used"]
    assert sorted(row.status for row in requirements) == ["assigned", "used"]
    assert sorted(row.pool_status for row in physicals) == ["reserved", "used"]
    assert len(removal_items) == 2
    assert sum(row.status == "completed" for row in removal_items) == 1
    assert terminal.completed_item_count == 1
    assert terminal.status == "in_progress"


def test_real_postgres_concurrent_terminal_replacement_is_idempotent(
    postgres_session_factory,
) -> None:
    """Catches two replace clicks duplicating assignments, mappings, or terminal audits."""
    team_id, terminal_id, assignment_id, run_id = seed_partial_global_terminal_state(
        postgres_session_factory
    )
    with postgres_session_factory() as session:
        PostgresCollectorTransferService(
            session=session,
            team_id=team_id,
            actor="task7-reset",
        ).rollback_assignment(assignment_id=assignment_id)
    start = Barrier(3)

    def replace_once() -> tuple[str, int | str]:
        start.wait(timeout=10)
        with postgres_session_factory() as session:
            try:
                result = PostgresCollectorTransferService(
                    session=session,
                    team_id=team_id,
                    actor="task7-replace",
                ).replace_terminal_missing(terminal_id=terminal_id)
                return "ok", int(result["assigned"])
            except Exception as exc:
                session.rollback()
                return "unexpected", f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(replace_once)
        second = executor.submit(replace_once)
        start.wait(timeout=10)
        outcomes = [first.result(timeout=20), second.result(timeout=20)]

    assert [kind for kind, _detail in outcomes] == ["ok", "ok"], outcomes
    assert sorted(int(detail) for _kind, detail in outcomes) == [0, 2]
    with postgres_session_factory() as session:
        active_assignments = list(
            session.scalars(
                select(CollectorAssignment).where(
                    CollectorAssignment.run_id == UUID(run_id),
                    CollectorAssignment.status.in_(("reserved", "used")),
                )
            )
        )
        requirements = list(
            session.scalars(
                select(CollectorRequirement).where(
                    CollectorRequirement.run_id == UUID(run_id)
                )
            )
        )
        physicals = list(
            session.scalars(
                select(PhysicalCollector).where(PhysicalCollector.team_id == team_id)
            )
        )
        removal_items = list(
            session.scalars(
                select(CollectorWorkbenchItem).where(
                    CollectorWorkbenchItem.run_id == UUID(run_id),
                    CollectorWorkbenchItem.item_kind == "collector_removal",
                )
            )
        )
        replacement_audits = session.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.team_id == team_id,
                AuditLog.action == "collector_workbench.terminal_replaced",
            )
        )

    assert len(active_assignments) == 2
    assert len({row.requirement_id for row in active_assignments}) == 2
    assert len({row.physical_collector_id for row in active_assignments}) == 2
    assert all(row.status == "assigned" for row in requirements)
    assert all(row.pool_status == "reserved" for row in physicals)
    assert len(removal_items) == 2
    assert replacement_audits == 1


def test_real_postgres_terminal_review_change_after_terminal_lock_is_deadlock_free_and_atomic(
    postgres_session_factory,
) -> None:
    """Catches a source-photo review change deadlocking replacement or leaking a partial pool allocation."""
    team_id, terminal_id, _assignment_id, run_id = seed_partial_global_terminal_state(
        postgres_session_factory
    )
    terminal_locked = Barrier(2)
    source_committed = Barrier(2)
    engine = postgres_session_factory.kw["bind"]

    def pause_after_terminal_lock(
        conn, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        normalized = " ".join(statement.lower().split())
        if (
            conn.info.get("collector_transfer_role") == "replace"
            and not conn.info.get("terminal_review_pause_seen")
            and "from collector_transfer_terminals" in normalized
            and "for update" in normalized
        ):
            conn.info["terminal_review_pause_seen"] = True
            terminal_locked.wait(timeout=10)
            source_committed.wait(timeout=10)

    event.listen(engine, "after_cursor_execute", pause_after_terminal_lock)

    def replace_after_source_change() -> tuple[str, str]:
        with postgres_session_factory() as session:
            connection = session.connection()
            connection.info["collector_transfer_role"] = "replace"
            try:
                PostgresCollectorTransferService(
                    session=session,
                    team_id=team_id,
                    actor="task7-replace",
                ).replace_terminal_missing(terminal_id=terminal_id)
                return "unexpected", "replacement accepted changed source"
            except TerminalSourceChangedError:
                session.rollback()
                return "terminal_source_changed", "ok"
            except TerminalReviewRequiredError:
                session.rollback()
                return "terminal_review_required", "ok"
            except Exception as exc:
                session.rollback()
                return "unexpected", f"{type(exc).__name__}: {exc}"

    def change_active_source_photo() -> tuple[str, str]:
        terminal_locked.wait(timeout=10)
        try:
            with postgres_session_factory.begin() as session:
                photo = session.scalar(
                    select(Photo)
                    .join(MaterialGroup, MaterialGroup.id == Photo.group_id)
                    .where(
                        MaterialGroup.team_id == team_id,
                        MaterialGroup.terminal
                        == session.scalar(
                            select(CollectorTransferTerminal.terminal_code).where(
                                CollectorTransferTerminal.id == UUID(terminal_id)
                            )
                        ),
                        Photo.is_active.is_(True),
                    )
                    .order_by(Photo.group_id, Photo.sort_order, Photo.id)
                    .with_for_update()
                )
                assert photo is not None
                photo.sha256 = sha256(f"{team_id}:changed-source".encode()).hexdigest()
            return "source_changed", "ok"
        finally:
            source_committed.wait(timeout=10)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            replacement = executor.submit(replace_after_source_change)
            source_change = executor.submit(change_active_source_photo)
            outcomes = [
                replacement.result(timeout=20),
                source_change.result(timeout=20),
            ]
    finally:
        event.remove(engine, "after_cursor_execute", pause_after_terminal_lock)

    assert ("source_changed", "ok") in outcomes, outcomes
    assert any(
        outcome[0] in {"terminal_source_changed", "terminal_review_required"}
        for outcome in outcomes
    ), outcomes
    assert all(outcome[0] != "unexpected" for outcome in outcomes), outcomes
    with postgres_session_factory() as session:
        assignments = list(
            session.scalars(
                select(CollectorAssignment)
                .where(CollectorAssignment.run_id == UUID(run_id))
                .order_by(CollectorAssignment.id)
            )
        )
        requirements = list(
            session.scalars(
                select(CollectorRequirement)
                .where(CollectorRequirement.run_id == UUID(run_id))
                .order_by(CollectorRequirement.id)
            )
        )
        physicals = list(
            session.scalars(
                select(PhysicalCollector)
                .where(PhysicalCollector.team_id == team_id)
                .order_by(PhysicalCollector.id)
            )
        )

    assert len(assignments) == 1
    assert [row.status for row in requirements].count("assigned") == 1
    assert [row.status for row in requirements].count("unmatched") == 1
    assert [row.pool_status for row in physicals].count("reserved") == 1
    assert [row.pool_status for row in physicals].count("available") == 1
