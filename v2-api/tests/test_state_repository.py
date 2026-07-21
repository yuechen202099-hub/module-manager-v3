from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
import hashlib
import logging
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.services import state_repository as repository
from app.services.construction_priority_import import PriorityImportRow


def test_json_repository_sets_construction_priority_through_simulation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    monkeypatch.setattr(
        repository.local_simulation,
        "set_construction_task_priority",
        lambda task_id, *, actor, priority: calls.append((task_id, actor, priority)) or {"id": task_id},
        raising=False,
    )

    result = repository.JsonStateRepository().set_construction_task_priority(
        7,
        actor="admin-a",
        priority=True,
    )

    assert result == {"id": 7}
    assert calls == [(7, "admin-a", True)]


def test_json_task_reads_mask_stale_priority_without_mutating_persisted_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = {
        "id": 7,
        "terminal": "T-007",
        "construction_priority": True,
    }
    state = {"tasks": [task], "groups": [], "summary": {}}

    monkeypatch.setattr(repository.local_simulation, "get_state", lambda: state)

    listed = repository.local_simulation.list_tasks()
    repository.local_simulation.task_status_summary()

    assert listed[0] is not task
    assert listed[0]["construction_priority"] is False
    assert task["construction_priority"] is True


def test_json_priority_import_preview_uses_non_mutating_task_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dirty_completed_task = {
        "id": 7,
        "terminal": "T-007",
        "construction_priority": True,
        "total_groups": 1,
        "uploaded_count": 1,
        "construction_available": False,
    }
    state = {"tasks": [dirty_completed_task], "groups": [], "audit_log": []}

    monkeypatch.setattr(repository.local_simulation, "get_state", lambda: state)
    monkeypatch.setattr(
        repository.local_simulation,
        "calculate_task_metrics",
        lambda _groups: {"renovation_count": 1, "uploaded_count": 1},
    )
    monkeypatch.setattr(
        repository.local_simulation,
        "list_tasks",
        lambda: pytest.fail("priority import preview must not refresh live tasks"),
    )

    result = repository.JsonStateRepository().import_construction_priorities(
        [PriorityImportRow(2, "T-007", True, "valid")],
        actor="admin-a",
        confirm=False,
    )

    assert result["counts"]["completed"] == 1
    assert dirty_completed_task["construction_priority"] is True
    assert state["audit_log"] == []


def test_postgres_priority_import_availability_stats_are_set_scoped() -> None:
    class Result:
        def all(self):
            return []

    class CapturingSession:
        def __init__(self) -> None:
            self.statements = []

        def execute(self, statement):
            self.statements.append(statement)
            return Result()

    session = CapturingSession()
    repository.PostgresStateRepository()._construction_priority_stats_map(
        session,
        "priority-team",
        [7, 8, 9],
    )

    assert len(session.statements) == 1
    sql = str(
        session.statements[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    assert "material_groups.team_id = 'priority-team'" in sql
    assert "material_groups.legacy_task_id in (7, 8, 9)" in sql
    assert "string_agg" not in sql
    assert "installer" not in sql


def test_json_priority_import_confirmation_aborts_all_priorities_and_audits_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id = f"priority-import-atomic-{uuid4()}"
    team_token = repository.local_simulation.set_current_team(team_id)
    try:
        state = repository.local_simulation.get_state()
        state["tasks"] = [
            {"id": 7, "terminal": "T-007", "construction_priority": False},
            {"id": 8, "terminal": "T-008", "construction_priority": False},
        ]
        state["groups"] = []
        state["audit_log"] = []
        monkeypatch.setattr(
            repository.local_simulation,
            "calculate_task_metrics",
            lambda _groups: {"renovation_count": 1, "uploaded_count": 0},
        )

        def set_priority(task_id: int, *, actor: str, priority: bool):
            current = repository.local_simulation.get_state()
            if task_id == 8:
                raise ValueError("second row rejected")
            task = next(task for task in current["tasks"] if task["id"] == task_id)
            task["construction_priority"] = priority
            current["audit_log"].append({"action": "construction_priority_updated", "actor": actor})
            return task

        monkeypatch.setattr(repository.local_simulation, "set_construction_task_priority", set_priority)

        with pytest.raises(ValueError, match="second row rejected"):
            repository.JsonStateRepository().import_construction_priorities(
                [
                    PriorityImportRow(2, "T-007", True, "valid"),
                    PriorityImportRow(3, "T-008", True, "valid"),
                ],
                actor="admin-a",
                confirm=True,
            )

        assert [task["construction_priority"] for task in state["tasks"]] == [False, False]
        assert state["audit_log"] == []
    finally:
        repository.local_simulation.reset_current_team(team_token)


def test_dual_priority_import_confirmation_rejects_before_json_or_mirror_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        repository.JsonStateRepository,
        "import_construction_priorities",
        lambda *_args, **_kwargs: pytest.fail("dual confirmation must not mutate JSON first"),
    )

    with pytest.raises(ValueError, match="unavailable in dual backend mode"):
        repository.DualWriteStateRepository().import_construction_priorities(
            [PriorityImportRow(2, "T-007", True, "valid")],
            actor="admin-a",
            confirm=True,
        )


def test_postgres_priority_import_skips_zero_group_true_without_aborting_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = SimpleNamespace(
        id="task-7",
        legacy_id=7,
        team_id="priority-team",
        terminal="T-007",
        construction_priority=False,
    )

    class ScalarResult:
        def all(self):
            return [task]

    class FakeSession:
        def __init__(self) -> None:
            self.staged = []
            self.commits = 0
            self.scalar_calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalars(self, statement):
            self.scalar_calls.append(statement)
            return ScalarResult()

        def add(self, value):
            self.staged.append(value)

        def commit(self):
            self.commits += 1

    session = FakeSession()

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

        def _construction_priority_stats_map(self, _session, _team_id, _task_ids):
            return {7: {"total_groups": 0, "uploaded_count": 0, "reviewed_count": 0, "unreviewed_count": 0}}

    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: "priority-team")

    result = TestPostgresRepository().import_construction_priorities(
        [PriorityImportRow(2, "T-007", True, "valid")],
        actor="admin-a",
        confirm=True,
    )

    assert result["confirmed"] is True
    assert result["counts"]["completed"] == 1
    assert result["counts"]["valid"] == 0
    assert task.construction_priority is False
    assert session.commits == 1
    assert [event.action for event in session.staged] == ["construction_priority_imported"]


def test_priority_import_preserves_parser_reason_for_json_and_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = PriorityImportRow(2, "", None, "malformed", "Terminal is required")
    state = {"tasks": [], "groups": [], "audit_log": []}
    monkeypatch.setattr(repository.local_simulation, "get_state", lambda: state)

    json_result = repository.JsonStateRepository().import_construction_priorities(
        [row],
        actor="admin-a",
        confirm=False,
    )
    postgres_items = repository.PostgresStateRepository._classify_construction_priority_import_rows(
        [row],
        {},
        {},
    )

    assert json_result["items"][0]["reason"] == "Terminal is required"
    assert postgres_items[0]["reason"] == "Terminal is required"


def test_postgres_priority_import_exposes_task_change_values_in_public_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = SimpleNamespace(
        id="task-7",
        legacy_id=7,
        team_id="priority-team",
        terminal="T-007",
        construction_priority=False,
        construction_priority_updated_by="",
        construction_priority_updated_at=None,
    )

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class FakeSession:
        def __init__(self) -> None:
            self.staged = []
            self.audit_mode = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, _statement):
            return len(self.staged)

        def scalars(self, _statement):
            if self.audit_mode:
                return Result(list(reversed(self.staged)))
            return Result([task])

        def add(self, value):
            self.staged.append(value)

        def commit(self):
            return None

    session = FakeSession()

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

        def _construction_priority_stats_map(self, _session, _team_id, _task_ids):
            return {7: {"total_groups": 1, "uploaded_count": 0, "reviewed_count": 0, "unreviewed_count": 0}}

    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: "priority-team")
    repo = TestPostgresRepository()
    repo.import_construction_priorities(
        [PriorityImportRow(2, "T-007", True, "valid")],
        actor="admin-a",
        confirm=True,
    )
    session.audit_mode = True
    audit = next(item for item in repo.list_audit_events()["items"] if item["action"] == "construction_priority_updated")

    assert audit["payload"] == {
        "task_id": 7,
        "terminal": "T-007",
        "before": False,
        "after": True,
    }


def test_postgres_priority_import_locks_initially_completed_and_unchanged_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unchanged = SimpleNamespace(id="task-7", legacy_id=7, team_id="priority-team", terminal="T-007", construction_priority=False)
    completed = SimpleNamespace(id="task-8", legacy_id=8, team_id="priority-team", terminal="T-008", construction_priority=False)

    class ScalarResult:
        def all(self):
            return [unchanged, completed]

    class FakeSession:
        def __init__(self) -> None:
            self.statements = []
            self.staged = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalars(self, statement):
            self.statements.append(statement)
            return ScalarResult()

        def add(self, value):
            self.staged.append(value)

        def commit(self):
            return None

    session = FakeSession()

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

        def _construction_priority_stats_map(self, _session, _team_id, _task_ids):
            return {
                7: {"total_groups": 1, "uploaded_count": 0, "reviewed_count": 0, "unreviewed_count": 0},
                8: {"total_groups": 1, "uploaded_count": 1, "reviewed_count": 0, "unreviewed_count": 1},
            }

    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: "priority-team")
    result = TestPostgresRepository().import_construction_priorities(
        [
            PriorityImportRow(2, "T-007", False, "valid"),
            PriorityImportRow(3, "T-008", False, "valid"),
        ],
        actor="admin-a",
        confirm=True,
    )

    assert len(session.statements) == 1
    locked_sql = str(session.statements[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert result["counts"] == {"valid": 0, "duplicate": 0, "conflict": 0, "unknown": 0, "completed": 1, "unchanged": 1, "malformed": 0}
    assert "FOR UPDATE" in locked_sql
    assert "tasks.terminal IN ('T-007', 'T-008')" in locked_sql


def test_postgres_priority_update_locks_task_and_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    task = SimpleNamespace(
        id="task-uuid",
        legacy_id=7,
        team_id="priority-team",
        terminal="T-PRIORITY",
        construction_priority=False,
        construction_priority_updated_by="",
        construction_priority_updated_at=None,
    )

    class FakeSession:
        def __init__(self) -> None:
            self.staged = []
            self.commits = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def add(self, value) -> None:
            self.staged.append(value)

        def commit(self) -> None:
            self.commits += 1

        def refresh(self, _value) -> None:
            return None

    session = FakeSession()

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

        def _task_by_legacy_id(self, checked_session, task_id: int, *, lock: bool = False):
            assert checked_session is session
            assert task_id == 7
            assert lock is True
            return task

        def _task_stats(self, checked_session, checked_task):
            assert checked_session is session
            assert checked_task is task
            return {"total_groups": 2, "uploaded_count": 1, "reviewed_count": 0, "unreviewed_count": 1}

        def _task_payload_stats(self, checked_session, checked_task):
            return self._task_stats(checked_session, checked_task)

    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: "priority-team")
    monkeypatch.setattr(repository, "_construction_task_payload", lambda checked_task, stats: {"priority": checked_task.construction_priority, **stats})
    repo = TestPostgresRepository()

    first = repo.set_construction_task_priority(7, actor="admin-a", priority=True)
    repeated = repo.set_construction_task_priority(7, actor="admin-b", priority=True)
    cleared = repo.set_construction_task_priority(7, actor="admin-c", priority=False)
    cleared_again = repo.set_construction_task_priority(7, actor="admin-d", priority=False)

    assert first["priority"] is True
    assert repeated["priority"] is True
    assert cleared["priority"] is False
    assert cleared_again["priority"] is False
    assert session.commits == 4
    assert [event.action for event in session.staged].count("construction_priority_updated") == 2
    assert task.construction_priority_updated_by == "admin-c"


def test_postgres_task_stats_query_is_scoped_to_target_task() -> None:
    task = SimpleNamespace(legacy_id=7, team_id="priority-team")

    class Result:
        def one(self):
            return SimpleNamespace(total_groups=2, uploaded_count=1, reviewed_count=0, unreviewed_count=1)

    class CapturingSession:
        def __init__(self) -> None:
            self.statements = []

        def execute(self, statement):
            self.statements.append(statement)
            return Result()

    session = CapturingSession()
    stats = repository.PostgresStateRepository()._task_stats(session, task)
    sql = str(session.statements[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert stats == {"total_groups": 2, "uploaded_count": 1, "reviewed_count": 0, "unreviewed_count": 1}
    assert len(session.statements) == 1
    assert "material_groups.legacy_task_id = 7" in sql
    assert "string_agg" not in sql.lower()
    assert "photos.is_active IS true" in sql


def test_postgres_priority_rejects_completed_and_zero_group_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    task = SimpleNamespace(
        id="task-uuid",
        legacy_id=8,
        team_id="priority-team",
        terminal="T-PRIORITY",
        construction_priority=False,
        construction_priority_updated_by="",
        construction_priority_updated_at=None,
    )

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def add(self, _value) -> None:
            pytest.fail("invalid priority update must not audit")

        def commit(self) -> None:
            pytest.fail("invalid priority update must not commit")

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return FakeSession()

        def _task_by_legacy_id(self, _session, task_id: int, *, lock: bool = False):
            assert task_id == 8
            assert lock is True
            return task

        def _task_stats(self, _session, _task):
            return self.stats

    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: "priority-team")
    repo = TestPostgresRepository()
    for stats in (
        {"total_groups": 2, "uploaded_count": 2, "reviewed_count": 0, "unreviewed_count": 2},
        {"total_groups": 0, "uploaded_count": 0, "reviewed_count": 0, "unreviewed_count": 0},
    ):
        repo.stats = stats
        with pytest.raises(ValueError, match="available"):
            repo.set_construction_task_priority(8, actor="admin-a", priority=True)


def test_postgres_final_upload_auto_clears_priority_with_audit_and_rolls_back_on_commit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = SimpleNamespace(
        id="task-uuid",
        legacy_id=9,
        team_id="priority-team",
        terminal="T-UPLOAD",
        construction_claimed_by="constructor-a",
        construction_priority=True,
        construction_priority_updated_by="admin-a",
        construction_priority_updated_at=None,
    )
    group = SimpleNamespace(
        id="group-uuid",
        legacy_id="g-priority",
        legacy_task_id=9,
        task_id=task.id,
        team_id="priority-team",
        display_meter_no="M-PRIORITY",
        meter_match_key="M-PRIORITY",
        installation_address="Priority road",
        photo_count=0,
        photos=[],
        raw_data={},
    )

    class FakeSession:
        def __init__(self, *, fail_commit: bool) -> None:
            self.fail_commit = fail_commit
            self.staged = []
            self.priority_before = task.construction_priority
            self.raw_before = deepcopy(group.raw_data)
            self.photo_count_before = group.photo_count
            self.photos_before = deepcopy(group.photos)
            self.rollbacks = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            if exc_type is not None:
                self.rollback()
            return False

        def scalar(self, _statement):
            return task

        def add(self, value) -> None:
            self.staged.append(value)

        def flush(self) -> None:
            return None

        def commit(self) -> None:
            if self.fail_commit:
                raise RuntimeError("injected upload commit failure")

        def rollback(self) -> None:
            self.rollbacks += 1
            task.construction_priority = self.priority_before
            group.raw_data = deepcopy(self.raw_before)
            group.photo_count = self.photo_count_before
            group.photos = deepcopy(self.photos_before)
            self.staged.clear()

        def refresh(self, _value) -> None:
            return None

    class TestPostgresRepository(repository.PostgresStateRepository):
        def __init__(self, session) -> None:
            super().__init__()
            self.session = session
            self.stats = {"total_groups": 2, "uploaded_count": 1, "reviewed_count": 0, "unreviewed_count": 1}

        def _session(self):
            return self.session

        def _group_by_legacy_id(self, checked_session, group_id: str, *, lock: bool = False):
            assert checked_session is self.session
            assert group_id == "g-priority"
            assert lock is True
            return group

        def _add_photo_records_to_group(self, checked_session, checked_group, **_kwargs):
            assert checked_session is self.session
            assert checked_group is group
            group.photo_count += len(_kwargs["photos"])
            group.photos.extend(deepcopy(_kwargs["photos"]))
            self.stats["uploaded_count"] = 2
            return {"added": 4, "skipped_duplicates": 0}

        def _task_stats(self, checked_session, checked_task):
            assert checked_session is self.session
            assert checked_task is task
            return dict(self.stats)

        def _task_payload_stats(self, checked_session, checked_task):
            return self._task_stats(checked_session, checked_task)

    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: "priority-team")
    monkeypatch.setattr(repository.local_simulation, "assert_not_placeholder_construction_group", lambda **_kwargs: None)
    monkeypatch.setattr(repository, "_group_payload", lambda _session, checked_group: {"id": checked_group.legacy_id})
    monkeypatch.setattr(
        repository,
        "_construction_task_payload",
        lambda checked_task, stats: {
            "construction_priority": checked_task.construction_priority,
            "construction_available": repository.construction_task_availability(stats)[0],
            **stats,
        },
    )

    successful_session = FakeSession(fail_commit=False)
    result = TestPostgresRepository(successful_session).upload_construction_group_batch(
        "g-priority",
        actor="constructor-a",
        client_batch_id="priority-final-upload",
        collector="collector-a",
        module_asset_no="module-a",
        photos=[{"url": "https://example.test/photo.jpg"}],
    )

    assert task.construction_priority is False
    assert result["task"]["construction_available"] is False
    assert result["task"]["construction_priority"] is False
    assert "construction_priority_auto_cleared" in [event.action for event in successful_session.staged]

    task.construction_priority = True
    group.photo_count = 0
    group.photos = []
    failing_session = FakeSession(fail_commit=True)
    with pytest.raises(RuntimeError, match="injected upload commit failure"):
        TestPostgresRepository(failing_session).upload_construction_group_batch(
            "g-priority",
            actor="constructor-a",
            client_batch_id="priority-final-upload-failure",
            collector="collector-a",
            module_asset_no="module-a",
            photos=[{"url": "https://example.test/photo.jpg"}],
        )

    assert failing_session.rollbacks == 1
    assert task.construction_priority is True
    assert group.photo_count == 0
    assert group.photos == []
    assert failing_session.staged == []


@pytest.mark.parametrize(
    ("stats", "expected"),
    [
        ({"total_groups": 4, "uploaded_count": 0, "unreviewed_count": 4}, (True, False)),
        ({"total_groups": 4, "uploaded_count": 2, "unreviewed_count": 2}, (True, True)),
        ({"total_groups": 4, "uploaded_count": 4, "unreviewed_count": 2}, (False, True)),
        ({"total_groups": 4, "uploaded_count": 2, "unreviewed_count": 0}, (True, False)),
        ({"total_groups": 0, "uploaded_count": 0, "unreviewed_count": 0}, (False, False)),
    ],
)
def test_construction_task_availability_matrix(stats, expected) -> None:
    assert repository.construction_task_availability(stats) == expected


def test_construction_priority_payload_is_defensive_and_shared_by_both_lists() -> None:
    task = SimpleNamespace(
        id="task-1",
        legacy_id=1,
        terminal="T-001",
        title="Terminal T-001",
        status="open",
        review_claimed_by=None,
        claimed_at=None,
        released_at=None,
        construction_enabled=False,
        construction_claimed_by=None,
        construction_claimed_at=None,
        construction_released_at=None,
        construction_opened_by=None,
        construction_opened_at=None,
        construction_closed_at=None,
        construction_priority=True,
        construction_priority_updated_by="dispatcher-a",
        construction_priority_updated_at=datetime(2026, 7, 21, 9, 30),
        raw_data={},
    )
    complete_stats = {
        "total_groups": 4,
        "uploaded_count": 4,
        "reviewed_count": 2,
        "unreviewed_count": 2,
    }
    partial_stats = {
        "total_groups": 4,
        "uploaded_count": 2,
        "reviewed_count": 0,
        "unreviewed_count": 2,
    }

    complete_payload = repository._task_payload(task, complete_stats)
    complete_construction_payload = repository._construction_task_payload(task, complete_stats)
    partial_payload = repository._task_payload(task, partial_stats)
    partial_construction_payload = repository._construction_task_payload(task, partial_stats)

    assert complete_payload["construction_priority"] is False
    assert complete_payload["construction_available"] is False
    assert complete_payload["review_available"] is True
    assert complete_construction_payload["construction_priority"] is False
    assert complete_construction_payload["construction_available"] is False
    assert complete_construction_payload["review_available"] is True
    assert partial_payload["construction_priority"] is True
    assert partial_payload["construction_available"] is True
    assert partial_payload["review_available"] is True
    assert {
        key: partial_payload[key]
        for key in ("construction_priority", "construction_available", "review_available")
    } == {
        key: partial_construction_payload[key]
        for key in ("construction_priority", "construction_available", "review_available")
    }
    assert partial_payload["construction_priority_updated_by"] == "dispatcher-a"
    assert partial_payload["construction_priority_updated_at"] == "2026-07-21T09:30:00"


def test_postgres_task_status_version_changes_for_effective_construction_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = SimpleNamespace(
        id="task-1",
        legacy_id=1,
        terminal="T-001",
        review_claimed_by=None,
        construction_claimed_by=None,
        construction_priority=False,
    )
    group_stats = SimpleNamespace(
        legacy_task_id=1,
        total_groups=4,
        address="",
        address_search_text="",
        meter_search_text="",
        uploaded_count=2,
        reviewed_count=0,
        unreviewed_count=2,
    )

    class Result:
        def __init__(self, rows) -> None:
            self.rows = rows

        def all(self):
            return self.rows

    class Session:
        def __init__(self) -> None:
            self.execute_calls = 0

        def execute(self, statement):
            self.execute_calls += 1
            return Result([task] if self.execute_calls % 2 else [group_stats])

        def scalar(self, statement):
            return 4

    postgres = repository.PostgresStateRepository()
    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: "default-team")
    monkeypatch.setattr(postgres, "_session", lambda: nullcontext(Session()))

    version_without_priority = postgres.task_status()["version"]
    task.construction_priority = True
    version_with_priority = postgres.task_status()["version"]

    assert version_with_priority != version_without_priority


