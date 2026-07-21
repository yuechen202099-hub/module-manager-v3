from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    AuditLog,
    GroupStatus,
    MaterialGroup,
    Project,
    Task,
    TaskStatus,
    Team,
    TotalCatalogRow,
    UnmatchedRecord,
)
from app.services import local_simulation
from app.services import state_repository as repository


@pytest.fixture()
def isolated_postgres(monkeypatch: pytest.MonkeyPatch):
    database_url = os.getenv("ROUND3_POSTGRES_TEST_URL", "").strip()
    if not database_url:
        pytest.skip("ROUND3_POSTGRES_TEST_URL is required for the real PostgreSQL concurrency test")
    parsed = make_url(database_url)
    assert parsed.get_backend_name() == "postgresql"
    assert parsed.host in {"localhost", "127.0.0.1", "::1"}, "PostgreSQL concurrency test must stay local"

    schema = f"round3_{uuid4().hex}"
    admin_engine = create_engine(database_url, pool_pre_ping=True)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    test_engine = create_engine(
        database_url,
        pool_pre_ping=True,
        execution_options={"schema_translate_map": {None: schema}},
        connect_args={
            "options": f"-csearch_path={schema},public -cstatement_timeout=15000 -clock_timeout=10000"
        },
    )
    try:
        Base.metadata.create_all(test_engine)
        with test_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE FUNCTION delay_round3_task_insert() RETURNS trigger AS $$
                    BEGIN
                        PERFORM pg_sleep(1);
                        RETURN NEW;
                    END;
                    $$ LANGUAGE plpgsql
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TRIGGER delay_round3_task_insert
                    BEFORE INSERT ON tasks
                    FOR EACH ROW EXECUTE FUNCTION delay_round3_task_insert()
                    """
                )
            )
        session_factory = sessionmaker(
            bind=test_engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        monkeypatch.setattr(repository, "SessionLocal", session_factory)
        yield session_factory
    finally:
        test_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def test_concurrent_postgres_finalization_for_same_terminal_reuses_one_task(
    isolated_postgres,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = isolated_postgres
    team_id = f"round3-team-{uuid4().hex[:12]}"
    terminal = "T-ROUND3-CONCURRENT"
    unmatched_ids = [f"round3-unmatched-{index}" for index in range(2)]
    meter_numbers = ["120000912473", "120000912474"]
    meter_keys = [local_simulation.build_total_catalog_match_key(value) for value in meter_numbers]
    monkeypatch.setattr(local_simulation, "current_team_id", lambda: team_id)

    with session_factory.begin() as session:
        team = Team(id=team_id, name="Round 3 PostgreSQL test")
        session.add(team)
        session.flush()
        project = Project(team_id=team_id, code=f"ROUND3-{uuid4().hex[:12]}", name="Round 3 project")
        session.add(project)
        session.flush()
        for index, (unmatched_id, meter_no, meter_key) in enumerate(
            zip(unmatched_ids, meter_numbers, meter_keys, strict=True)
        ):
            session.add(
                TotalCatalogRow(
                    team_id=team_id,
                    project_id=project.id,
                    source_row_number=index + 1,
                    terminal=terminal,
                    original_meter_no=meter_no,
                    meter_match_key=meter_key,
                    installation_address=f"Round 3 road {index}",
                    raw_data={},
                )
            )
            session.add(
                UnmatchedRecord(
                    team_id=team_id,
                    legacy_id=unmatched_id,
                    record_type="scan",
                    status="open",
                    terminal="",
                    meter_no=meter_no,
                    meter_match_key=meter_key,
                    barcode=meter_no,
                    collector="C001",
                    module_asset_no=f"M00{index}",
                    address=f"Round 3 road {index}",
                    payload={
                        "temporary_review": {
                            "schema_version": 1,
                            "unmatched_id": unmatched_id,
                            "version": 1,
                            "state": "reviewed",
                            "meter_no": meter_no,
                            "collector": "C001",
                            "module_asset_no": f"M00{index}",
                            "manual_confirmed": True,
                            "reviewer": "reviewer-a",
                            "photos": [],
                        }
                    },
                )
            )

    state_repo = repository.PostgresStateRepository()
    candidate_keys = [
        state_repo.list_unmatched_match_candidates(unmatched_id)["items"][0]["candidate_key"]
        for unmatched_id in unmatched_ids
    ]
    start = Barrier(2)

    def finalize(index: int) -> dict:
        start.wait(timeout=5)
        return state_repo.finalize_unmatched_match(
            unmatched_ids[index],
            actor=f"admin-{index}",
            candidate_key=candidate_keys[index],
            expected_version=1,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(finalize, index) for index in range(2)]
        results = [future.result(timeout=15) for future in futures]

    with session_factory() as session:
        tasks = list(
            session.scalars(select(Task).where(Task.team_id == team_id, Task.terminal == terminal)).all()
        )
        groups = list(
            session.scalars(
                select(MaterialGroup).where(
                    MaterialGroup.team_id == team_id,
                    MaterialGroup.meter_match_key.in_(meter_keys),
                )
            ).all()
        )
        task_count = session.scalar(
            select(func.count(Task.id)).where(Task.team_id == team_id, Task.terminal == terminal)
        )

    assert len(results) == 2
    assert task_count == 1
    assert len(tasks) == 1
    assert len(groups) == 2
    assert {group.meter_match_key for group in groups} == set(meter_keys)
    assert {group.task_id for group in groups} == {tasks[0].id}


@pytest.mark.parametrize(
    ("order", "setter_priority"),
    [
        ("setter_before_upload", True),
        ("upload_before_setter", False),
    ],
)
def test_concurrent_postgres_priority_setter_and_final_upload_settle_closed_task(
    isolated_postgres,
    monkeypatch: pytest.MonkeyPatch,
    order: str,
    setter_priority: bool,
) -> None:
    session_factory = isolated_postgres
    team_id = f"round3-priority-team-{uuid4().hex[:12]}"
    task_id = 310083
    group_id = f"round3-priority-group-{uuid4().hex[:12]}"
    constructor = "constructor-round3"
    monkeypatch.setattr(local_simulation, "current_team_id", lambda: team_id)

    with session_factory.begin() as session:
        team = Team(id=team_id, name="Round 3 priority concurrency test")
        session.add(team)
        session.flush()
        project = Project(team_id=team_id, code=f"ROUND3-P-{uuid4().hex[:12]}", name="Round 3 project")
        session.add(project)
        session.flush()
        task = Task(
            team_id=team_id,
            legacy_id=task_id,
            terminal="T-ROUND3-PRIORITY",
            project_id=project.id,
            title="Round 3 priority terminal",
            status=TaskStatus.PUBLISHED,
            construction_enabled=True,
            construction_claimed_by=constructor,
            construction_priority=True,
            raw_data={},
        )
        session.add(task)
        session.flush()
        session.add(
            MaterialGroup(
                team_id=team_id,
                legacy_id=group_id,
                legacy_task_id=task_id,
                terminal=task.terminal,
                project_id=project.id,
                task_id=task.id,
                meter_match_key=f"round3-priority-meter-{uuid4().hex[:12]}",
                display_meter_no="120000912483",
                installation_address="Round 3 priority road",
                status=GroupStatus.UNREVIEWED,
                photo_count=0,
                raw_data={},
            )
        )

    state_repo = repository.PostgresStateRepository()
    start = Barrier(3)
    allow_second_task_lock = Event()
    first_operation_finished = Event()
    upload_finished = Event()
    original_group_lookup = repository.PostgresStateRepository._group_by_legacy_id
    original_task_lookup = repository.PostgresStateRepository._task_by_legacy_id

    if order == "setter_before_upload":
        def gate_upload_after_group_lock(self, session, checked_group_id, *, lock=False):
            group = original_group_lookup(self, session, checked_group_id, lock=lock)
            assert allow_second_task_lock.wait(timeout=10)
            return group

        monkeypatch.setattr(
            repository.PostgresStateRepository,
            "_group_by_legacy_id",
            gate_upload_after_group_lock,
        )
    else:
        def gate_setter_before_task_lock(self, session, checked_task_id, *, lock=False):
            assert allow_second_task_lock.wait(timeout=10)
            return original_task_lookup(self, session, checked_task_id, lock=lock)

        monkeypatch.setattr(
            repository.PostgresStateRepository,
            "_task_by_legacy_id",
            gate_setter_before_task_lock,
        )

    def set_priority() -> dict:
        start.wait(timeout=5)
        result = state_repo.set_construction_task_priority(
            task_id,
            actor="dispatcher-round3",
            priority=setter_priority,
        )
        first_operation_finished.set()
        return result

    def final_upload() -> dict:
        start.wait(timeout=5)
        result = state_repo.upload_construction_group_batch(
            group_id,
            actor=constructor,
            client_batch_id=f"round3-priority-batch-{order}",
            collector="C-ROUND3",
            module_asset_no="M-ROUND3",
            photos=[
                {
                    "url": f"https://example.test/{order}/before.jpg",
                    "sha256": "a" * 64,
                    "client_photo_id": "before",
                    "slot": "before_box",
                },
                {
                    "url": f"https://example.test/{order}/module.jpg",
                    "sha256": "b" * 64,
                    "client_photo_id": "module",
                    "slot": "module_meter",
                },
                {
                    "url": f"https://example.test/{order}/after.jpg",
                    "sha256": "c" * 64,
                    "client_photo_id": "after",
                    "slot": "after_box",
                },
                {
                    "url": f"https://example.test/{order}/collector.jpg",
                    "sha256": "d" * 64,
                    "client_photo_id": "collector",
                    "slot": "collector_barcode",
                },
            ],
        )
        first_operation_finished.set()
        upload_finished.set()
        return result

    with session_factory() as locking_session:
        locking_session.scalar(
            select(Task).where(Task.team_id == team_id, Task.legacy_id == task_id).with_for_update()
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            setter_future = executor.submit(set_priority)
            upload_future = executor.submit(final_upload)
            start.wait(timeout=5)
            if order == "setter_before_upload":
                locking_session.commit()
                assert first_operation_finished.wait(timeout=10)
                allow_second_task_lock.set()
            else:
                locking_session.commit()
                assert upload_finished.wait(timeout=10)
                allow_second_task_lock.set()
            setter_result = setter_future.result(timeout=15)
            upload_result = upload_future.result(timeout=15)

    with session_factory() as session:
        task = session.scalar(select(Task).where(Task.team_id == team_id, Task.legacy_id == task_id))
        auto_clear_count = session.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.team_id == team_id,
                AuditLog.action == "construction_priority_auto_cleared",
            )
        )

    assert task is not None
    assert task.construction_priority is False
    assert upload_result["task"]["construction_priority"] is False
    assert upload_result["task"]["construction_available"] is False
    assert auto_clear_count == 1
    if order == "setter_before_upload":
        assert setter_result["construction_priority"] is True
        assert setter_result["construction_available"] is True
    else:
        assert setter_result["construction_priority"] is False
        assert setter_result["construction_available"] is False
