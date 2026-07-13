from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import MaterialGroup, Project, Task, Team, TotalCatalogRow, UnmatchedRecord
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