def test_postgres_task_stats_count_only_uploaded_unreviewed_groups() -> None:
    class Result:
        def all(self):
            return []

    class CapturingSession:
        def __init__(self) -> None:
            self.statements = []

        def execute(self, statement):
            self.statements.append(statement)
            return Result()

    session = CapturingSession()
    repository.PostgresStateRepository()._task_stats_map(
        session,
        "default-team",
        include_search_text=False,
    )

    sql = str(
        session.statements[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).replace("\n", " ")

    assert (
        "material_groups.status = 'unreviewed' AND "
        "(material_groups.photo_count > 0 OR (EXISTS"
    ) in sql


def test_postgres_active_photo_statistics_match_payload_and_status_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = SimpleNamespace(
        id="task-1",
        legacy_id=1,
        terminal="T-001",
        title="Terminal T-001",
        status=repository.TaskStatus.PUBLISHED,
        review_claimed_by=None,
        claimed_at=None,
        released_at=None,
        construction_enabled=False,
        construction_claimed_by=None,
        construction_claimed_at=None,
        construction_priority=True,
    )
    active_photo_stats = {
        "total_groups": 1,
        "uploaded_count": 1,
        "reviewed_count": 0,
        "unreviewed_count": 1,
    }
    stale_photo_count_stats = SimpleNamespace(
        legacy_task_id=1,
        total_groups=1,
        uploaded_count=0,
        reviewed_count=0,
        unreviewed_count=0,
    )

    class Result:
        def __init__(self, rows) -> None:
            self.rows = rows

        def all(self):
            return self.rows

    class Session:
        def __init__(self) -> None:
            self.execute_calls = 0

        def execute(self, statement):
            self.execute_calls += 1
            return Result([task] if self.execute_calls == 1 else [stale_photo_count_stats])

        def scalar(self, statement):
            return 1

    class ActivePhotoRepository(repository.PostgresStateRepository):
        def _task_stats_map(
            self,
            session,
            team_id: str,
            *,
            include_search_text: bool = True,
            include_installer_distribution: bool = True,
        ):
            return {1: active_photo_stats}

    postgres = ActivePhotoRepository()
    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: "default-team")
    monkeypatch.setattr(postgres, "_session", lambda: nullcontext(Session()))

    payload = repository._task_payload(task, active_photo_stats)
    status = postgres.task_status()
    expected_status = repository._build_task_status_summary(
        [
            {
                "id": 1,
                "terminal": "T-001",
                "claimed_by": "",
                "construction_assigned_to": "",
                "construction_priority": False,
                **active_photo_stats,
            }
        ],
        {
            "total_catalog_rows": 1,
            "groups": 1,
            "photo_rows_linked": 1,
            "approved_groups": 0,
            "reviewed_groups": 0,
            "unreviewed_groups": 1,
        },
    )

    assert payload["construction_priority"] is False
    assert payload["construction_available"] is False
    assert payload["review_available"] is True
    assert status["version"] == expected_status["version"]


def test_json_state_repository_delegates_core_task_operations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repository.settings, "state_backend", "json")
    monkeypatch.setattr(repository.local_simulation, "get_state", lambda: {"summary": {"groups": 2}, "paths": {}})
    monkeypatch.setattr(
        repository.local_simulation,
        "list_tasks",
        lambda **_kwargs: [{"id": 7, "terminal": "T-007"}],
    )
    monkeypatch.setattr(
        repository.local_simulation,
        "list_unmatched_records",
        lambda query="", limit=100, offset=0, assigned_to="": {
            "total": 1,
            "items": [{"unmatched_id": "u-1"}],
        },
    )
    monkeypatch.setattr(
        repository.local_simulation,
        "list_replacement_records",
        lambda query="", limit=100, offset=0: {"total": 1, "items": [{"group_id": "g-1"}]},
    )
    monkeypatch.setattr(
        repository.local_simulation,
        "list_exception_groups",
        lambda reviewer="", limit=100, offset=0: {"total": 1, "items": [{"id": "g-1"}]},
    )
    monkeypatch.setattr(
        repository.local_simulation,
        "update_group_metadata",
        lambda group_id, actor, updates, audit_action="update_group_metadata": {
            "group": {"id": group_id, "actor": actor, "updates": updates}
        },
    )
    monkeypatch.setattr(
        repository.local_simulation,
        "claim_task",
        lambda task_id, reviewer: {"id": task_id, "claimed_by": reviewer},
    )

    repo = repository.get_state_repository()

    assert repo.list_tasks() == [{"id": 7, "terminal": "T-007"}]
    assert repo.summary() == {"summary": {"groups": 2}, "paths": {}}
    assert repo.list_unmatched_records(query="x") == {"total": 1, "items": [{"unmatched_id": "u-1"}]}
    assert repo.list_replacement_records(query="new") == {"total": 1, "items": [{"group_id": "g-1"}]}
    assert repo.list_exception_groups(reviewer="reviewer-a") == {"total": 1, "items": [{"id": "g-1"}]}
    assert repo.update_group_metadata("g-1", actor="reviewer-a", updates={"collector": "c"}) == {
        "group": {"id": "g-1", "actor": "reviewer-a", "updates": {"collector": "c"}}
    }
    assert repo.claim_task(7, "reviewer-a") == {"id": 7, "claimed_by": "reviewer-a"}


def test_json_unmatched_export_returns_one_copied_filtered_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    source = {
        "total": 2,
        "items": [
            {"unmatched_id": "u-export-1", "raw": {"source": "a"}},
            {"unmatched_id": "u-export-2", "raw": {"source": "b"}},
        ],
        "stats": {"pending": 2, "assigned": 0, "outside": 0},
    }
    calls: list[dict] = []

    def list_snapshot(query="", limit=100, offset=0, assigned_to=""):
        calls.append({"query": query, "limit": limit, "offset": offset, "assigned_to": assigned_to})
        return source

    monkeypatch.setattr(repository.local_simulation, "list_unmatched_records", list_snapshot)

    result = repository.JsonStateRepository().export_unmatched_records(query="meter-a", limit=500)
    result["items"][0]["raw"]["source"] = "changed"

    assert calls == [{"query": "meter-a", "limit": 500, "offset": 0, "assigned_to": ""}]
    assert result["total"] == 2
    assert source["items"][0]["raw"]["source"] == "a"


def test_postgres_unmatched_payload_counts_image_urls() -> None:
    record = SimpleNamespace(
        legacy_id="u-image",
        record_type="scan",
        status="open",
        terminal="T-IMG",
        meter_no="M-IMG",
        meter_match_key="M-IMG",
        barcode="M-IMG",
        collector="collector",
        module_asset_no="module",
        address="image road",
        payload={"image_urls": ["https://example.test/a.jpg", "https://example.test/b.jpg"]},
    )

    payload = repository._unmatched_payload(record)

    assert payload["photo_urls"] == ["https://example.test/a.jpg", "https://example.test/b.jpg"]
    assert payload["photo_count"] == 2


def test_unmatched_duplicate_key_blocks_reimport_after_association() -> None:
    existing = SimpleNamespace(
        legacy_id="scan-unmatched-old",
        record_type="scan",
        status="associated",
        terminal="T-REPLACE",
        meter_no="NEW-REPLACE-001",
        meter_match_key="NEW-REPLACE-001",
        barcode="NEW-REPLACE-001",
        collector="collector",
        module_asset_no="module",
        address="replacement road",
        payload={
            "meter_no": "NEW-REPLACE-001",
            "barcode": "NEW-REPLACE-001",
            "meter_match_key": "NEW-REPLACE-001",
            "terminal": "T-REPLACE",
            "image_urls": ["https://example.test/replacement.jpg"],
            "replacement_old_meter_no": "OLD-REPLACE-001",
        },
    )

    incoming = {
        "meter_no": "NEW-REPLACE-001",
        "barcode": "NEW-REPLACE-001",
        "meter_match_key": "NEW-REPLACE-001",
        "terminal": "T-REPLACE",
        "image_urls": ["https://example.test/replacement.jpg"],
    }

    assert repository._unmatched_duplicate_keys([existing]) == {
        repository.local_simulation.make_unmatched_duplicate_key(incoming)
    }


def test_postgres_construction_photo_without_client_completion_is_not_confirmed_non_idle() -> None:
    photo = SimpleNamespace(
        raw_data={"upload_source": "construction-mobile", "client_completed_at": ""},
        source="",
        taken_at=None,
        created_at=datetime(2026, 6, 22, 10, 30),
    )

    assert repository._photo_work_datetime(photo) == datetime(2026, 6, 22, 10, 30)
    assert repository._photo_confirmed_non_idle_datetime(photo) is None

    photo.raw_data["client_completed_at"] = "2026-06-22T09:30:00"

    assert repository._photo_confirmed_non_idle_datetime(photo) == datetime(2026, 6, 22, 9, 30)


def test_dual_backend_keeps_json_as_authoritative_source(monkeypatch: pytest.MonkeyPatch) -> None:
    class MirrorRepository:
        def release_task(self, *args, **kwargs):
            return {"mirror": True}

    monkeypatch.setattr(repository.settings, "state_backend", "dual")
    monkeypatch.setattr(repository.DualWriteStateRepository, "postgres_repository_factory", MirrorRepository)
    monkeypatch.setattr(repository.local_simulation, "release_task", lambda task_id, reviewer, force=False: {"id": task_id, "force": force})

    repo = repository.get_state_repository()

    assert isinstance(repo, repository.DualWriteStateRepository)
    assert repo.release_task(3, "admin", force=True) == {"id": 3, "force": True}


def test_dual_backend_mirrors_core_writes_after_json_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, tuple, dict]] = []

    class MirrorRepository:
        def classify_photo(self, *args, **kwargs):
            calls.append(("classify_photo", args, kwargs))

        def update_group_metadata(self, *args, **kwargs):
            calls.append(("update_group_metadata", args, kwargs))

        def reset_group_to_unconstructed(self, *args, **kwargs):
            calls.append(("reset_group_to_unconstructed", args, kwargs))

        def record_construction_activity_event(self, *args, **kwargs):
            calls.append(("record_construction_activity_event", args, kwargs))

        def upload_construction_group_batch(self, *args, **kwargs):
            calls.append(("upload_construction_group_batch", args, kwargs))

    monkeypatch.setattr(repository.settings, "state_backend", "dual")
    monkeypatch.setattr(repository.DualWriteStateRepository, "postgres_repository_factory", MirrorRepository)
    monkeypatch.setattr(
        repository.local_simulation,
        "classify_photo",
        lambda group_id, photo_id, category, reviewer: {
            "group_id": group_id,
            "photo_id": photo_id,
            "category": category,
            "reviewer": reviewer,
        },
    )
    monkeypatch.setattr(
        repository.local_simulation,
        "update_group_metadata",
        lambda group_id, actor, updates, audit_action="update_group_metadata": {
            "group_id": group_id,
            "actor": actor,
            "updates": updates,
            "audit_action": audit_action,
        },
    )
    monkeypatch.setattr(
        repository.local_simulation,
        "reset_group_to_unconstructed",
        lambda group_id, actor, reason="", force=False: {
            "group_id": group_id,
            "actor": actor,
            "reason": reason,
            "force": force,
        },
    )
    monkeypatch.setattr(
        repository.local_simulation,
        "record_construction_activity_event",
        lambda **kwargs: {"event_type": kwargs["event_type"], "actor": kwargs["actor"]},
    )
    monkeypatch.setattr(
        repository.local_simulation,
        "upload_construction_group_batch",
        lambda group_id, **kwargs: {"group": {"id": group_id}, "added": len(kwargs["photos"])},
    )

    repo = repository.get_state_repository()

    assert repo.classify_photo("g-1", "p-1", "after_box", "reviewer-a")["category"] == "after_box"
    assert repo.update_group_metadata("g-1", actor="reviewer-a", updates={"collector": "c"})["updates"] == {
        "collector": "c"
    }
    assert repo.reset_group_to_unconstructed("g-1", actor="reviewer-a", reason="wrong", force=True)["force"] is True
    assert (
        repo.record_construction_activity_event(
            event_type="construction_heartbeat",
            actor="constructor",
            task_id=7,
            occurred_at="2026-06-22T09:00:00",
        )["actor"]
        == "constructor"
    )
    assert (
        repo.upload_construction_group_batch(
            "g-1",
            actor="constructor",
            client_batch_id="batch-1",
            collector="collector",
            module_asset_no="module",
            photos=[{"url": "/uploads/a.jpg"}],
            creator="施工员",
            client_completed_at="2026-06-22T09:30:00",
        )["added"]
        == 1
    )
    assert calls == [
        ("classify_photo", ("g-1", "p-1", "after_box", "reviewer-a"), {}),
        (
            "update_group_metadata",
            ("g-1",),
            {"actor": "reviewer-a", "updates": {"collector": "c"}, "audit_action": "update_group_metadata"},
        ),
        ("reset_group_to_unconstructed", ("g-1",), {"actor": "reviewer-a", "reason": "wrong", "force": True}),
        (
            "record_construction_activity_event",
            (),
            {
                "event_type": "construction_heartbeat",
                "actor": "constructor",
                "task_id": 7,
                "group_id": "",
                "client_batch_id": "",
                "occurred_at": "2026-06-22T09:00:00",
                "payload": None,
            },
        ),
        (
            "upload_construction_group_batch",
            ("g-1",),
            {
                "actor": "constructor",
                "client_batch_id": "batch-1",
                "collector": "collector",
                "module_asset_no": "module",
                "photos": [{"url": "/uploads/a.jpg"}],
                "creator": "施工员",
                "client_completed_at": "2026-06-22T09:30:00",
            },
        ),
    ]


