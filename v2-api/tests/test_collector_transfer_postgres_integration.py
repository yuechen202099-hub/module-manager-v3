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
from uuid import uuid4

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
    PhysicalCollector,
    Project,
    ProjectStatus,
    Team,
)
from app.services.collector_transfer import (
    CollectorPhotoConflictError,
    CollectorWorkbenchIncompleteError,
    PostgresCollectorTransferService,
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

    assert sorted(int(item["assignment_count"]) for item in outcomes) == [1, 1]
    assert sorted(len(item["assignments"]) for item in outcomes) == [0, 1]
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
