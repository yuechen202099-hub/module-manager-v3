from __future__ import annotations

import logging
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.services import state_repository as repository


def test_json_state_repository_delegates_core_task_operations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repository.settings, "state_backend", "json")
    monkeypatch.setattr(repository.local_simulation, "get_state", lambda: {"summary": {"groups": 2}, "paths": {}})
    monkeypatch.setattr(repository.local_simulation, "list_tasks", lambda: [{"id": 7, "terminal": "T-007"}])
    monkeypatch.setattr(
        repository.local_simulation,
        "list_unmatched_records",
        lambda query="", limit=100, offset=0: {"total": 1, "items": [{"unmatched_id": "u-1"}]},
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
    monkeypatch.setattr(repository.settings, "state_backend", "dual")
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
    group = SimpleNamespace(id="group-uuid", team_id="alpha-team", task_id=None, legacy_task_id=1)

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
    captured_scalars = []

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

    class FakeScalars:
        def __init__(self, statement):
            captured_scalars.append(statement)

        def all(self):
            return []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, _statement):
            return 0

        def execute(self, _statement):
            if not hasattr(self, "_executed_group_stats"):
                self._executed_group_stats = True
                return FakeOneResult()
            return FakeAllResult()

        def scalars(self, statement):
            return FakeScalars(statement)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return FakeSession()

    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: "alpha-team")

    TestPostgresRepository().summary()

    assert captured_scalars
    compiled = str(captured_scalars[-1].compile(dialect=postgresql.dialect()))
    assert "photos.group_id IS NOT NULL" in compiled


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