def test_dual_backend_does_not_break_json_when_postgres_mirror_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class BrokenMirrorRepository:
        def release_task(self, *args, **kwargs):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(repository.settings, "state_backend", "dual")
    monkeypatch.setattr(repository.DualWriteStateRepository, "postgres_repository_factory", BrokenMirrorRepository)
    monkeypatch.setattr(
        repository.local_simulation,
        "release_task",
        lambda task_id, reviewer, force=False: {"id": task_id, "reviewer": reviewer, "force": force},
    )

    repo = repository.get_state_repository()

    with caplog.at_level(logging.WARNING):
        assert repo.release_task(8, "reviewer-a", force=True) == {
            "id": 8,
            "reviewer": "reviewer-a",
            "force": True,
        }

    assert "Dual write mirror failed for release_task" in caplog.text


def _postgres_finalize_record(*, version: int = 1, terminal: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        id="unmatched-uuid",
        legacy_id="unmatched-finalize-1",
        team_id="default-team",
        record_type="scan",
        status="open",
        terminal=terminal,
        meter_no="120000912473",
        meter_match_key="0000912473",
        barcode="120000912473",
        collector="C001",
        module_asset_no="M001",
        address="match road",
        payload={
            "photo_urls": ["https://photos.example/1.jpg"],
            "temporary_review": {
                "schema_version": 1,
                "unmatched_id": "unmatched-finalize-1",
                "version": version,
                "state": "reviewed",
                "meter_no": "120000912473",
                "collector": "C001",
                "module_asset_no": "M001",
                "manual_confirmed": True,
                "reviewer": "reviewer-a",
                "reviewed_at": "2026-07-13T09:00:00+00:00",
                "updated_at": "2026-07-13T09:00:00+00:00",
                "photos": [],
            },
        },
    )


def _postgres_finalize_group() -> SimpleNamespace:
    return SimpleNamespace(
        id="group-uuid",
        legacy_id="g-finalized",
        legacy_task_id=7,
        task_id=None,
        team_id="default-team",
        terminal="T-FINAL",
        display_meter_no="120000912473",
        meter_match_key="0000912473",
        installation_address="match road",
        status=repository.GroupStatus.INCOMPLETE,
        photo_count=0,
        reviewer=None,
        reviewed_at=None,
        review_note="",
        exception_note="",
        exception_reasons=[],
        has_archive_blocker=False,
        raw_data={"status": "incomplete", "source_unmatched_id": "unmatched-finalize-1"},
    )


class FinalizeFakeScalars:
    def __init__(self, items=None):
        self.items = list(items or [])

    def all(self):
        return self.items


class FinalizeFakeSession:
    def __init__(self, record: SimpleNamespace, *, fail_commit: bool = False):
        self.record = record
        self.record_snapshot = deepcopy(vars(record))
        self.fail_commit = fail_commit
        self.statements = []
        self.staged = []
        self.rolled_back_staged = []
        self.commit_attempts = 0
        self.commit_calls = 0
        self.rollback_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def scalar(self, statement):
        self.statements.append(statement)
        sql = str(statement)
        if "pg_advisory_xact_lock" in sql:
            return 0
        if "FROM unmatched_records" in sql:
            return self.record
        if "FROM projects" in sql:
            return uuid4()
        if "FROM material_groups" in sql:
            return None
        return 0

    def scalars(self, statement):
        self.statements.append(statement)
        return FinalizeFakeScalars()

    def get(self, model, identity):
        return None

    def add(self, value):
        self.staged.append(value)

    def commit(self):
        self.commit_attempts += 1
        if self.fail_commit:
            raise RuntimeError("late PostgreSQL commit failure")
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1
        self.rolled_back_staged = list(self.staged)
        self.staged.clear()
        vars(self.record).clear()
        vars(self.record).update(deepcopy(self.record_snapshot))

    def refresh(self, value):
        return None


class ReviewFakeSession(FinalizeFakeSession):
    def __init__(self, record: SimpleNamespace, *, fail_commit: bool = False):
        super().__init__(record, fail_commit=fail_commit)
        self.active = False

    def __enter__(self):
        self.active = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self.active = False
        return False


class FormalGroupSuccessSession:
    def __init__(self, *, task: SimpleNamespace, record: SimpleNamespace | None = None) -> None:
        self.task = task
        self.record = record
        self.statements = []
        self.staged = []
        self.groups = []
        self.commit_calls = 0
        self.rollback_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def scalar(self, statement):
        self.statements.append(statement)
        sql = str(statement)
        if "FROM unmatched_records" in sql:
            return self.record
        if "FROM material_groups" in sql:
            return None
        return 0

    def scalars(self, statement):
        self.statements.append(statement)
        return FinalizeFakeScalars()

    def get(self, model, identity):
        if model is repository.Task and identity == self.task.id:
            return self.task
        return None

    def add(self, value):
        if isinstance(value, repository.MaterialGroup):
            value.id = value.id or uuid4()
            self.groups.append(value)
        self.staged.append(value)

    def flush(self):
        return None

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1

    def refresh(self, value):
        return None


class FinalizationIdentityRaceSession:
    def __init__(self, record, existing_group, project_id) -> None:
        self.record = record
        self.record_snapshot = deepcopy(vars(record))
        self.existing_group = existing_group
        self.project_id = project_id
        self.statements = []
        self.staged = []
        self.commit_calls = 0
        self.rollback_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def scalar(self, statement):
        self.statements.append(statement)
        sql = str(statement)
        if "pg_advisory_xact_lock" in sql:
            return 0
        if "FROM unmatched_records" in sql:
            return self.record
        if "FROM projects" in sql:
            return self.project_id
        if "FROM material_groups" in sql:
            if "WHERE material_groups.project_id =" in sql and "material_groups.meter_match_key =" in sql:
                return self.existing_group
            return None
        if "count(photos.id)" in sql:
            return 0
        return 0

    def scalars(self, statement):
        self.statements.append(statement)
        return FinalizeFakeScalars()

    def get(self, model, identity):
        return None

    def add(self, value):
        self.staged.append(value)

    def flush(self):
        return None

    def commit(self):
        if any(isinstance(value, repository.MaterialGroup) and value is not self.existing_group for value in self.staged):
            raise IntegrityError("INSERT material_groups", {}, RuntimeError("project/meter identity conflict"))
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1
        self.staged.clear()
        vars(self.record).clear()
        vars(self.record).update(deepcopy(self.record_snapshot))

    def refresh(self, value):
        return None


class LegacyMutationSession:
    def __init__(self, record, group, *, fail_commit: bool = False) -> None:
        self.record = record
        self.group = group
        self.record_snapshot = deepcopy(vars(record))
        self.group_snapshot = deepcopy(vars(group))
        self.fail_commit = fail_commit
        self.statements = []
        self.staged = []
        self.persisted = []
        self.commit_attempts = 0
        self.rollback_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.rollback()
        return False

    def scalar(self, statement):
        self.statements.append(statement)
        sql = str(statement)
        if "FROM unmatched_records" in sql:
            return self.record
        if "FROM material_groups" in sql:
            return self.group
        if "count(photos.id)" in sql:
            return 0
        return None

    def scalars(self, statement):
        self.statements.append(statement)
        return FinalizeFakeScalars()

    def get(self, model, identity):
        return None

    def add(self, value):
        self.staged.append(value)

    def flush(self):
        return None

    def commit(self):
        self.commit_attempts += 1
        if self.fail_commit:
            raise RuntimeError("legacy mutation commit failed")
        self.persisted.extend(self.staged)

    def rollback(self):
        self.rollback_calls += 1
        self.staged.clear()
        vars(self.record).clear()
        vars(self.record).update(deepcopy(self.record_snapshot))
        vars(self.group).clear()
        vars(self.group).update(deepcopy(self.group_snapshot))

    def refresh(self, value):
        return None


def formal_group_task() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        legacy_id=41,
        team_id="default-team",
        terminal="T-FORMAL",
        construction_claimed_by=None,
    )


def test_postgres_exact_group_creation_uses_unique_stable_formal_group_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions: list[FormalGroupSuccessSession] = []
    task = formal_group_task()

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            session = FormalGroupSuccessSession(task=task)
            sessions.append(session)
            return session

        def _project_id_for_team(self, session, team_id: str):
            return uuid4()

        def _ensure_task_for_terminal(self, session, team_id: str, terminal: str):
            return task

        def _task_stats(self, session, checked_task):
            return {}

        def _task_payload_stats(self, session, checked_task):
            return self._task_stats(session, checked_task)

    monkeypatch.setattr(repository, "_construction_task_payload", lambda checked_task, stats: {"id": checked_task.legacy_id})
    repo = TestPostgresRepository()

    first = repo.create_empty_group_for_terminal(
        terminal="T-FORMAL",
        actor="admin-a",
        meter_no="120000000001",
    )
    second = repo.create_empty_group_for_terminal(
        terminal="T-FORMAL",
        actor="admin-a",
        meter_no="120000000002",
    )

    exposed_ids = [first["group"]["id"], second["group"]["id"]]
    persisted_ids = [sessions[0].groups[0].legacy_id, sessions[1].groups[0].legacy_id]
    assert all(group_id.startswith("g-") for group_id in exposed_ids)
    assert all(not group_id.startswith(("manual-", "unmatched-")) for group_id in exposed_ids)
    assert len(set(exposed_ids)) == 2
    assert exposed_ids == persisted_ids
    assert repository._group_payload(sessions[0], sessions[0].groups[0])["id"] == first["group"]["id"]
    assert all(session.commit_calls == 1 for session in sessions)


def test_postgres_unmatched_finalization_materializes_stable_formal_group_id() -> None:
    record = _postgres_finalize_record()
    record.payload = {**record.payload, "photo_urls": []}
    task = formal_group_task()
    session = FormalGroupSuccessSession(task=task, record=record)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

        def _resolve_unmatched_candidate(self, checked_session, locked_record, review, candidate_key):
            assert checked_session is session
            assert locked_record is record
            return {
                "candidate_key": candidate_key,
                "target_group_id": "",
                "terminal": "T-FORMAL",
                "meter_no": "120000912473",
                "meter_match_key": "0000912473",
                "address": "formal road",
            }

        def _project_id_for_team(self, checked_session, team_id: str):
            return uuid4()

        def _ensure_task_for_terminal(self, checked_session, team_id: str, terminal: str):
            return task

    result = TestPostgresRepository().finalize_unmatched_match(
        record.legacy_id,
        actor="admin-a",
        candidate_key="catalog:formal:T-FORMAL",
        expected_version=1,
    )

    materialized_groups = [item for item in session.staged if isinstance(item, repository.MaterialGroup)]
    assert len(materialized_groups) == 1
    materialized = materialized_groups[0]
    assert result["group"]["id"].startswith("g-")
    assert not result["group"]["id"].startswith(("manual-", "unmatched-"))
    assert result["group"]["id"] == materialized.legacy_id
    assert repository._group_payload(session, materialized)["id"] == result["group"]["id"]
    assert session.commit_calls == 1
    assert session.rollback_calls == 0


def test_postgres_finalization_reuses_compatible_group_after_duplicate_catalog_race() -> None:
    record = _postgres_finalize_record()
    record.payload = {**record.payload, "photo_urls": []}
    project_id = uuid4()
    candidate_catalog_id = uuid4()
    existing_catalog_id = uuid4()
    task = formal_group_task()
    group = _postgres_finalize_group()
    group.project_id = project_id
    group.task_id = task.id
    group.legacy_task_id = task.legacy_id
    group.terminal = "T-FORMAL"
    group.total_catalog_row_id = existing_catalog_id
    session = FinalizationIdentityRaceSession(record, group, project_id)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

        def _resolve_unmatched_candidate(self, checked_session, locked_record, review, candidate_key):
            return {
                "candidate_key": candidate_key,
                "catalog_row_db_id": str(candidate_catalog_id),
                "target_group_id": "",
                "terminal": "T-FORMAL",
                "meter_no": "120000912473",
                "meter_match_key": "0000912473",
                "address": "formal road",
            }

        def _ensure_task_for_terminal(self, checked_session, team_id: str, terminal: str):
            return task

    result = TestPostgresRepository().finalize_unmatched_match(
        record.legacy_id,
        actor="admin-a",
        candidate_key=f"catalog:{candidate_catalog_id}:T-FORMAL",
        expected_version=1,
    )

    compiled = [
        str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for statement in session.statements
    ]
    expected_lock_key = int.from_bytes(
        hashlib.sha256(f"{project_id}\0{record.meter_match_key}".encode("utf-8")).digest()[:8],
        byteorder="big",
        signed=True,
    )
    assert any(f"pg_advisory_xact_lock({expected_lock_key})" in sql for sql in compiled)
    assert any(
        "FROM material_groups" in sql
        and "WHERE material_groups.project_id =" in sql
        and "material_groups.meter_match_key =" in sql
        and "FOR UPDATE" in sql
        for sql in compiled
    )
    assert result["group"]["id"] == group.legacy_id
    assert result["attached"] is True
    assert group.total_catalog_row_id == existing_catalog_id
    assert not any(isinstance(item, repository.MaterialGroup) and item is not group for item in session.staged)
    assert session.commit_calls == 1
    assert session.rollback_calls == 0


def test_postgres_finalization_rejects_incompatible_group_on_unique_identity() -> None:
    record = _postgres_finalize_record()
    record.payload = {**record.payload, "photo_urls": []}
    project_id = uuid4()
    task = formal_group_task()
    group = _postgres_finalize_group()
    group.project_id = project_id
    group.task_id = task.id
    group.legacy_task_id = task.legacy_id
    group.terminal = "T-OTHER"
    group.total_catalog_row_id = uuid4()
    session = FinalizationIdentityRaceSession(record, group, project_id)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

        def _resolve_unmatched_candidate(self, checked_session, locked_record, review, candidate_key):
            return {
                "candidate_key": candidate_key,
                "catalog_row_db_id": str(uuid4()),
                "target_group_id": "",
                "terminal": "T-FORMAL",
                "meter_no": "120000912473",
                "meter_match_key": "0000912473",
                "address": "formal road",
            }

        def _ensure_task_for_terminal(self, checked_session, team_id: str, terminal: str):
            return task

    with pytest.raises(ValueError, match="conflicts with existing formal group identity"):
        TestPostgresRepository().finalize_unmatched_match(
            record.legacy_id,
            actor="admin-a",
            candidate_key="catalog:duplicate:T-FORMAL",
            expected_version=1,
        )

    assert record.status == "open"
    assert session.commit_calls == 0
    assert session.rollback_calls == 1
    assert session.staged == []


@pytest.mark.parametrize(
    ("terminal", "meter_no"),
    [
        ("", "120000000001"),
        ("00000000", "120000000001"),
        ("未关联终端", "120000000001"),
        ("manual-terminal", "120000000001"),
        ("unmatched-terminal", "120000000001"),
        ("T-REAL", ""),
        ("T-REAL", "00000000"),
        ("T-REAL", "未关联终端"),
        ("T-REAL", "manual-meter"),
        ("T-REAL", "unmatched-meter"),
    ],
)
def test_postgres_repository_rejects_placeholder_formal_identity_before_session(
    terminal: str,
    meter_no: str,
) -> None:
    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            pytest.fail("invalid formal identity must be rejected before a transaction starts")

    with pytest.raises(ValueError, match="real (terminal|meter number)"):
        TestPostgresRepository().create_empty_group_for_terminal(
            terminal=terminal,
            actor="admin",
            meter_no=meter_no,
        )


