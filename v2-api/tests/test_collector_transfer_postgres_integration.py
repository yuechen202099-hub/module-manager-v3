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
from sqlalchemy import create_engine, func, select
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
from app.services.collector_transfer import PostgresCollectorTransferService


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
                collector_no=f"TASK7-POOL-{index + 1}",
                pool_status="available",
            )
            session.add(physical)
            session.flush()
            session.add(
                CollectorPhoto(
                    team_id=team_id,
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
    assert rolled_back == {"assignment_id": assignment_id, "run_id": run_id, "status": "rolled_back"}

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
