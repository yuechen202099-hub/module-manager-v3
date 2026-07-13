from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app import main as main_module
from app.api.routes import auth, local_test
from app.core import security
from app.database import Base
from app.models import AuditLog, Project, Task, Team, UnmatchedRecord
from app.services import account_store, local_simulation
from app.services import state_repository as repository


INVALID_TERMINALS = ("00000000", "未关联终端", "manual-terminal", "unmatched-terminal")
TEAM_ID = "round4-postgres-team"


@pytest.fixture()
def isolated_round4_postgres(monkeypatch: pytest.MonkeyPatch):
    database_url = os.getenv("ROUND4_POSTGRES_TEST_URL", "").strip()
    if not database_url:
        pytest.skip("ROUND4_POSTGRES_TEST_URL is required for the real PostgreSQL validation tests")
    parsed = make_url(database_url)
    assert parsed.get_backend_name() == "postgresql"
    assert parsed.host in {"localhost", "127.0.0.1", "::1"}, "PostgreSQL validation tests must stay local"

    schema = f"round4_{uuid4().hex}"
    admin_engine = create_engine(database_url, pool_pre_ping=True)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    test_engine = create_engine(
        database_url,
        pool_pre_ping=True,
        execution_options={"schema_translate_map": {None: schema}},
        connect_args={
            "options": f"-csearch_path={schema},public -cstatement_timeout=10000 -clock_timeout=5000"
        },
    )
    try:
        Base.metadata.create_all(test_engine)
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


def seed_placeholder_assign_state(session_factory) -> dict[str, str]:
    unmatched_ids: dict[str, str] = {}
    with session_factory.begin() as session:
        session.add(Team(id=TEAM_ID, name="Round 4 PostgreSQL validation"))
        session.flush()
        project = Project(team_id=TEAM_ID, code=f"ROUND4-{uuid4().hex[:12]}", name="Round 4 project")
        session.add(project)
        session.flush()
        for index, terminal in enumerate(INVALID_TERMINALS, start=1):
            unmatched_id = f"round4-invalid-terminal-{index}"
            unmatched_ids[terminal] = unmatched_id
            session.add(
                Task(
                    team_id=TEAM_ID,
                    legacy_id=9400 + index,
                    terminal=terminal,
                    project_id=project.id,
                    title=f"Historical placeholder task {index}",
                    construction_enabled=False,
                    raw_data={"sentinel": terminal},
                )
            )
            session.add(
                UnmatchedRecord(
                    team_id=TEAM_ID,
                    legacy_id=unmatched_id,
                    record_type="scan",
                    status="open",
                    terminal=terminal,
                    meter_no=f"1200009124{index:02d}",
                    meter_match_key=f"09124{index:02d}",
                    barcode=f"1200009124{index:02d}",
                    collector="C001",
                    module_asset_no=f"M00{index}",
                    address=f"Round 4 road {index}",
                    payload={
                        "sentinel": terminal,
                        "temporary_review": {
                            "schema_version": 1,
                            "unmatched_id": unmatched_id,
                            "version": 1,
                            "state": "pending",
                            "photos": [],
                        },
                    },
                )
            )
    return unmatched_ids


def database_snapshot(session_factory) -> dict:
    with session_factory() as session:
        unmatched_rows = session.execute(
            select(UnmatchedRecord.__table__)
            .where(UnmatchedRecord.team_id == TEAM_ID)
            .order_by(UnmatchedRecord.legacy_id)
        ).mappings().all()
        task_rows = session.execute(
            select(Task.__table__).where(Task.team_id == TEAM_ID).order_by(Task.legacy_id)
        ).mappings().all()
        audit_rows = session.execute(
            select(AuditLog.__table__).where(AuditLog.team_id == TEAM_ID).order_by(AuditLog.created_at, AuditLog.id)
        ).mappings().all()
    return deepcopy(
        {
            "unmatched": [dict(row) for row in unmatched_rows],
            "tasks": [dict(row) for row in task_rows],
            "audit": [dict(row) for row in audit_rows],
        }
    )


def production_postgres_settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        app_env="production",
        allowed_origins=["https://www.sgcc.online", "https://sgcc.online"],
        trusted_hosts=["testserver", "127.0.0.1", "localhost"],
        trusted_proxy_hosts={"testclient"},
        security_frame_ancestors="'self'",
        state_backend="postgres",
        max_upload_mb=20,
        max_upload_files_per_request=8,
        photo_proxy_hosts=set(),
        demo_auth_enabled=False,
        admin_username="round4-admin",
        admin_password="Round4AdminPass123",
        admin_team_id=TEAM_ID,
        auth_users_path=str(tmp_path / "round4-users.json"),
        jwt_secret="round4-postgres-http-jwt-secret",
        jwt_expire_minutes=60,
    )


def patch_production_postgres_settings(monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace) -> None:
    for module in (auth, account_store, security, main_module, local_test, repository):
        monkeypatch.setattr(module, "settings", settings)


def issue_http_with_timeout(client: TestClient, path: str, headers: dict[str, str]) -> object:
    responses = []
    errors: list[BaseException] = []

    def issue_request() -> None:
        try:
            responses.append(
                client.patch(
                    path,
                    headers=headers,
                    json={
                        "actor": "forged-actor",
                        "expected_version": 1,
                        "constructor": "constructor-a",
                        "note": "must not mutate PostgreSQL",
                    },
                )
            )
        except BaseException as exc:  # pragma: no cover - assertion reports transport failures
            errors.append(exc)

    request_thread = Thread(target=issue_request, daemon=True)
    request_thread.start()
    request_thread.join(timeout=5)
    assert not request_thread.is_alive(), "PostgreSQL legacy assign HTTP request exceeded 5-second guard"
    assert errors == []
    assert len(responses) == 1
    return responses[0]


def test_postgres_repository_legacy_assign_rejects_placeholder_terminals_before_any_mutation(
    isolated_round4_postgres,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = isolated_round4_postgres
    unmatched_ids = seed_placeholder_assign_state(session_factory)
    monkeypatch.setattr(local_simulation, "current_team_id", lambda: TEAM_ID)
    state_repo = repository.PostgresStateRepository()

    for terminal in INVALID_TERMINALS:
        before = database_snapshot(session_factory)
        with pytest.raises(ValueError, match="real terminal"):
            state_repo.assign_unmatched_record(
                unmatched_ids[terminal],
                actor="round4-admin",
                constructor="constructor-a",
                expected_version=1,
                note="must not mutate PostgreSQL",
            )
        assert database_snapshot(session_factory) == before


def test_postgres_http_legacy_assign_rejects_placeholder_terminals_before_any_mutation(
    isolated_round4_postgres,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session_factory = isolated_round4_postgres
    unmatched_ids = seed_placeholder_assign_state(session_factory)
    settings = production_postgres_settings(tmp_path)
    patch_production_postgres_settings(monkeypatch, settings)

    with TestClient(main_module.create_app()) as client:
        login = client.post(
            "/auth/login",
            json={"username": settings.admin_username, "password": settings.admin_password},
        )
        assert login.status_code == 200
        headers = {"Authorization": f"bearer {login.json()['data']['access_token']}"}

        for terminal in INVALID_TERMINALS:
            before = database_snapshot(session_factory)
            response = issue_http_with_timeout(
                client,
                f"/local-test/unmatched/{unmatched_ids[terminal]}/assign",
                headers,
            )
            assert response.status_code == 400
            assert "real terminal" in response.text
            assert database_snapshot(session_factory) == before