def test_postgres_group_creation_rejects_placeholder_match_key_before_session() -> None:
    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            pytest.fail("invalid formal identity must be rejected before a transaction starts")

    with pytest.raises(ValueError, match="real meter match key"):
        TestPostgresRepository().create_empty_group_for_terminal(
            terminal="T-REAL",
            actor="admin",
            meter_no="120000000001",
            meter_match_key="unmatched-key",
        )


def test_postgres_create_group_from_unmatched_uses_one_locked_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    record = _postgres_finalize_record()
    fake_session = FinalizeFakeSession(record)
    helper_calls: list[str] = []
    group = _postgres_finalize_group()
    group.task_id = "task-uuid"

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return fake_session

        def create_empty_group_for_terminal(self, **kwargs):
            helper_calls.append("create-empty")
            return {"group": {"id": "split-group"}, "task": {"id": 7}}

        def associate_unmatched_record(self, *args, **kwargs):
            helper_calls.append("associate")
            return {"group": {"id": "split-group"}, "import_result": {"photos_new": 1}}

        def _materialize_unmatched_candidate(self, session, locked_record, review, candidate, actor):
            assert session is fake_session
            assert locked_record is record
            assert candidate["terminal"] == "T-ATOMIC"
            session.add(group)
            return group, False

    monkeypatch.setattr(repository, "_group_payload", lambda session, value: {"id": value.legacy_id, "terminal": value.terminal})

    result = TestPostgresRepository().create_group_from_unmatched_record(
        record.legacy_id,
        actor="admin-a",
        expected_version=1,
        terminal="T-ATOMIC",
        updates={"meter_no": "120000912473"},
    )

    compiled = str(fake_session.statements[0].compile(dialect=postgresql.dialect()))
    audits = [item for item in fake_session.staged if isinstance(item, repository.AuditLog)]
    assert "FOR UPDATE" in compiled
    assert helper_calls == []
    assert fake_session.commit_calls == 1
    assert fake_session.rollback_calls == 0
    assert record.status == "associated"
    assert record.payload["temporary_review"]["version"] == 2
    assert len(audits) == 1
    assert audits[0].action == "create_group_from_unmatched"
    assert result["group"]["id"] == "g-finalized"


def test_postgres_create_group_from_unmatched_rolls_back_group_task_and_audit_on_failure() -> None:
    record = _postgres_finalize_record()
    before = deepcopy(vars(record))
    fake_session = FinalizeFakeSession(record)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return fake_session

        def _materialize_unmatched_candidate(self, session, locked_record, review, candidate, actor):
            session.add(SimpleNamespace(kind="task"))
            session.add(SimpleNamespace(kind="group"))
            session.add(repository.AuditLog(action="should-rollback", entity_type="test"))
            raise ValueError("atomic materialization failed")

    with pytest.raises(ValueError, match="atomic materialization failed"):
        TestPostgresRepository().create_group_from_unmatched_record(
            record.legacy_id,
            actor="admin-a",
            expected_version=1,
            terminal="T-ATOMIC",
            updates={"meter_no": "120000912473"},
        )

    assert fake_session.commit_calls == 0
    assert fake_session.rollback_calls == 1
    assert fake_session.staged == []
    assert vars(record) == before


def test_postgres_create_group_from_unmatched_rejects_stale_version_without_staging() -> None:
    record = _postgres_finalize_record(version=2)
    before = deepcopy(vars(record))
    fake_session = FinalizeFakeSession(record)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return fake_session

    with pytest.raises(repository.unmatched_review.ReviewVersionConflict):
        TestPostgresRepository().create_group_from_unmatched_record(
            record.legacy_id,
            actor="admin-a",
            expected_version=1,
            terminal="T-ATOMIC",
            updates={"meter_no": "120000912473"},
        )

    assert fake_session.commit_calls == 0
    assert fake_session.rollback_calls == 1
    assert fake_session.staged == []
    assert vars(record) == before


def _review_photo_id(record: SimpleNamespace) -> str:
    review = repository.unmatched_review.build_review(repository._unmatched_payload(record))
    return review["photos"][0]["id"]


