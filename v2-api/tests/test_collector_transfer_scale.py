from __future__ import annotations

import asyncio
import gc
import tracemalloc
from contextlib import contextmanager
from threading import Event
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes import collector_transfer as routes
from app.database import Base
from app.models import (
    CollectorPhoto,
    CollectorScanEvent,
    GroupBarcodeVerification,
    MaterialGroup,
    Photo,
    PhysicalCollector,
    Project,
    ProjectStatus,
    Team,
)
from app.services.collector_transfer import PostgresCollectorTransferService


PRODUCTION_GROUP_COUNT = 22_358
PRODUCTION_PHOTO_COUNT = 17_453


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(_type: JSONB, _compiler: object, **_kwargs: object) -> str:
    return "JSON"


@pytest.fixture(scope="module")
def production_scale_database(tmp_path_factory):
    database_path = tmp_path_factory.mktemp("collector-transfer-scale") / "scale.sqlite3"
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def register_uuid_function(connection, _connection_record) -> None:
        connection.create_function("gen_random_uuid", 0, lambda: uuid4().hex)

    Base.metadata.create_all(engine)
    project_id = uuid4()
    with engine.begin() as connection:
        connection.execute(Team.__table__.insert(), {"id": "team-1", "name": "规模测试团队"})
        connection.execute(
            Project.__table__.insert(),
            {
                "id": project_id,
                "team_id": "team-1",
                "code": "P-SCALE",
                "name": "规模测试项目",
                "status": ProjectStatus.ACTIVE,
                "settings": {},
            },
        )
        group_ids: list[UUID] = []
        for batch_start in range(0, PRODUCTION_GROUP_COUNT, 1_000):
            batch_end = min(batch_start + 1_000, PRODUCTION_GROUP_COUNT)
            rows = []
            for index in range(batch_start, batch_end):
                group_id = UUID(int=(0xA << 124) | index)
                group_ids.append(group_id)
                rows.append(
                    {
                        "id": group_id,
                        "team_id": "team-1",
                        "project_id": project_id,
                        "terminal": f"T-{index:05d}",
                        "meter_match_key": f"M-{index:05d}",
                        "display_meter_no": f"M-{index:05d}",
                        "installation_address": f"规模测试地址 {index}",
                        "raw_data": {"collector": f"RAW-{index:05d}"},
                    }
                )
            connection.execute(MaterialGroup.__table__.insert(), rows)
        for batch_start in range(0, PRODUCTION_PHOTO_COUNT, 1_000):
            batch_end = min(batch_start + 1_000, PRODUCTION_PHOTO_COUNT)
            connection.execute(
                Photo.__table__.insert(),
                [
                    {
                        "id": UUID(int=(0xB << 124) | index),
                        "team_id": "team-1",
                        "group_id": group_ids[index],
                        "sha256": f"{index:064x}",
                        "object_key": f"scale/{index:05d}.jpg",
                        "collector": f"PHOTO-{index:05d}",
                        "sort_order": 0,
                        "is_active": True,
                    }
                    for index in range(batch_start, batch_end)
                ],
            )

    session_factory = sessionmaker(engine, expire_on_commit=False)
    try:
        yield engine, session_factory, project_id
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _collector_lookup(
    service: PostgresCollectorTransferService,
    project_id: UUID,
    candidate: str,
) -> bool:
    return service._project_has_collector_number(project_id, candidate)