def test_postgres_get_unmatched_review_reads_record_without_lock_or_commit() -> None:
    record = _postgres_finalize_record()
    fake_session = ReviewFakeSession(record)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return fake_session

    result = TestPostgresRepository().get_unmatched_review(record.legacy_id)

    compiled = str(fake_session.statements[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" not in compiled
    assert result["record"]["unmatched_id"] == record.legacy_id
    assert result["review"]["version"] == 1
    assert result["review"]["photos"][0]["source_url"] == "https://photos.example/1.jpg"
    assert fake_session.commit_calls == 0
    assert fake_session.rollback_calls == 0


def test_postgres_save_unmatched_review_locks_and_uses_single_audit_and_commit() -> None:
    record = _postgres_finalize_record()
    fake_session = ReviewFakeSession(record)
    photo_id = _review_photo_id(record)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return fake_session

    result = TestPostgresRepository().save_unmatched_review(
        record.legacy_id,
        actor="reviewer-a",
        expected_version=1,
        metadata={"meter_no": "120000912474", "terminal": "00000000"},
        photo_updates=[{"id": photo_id, "category": "collector_barcode", "source_url": "tampered"}],
        state="reviewed",
    )

    compiled = str(fake_session.statements[0].compile(dialect=postgresql.dialect()))
    audits = [item for item in fake_session.staged if isinstance(item, repository.AuditLog)]
    assert "FOR UPDATE" in compiled
    assert fake_session.commit_calls == 1
    assert fake_session.rollback_calls == 0
    assert len(audits) == 1
    assert audits[0].action == "unmatched_review_saved"
    assert audits[0].actor_username == "reviewer-a"
    assert result["review"]["version"] == 2
    assert result["review"]["meter_no"] == "120000912474"
    assert result["review"]["photos"][0]["category"] == "collector_barcode"
    assert result["review"]["photos"][0]["source_url"] == "https://photos.example/1.jpg"
    assert "terminal" not in result["review"]


def test_postgres_save_unmatched_review_version_conflict_rolls_back_without_mutation() -> None:
    record = _postgres_finalize_record(version=2)
    before = deepcopy(vars(record))
    fake_session = ReviewFakeSession(record)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return fake_session

    with pytest.raises(repository.unmatched_review.ReviewVersionConflict):
        TestPostgresRepository().save_unmatched_review(
            record.legacy_id,
            actor="reviewer-a",
            expected_version=1,
            metadata={"meter_no": "120000912474"},
        )

    assert fake_session.commit_calls == 0
    assert fake_session.rollback_calls == 1
    assert fake_session.staged == []
    assert vars(record) == before


def test_postgres_save_unmatched_review_rolls_back_on_commit_failure() -> None:
    record = _postgres_finalize_record()
    before = deepcopy(vars(record))
    fake_session = ReviewFakeSession(record, fail_commit=True)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return fake_session

    with pytest.raises(RuntimeError, match="late PostgreSQL commit failure"):
        TestPostgresRepository().save_unmatched_review(
            record.legacy_id,
            actor="reviewer-a",
            expected_version=1,
            metadata={"collector": "C002"},
        )

    assert fake_session.commit_attempts == 1
    assert fake_session.commit_calls == 0
    assert fake_session.rollback_calls == 1
    assert any(isinstance(item, repository.AuditLog) for item in fake_session.rolled_back_staged)
    assert vars(record) == before


def test_postgres_rescan_unmatched_review_scans_outside_session_then_relocks_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _postgres_finalize_record()
    photo_id = _review_photo_id(record)
    sessions: list[ReviewFakeSession] = []
    scan_calls = []

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            session = ReviewFakeSession(record)
            sessions.append(session)
            return session

    def fake_scan(photo, context, *, use_ocr=False):
        assert len(sessions) == 1
        assert sessions[0].active is False
        scan_calls.append((deepcopy(photo), deepcopy(context), use_ocr))
        return {
            "barcode_check_status": "matched",
            "barcode_check_method": "barcode_qr_ocr",
            "barcode_check_matched_value": "120000912473",
            "qr_values": ["120000912473"],
        }

    monkeypatch.setattr(repository.photo_barcode_check, "check_photo_barcode", fake_scan)

    result = TestPostgresRepository().rescan_unmatched_review_photo(
        record.legacy_id,
        photo_id,
        actor="reviewer-a",
        expected_version=1,
        category="collector_barcode",
    )

    assert len(sessions) == 2
    snapshot_sql = str(sessions[0].statements[0].compile(dialect=postgresql.dialect()))
    persistence_sql = str(sessions[1].statements[0].compile(dialect=postgresql.dialect()))
    audits = [item for item in sessions[1].staged if isinstance(item, repository.AuditLog)]
    assert "FOR UPDATE" not in snapshot_sql
    assert "FOR UPDATE" in persistence_sql
    assert sessions[0].commit_calls == 0
    assert sessions[1].commit_calls == 1
    assert sessions[1].rollback_calls == 0
    assert len(audits) == 1
    assert audits[0].action == "unmatched_review_barcode_rescan"
    assert audits[0].before_data["confirmation"] == {
        "manual_confirmed": True,
        "reviewed_at": "2026-07-13T09:00:00+00:00",
    }
    assert audits[0].after_data["confirmation"] == {
        "manual_confirmed": False,
        "reviewed_at": "",
    }
    assert scan_calls[0][0]["category"] == "collector_barcode"
    assert scan_calls[0][2] is True
    assert result["review"]["version"] == 2
    assert result["review"]["manual_confirmed"] is False
    assert result["review"]["reviewed_at"] == ""
    assert result["photo"]["barcode_check_status"] == "matched"
    assert result["photo"]["barcode_rescanned_by"] == "reviewer-a"


def test_postgres_rescan_unmatched_review_rejects_version_drift_before_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _postgres_finalize_record()
    before_scan = deepcopy(vars(record))
    photo_id = _review_photo_id(record)
    sessions: list[ReviewFakeSession] = []

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            session = ReviewFakeSession(record)
            sessions.append(session)
            return session

    def drifting_scan(photo, context, *, use_ocr=False):
        drifted_review = deepcopy(record.payload["temporary_review"])
        drifted_review["version"] = 2
        record.payload = {**record.payload, "temporary_review": drifted_review}
        return {"barcode_check_status": "matched"}

    monkeypatch.setattr(repository.photo_barcode_check, "check_photo_barcode", drifting_scan)

    with pytest.raises(repository.unmatched_review.ReviewVersionConflict):
        TestPostgresRepository().rescan_unmatched_review_photo(
            record.legacy_id,
            photo_id,
            actor="reviewer-a",
            expected_version=1,
            category="collector_barcode",
        )

    assert len(sessions) == 2
    assert sessions[1].commit_calls == 0
    assert sessions[1].rollback_calls == 1
    assert sessions[1].staged == []
    assert record.payload["temporary_review"]["version"] == 2
    assert record.payload["temporary_review"] != before_scan["payload"]["temporary_review"]


def test_postgres_rescan_unmatched_review_rejects_stale_expected_version_before_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _postgres_finalize_record(version=2)
    before = deepcopy(vars(record))
    photo_id = _review_photo_id(record)
    sessions: list[ReviewFakeSession] = []

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            session = ReviewFakeSession(record)
            sessions.append(session)
            return session

    monkeypatch.setattr(
        repository.photo_barcode_check,
        "check_photo_barcode",
        lambda *args, **kwargs: pytest.fail("stale rescan must not start a CPU scan"),
    )

    with pytest.raises(repository.unmatched_review.ReviewVersionConflict):
        TestPostgresRepository().rescan_unmatched_review_photo(
            record.legacy_id,
            photo_id,
            actor="reviewer-a",
            expected_version=1,
            category="collector_barcode",
        )

    assert len(sessions) == 1
    assert sessions[0].commit_calls == 0
    assert sessions[0].rollback_calls == 0
    assert vars(record) == before


def test_postgres_confirm_unmatched_review_locks_and_uses_single_audit_and_commit() -> None:
    record = _postgres_finalize_record()
    fake_session = ReviewFakeSession(record)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return fake_session

    result = TestPostgresRepository().confirm_unmatched_review(
        record.legacy_id,
        actor="reviewer-a",
        expected_version=1,
        confirmed=True,
    )

    compiled = str(fake_session.statements[0].compile(dialect=postgresql.dialect()))
    audits = [item for item in fake_session.staged if isinstance(item, repository.AuditLog)]
    assert "FOR UPDATE" in compiled
    assert fake_session.commit_calls == 1
    assert fake_session.rollback_calls == 0
    assert len(audits) == 1
    assert audits[0].action == "unmatched_review_confirmed"
    assert result["review"]["version"] == 2
    assert result["review"]["manual_confirmed"] is True
    assert result["review"]["reviewer"] == "reviewer-a"
    assert "formal_scan_pass" not in result["review"]


def test_postgres_finalize_unmatched_uses_for_update_and_single_commit() -> None:
    record = _postgres_finalize_record()
    fake_session = FinalizeFakeSession(record)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return fake_session

        def _resolve_unmatched_candidate(self, session, locked_record, review, candidate_key):
            assert locked_record is record
            assert review["version"] == 1
            assert candidate_key == "catalog:catalog-1:T-FINAL"
            return {
                "candidate_key": candidate_key,
                "target_group_id": "",
                "terminal": "T-FINAL",
                "meter_no": "120000912473",
                "address": "match road",
                "match_reasons": ["meter exact"],
            }

        def _materialize_unmatched_candidate(self, session, locked_record, review, candidate, actor):
            return _postgres_finalize_group(), False

    result = TestPostgresRepository().finalize_unmatched_match(
        record.legacy_id,
        actor="admin-a",
        candidate_key="catalog:catalog-1:T-FINAL",
        expected_version=1,
    )

    compiled = [
        str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        for statement in fake_session.statements
    ]
    audits = [item for item in fake_session.staged if isinstance(item, repository.AuditLog)]
    assert any("pg_advisory_xact_lock" in sql for sql in compiled)
    assert any("FROM unmatched_records" in sql and "FOR UPDATE" in sql for sql in compiled)
    assert fake_session.commit_calls == 1
    assert fake_session.rollback_calls == 0
    assert record.status == "associated"
    assert record.payload["temporary_review"]["version"] == 1
    assert record.payload["associated_group_id"] == "g-finalized"
    assert len(audits) == 1
    assert audits[0].action == "unmatched_review_finalized"
    assert result["group"]["terminal"] == "T-FINAL"
    assert result["attached"] is False
    assert "00000000" not in str(result)


def test_postgres_finalize_requires_manual_confirmation_without_writes() -> None:
    record = _postgres_finalize_record()
    record.payload["temporary_review"]["manual_confirmed"] = False
    record.payload["temporary_review"]["reviewer"] = ""
    record.payload["temporary_review"]["reviewed_at"] = ""
    before = deepcopy(vars(record))
    fake_session = FinalizeFakeSession(record)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return fake_session

    with pytest.raises(ValueError, match="Manual confirmation required"):
        TestPostgresRepository().finalize_unmatched_match(
            record.legacy_id,
            actor="admin-a",
            candidate_key="catalog:catalog-1:T-FINAL",
            expected_version=1,
        )

    assert fake_session.commit_calls == 0
    assert fake_session.staged == []
    assert vars(record) == before


def test_postgres_legacy_identity_patch_syncs_review_and_revokes_confirmation() -> None:
    record = _postgres_finalize_record()
    group = _postgres_finalize_group()
    session = LegacyMutationSession(record, group)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

    result = TestPostgresRepository().update_unmatched_record(
        record.legacy_id,
        actor="admin-a",
        expected_version=1,
        updates={
            "meter_no": "120000912474",
            "collector": "C002",
            "module_asset_no": "M002",
        },
    )

    review = result["record"]["temporary_review"]
    assert review["meter_no"] == "120000912474"
    assert review["collector"] == "C002"
    assert review["module_asset_no"] == "M002"
    assert review["manual_confirmed"] is False
    assert review["reviewer"] == ""
    assert review["reviewed_at"] == ""


def test_postgres_asset_no_alias_syncs_canonical_module_and_revokes_confirmation() -> None:
    record = _postgres_finalize_record()
    group = _postgres_finalize_group()
    session = LegacyMutationSession(record, group)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

    result = TestPostgresRepository().update_unmatched_record(
        record.legacy_id,
        actor="admin-a",
        expected_version=1,
        updates={"asset_no": "M002"},
    )

    review = result["record"]["temporary_review"]
    assert result["record"]["module_asset_no"] == "M002"
    assert review["module_asset_no"] == "M002"
    assert review["manual_confirmed"] is False
    assert review["reviewer"] == ""
    assert review["reviewed_at"] == ""


@pytest.mark.parametrize(
    ("terminal", "meter_no"),
    [
        ("manual-1", "120000912473"),
        ("unmatched-1", "120000912473"),
        ("未关联终端", "120000912473"),
        ("00000000", "120000912473"),
        ("T-STRICT", "manual-1"),
        ("T-STRICT", "unmatched-1"),
        ("T-STRICT", "未关联终端"),
        ("T-STRICT", "00000000"),
    ],
)
def test_postgres_candidate_finalization_rejects_synthetic_identity_without_writes(
    terminal: str,
    meter_no: str,
) -> None:
    record = _postgres_finalize_record()
    before = deepcopy(vars(record))
    fake_session = FinalizeFakeSession(record)
    materialize_calls = 0

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return fake_session

        def _resolve_unmatched_candidate(self, session, locked_record, review, candidate_key):
            return {
                "candidate_key": candidate_key,
                "target_group_id": "",
                "terminal": terminal,
                "meter_no": meter_no,
                "meter_match_key": "0000912473",
                "address": "strict road",
            }

        def _materialize_unmatched_candidate(self, session, locked_record, review, candidate, actor):
            nonlocal materialize_calls
            materialize_calls += 1
            group = _postgres_finalize_group()
            session.add(group)
            session.add(SimpleNamespace(kind="formal-photo"))
            return group, False

    with pytest.raises(ValueError, match="real (terminal|meter number)"):
        TestPostgresRepository().finalize_unmatched_match(
            record.legacy_id,
            actor="admin-a",
            candidate_key=f"catalog:strict:{terminal}:{meter_no}",
            expected_version=1,
        )

    assert materialize_calls == 0
    assert fake_session.commit_calls == 0
    assert fake_session.rollback_calls == 1
    assert fake_session.staged == []
    assert vars(record) == before


def test_postgres_finalize_replay_returns_stored_result_without_duplicate_writes() -> None:
    record = _postgres_finalize_record()
    fake_session = FinalizeFakeSession(record)
    group = _postgres_finalize_group()
    formal_photo = SimpleNamespace(kind="formal-photo")
    materialize_calls = 0

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return fake_session

        def _resolve_unmatched_candidate(self, session, locked_record, review, candidate_key):
            return {
                "candidate_key": candidate_key,
                "target_group_id": "",
                "terminal": "T-FINAL",
                "meter_no": "120000912473",
                "meter_match_key": "0000912473",
                "address": "match road",
            }

        def _materialize_unmatched_candidate(self, session, locked_record, review, candidate, actor):
            nonlocal materialize_calls
            materialize_calls += 1
            session.add(group)
            session.add(formal_photo)
            return group, False

    repo = TestPostgresRepository()
    first = repo.finalize_unmatched_match(
        record.legacy_id,
        actor="admin-a",
        candidate_key="catalog:catalog-1:T-FINAL",
        expected_version=1,
    )
    second = repo.finalize_unmatched_match(
        record.legacy_id,
        actor="admin-a",
        candidate_key="catalog:catalog-1:T-FINAL",
        expected_version=1,
    )

    compiled = [
        str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for statement in fake_session.statements
    ]
    advisory_locks = [sql for sql in compiled if "pg_advisory_xact_lock" in sql]
    audits = [item for item in fake_session.staged if isinstance(item, repository.AuditLog)]
    stored_replay = record.payload["finalization_replay"]
    assert second == first
    assert stored_replay == {
        "candidate_key": "catalog:catalog-1:T-FINAL",
        "expected_version": 1,
        "result": first,
    }
    assert len(advisory_locks) == 1
    assert materialize_calls == 1
    assert sum(item is group for item in fake_session.staged) == 1
    assert sum(item is formal_photo for item in fake_session.staged) == 1
    assert len(audits) == 1
    assert fake_session.commit_calls == 1


def test_postgres_open_record_never_trusts_forged_replay_payload() -> None:
    record = _postgres_finalize_record(version=2)
    forged = {"group": {"id": "g-forged", "terminal": "T-FORGED"}, "attached": False}
    record.payload = {
        **record.payload,
        "finalization_replay": {
            "candidate_key": "catalog:catalog-1:T-FINAL",
            "expected_version": 1,
            "result": forged,
        },
    }
    fake_session = FinalizeFakeSession(record)
    materialize_calls = 0

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return fake_session

        def _resolve_unmatched_candidate(self, session, locked_record, review, candidate_key):
            pytest.fail("stale open review must fail before candidate resolution")

        def _materialize_unmatched_candidate(self, session, locked_record, review, candidate, actor):
            nonlocal materialize_calls
            materialize_calls += 1
            return _postgres_finalize_group(), False

    with pytest.raises(repository.unmatched_review.ReviewVersionConflict):
        TestPostgresRepository().finalize_unmatched_match(
            record.legacy_id,
            actor="admin-a",
            candidate_key="catalog:catalog-1:T-FINAL",
            expected_version=1,
        )

    assert record.status == "open"
    assert materialize_calls == 0
    assert fake_session.commit_calls == 0
    assert fake_session.rollback_calls == 1
    assert fake_session.staged == []


def test_postgres_finalize_unmatched_rolls_back_all_staged_writes_on_failure() -> None:
    record = _postgres_finalize_record()
    fake_session = FinalizeFakeSession(record)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return fake_session

        def _resolve_unmatched_candidate(self, session, locked_record, review, candidate_key):
            return {
                "candidate_key": candidate_key,
                "terminal": "T-FINAL",
                "meter_no": "120000912473",
            }

        def _materialize_unmatched_candidate(self, session, locked_record, review, candidate, actor):
            session.add(_postgres_finalize_group())
            raise ValueError("candidate materialization failed")

    with pytest.raises(ValueError, match="materialization failed"):
        TestPostgresRepository().finalize_unmatched_match(
            record.legacy_id,
            actor="admin-a",
            candidate_key="catalog:catalog-1:T-FINAL",
            expected_version=1,
        )

    assert fake_session.commit_calls == 0
    assert fake_session.rollback_calls == 1
    assert fake_session.staged == []
    assert record.status == "open"
    assert record.payload.get("associated_group_id") is None


def test_postgres_finalize_unmatched_selects_exact_group_identity_on_shared_terminal() -> None:
    record = _postgres_finalize_record()
    catalog_id = "11111111-1111-1111-1111-111111111111"
    catalog = SimpleNamespace(
        id=catalog_id,
        terminal="T-SHARED",
        original_meter_no="120000912473",
        meter_match_key="0000912473",
        installation_address="match road",
        installer="",
        source_file="catalog.xlsx",
        source_row_number=2,
        raw_data={},
    )
    unrelated = SimpleNamespace(
        id="group-unrelated-uuid",
        legacy_id="g-shared-a-unrelated",
        terminal="T-SHARED",
        total_catalog_row_id="22222222-2222-2222-2222-222222222222",
        meter_match_key="9999999999",
    )
    exact = SimpleNamespace(
        id="group-exact-uuid",
        legacy_id="g-shared-z-exact",
        terminal="T-SHARED",
        total_catalog_row_id=catalog_id,
        meter_match_key="0000912473",
    )

    class CandidateSession:
        def __init__(self):
            self.calls = 0

        def scalars(self, statement):
            self.calls += 1
            return FinalizeFakeScalars([catalog] if self.calls == 1 else [unrelated, exact])

    candidates = repository.PostgresStateRepository()._unmatched_match_candidates_for_session(
        CandidateSession(),
        record,
        repository.unmatched_review.build_review(repository._unmatched_payload(record)),
    )

    assert len(candidates) == 1
    assert candidates[0]["target_group_id"] == exact.legacy_id


def test_postgres_unmatched_search_includes_corrected_temporary_review_identity() -> None:
    record = _postgres_finalize_record()
    record.payload["temporary_review"].update(
        {
            "meter_no": "CORRECTED-METER-001",
            "collector": "CORRECTED-COLLECTOR-001",
            "module_asset_no": "CORRECTED-MODULE-001",
        }
    )
    class SearchSession(FinalizeFakeSession):
        def scalar(self, statement):
            self.statements.append(statement)
            return 1

        def scalars(self, statement):
            self.statements.append(statement)
            return FinalizeFakeScalars([record])

    session = SearchSession(record)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

    result = TestPostgresRepository().list_unmatched_records(
        query="CORRECTED-METER-001",
        limit=20,
        offset=40,
        assigned_to="constructor-a",
    )

    compiled_statements = [
        statement.compile(dialect=postgresql.dialect())
        for statement in session.statements
    ]
    compiled_sql = "\n".join(str(statement) for statement in compiled_statements)
    compiled_params = [
        value
        for statement in compiled_statements
        for value in statement.params.values()
    ]
    assert "->>" in compiled_sql
    assert all(
        value in compiled_params
        for value in (
            "temporary_review",
            "meter_no",
            "collector",
            "module_asset_no",
            "assigned_to",
            "constructor-a",
        )
    )
    assert "LIMIT" in compiled_sql and "OFFSET" in compiled_sql
    assert result["stats"] == {"pending": 1, "assigned": 1, "outside": 1}


def test_postgres_unmatched_export_uses_one_windowed_snapshot_statement() -> None:
    first = _postgres_finalize_record()
    first.legacy_id = "u-export-1"
    second = deepcopy(first)
    second.legacy_id = "u-export-2"

    class ExportSession(FinalizeFakeSession):
        def execute(self, statement):
            self.statements.append(statement)
            return SimpleNamespace(all=lambda: [(first, 2), (second, 2)])

        def scalar(self, _statement):
            raise AssertionError("export must not issue a separate count statement")

        def scalars(self, _statement):
            raise AssertionError("export must not issue a separate records statement")

    session = ExportSession(first)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

    result = TestPostgresRepository().export_unmatched_records(
        query="CORRECTED-METER-001",
        limit=500,
    )

    assert len(session.statements) == 1
    compiled = session.statements[0].compile(dialect=postgresql.dialect())
    compiled_sql = str(compiled)
    assert "count(*) OVER ()" in compiled_sql
    assert "LIMIT" in compiled_sql
    assert all(
        value in compiled.params.values()
        for value in ("temporary_review", "meter_no", "collector", "module_asset_no")
    )
    assert result["total"] == 2
    assert [item["unmatched_id"] for item in result["items"]] == ["u-export-1", "u-export-2"]


def test_postgres_candidate_view_is_transactionally_audited() -> None:
    record = _postgres_finalize_record()
    session = FinalizeFakeSession(record)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

    result = TestPostgresRepository().list_unmatched_match_candidates(
        record.legacy_id,
        actor="reviewer-a",
    )

    audits = [item for item in session.staged if isinstance(item, repository.AuditLog)]
    assert result == {"total": 0, "items": []}
    assert session.commit_calls == 1
    assert len(audits) == 1
    assert audits[0].action == "unmatched_review_candidates_viewed"
    assert audits[0].actor_username == "reviewer-a"
    assert audits[0].payload == {
        "unmatched_id": record.legacy_id,
        "review_version": 1,
        "candidate_count": 0,
        "candidate_digest": repository.unmatched_review.candidate_snapshot_digest([]),
    }


def test_postgres_candidate_view_requires_manual_confirmation_without_audit() -> None:
    record = _postgres_finalize_record()
    record.payload["temporary_review"]["manual_confirmed"] = False
    session = FinalizeFakeSession(record)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

    with pytest.raises(ValueError, match="Manual confirmation required"):
        TestPostgresRepository().list_unmatched_match_candidates(
            record.legacy_id,
            actor="reviewer-a",
        )

    assert session.commit_calls == 0
    assert [item for item in session.staged if isinstance(item, repository.AuditLog)] == []


def test_postgres_migrated_photo_uses_same_backend_independent_id_as_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _postgres_finalize_record()
    review = repository.unmatched_review.build_review(repository._unmatched_payload(record))
    rows = repository.unmatched_review.migrate_review_to_photo_rows(review)
    group = _postgres_finalize_group()
    session = FinalizeFakeSession(record)
    monkeypatch.setattr(repository, "_reset_group_after_photo_evidence_change", lambda checked_session, checked_group: None)

    result = repository.PostgresStateRepository()._add_photo_records_to_group(
        session,
        group,
        actor="admin-a",
        photos=rows,
        source="unmatched-review-finalize",
    )

    photos = [item for item in session.staged if isinstance(item, repository.Photo)]
    assert result["added"] == 1
    assert len(photos) == 1
    assert rows[0]["id"] == photos[0].legacy_id
    assert photos[0].legacy_id == repository.unmatched_review.migrated_formal_photo_id(
        review["unmatched_id"],
        review["photos"][0]["id"],
    )


def test_postgres_unmatched_review_keeps_distinct_download_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _postgres_finalize_record()
    group = _postgres_finalize_group()
    session = FinalizeFakeSession(record)
    monkeypatch.setattr(repository, "_reset_group_after_photo_evidence_change", lambda checked_session, checked_group: None)

    result = repository.PostgresStateRepository()._add_photo_records_to_group(
        session,
        group,
        actor="admin-a",
        photos=[
            {
                "id": "photo-a",
                "url": "https://example.test/detail?downloadImg=cloud%3A%2F%2Fphoto-a.jpg",
                "source_url": "https://example.test/detail?downloadImg=cloud%3A%2F%2Fphoto-a.jpg",
                "category": "before_box",
            },
            {
                "id": "photo-b",
                "url": "https://example.test/detail?downloadImg=cloud%3A%2F%2Fphoto-b.jpg",
                "source_url": "https://example.test/detail?downloadImg=cloud%3A%2F%2Fphoto-b.jpg",
                "category": "after_box",
            },
        ],
        source="unmatched-review-finalize",
    )

    photos = [item for item in session.staged if isinstance(item, repository.Photo)]
    assert result["added"] == 2
    assert len(photos) == 2
    assert photos[0].source_url_hash != photos[1].source_url_hash


def test_postgres_unmatched_review_photo_payload_reads_back_every_evidence_field() -> None:
    evidence = {
        key: [f"{key}-value"]
        for key in repository.unmatched_review.PHOTO_EVIDENCE_FIELDS
    }
    evidence.update(
        {
            "barcode_check_status": "matched",
            "barcode_checked_at": "2026-07-13T09:00:00+00:00",
            "barcode_check_method": "barcode_qr_ocr",
            "barcode_check_error": "",
            "barcode_rescanned_by": "reviewer-a",
            "barcode_rescanned_at": "2026-07-13T08:59:00+00:00",
            "temporary_review_manual_confirmed": True,
            "temporary_review_reviewer": "reviewer-a",
            "temporary_review_reviewed_at": "2026-07-13T09:00:00+00:00",
        }
    )
    photo = SimpleNamespace(
        id="photo-uuid",
        legacy_id="p-evidence",
        image_url="https://photos.example/evidence.jpg",
        source_url="https://photos.example/evidence.jpg",
        storage_type="",
        storage_bucket="",
        storage_key="",
        sha256="sha-evidence",
        category="before_box",
        archive_filename="",
        archive_status="",
        sort_order=1,
        barcode="120000912473",
        collector="C001",
        asset_no="M001",
        creator="reviewer-a",
        raw_data=evidence,
    )

    payload = repository._photo_payload(photo)

    for key in repository.unmatched_review.PHOTO_EVIDENCE_FIELDS:
        assert payload[key] == evidence[key]
    assert payload["temporary_review_manual_confirmed"] is True
    assert payload["temporary_review_reviewer"] == "reviewer-a"
    assert payload["temporary_review_reviewed_at"] == "2026-07-13T09:00:00+00:00"


def test_postgres_unmatched_review_locks_and_merges_duplicate_photo_evidence() -> None:
    source_url = "https://photos.example/duplicate.jpg?token=old"
    canonical_hash = repository.hashlib.sha256(
        source_url.split("?", 1)[0].encode("utf-8")
    ).hexdigest()
    existing = SimpleNamespace(
        source_fingerprint="older-explicit-fingerprint",
        sha256="older-sha",
        storage_type="",
        storage_key="",
        source_url_hash=canonical_hash,
        raw_data={},
        category="unclassified",
        source_url=source_url,
        image_url=source_url,
    )
    group = SimpleNamespace(
        id="group-uuid",
        legacy_id="g-duplicate",
        team_id="default-team",
        display_meter_no="120000912473",
        photo_count=1,
        status=repository.GroupStatus.INCOMPLETE,
        reviewer=None,
        review_note="",
        exception_note="",
        reviewed_at=None,
        raw_data={},
    )

    class DuplicateSession:
        def __init__(self):
            self.statements = []
            self.flush_calls = 0
            self.added = []

        def scalars(self, statement):
            self.statements.append(statement)
            return FinalizeFakeScalars([existing])

        def scalar(self, statement):
            self.statements.append(statement)
            return 1

        def add(self, value):
            self.added.append(value)

        def flush(self):
            self.flush_calls += 1

    session = DuplicateSession()
    result = repository.PostgresStateRepository()._add_photo_records_to_group(
        session,
        group,
        actor="admin-a",
        photos=[
            {
                "url": source_url,
                "source_url": source_url,
                "source_fingerprint": "temporary-review-photo-id",
                "category": "before_box",
                "qr_values": ["QR-001"],
                "barcode_rescanned_by": "reviewer-a",
                "temporary_review_manual_confirmed": True,
            }
        ],
        source="unmatched-review-finalize",
    )

    compiled = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in compiled
    assert result == {"added": 0, "skipped_duplicates": 1, "merged_duplicates": 1}
    assert session.added == []
    assert session.flush_calls == 2
    assert existing.category == "before_box"
    assert existing.raw_data["qr_values"] == ["QR-001"]
    assert existing.raw_data["barcode_rescanned_by"] == "reviewer-a"
    assert existing.raw_data["temporary_review_manual_confirmed"] is True


def test_postgres_duplicate_evidence_resets_formal_review_archive_and_exception_state() -> None:
    source_url = "https://photos.example/reviewed-duplicate.jpg?token=old"
    canonical_hash = repository.hashlib.sha256(
        source_url.split("?", 1)[0].encode("utf-8")
    ).hexdigest()
    existing = SimpleNamespace(
        source_fingerprint="older-explicit-fingerprint",
        sha256="older-sha",
        storage_type="",
        storage_key="",
        source_url_hash=canonical_hash,
        raw_data={"archive_status": "archived", "archived_by": "reviewer-old"},
        category="unclassified",
        source_url=source_url,
        image_url=source_url,
        archive_status="archived",
        archive_filename="before_box.jpg",
        is_active=True,
    )
    untouched = SimpleNamespace(
        source_fingerprint="untouched-fingerprint",
        sha256="untouched-sha",
        storage_type="",
        storage_key="",
        source_url_hash=repository.hashlib.sha256(b"https://photos.example/untouched.jpg").hexdigest(),
        raw_data={"archive_status": "archived", "archived_by": "reviewer-old"},
        category="collector_barcode",
        source_url="https://photos.example/untouched.jpg",
        image_url="https://photos.example/untouched.jpg",
        archive_status="archived",
        archive_filename="collector_barcode.jpg",
        archived_at=datetime(2026, 7, 12, 9, 0),
        classified_by="reviewer-old",
        classified_at=datetime(2026, 7, 12, 8, 0),
        is_active=True,
    )
    group = SimpleNamespace(
        id="group-uuid",
        legacy_id="g-reviewed-duplicate",
        team_id="default-team",
        display_meter_no="120000912473",
        photo_count=4,
        status=repository.GroupStatus.APPROVED,
        reviewer="reviewer-old",
        reviewed_by_id="reviewer-uuid",
        review_note="approved",
        exception_status="open",
        exception_note="stale exception",
        exception_reasons=["stale exception"],
        has_archive_blocker=True,
        reviewed_at=datetime(2026, 7, 12, 9, 0),
        raw_data={
            "status": "approved",
            "reviewer": "reviewer-old",
            "reviewed_at": "2026-07-12T09:00:00+00:00",
            "exception_note": "stale exception",
            "exception_reasons": ["stale exception"],
        },
    )

    class DuplicateSession:
        def __init__(self):
            self.flush_calls = 0

        def scalars(self, statement):
            return FinalizeFakeScalars([existing, untouched])

        def scalar(self, statement):
            return 4

        def add(self, value):
            raise AssertionError("duplicate evidence must update the existing photo")

        def flush(self):
            self.flush_calls += 1

    result = repository.PostgresStateRepository()._add_photo_records_to_group(
        DuplicateSession(),
        group,
        actor="admin-a",
        photos=[
            {
                "url": source_url,
                "source_url": source_url,
                "source_fingerprint": "temporary-review-photo-id",
                "category": "before_box",
                "qr_values": ["QR-UPDATED"],
            }
        ],
        source="unmatched-review-finalize",
    )

    assert result == {"added": 0, "skipped_duplicates": 1, "merged_duplicates": 1}
    assert repository._legacy_group_status(group) == "pending"
    assert group.reviewer is None
    assert group.reviewed_by_id is None
    assert group.review_note == ""
    assert group.reviewed_at is None
    assert group.exception_status is None
    assert group.exception_note == ""
    assert group.exception_reasons == []
    assert group.has_archive_blocker is False
    assert existing.archive_status != "archived"
    assert existing.archive_filename == ""
    assert existing.raw_data["qr_values"] == ["QR-UPDATED"]
    assert existing.category == "before_box"
    assert untouched.category == "collector_barcode"
    assert untouched.archive_status != "archived"
    assert untouched.archive_filename == ""
    assert untouched.archived_at is None
    assert untouched.classified_by == ""
    assert untouched.classified_at is None


def test_postgres_unmatched_review_reactivates_soft_deleted_duplicate_photo() -> None:
    source_url = "https://photos.example/soft-deleted.jpg?token=old"
    canonical_hash = repository.hashlib.sha256(
        source_url.split("?", 1)[0].encode("utf-8")
    ).hexdigest()
    deleted_at = datetime(2026, 7, 12, 9, 0)
    existing = SimpleNamespace(
        source_fingerprint="older-explicit-fingerprint",
        sha256="older-sha",
        storage_type="",
        storage_key="",
        source_url_hash=canonical_hash,
        raw_data={"delete_reason": "temporary duplicate"},
        category="unclassified",
        source_url=source_url,
        image_url=source_url,
        is_active=False,
        deleted_at=deleted_at,
        deleted_by="reviewer-old",
        delete_reason="temporary duplicate",
        sort_order=7,
    )
    group = SimpleNamespace(
        id="group-uuid",
        legacy_id="g-soft-deleted",
        team_id="default-team",
        display_meter_no="120000912473",
        photo_count=0,
        status=repository.GroupStatus.INCOMPLETE,
        reviewer=None,
        review_note="",
        exception_status="",
        exception_note="",
        exception_reasons=[],
        has_archive_blocker=False,
        reviewed_at=None,
        raw_data={"photo_count": 0, "status": "incomplete"},
    )

    class SoftDeletedSession:
        def __init__(self):
            self.statements = []
            self.flush_calls = 0

        def scalars(self, statement):
            self.statements.append(statement)
            return FinalizeFakeScalars([existing])

        def scalar(self, statement):
            self.statements.append(statement)
            return 0

        def add(self, value):
            raise AssertionError("soft-deleted duplicate must be reactivated, not recreated")

        def flush(self):
            self.flush_calls += 1

    session = SoftDeletedSession()
    result = repository.PostgresStateRepository()._add_photo_records_to_group(
        session,
        group,
        actor="admin-a",
        photos=[
            {
                "url": source_url,
                "source_url": source_url,
                "source_fingerprint": "temporary-review-photo-id",
                "category": "before_box",
                "qr_values": ["QR-REACTIVATED"],
                "temporary_review_manual_confirmed": True,
            }
        ],
        source="unmatched-review-finalize",
    )

    compiled = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in compiled
    assert result == {
        "added": 0,
        "skipped_duplicates": 1,
        "merged_duplicates": 1,
        "reactivated_duplicates": 1,
    }
    assert existing.is_active is True
    assert existing.deleted_at is None
    assert existing.deleted_by == ""
    assert existing.delete_reason == ""
    assert existing.sort_order == 1
    assert existing.category == "before_box"
    assert existing.raw_data["qr_values"] == ["QR-REACTIVATED"]
    assert group.photo_count == 1
    assert group.raw_data["photo_count"] == 1
    assert session.flush_calls >= 1


def test_postgres_unmatched_review_prefers_active_duplicate_over_inactive_equivalent() -> None:
    source_url = "https://photos.example/shared-identity.jpg?token=current"
    canonical_hash = repository.hashlib.sha256(
        source_url.split("?", 1)[0].encode("utf-8")
    ).hexdigest()
    active = SimpleNamespace(
        source_fingerprint="active-fingerprint",
        sha256="active-sha",
        storage_type="",
        storage_key="",
        source_url_hash=canonical_hash,
        raw_data={},
        category="unclassified",
        source_url=source_url,
        image_url=source_url,
        is_active=True,
        deleted_at=None,
        deleted_by="",
        delete_reason="",
        sort_order=1,
    )
    inactive = SimpleNamespace(
        source_fingerprint="inactive-fingerprint",
        sha256="inactive-sha",
        storage_type="",
        storage_key="",
        source_url_hash=canonical_hash,
        raw_data={"delete_reason": "older duplicate"},
        category="unclassified",
        source_url=source_url,
        image_url=source_url,
        is_active=False,
        deleted_at=datetime(2026, 7, 12, 9, 0),
        deleted_by="reviewer-old",
        delete_reason="older duplicate",
        sort_order=2,
    )
    group = SimpleNamespace(
        id="group-uuid",
        legacy_id="g-active-preferred",
        team_id="default-team",
        display_meter_no="120000912473",
        photo_count=1,
        status=repository.GroupStatus.INCOMPLETE,
        reviewer=None,
        review_note="",
        exception_status="",
        exception_note="",
        exception_reasons=[],
        has_archive_blocker=False,
        reviewed_at=None,
        raw_data={"photo_count": 1, "status": "incomplete"},
    )

    class ActivePreferredSession:
        def __init__(self):
            self.flush_calls = 0

        def scalars(self, statement):
            return FinalizeFakeScalars([active, inactive])

        def scalar(self, statement):
            return 1

        def add(self, value):
            raise AssertionError("existing active duplicate must be reused")

        def flush(self):
            self.flush_calls += 1

    result = repository.PostgresStateRepository()._add_photo_records_to_group(
        ActivePreferredSession(),
        group,
        actor="admin-a",
        photos=[
            {
                "url": source_url,
                "source_url": source_url,
                "source_fingerprint": "incoming-fingerprint",
                "category": "before_box",
                "qr_values": ["QR-ACTIVE"],
                "temporary_review_manual_confirmed": True,
            }
        ],
        source="unmatched-review-finalize",
    )

    assert result == {"added": 0, "skipped_duplicates": 1, "merged_duplicates": 1}
    assert active.category == "before_box"
    assert active.raw_data["qr_values"] == ["QR-ACTIVE"]
    assert inactive.is_active is False
    assert inactive.deleted_at == datetime(2026, 7, 12, 9, 0)
    assert inactive.raw_data == {"delete_reason": "older duplicate"}
    assert group.photo_count == 1


def test_postgres_finalize_unmatched_rolls_back_after_all_writes_are_staged() -> None:
    record = _postgres_finalize_record()
    before = deepcopy(vars(record))
    fake_session = FinalizeFakeSession(record, fail_commit=True)
    formal_photo = SimpleNamespace(kind="formal-photo")

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return fake_session

        def _resolve_unmatched_candidate(self, session, locked_record, review, candidate_key):
            return {
                "candidate_key": candidate_key,
                "target_group_id": "",
                "terminal": "T-FINAL",
                "meter_no": "120000912473",
                "meter_match_key": "0000912473",
                "address": "match road",
            }

        def _materialize_unmatched_candidate(self, session, locked_record, review, candidate, actor):
            group = _postgres_finalize_group()
            session.add(group)
            session.add(formal_photo)
            return group, False

    with pytest.raises(RuntimeError, match="late PostgreSQL commit failure"):
        TestPostgresRepository().finalize_unmatched_match(
            record.legacy_id,
            actor="admin-a",
            candidate_key="catalog:catalog-1:T-FINAL",
            expected_version=1,
        )

    assert fake_session.commit_attempts == 1
    assert fake_session.commit_calls == 0
    assert fake_session.rollback_calls == 1
    assert fake_session.staged == []
    assert any(item is formal_photo for item in fake_session.rolled_back_staged)
    assert any(isinstance(item, repository.AuditLog) for item in fake_session.rolled_back_staged)
    assert vars(record) == before


def test_postgres_finalize_unmatched_checks_version_before_candidate_or_formal_mutation() -> None:
    record = _postgres_finalize_record(version=2)
    fake_session = FinalizeFakeSession(record)
    calls = {"resolve": 0, "materialize": 0}

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return fake_session

        def _resolve_unmatched_candidate(self, session, locked_record, review, candidate_key):
            calls["resolve"] += 1
            return {}

        def _materialize_unmatched_candidate(self, session, locked_record, review, candidate, actor):
            calls["materialize"] += 1
            return _postgres_finalize_group(), False

    with pytest.raises(repository.unmatched_review.ReviewVersionConflict):
        TestPostgresRepository().finalize_unmatched_match(
            record.legacy_id,
            actor="admin-a",
            candidate_key="catalog:catalog-1:T-FINAL",
            expected_version=1,
        )

    assert calls == {"resolve": 0, "materialize": 0}
    assert fake_session.commit_calls == 0
    assert fake_session.rollback_calls == 1
    assert fake_session.staged == []


def test_dual_backend_finalize_unmatched_match_fails_before_json_or_postgres_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    class MirrorRepository:
        def finalize_unmatched_match(self, *args, **kwargs):
            calls.append((args, kwargs))

    monkeypatch.setattr(repository.DualWriteStateRepository, "postgres_repository_factory", MirrorRepository)
    monkeypatch.setattr(
        repository.local_simulation,
        "finalize_unmatched_match",
        lambda unmatched_id, **kwargs: calls.append((unmatched_id, kwargs)),
        raising=False,
    )

    with pytest.raises(repository.StateBackendNotReady, match="before either backend mutated"):
        repository.DualWriteStateRepository().finalize_unmatched_match(
            "unmatched-finalize-1",
            actor="admin-a",
            candidate_key="catalog:catalog-1:T-FINAL",
            expected_version=3,
        )

    assert calls == []


def test_dual_backend_candidate_view_fails_before_json_or_postgres_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    class MirrorRepository:
        def list_unmatched_match_candidates(self, *args, **kwargs):
            calls.append((args, kwargs))
            raise RuntimeError("postgres audit unavailable")

    monkeypatch.setattr(repository.DualWriteStateRepository, "postgres_repository_factory", MirrorRepository)
    monkeypatch.setattr(
        repository.local_simulation,
        "list_unmatched_match_candidates",
        lambda unmatched_id, actor="": calls.append((unmatched_id, actor)),
    )

    with pytest.raises(repository.StateBackendNotReady, match="before either backend mutated"):
        repository.DualWriteStateRepository().list_unmatched_match_candidates(
            "unmatched-candidate-1",
            actor="reviewer-a",
        )

    assert calls == []


LEGACY_UNMATCHED_MUTATION_CASES = (
    ("update", "unmatched_record_updated"),
    ("assign", "unmatched_record_assigned"),
    ("unassign", "unmatched_record_unassigned"),
    ("outside", "unmatched_record_marked_outside_project"),
    ("associate", "unmatched_record_associated"),
    ("delete", "unmatched_record_deleted"),
)


def invoke_legacy_unmatched_mutation(repo, operation: str, *, expected_version: int) -> dict:
    common = {
        "unmatched_id": "unmatched-finalize-1",
        "actor": "admin-a",
        "expected_version": expected_version,
    }
    if operation == "update":
        return repo.update_unmatched_record(**common, updates={"note": "updated"})
    if operation == "assign":
        return repo.assign_unmatched_record(**common, constructor="constructor-a", note="assigned")
    if operation == "unassign":
        return repo.unassign_unmatched_record(**common, reason="released")
    if operation == "outside":
        return repo.mark_unmatched_outside_project(**common, note="outside")
    if operation == "associate":
        return repo.associate_unmatched_record(**common, target_group_id="g-finalized")
    if operation == "delete":
        return repo.delete_unmatched_record(**common, reason="invalid source")
    raise AssertionError(f"Unsupported test operation: {operation}")


@pytest.mark.parametrize(("operation", "expected_action"), LEGACY_UNMATCHED_MUTATION_CASES)
def test_postgres_legacy_unmatched_mutations_stage_transactional_audit(
    operation: str,
    expected_action: str,
) -> None:
    record = _postgres_finalize_record(terminal="T-LEGACY-ASSIGN" if operation == "assign" else "")
    group = _postgres_finalize_group()
    session = LegacyMutationSession(record, group)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

    invoke_legacy_unmatched_mutation(TestPostgresRepository(), operation, expected_version=1)

    audits = [item for item in session.persisted if isinstance(item, repository.AuditLog)]
    assert len(audits) == 1
    audit = audits[0]
    assert audit.actor_username == "admin-a"
    assert audit.action == expected_action
    assert audit.entity_type == "unmatched_record"
    assert audit.entity_id == record.id
    assert audit.payload["expected_version"] == 1
    assert audit.before_data["unmatched_id"] == record.legacy_id
    assert audit.after_data["unmatched_id"] == record.legacy_id
    assert audit.before_data["photo_urls"] == "[REDACTED]"
    assert session.commit_attempts == 1
    assert session.rollback_calls == 0


@pytest.mark.parametrize(("operation", "expected_action"), LEGACY_UNMATCHED_MUTATION_CASES)
def test_postgres_legacy_unmatched_stale_writes_add_no_audit(
    operation: str,
    expected_action: str,
) -> None:
    del expected_action
    record = _postgres_finalize_record(
        version=2,
        terminal="T-LEGACY-ASSIGN" if operation == "assign" else "",
    )
    group = _postgres_finalize_group()
    session = LegacyMutationSession(record, group)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

    with pytest.raises(repository.unmatched_review.ReviewVersionConflict):
        invoke_legacy_unmatched_mutation(TestPostgresRepository(), operation, expected_version=1)

    assert not any(isinstance(item, repository.AuditLog) for item in session.staged)
    assert not any(isinstance(item, repository.AuditLog) for item in session.persisted)
    assert session.commit_attempts == 0


@pytest.mark.parametrize(("operation", "expected_action"), LEGACY_UNMATCHED_MUTATION_CASES)
def test_postgres_legacy_unmatched_failed_writes_persist_no_audit(
    operation: str,
    expected_action: str,
) -> None:
    del expected_action
    record = _postgres_finalize_record(terminal="T-LEGACY-ASSIGN" if operation == "assign" else "")
    group = _postgres_finalize_group()
    session = LegacyMutationSession(record, group, fail_commit=True)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

    with pytest.raises(RuntimeError, match="legacy mutation commit failed"):
        invoke_legacy_unmatched_mutation(TestPostgresRepository(), operation, expected_version=1)

    assert not any(isinstance(item, repository.AuditLog) for item in session.persisted)
    assert session.staged == []
    assert session.commit_attempts == 1
    assert session.rollback_calls == 1
    assert record.status == "open"


def test_postgres_construction_activity_audit_redacts_nested_photo_secrets_before_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class AuditSession:
        def __init__(self) -> None:
            self.staged = []

        def add(self, value) -> None:
            self.staged.append(value)

    session = AuditSession()
    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: "default-team")

    repository.PostgresStateRepository()._add_construction_activity_audit(
        session,
        "construction_photo_uploaded",
        "constructor-a",
        {
            "group_id": "g-1",
            "nested": {
                "source_url": "https://photos.example/raw.jpg?token=secret",
                "storage": {
                    "storage_bucket": "private-bucket",
                    "storage_key": "private/photo.jpg",
                    "storageBucket": "private-camel-bucket",
                    "storageKey": "private/camel-photo.jpg",
                    "objectKey": "private/camel-object.jpg",
                    "ossKey": "private/camel-oss.jpg",
                },
                "signedUrl": "https://photos.example/camel-signed.jpg?token=secret",
                "rawUrl": "https://photos.example/camel-raw.jpg?token=secret",
                "presignedUrl": "https://photos.example/presigned.jpg?token=secret",
                "rawSignedUrl": "https://photos.example/raw-signed.jpg?token=secret",
                "bucketName": "private-provider-bucket",
                "storageObjectKey": "private/storage-object.jpg",
                "ossObjectKey": "private/oss-object.jpg",
                "presignedUri": "oss://private/presigned",
                "rawSignedURI": "oss://private/raw-signed",
                "signed-link": "https://photos.example/signed-link",
                "s3Key": "private/s3-object.jpg",
                "cos_object_name": "private/cos-object.jpg",
                "ossPath": "private/oss-path.jpg",
                "objectPath": "private/object-path.jpg",
            },
        },
    )

    assert len(session.staged) == 1
    audit = session.staged[0]
    assert audit.payload == {
        "group_id": "g-1",
        "nested": {
            "source_url": "[REDACTED]",
            "storage": {
                "storage_bucket": "[REDACTED]",
                "storage_key": "[REDACTED]",
                "storageBucket": "[REDACTED]",
                "storageKey": "[REDACTED]",
                "objectKey": "[REDACTED]",
                "ossKey": "[REDACTED]",
            },
            "signedUrl": "[REDACTED]",
            "rawUrl": "[REDACTED]",
            "presignedUrl": "[REDACTED]",
            "rawSignedUrl": "[REDACTED]",
            "bucketName": "[REDACTED]",
            "storageObjectKey": "[REDACTED]",
            "ossObjectKey": "[REDACTED]",
            "presignedUri": "[REDACTED]",
            "rawSignedURI": "[REDACTED]",
            "signed-link": "[REDACTED]",
            "s3Key": "[REDACTED]",
            "cos_object_name": "[REDACTED]",
            "ossPath": "[REDACTED]",
            "objectPath": "[REDACTED]",
        },
    }


def test_postgres_audit_response_recursively_redacts_provider_style_secret_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = SimpleNamespace(
        legacy_id="audit-round6",
        id=uuid4(),
        action="provider-audit",
        actor_username="admin-a",
        payload={
            "candidate_key": "catalog:row-1",
            "provider": {
                "presignedUrl": "https://photos.example/presigned.jpg?token=secret",
                "rawSignedUrl": "https://photos.example/raw-signed.jpg?token=secret",
                "image-source-url": "https://photos.example/source.jpg?token=secret",
                "bucket_name": "private-bucket",
                "storage-object-key": "private/storage.jpg",
                "oss_ObjectKey": "private/oss.jpg",
                "presignedUri": "oss://private/presigned",
                "rawSignedURI": "oss://private/raw-signed",
                "signed-link": "https://photos.example/signed-link",
                "s3Key": "private/s3-object.jpg",
                "cos_object_name": "private/cos-object.jpg",
                "ossPath": "private/oss-path.jpg",
                "objectPath": "private/object-path.jpg",
            },
        },
        after_data=None,
        created_at=datetime(2026, 7, 14, 12, 0, 0),
    )

    class AuditSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def scalar(self, statement):
            return 1

        def scalars(self, statement):
            return self

        def all(self):
            return [row]

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return AuditSession()

    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: "default-team")

    result = TestPostgresRepository().list_audit_events()

    provider = result["items"][0]["payload"]["provider"]
    assert result["items"][0]["payload"]["candidate_key"] == "[REDACTED]"
    assert set(provider.values()) == {"[REDACTED]"}


@pytest.mark.parametrize(
    ("operation", "value"),
    [
        (operation, value)
        for operation in ("terminal", "meter_no", "meter_match_key")
        for value in ("00000000", "未关联终端", "manual-placeholder", "unmatched-placeholder")
    ],
)
def test_postgres_formal_identity_updates_reject_placeholders_before_transaction(
    operation: str,
    value: str,
) -> None:
    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            pytest.fail("invalid formal identity must be rejected before a transaction starts")

    repo = TestPostgresRepository()
    with pytest.raises(ValueError, match="real (terminal|meter number|meter match key)"):
        if operation == "terminal":
            repo.update_group_terminal("g-1", terminal=value, actor="admin")
        else:
            repo.update_group_metadata("g-1", actor="admin", updates={operation: value})


def test_postgres_classify_photo_persists_archive_fields() -> None:
    photo = SimpleNamespace(
        id="photo-uuid",
        legacy_id="p-1",
        image_url="https://example.test/photo.jpg",
        source_url="",
        storage_type="external_url",
        storage_bucket="",
        storage_key="",
        sha256="a" * 64,
        category="unclassified",
        archive_filename="",
        archive_status="pending",
        archived_at=None,
        classified_by="",
        classified_at=None,
        sort_order=1,
        barcode="",
        collector="",
        asset_no="",
        creator="",
        raw_data={},
    )
    group = SimpleNamespace(
        id="group-uuid",
        team_id="alpha-team",
        task_id=None,
        legacy_id="g-1",
        legacy_task_id=1,
        raw_data={},
        status=repository.GroupStatus.UNREVIEWED,
        photo_count=1,
    )

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, _statement):
            return photo

        def commit(self):
            pass

        def refresh(self, _obj):
            pass

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return FakeSession()

        def _group_by_legacy_id(self, session, group_id: str, *, lock: bool = False):
            assert group_id == "g-1"
            return group

        def _ensure_task_claimed_by(self, session, checked_group, actor: str, *, force: bool = False) -> None:
            assert checked_group is group
            assert actor == "reviewer-a"

    result = TestPostgresRepository().classify_photo("g-1", "p-1", "after_box", "reviewer-a")

    assert result["category"] == "after_box"
    assert result["archive_status"] == "archived"
    assert result["archive_filename"]
    assert photo.archive_status == "archived"
    assert photo.archive_filename == result["archive_filename"]
    assert photo.archived_at is not None
    assert photo.raw_data["archive_status"] == "archived"
    assert photo.raw_data["category_label"] == repository.local_simulation.PHOTO_CATEGORIES["after_box"]