def test_project_collector_lookup_is_bounded_at_production_cardinality(
    production_scale_database,
) -> None:
    engine, session_factory, project_id = production_scale_database
    loaded_source_entities: list[object] = []
    recorded_selects: list[str] = []

    with session_factory() as session:
        def record_loaded(_session: Session, instance: object) -> None:
            if isinstance(instance, (GroupBarcodeVerification, MaterialGroup, Photo)):
                loaded_source_entities.append(instance)

        def record_sql(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
            if statement.lstrip().upper().startswith("SELECT"):
                recorded_selects.append(statement)

        event.listen(session, "loaded_as_persistent", record_loaded)
        event.listen(engine, "before_cursor_execute", record_sql)
        gc.collect()
        tracemalloc.start()
        baseline_current, _ = tracemalloc.get_traced_memory()
        try:
            result = _collector_lookup(
                PostgresCollectorTransferService(
                    session=session,
                    team_id="team-1",
                    actor="scale-test",
                ),
                project_id,
                "GUARANTEED-NONMATCH",
            )
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
            event.remove(engine, "before_cursor_execute", record_sql)
            event.remove(session, "loaded_as_persistent", record_loaded)

    assert result is False
    assert loaded_source_entities == []
    assert len(recorded_selects) <= 2
    assert not any(
        "GROUP_ID IN (" in statement.upper()
        for statement in recorded_selects
    )
    assert peak - baseline_current < 64 * 1024 * 1024


def test_project_meter_projection_streams_selected_columns_at_production_cardinality(
    production_scale_database,
) -> None:
    """Catches run projection hydrating source ORM rows, generating an ID IN-list, or exceeding its memory gate."""
    engine, session_factory, project_id = production_scale_database
    loaded_source_entities: list[object] = []
    recorded_selects: list[str] = []

    with session_factory() as session:
        def record_loaded(_session: Session, instance: object) -> None:
            if isinstance(instance, (MaterialGroup, Photo)):
                loaded_source_entities.append(instance)

        def record_sql(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
            if statement.lstrip().upper().startswith("SELECT"):
                recorded_selects.append(statement)

        event.listen(session, "loaded_as_persistent", record_loaded)
        event.listen(engine, "before_cursor_execute", record_sql)
        gc.collect()
        tracemalloc.start()
        baseline_current, _ = tracemalloc.get_traced_memory()
        try:
            projection, _photos = PostgresCollectorTransferService(
                session=session,
                team_id="team-1",
                actor="scale-test",
            )._project_meter_projection(project_id)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
            event.remove(engine, "before_cursor_execute", record_sql)
            event.remove(session, "loaded_as_persistent", record_loaded)

    source_selects = [
        statement
        for statement in recorded_selects
        if "FROM MATERIAL_GROUPS" in statement.upper() or "FROM PHOTOS" in statement.upper()
    ]
    assert len(projection.sources) == PRODUCTION_GROUP_COUNT
    assert len(_photos) == PRODUCTION_PHOTO_COUNT
    assert loaded_source_entities == []
    assert len(source_selects) <= 2
    assert not any("GROUP_ID IN (" in statement.upper() for statement in source_selects)
    assert peak - baseline_current < 256 * 1024 * 1024


def test_global_terminal_candidate_page_is_bounded_at_production_cardinality(
    production_scale_database,
) -> None:
    """Catches candidate paging hydrating source rows or building project-sized IN lists."""
    engine, session_factory, _project_id = production_scale_database
    loaded_source_entities: list[object] = []
    recorded_selects: list[str] = []

    with session_factory() as session:
        def record_loaded(_session: Session, instance: object) -> None:
            if isinstance(instance, (MaterialGroup, Photo)):
                loaded_source_entities.append(instance)

        def record_sql(_connection, _cursor, statement, _parameters, _context, _executemany) -> None:
            if statement.lstrip().upper().startswith("SELECT"):
                recorded_selects.append(statement)

        event.listen(session, "loaded_as_persistent", record_loaded)
        event.listen(engine, "before_cursor_execute", record_sql)
        try:
            result = PostgresCollectorTransferService(
                session=session,
                team_id="team-1",
                actor="scale-test",
            ).list_global_terminals(page=1, page_size=50, include_blocked=True)
        finally:
            event.remove(engine, "before_cursor_execute", record_sql)
            event.remove(session, "loaded_as_persistent", record_loaded)

    source_selects = [
        statement
        for statement in recorded_selects
        if "FROM MATERIAL_GROUPS" in statement.upper() or "FROM PHOTOS" in statement.upper()
    ]
    assert result["page_size"] == 50
    assert len(result["items"]) == 50
    assert result["total"] == PRODUCTION_GROUP_COUNT
    assert loaded_source_entities == []
    assert len(recorded_selects) <= 12
    assert len(source_selects) <= 6
    assert not any(statement.count("?") > 1_000 for statement in source_selects)


@pytest.mark.parametrize(
    ("collector_no", "expected_count_delta"),
    [
        ("GUARANTEED-NONMATCH", (0, 0, 0)),
        ("PHOTO-00000", (1, 0, 1)),
    ],
    ids=("non_direct", "direct_required"),
)
def test_cancelled_asgi_scan_quiesces_with_exact_bounded_outcome(
    production_scale_database,
    monkeypatch,
    collector_no: str,
    expected_count_delta: tuple[int, int, int],
) -> None:
    """Catches a cancelled sync worker repeating writes or retaining its database connection."""
    engine, session_factory, project_id = production_scale_database
    lookup_finished = Event()
    release_handler = Event()
    handler_finished = Event()
    original_lookup = PostgresCollectorTransferService._project_has_collector_number

    def observed_lookup(self, scoped_project_id: UUID, candidate: str) -> bool:
        result = original_lookup(self, scoped_project_id, candidate)
        lookup_finished.set()
        assert release_handler.wait(timeout=10)
        return result

    @contextmanager
    def real_service_for_request(_request):
        try:
            with session_factory() as session:
                try:
                    yield PostgresCollectorTransferService(
                        session=session,
                        team_id="team-1",
                        actor="cancelled-client",
                    )
                except BaseException:
                    session.rollback()
                    raise
        finally:
            handler_finished.set()

    monkeypatch.setattr(
        PostgresCollectorTransferService,
        "_project_has_collector_number",
        observed_lookup,
    )
    monkeypatch.setattr(routes, "service_for_request", real_service_for_request)
    monkeypatch.setattr(routes, "ok", lambda _request, result: result)
    app = FastAPI()
    app.include_router(routes.router)

    with session_factory() as session:
        before_counts = (
            session.scalar(select(func.count(PhysicalCollector.id))),
            session.scalar(select(func.count(CollectorPhoto.id))),
            session.scalar(select(func.count(CollectorScanEvent.id))),
        )

    async def cancel_in_flight_request() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            request_task = asyncio.create_task(
                client.post(
                    "/collector-transfer/inventory/scan",
                    json={
                        "project_id": str(project_id),
                        "collector_no": collector_no,
                    },
                )
            )
            assert await asyncio.to_thread(lookup_finished.wait, 10)
            assert request_task.cancel() is True
            assert request_task.cancelling() == 1
            release_handler.set()
            with pytest.raises(asyncio.CancelledError):
                await request_task
            assert await asyncio.to_thread(handler_finished.wait, 10)

    try:
        asyncio.run(cancel_in_flight_request())
    finally:
        release_handler.set()

    assert engine.pool.checkedout() == 0
    with session_factory() as session:
        after_counts = (
            session.scalar(select(func.count(PhysicalCollector.id))),
            session.scalar(select(func.count(CollectorPhoto.id))),
            session.scalar(select(func.count(CollectorScanEvent.id))),
        )
        assert session.scalar(select(func.count(Project.id))) == 1
    expected_counts = tuple(
        before + delta
        for before, delta in zip(before_counts, expected_count_delta, strict=True)
    )
    assert after_counts == expected_counts
    assert engine.pool.checkedout() == 0
    with session_factory() as session:
        followup_counts = (
            session.scalar(select(func.count(PhysicalCollector.id))),
            session.scalar(select(func.count(CollectorPhoto.id))),
            session.scalar(select(func.count(CollectorScanEvent.id))),
        )
        assert session.scalar(select(func.count(Project.id))) == 1
    assert followup_counts == after_counts
    assert engine.pool.checkedout() == 0