def test_postgres_reset_group_to_unconstructed_clears_barcode_evidence() -> None:
    group = SimpleNamespace(
        id="group-uuid",
        team_id="default-team",
        task_id=None,
        legacy_id="g-reset",
        legacy_task_id=1,
        display_meter_no="METER-RESET",
        meter_match_key="METER-RESET",
        terminal="TERM-RESET",
        installation_address="reset road",
        status=repository.GroupStatus.APPROVED,
        photo_count=1,
        reviewer="reviewer-a",
        reviewed_at=None,
        review_note="ok",
        exception_note="",
        exception_reasons=[],
        has_archive_blocker=False,
        exception_status=None,
        raw_data={
            "status": "approved",
            "collector": "COLLECTOR-OLD",
            "module_asset_no": "MODULE-OLD",
            "asset_no": "MODULE-OLD",
            "construction_collector": "COLLECTOR-OLD",
            "construction_module_asset_no": "MODULE-OLD",
            "group_barcode_manual_confirmed": True,
            "group_barcode_manual_confirmed_fields": ["meter", "module", "collector"],
            "group_barcode_manual_confirmed_by": "reviewer-a",
            "group_barcode_manual_confirmed_at": "2026-06-29T10:00:00+08:00",
        },
    )
    photos = [
        SimpleNamespace(
            id="photo-uuid",
            legacy_id="p-reset",
            group_id=group.id,
            team_id=group.team_id,
            is_active=True,
            deleted_at=None,
            deleted_by="",
            delete_reason="",
        )
    ]

    class FakeScalars:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return list(self._rows)

    class FakeSession:
        def __init__(self):
            self.audit_logs = []
            self.committed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalars(self, _statement):
            return FakeScalars([photo for photo in photos if photo.is_active])

        def get(self, _model, _key):
            return None

        def add(self, item):
            self.audit_logs.append(item)

        def commit(self):
            self.committed = True

        def refresh(self, _obj):
            pass

    fake_session = FakeSession()

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return fake_session

        def _group_by_legacy_id(self, session, group_id: str, *, lock: bool = False):
            assert group_id == "g-reset"
            assert lock is True
            return group

        def _ensure_task_claimed_by(self, session, checked_group, actor: str, *, force: bool = False) -> None:
            assert checked_group is group
            assert actor == "admin"
            assert force is True

    result = TestPostgresRepository().reset_group_to_unconstructed(
        "g-reset",
        actor="admin",
        reason="重新施工",
        force=True,
    )

    assert group.raw_data["collector"] == ""
    assert group.raw_data["module_asset_no"] == ""
    assert group.raw_data["asset_no"] == ""
    assert group.raw_data["construction_collector"] == ""
    assert group.raw_data["construction_module_asset_no"] == ""
    assert group.raw_data["group_barcode_manual_confirmed"] is False
    assert group.raw_data["group_barcode_manual_confirmed_fields"] == []
    assert group.raw_data["group_barcode_manual_confirmed_by"] == ""
    assert group.raw_data["group_barcode_manual_confirmed_at"] == ""
    assert photos[0].is_active is False
    assert result["group"]["photo_count"] == 0
    assert result["group"].get("collector", "") == ""
    assert result["group"].get("module_asset_no", "") == ""
    assert result["group"].get("construction_collector", "") == ""
    assert result["group"].get("construction_module_asset_no", "") == ""
    assert not result["group"].get("group_barcode_manual_confirmed", False)
    assert result["soft_deleted_photos"] == 1
    assert fake_session.committed is True
    assert fake_session.audit_logs


def test_postgres_installer_workload_uses_material_group_installation_address() -> None:
    photo = SimpleNamespace(
        id="photo-uuid",
        raw_data={"client_completed_at": "2026-06-08T09:30:00", "upload_source": "construction-mobile"},
        source="construction",
        created_at=datetime(2026, 6, 22, 8, 10),
        taken_at=None,
        sort_order=1,
        legacy_id="p-1",
    )
    group = SimpleNamespace(
        id="group-uuid",
        legacy_id="g-1",
        legacy_task_id=1,
        display_meter_no="110020000001",
        terminal="350000000001",
        installation_address="上海市测试区测试路1号101室",
        status=repository.GroupStatus.APPROVED,
        raw_data={},
        last_photo_imported_at=None,
        exception_status="",
        has_archive_blocker=False,
        exception_reasons=[],
        exception_note="",
        review_note="",
        photo_count=1,
    )

    class FakeResult:
        def all(self):
            return [(photo, group)]

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, _statement):
            return FakeResult()

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return FakeSession()

    workload = TestPostgresRepository().installer_daily_workload("installer-a")

    item = workload["items"][0]
    segment_addresses = [
        address
        for segment in item["two_hour_segments"]
        for address in segment["addresses"]
    ]
    assert item["date"] == "2026-06-08"
    assert item["start_time"] == "09:30"
    assert segment_addresses[0]["address"] == group.installation_address


def test_postgres_group_search_includes_raw_display_fields() -> None:
    captured: list[object] = []

    class FakeScalars:
        def __init__(self, items):
            self._items = items

        def all(self):
            return self._items

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, statement):
            captured.append(statement)
            return 0

        def scalars(self, statement):
            captured.append(statement)
            return FakeScalars([])

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return FakeSession()

    TestPostgresRepository().search_group_targets(query="安装人员A", terminal="", limit=5, offset=0)

    compiled = "\n".join(
        str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for statement in captured
    )
    assert "CAST(material_groups.raw_data AS VARCHAR) ILIKE" in compiled
    assert "tasks.construction_claimed_by ILIKE" in compiled
    assert "tasks.review_claimed_by ILIKE" not in compiled


def test_postgres_group_payload_does_not_treat_reviewer_as_installer() -> None:
    class FakeSession:
        def scalars(self, _statement):
            class Result:
                def all(self):
                    return []

            return Result()

        def get(self, model, key):
            assert model is repository.Task
            assert key == "task-uuid"
            return SimpleNamespace(construction_claimed_by="", review_claimed_by="reviewer-a")

    group = SimpleNamespace(
        id="group-uuid",
        legacy_id="g-1",
        legacy_task_id=124,
        task_id="task-uuid",
        meter_match_key="M-1",
        display_meter_no="METER-1",
        terminal="TERM-1",
        installation_address="addr",
        status=repository.GroupStatus.UNREVIEWED,
        photo_count=0,
        reviewer="",
        reviewed_at=None,
        review_note="",
        exception_note="",
        exception_reasons=[],
        has_archive_blocker=False,
        raw_data={},
        team_id="default-team",
    )

    payload = repository._group_payload(FakeSession(), group, include_photos=False)

    assert payload.get("installer", "") == ""


def test_postgres_task_stats_installer_distribution_trims_group_fields() -> None:
    captured = []

    class FakeResult:
        def all(self):
            return []

    class FakeSession:
        def execute(self, statement):
            captured.append(statement)
            return FakeResult()

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return FakeSession()

    TestPostgresRepository()._task_stats_map(FakeSession(), "default-team")

    compiled = "\n".join(
        str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).lower()
        for statement in captured
    )
    photo_installer_sql = str(
        captured[1].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    ).lower()
    assert "trim(material_groups.raw_data ->> 'installer')" in compiled
    assert "trim(material_groups.raw_data ->> 'constructor')" in compiled
    assert "trim(material_groups.raw_data ->> 'creator')" in compiled
    assert "trim(photos.creator)" in compiled
    assert "material_groups.photo_count > 0" not in photo_installer_sql


def test_installer_distribution_displays_account_name(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_user(username: str):
        if username == "xa":
            return {"username": "xa", "name": "樊哲浩"}
        return None

    monkeypatch.setattr(repository.account_store, "get_user", fake_get_user)

    assert repository._installer_distribution_from_counts(
        {"xa": 1, "樊哲浩": 2},
        completed_count=3,
    ) == [{"installer": "樊哲浩", "group_count": 3, "share": 1.0}]


def test_installer_distribution_reuses_shared_name_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_get_user(username: str):
        calls.append(username)
        return {"username": username, "name": "樊哲浩"} if username == "xa" else None

    monkeypatch.setattr(repository.account_store, "get_user", fake_get_user)
    name_cache: dict[str, str] = {}

    assert repository._installer_distribution_from_counts(
        {"xa": 1},
        completed_count=1,
        name_cache=name_cache,
    ) == [{"installer": "樊哲浩", "group_count": 1, "share": 1.0}]
    assert repository._installer_distribution_from_counts(
        {"xa": 2},
        completed_count=2,
        name_cache=name_cache,
    ) == [{"installer": "樊哲浩", "group_count": 2, "share": 1.0}]

    assert calls == ["xa"]


def test_postgres_quality_exception_marks_and_clears_missing_collector_photo() -> None:
    def photo(category: str):
        return SimpleNamespace(
            raw_data={"construction_slot": category, "upload_source": "construction-mobile"},
            category=category,
        )

    photos = [photo("before_box"), photo("module_meter"), photo("after_box")]
    group = SimpleNamespace(
        id="group-uuid",
        team_id="default-team",
        photo_count=3,
        status=repository.GroupStatus.UNREVIEWED,
        exception_status="",
        exception_note="",
        exception_reasons=[],
        has_archive_blocker=False,
        reviewer="reviewer",
        review_note="",
        reviewed_at=datetime(2026, 6, 8, 9, 30),
        raw_data={},
    )

    class FakeScalars:
        def __init__(self, items):
            self._items = items

        def all(self):
            return self._items

    class FakeSession:
        def scalars(self, _statement):
            return FakeScalars(photos)

    repository._apply_photo_quality_exception_status(FakeSession(), group)

    assert group.status == repository.GroupStatus.REJECTED
    assert group.exception_note == repository.local_simulation.MISSING_COLLECTOR_PHOTO_LABEL
    assert repository.local_simulation.MISSING_COLLECTOR_PHOTO_REASON in group.exception_reasons

    photos.append(photo("collector_barcode"))
    group.photo_count = 4
    repository._apply_photo_quality_exception_status(FakeSession(), group)

    assert group.status == repository.GroupStatus.UNREVIEWED
    assert group.exception_note == ""
    assert repository.local_simulation.MISSING_COLLECTOR_PHOTO_REASON not in group.exception_reasons


def test_postgres_exception_listing_revalidates_stale_missing_module_note() -> None:
    def photo(slot: str, asset_no: str = ""):
        return SimpleNamespace(
            id=f"photo-{slot}",
            legacy_id=f"p-{slot}",
            group_id="group-uuid",
            team_id="default-team",
            is_active=True,
            raw_data={"construction_slot": slot},
            category=slot,
            asset_no=asset_no,
            image_url="https://example.test/photo.jpg",
            source_url="",
            storage_type="",
            storage_key="",
            storage_bucket="",
            sha256="",
            archive_filename="",
            archive_status="",
            sort_order=1,
            created_at=datetime(2026, 6, 8, 9, 30),
            barcode="",
            collector="collector-a",
            creator="installer-a",
        )

    group = SimpleNamespace(
        id="group-uuid",
        legacy_id="g-stale-module",
        legacy_task_id=1,
        task_id=None,
        team_id="default-team",
        display_meter_no="110020000001",
        meter_match_key="110020000001",
        terminal="350000000001",
        installation_address="addr",
        status=repository.GroupStatus.REJECTED,
        raw_data={
            "status": "exception",
            "construction_module_asset_no": "MOD-001",
            "exception_note": "\u7f3a\u5c11\u6a21\u5757\u8d44\u4ea7\u7f16\u53f7",
            "exception_reasons": [],
        },
        last_photo_imported_at=None,
        exception_status=None,
        has_archive_blocker=False,
        exception_reasons=[],
        exception_note="\u7f3a\u5c11\u6a21\u5757\u8d44\u4ea7\u7f16\u53f7",
        review_note="",
        reviewer="",
        reviewed_at=None,
        photo_count=4,
        updated_at=None,
    )
    photos = [
        photo("before_box"),
        photo("module_meter", "MOD-001"),
        photo("after_box"),
        photo("collector_barcode"),
    ]

    class FakeScalars:
        def __init__(self, items):
            self._items = items

        def all(self):
            return self._items

    class FakeSession:
        def __init__(self):
            self.committed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def _matches_exception_statement(self):
            return (
                group.photo_count > 0
                and (
                    group.status in {repository.GroupStatus.INCOMPLETE, repository.GroupStatus.REJECTED}
                    or group.has_archive_blocker
                    or group.exception_status == "open"
                )
            )

        def scalar(self, _statement):
            return 1 if self._matches_exception_statement() else 0

        def scalars(self, statement):
            text = str(statement)
            if "FROM material_groups" in text:
                if (
                    "material_groups.status IN" in text
                    or "material_groups.has_archive_blocker" in text
                    or "material_groups.exception_status" in text
                ):
                    return FakeScalars([group] if self._matches_exception_statement() else [])
                return FakeScalars([group])
            if "FROM photos" in text:
                return FakeScalars(photos)
            return FakeScalars([])

        def get(self, _model, _key):
            return None

        def commit(self):
            self.committed = True

    fake_session = FakeSession()

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return fake_session

    result = TestPostgresRepository().list_exception_groups(limit=100, offset=0)

    assert result["total"] == 0
    assert result["items"] == []
    assert group.exception_note == ""
    assert group.raw_data["exception_note"] == ""
    assert group.status == repository.GroupStatus.UNREVIEWED
    assert fake_session.committed is True


def test_postgres_exception_listing_preserves_manual_exception_note() -> None:
    def photo(slot: str, asset_no: str = ""):
        return SimpleNamespace(
            id=f"photo-{slot}",
            legacy_id=f"p-{slot}",
            group_id="group-uuid",
            team_id="default-team",
            is_active=True,
            raw_data={"construction_slot": slot},
            category=slot,
            asset_no=asset_no,
            image_url="https://example.test/photo.jpg",
            source_url="",
            storage_type="",
            storage_key="",
            storage_bucket="",
            sha256="",
            archive_filename="",
            archive_status="",
            sort_order=1,
            created_at=datetime(2026, 6, 8, 9, 30),
            barcode="",
            collector="collector-a",
            creator="installer-a",
        )

    group = SimpleNamespace(
        id="group-uuid",
        legacy_id="g-manual-module",
        legacy_task_id=1,
        task_id=None,
        team_id="default-team",
        display_meter_no="110020000002",
        meter_match_key="110020000002",
        terminal="350000000001",
        installation_address="addr",
        status=repository.GroupStatus.REJECTED,
        raw_data={
            "status": "exception",
            "construction_module_asset_no": "MOD-002",
            "exception_note": "\u7f3a\u5c11\u6a21\u5757\u8d44\u4ea7\u7f16\u53f7",
            "exception_category": "manual_quality",
        },
        last_photo_imported_at=None,
        exception_status=None,
        has_archive_blocker=True,
        exception_reasons=["manual_quality", "\u7f3a\u5c11\u6a21\u5757\u8d44\u4ea7\u7f16\u53f7"],
        exception_note="\u7f3a\u5c11\u6a21\u5757\u8d44\u4ea7\u7f16\u53f7",
        review_note="",
        reviewer="reviewer-a",
        reviewed_at=None,
        photo_count=4,
        updated_at=None,
    )
    photos = [
        photo("before_box"),
        photo("module_meter", "MOD-002"),
        photo("after_box"),
        photo("collector_barcode"),
    ]

    class FakeScalars:
        def __init__(self, items):
            self._items = items

        def all(self):
            return self._items

    class FakeSession:
        def __init__(self):
            self.committed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, _statement):
            return 1

        def scalars(self, statement):
            text = str(statement)
            if "FROM material_groups" in text:
                return FakeScalars([group])
            if "FROM photos" in text:
                return FakeScalars(photos)
            return FakeScalars([])

        def get(self, _model, _key):
            return None

        def commit(self):
            self.committed = True

    fake_session = FakeSession()

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return fake_session

    result = TestPostgresRepository().list_exception_groups(limit=100, offset=0)

    assert result["total"] == 1
    assert result["items"][0]["id"] == "g-manual-module"
    assert group.exception_note == "\u7f3a\u5c11\u6a21\u5757\u8d44\u4ea7\u7f16\u53f7"
    assert group.exception_reasons == ["manual_quality", "\u7f3a\u5c11\u6a21\u5757\u8d44\u4ea7\u7f16\u53f7"]
    assert group.status == repository.GroupStatus.REJECTED
    assert group.has_archive_blocker is True
    assert fake_session.committed is False


def test_postgres_photo_accuracy_summary_counts_raw_photo_metadata() -> None:
    photos = [
        SimpleNamespace(raw_data={"barcode_check_status": "matched"}),
        SimpleNamespace(raw_data={"barcode_check_status": "mismatched"}),
        SimpleNamespace(raw_data={"barcode_check_status": "unreadable"}),
        SimpleNamespace(raw_data={"barcode_check_status": "not_required"}),
        SimpleNamespace(raw_data={}),
    ]

    assert repository._photo_accuracy_summary(photos) == {
        "photo_accuracy_checked": 3,
        "photo_accuracy_passed": 1,
        "photo_accuracy_failed": 1,
        "photo_accuracy_unreadable": 1,
        "photo_accuracy_not_required": 1,
        "photo_accuracy_rate": 0.3333,
    }


def test_postgres_summary_photo_accuracy_filters_to_grouped_photos(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_execute = []

    class FakeOneResult:
        def one(self):
            return SimpleNamespace(
                groups=0,
                photo_rows_linked=0,
                scanned_groups=0,
                approved_groups=0,
                reviewed_groups=0,
                unreviewed_groups=0,
                exception_groups=0,
                incomplete_groups=0,
                unconstructed_groups=0,
            )

    class FakeAllResult:
        def all(self):
            return []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, _statement):
            return 0

        def execute(self, statement):
            captured_execute.append(statement)
            if not hasattr(self, "_executed_group_stats"):
                self._executed_group_stats = True
                return FakeOneResult()
            return FakeAllResult()

        def scalars(self, statement):
            raise AssertionError("summary should aggregate photo accuracy without loading Photo ORM rows")

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return FakeSession()

    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: "alpha-team")

    TestPostgresRepository().summary()

    assert captured_execute
    compiled_statements = [
        str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for statement in captured_execute
    ]
    compiled = next(statement for statement in compiled_statements if "barcode_check_status" in statement)
    assert "photos.group_id IS NOT NULL" in compiled


def test_postgres_summary_uses_lightweight_barcode_accuracy_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_execute: list[object] = []

    class FakeOneResult:
        def one(self):
            return SimpleNamespace(
                groups=2,
                photo_rows_linked=4,
                scanned_groups=1,
                approved_groups=0,
                reviewed_groups=0,
                unreviewed_groups=1,
                exception_groups=0,
                incomplete_groups=0,
                unconstructed_groups=1,
            )

    class FakeAllResult:
        def __init__(self, rows=None):
            self._rows = rows or []

        def all(self):
            return self._rows

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, _statement):
            return 10

        def execute(self, statement):
            captured_execute.append(statement)
            index = len(captured_execute)
            if index == 1:
                return FakeOneResult()
            return FakeAllResult([])

        def scalars(self, _statement):
            raise AssertionError("summary must not load full ORM rows for barcode accuracy")

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return FakeSession()

    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: "alpha-team")

    result = TestPostgresRepository().summary()["summary"]

    assert result["photo_accuracy_checked"] == 0
    assert result["group_barcode_accuracy_not_required"] == 2
    compiled = "\n".join(
        str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for statement in captured_execute
    )
    assert "photos.raw_data ->> 'barcode_check_status'" in compiled
    assert "count(photos.id)" in compiled.lower()


def test_group_barcode_accuracy_summary_skips_payload_build_for_incomplete_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_build_group_barcode_check(group: dict) -> dict:
        calls.append(str(group.get("id")))
        return {"group_barcode_check_status": "matched"}

    monkeypatch.setattr(repository.photo_barcode_check, "build_group_barcode_check", fake_build_group_barcode_check)
    groups = [
        {"id": "complete", "photos": [{"barcode_check_status": "matched"} for _ in range(4)]},
        {"id": "incomplete", "photos": [{"barcode_check_status": "matched"} for _ in range(3)]},
    ]

    assert repository._group_barcode_accuracy_summary(groups, {}) == {
        "group_barcode_accuracy_checked": 1,
        "group_barcode_accuracy_passed": 1,
        "group_barcode_accuracy_failed": 0,
        "group_barcode_accuracy_unreadable": 0,
        "group_barcode_accuracy_not_required": 1,
        "group_barcode_accuracy_rate": 1.0,
    }
    assert calls == ["complete"]


def test_postgres_list_tasks_board_view_omits_large_search_text() -> None:
    task = SimpleNamespace(
        id="task-uuid",
        legacy_id=7,
        terminal="T-007",
        title="终端 T-007",
        status=repository.TaskStatus.PUBLISHED,
        review_claimed_by="",
        claimed_at=None,
        released_at=None,
        construction_enabled=True,
        construction_claimed_by="installer-a",
        construction_claimed_at=None,
    )

    class FakeScalars:
        def all(self):
            return [task]

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalars(self, _statement):
            return FakeScalars()

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return FakeSession()

        def _task_stats_map(
            self,
            session,
            team_id: str,
            *,
            include_search_text: bool = True,
            include_installer_distribution: bool = True,
        ):
            assert include_search_text is False
            assert include_installer_distribution is True
            return {
                7: {
                    "total_groups": 4,
                    "address": "上海市测试路1号",
                    "address_search_text": "这段很长不应进入驾驶舱首屏",
                    "meter_search_text": "METER-001 METER-002",
                    "uploaded_count": 3,
                    "reviewed_count": 2,
                    "unreviewed_count": 1,
                    "installer_distribution": [{"installer": "张三", "group_count": 3, "share": 1.0}],
                }
            }

    rows = TestPostgresRepository().list_tasks(summary_only=True)

    assert rows[0]["terminal"] == "T-007"
    assert rows[0]["address"] == "上海市测试路1号"
    assert rows[0]["address_search_text"] == ""
    assert rows[0]["meter_search_text"] == ""
    assert rows[0]["installer_distribution"][0]["installer"] == "张三"


def test_postgres_list_tasks_can_skip_installer_distribution() -> None:
    task = SimpleNamespace(
        id="task-uuid",
        legacy_id=7,
        terminal="T-007",
        title="终端 T-007",
        status=repository.TaskStatus.PUBLISHED,
        review_claimed_by="",
        claimed_at=None,
        released_at=None,
        construction_enabled=True,
        construction_claimed_by="",
        construction_claimed_at=None,
    )
    calls: list[dict] = []

    class FakeScalars:
        def all(self):
            return [task]

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalars(self, _statement):
            return FakeScalars()

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return FakeSession()

        def _task_stats_map(self, _session, _team_id: str, **kwargs):
            calls.append(kwargs)
            return {}

    TestPostgresRepository().list_tasks(include_installer_distribution=False)

    assert calls == [{"include_search_text": True, "include_installer_distribution": False}]


def test_postgres_review_queue_limits_before_payload_build(monkeypatch: pytest.MonkeyPatch) -> None:
    groups = [SimpleNamespace(id=f"model-{index}", legacy_id=f"group-{index}") for index in range(45)]
    built: list[str] = []

    class AggregateResult:
        def one(self):
            return SimpleNamespace(
                all_count=45,
                reviewable_count=45,
                exception_count=0,
                archived_count=0,
                unconstructed_count=0,
            )

    class PhotoResult:
        def all(self):
            return []

    class PageScalars:
        def all(self):
            return groups[:20]

    class FakeSession:
        def __init__(self) -> None:
            self.execute_calls = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, _statement):
            self.execute_calls += 1
            return AggregateResult() if self.execute_calls == 1 else PhotoResult()

        def scalars(self, _statement):
            return PageScalars()

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return FakeSession()

        def _task_by_legacy_id(self, _session, _task_id):
            return SimpleNamespace(id="task-model")

    def minimal_group(_session, group, include_photos=False):
        assert include_photos is False
        built.append(str(group.id))
        return {
            "id": group.legacy_id,
            "task_id": 1,
            "meter_no": "10000001",
            "status": "pending",
            "photo_count": 4,
            "photos": [],
        }

    monkeypatch.setattr(repository, "_group_payload", minimal_group)

    result = TestPostgresRepository().list_review_task_groups(1, limit=20, offset=0)

    assert len(result["items"]) == 20
    assert len(built) == 20


def test_json_state_repository_delegates_review_risk_operations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repository.settings, "state_backend", "json")
    monkeypatch.setattr(
        repository.local_simulation,
        "delete_group_photo",
        lambda group_id, photo_id, reviewer: {"group_id": group_id, "photo_id": photo_id, "reviewer": reviewer},
    )
    monkeypatch.setattr(
        repository.local_simulation,
        "reset_group_to_unconstructed",
        lambda group_id, actor, reason="", force=False: {
            "group_id": group_id,
            "actor": actor,
            "reason": reason,
            "force": force,
        },
    )
    monkeypatch.setattr(
        repository.local_simulation,
        "return_group_to_exception_order",
        lambda group_id, actor, category, note, force=False: {
            "group_id": group_id,
            "actor": actor,
            "category": category,
            "note": note,
            "force": force,
        },
    )

    repo = repository.get_state_repository()

    assert repo.delete_photo("g-1", "p-1", "reviewer-a") == {
        "group_id": "g-1",
        "photo_id": "p-1",
        "reviewer": "reviewer-a",
    }
    assert repo.reset_group_to_unconstructed("g-1", actor="reviewer-a", reason="wrong site", force=True) == {
        "group_id": "g-1",
        "actor": "reviewer-a",
        "reason": "wrong site",
        "force": True,
    }
    assert repo.return_group_to_exception_order("g-1", actor="reviewer-a", category="照片错误", note="补拍") == {
        "group_id": "g-1",
        "actor": "reviewer-a",
        "category": "照片错误",
        "note": "补拍",
        "force": False,
    }


def test_unknown_state_backend_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repository.settings, "state_backend", "unsafe-mode")

    with pytest.raises(repository.StateBackendNotReady):
        repository.get_state_repository()
