from __future__ import annotations

import importlib.util
import inspect
import json
import hashlib
import sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[2]
API_ROOT = ROOT / "v2-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services import state_repository as state_repository_module

SCRIPT_PATH = Path(__file__).with_name("production_v3081_reconcile.py")
SPEC = importlib.util.spec_from_file_location("production_v3081_reconcile", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
reconcile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reconcile)


class FakeRepository:
    def __init__(self, bind, candidates: list[dict[str, object]]) -> None:
        self.bind = bind
        self.candidates = candidates

    def _session(self) -> Session:
        return Session(bind=self.bind)

    def _unmatched_match_candidates_for_session(self, session, record, review):
        return list(self.candidates)

    def _resolve_unmatched_candidate(self, session, record, review, candidate_key):
        return next(item for item in self.candidates if item["candidate_key"] == candidate_key)

    def finalize_unmatched_match(self, candidate_key: str) -> dict[str, object]:
        with self._session() as session:
            candidate = self._resolve_unmatched_candidate(session, object(), {}, candidate_key)
            session.execute(text("INSERT INTO writes(value) VALUES ('committed-inside-repository')"))
            session.commit()
            return {
                "attached": bool(candidate["has_existing_group"]),
                "group": {"id": candidate["target_group_id"]},
            }


def sqlite_fixture():
    bind = create_engine("sqlite+pysqlite:///:memory:")
    with bind.begin() as connection:
        connection.execute(text("CREATE TABLE writes(value TEXT NOT NULL)"))
    return bind


def candidate(target: str = "g-12102") -> dict[str, object]:
    return {
        "candidate_key": "candidate:expected",
        "target_group_id": target,
        "has_existing_group": True,
        "terminal": "350000135073",
    }


def committed_rows(bind) -> int:
    with bind.connect() as connection:
        return int(connection.scalar(text("SELECT count(*) FROM writes")) or 0)


def test_repository_commit_guard_rolls_back_repository_commit_when_verification_fails() -> None:
    bind = sqlite_fixture()
    repository = FakeRepository(bind, [candidate()])

    with pytest.raises(RuntimeError, match="verification failed"):
        with reconcile.repository_commit_guard(repository, bind=bind) as connection:
            repository.finalize_unmatched_match("candidate:expected")
            assert connection.scalar(text("SELECT count(*) FROM writes")) == 1
            raise RuntimeError("verification failed")

    assert committed_rows(bind) == 0


def test_repository_commit_guard_persists_only_after_verification_succeeds() -> None:
    bind = sqlite_fixture()
    repository = FakeRepository(bind, [candidate()])

    with reconcile.repository_commit_guard(repository, bind=bind) as connection:
        result = repository.finalize_unmatched_match("candidate:expected")
        assert result["group"]["id"] == "g-12102"
        assert connection.scalar(text("SELECT count(*) FROM writes")) == 1
        verification_session = Session(
            bind=connection,
            join_transaction_mode="rollback_only",
        )
        assert verification_session.scalar(text("SELECT count(*) FROM writes")) == 1
        verification_session.close()
        assert connection.in_transaction()

    assert committed_rows(bind) == 1
    assert "_session" not in repository.__dict__


@pytest.mark.parametrize(
    "candidates, message",
    [
        ([candidate(), {**candidate("g-12164"), "candidate_key": "candidate:other"}], "candidate count"),
        ([candidate("g-99999")], "candidate target changed"),
        ([{**candidate(), "has_existing_group": False}], "candidate has no existing group"),
    ],
)
def test_strict_candidate_resolution_rejects_unsafe_transaction_candidates(candidates, message) -> None:
    bind = sqlite_fixture()
    repository = FakeRepository(bind, candidates)

    with pytest.raises(RuntimeError, match=message):
        with reconcile.repository_commit_guard(repository, bind=bind):
            with reconcile.strict_candidate_resolution(
                repository,
                expected_candidate_key="candidate:expected",
                expected_target_group_id="g-12102",
            ):
                repository.finalize_unmatched_match("candidate:expected")

    assert committed_rows(bind) == 0
    assert "_resolve_unmatched_candidate" not in repository.__dict__


def test_collect_migrated_photo_ids_accepts_direct_and_merged_evidence() -> None:
    photos = [
        SimpleNamespace(source_fingerprint="direct-photo", raw_data={}),
        SimpleNamespace(source_fingerprint="existing-photo", raw_data={"source_fingerprint": "merged-photo"}),
    ]

    assert reconcile.collect_migrated_photo_ids(photos) == {
        "direct-photo",
        "existing-photo",
        "merged-photo",
    }


def test_deduplicated_photo_can_satisfy_multiple_review_entries_with_same_source() -> None:
    evidence = reconcile.build_review_photo_evidence(
        [
            {"id": "review-a", "source_url": "https://example.test/photo.jpg?signature=one"},
            {"id": "review-b", "source_url": "https://example.test/photo.jpg?signature=two"},
        ]
    )
    active_photos = [
        SimpleNamespace(
            source_fingerprint="stored-photo",
            raw_data={},
            sha256="",
            storage_type="",
            storage_key="",
            source_url_hash=evidence[0]["source_url_hash"],
        )
    ]

    assert reconcile.matched_review_photo_ids(active_photos, evidence) == {
        "review-a",
        "review-b",
    }
    assert reconcile.unique_review_photo_source_count(evidence) == 1


def test_photo_evidence_reports_an_unmigrated_distinct_source() -> None:
    evidence = reconcile.build_review_photo_evidence(
        [
            {"id": "review-a", "source_url": "https://example.test/a.jpg"},
            {"id": "review-b", "source_url": "https://example.test/b.jpg"},
        ]
    )
    active_photos = [
        SimpleNamespace(
            source_fingerprint="stored-photo",
            raw_data={},
            sha256="",
            storage_type="",
            storage_key="",
            source_url_hash=evidence[0]["source_url_hash"],
        )
    ]

    assert reconcile.matched_review_photo_ids(active_photos, evidence) == {"review-a"}
    assert reconcile.unique_review_photo_source_count(evidence) == 2


def test_photo_evidence_keeps_distinct_download_targets_separate() -> None:
    evidence = reconcile.build_review_photo_evidence(
        [
            {
                "id": "review-a",
                "source_url": "https://example.test/detail?downloadImg=cloud%3A%2F%2Fphoto-a.jpg",
            },
            {
                "id": "review-b",
                "source_url": "https://example.test/detail?downloadImg=cloud%3A%2F%2Fphoto-b.jpg",
            },
        ]
    )
    active_photos = [
        SimpleNamespace(
            source_fingerprint="stored-photo",
            raw_data={},
            sha256="",
            storage_type="",
            storage_key="",
            source_url_hash=evidence[0]["source_url_hash"],
        )
    ]

    assert reconcile.matched_review_photo_ids(active_photos, evidence) == {"review-a"}
    assert reconcile.unique_review_photo_source_count(evidence) == 2


def test_activate_team_uses_normalized_repository_team_id() -> None:
    token, team_id = reconcile.activate_team(" Default-Team ")
    try:
        assert team_id == "default-team"
    finally:
        reconcile.local_simulation.reset_current_team(token)


def test_apply_keeps_finalize_and_full_verification_inside_commit_guard() -> None:
    source = inspect.getsource(reconcile.apply_record)
    guard_at = source.index("with repository_commit_guard(")
    finalize_at = source.index("repository.finalize_unmatched_match(")
    verify_at = source.index("verify_associated_in_session(", finalize_at)

    assert guard_at < finalize_at < verify_at
    assert "with strict_candidate_resolution(" in source[guard_at:finalize_at]


def test_apply_checks_for_safe_replay_before_requiring_open_dry_run() -> None:
    source = inspect.getsource(reconcile.apply_record)

    assert source.index("associated_snapshot(") < source.index("dry_run_record(")


class RepairState:
    def __init__(self, *, replayed: bool = False, production_shape: bool = False) -> None:
        self.raw_url = "https://photos.example/review-a.jpg?signature=secret&stable=identity"
        categories = ["before_box", "collector_barcode", "module_meter", "after_box"]
        self.review_rows = [
            {"id": "review-1", "source_url": self.raw_url, "category": categories[0]},
            *[
                {
                    "id": f"review-{index}",
                    "source_url": f"https://photos.example/review-{index}.jpg?signature={index}",
                    "category": categories[index - 1],
                }
                for index in range(2, 5)
            ],
        ]
        self.evidence = reconcile.build_review_photo_evidence(self.review_rows)
        self.migrated_rows = [
            {
                "id": f"formal-{row['id']}",
                "url": row["source_url"],
                "image_url": row["source_url"],
                "source_url": row["source_url"],
                "source_fingerprint": row["id"],
                "category": row["category"],
            }
            for row in self.review_rows
        ]
        self.record = SimpleNamespace(
            id=17,
            legacy_id="scan-unmatched-422f7a0a030a6d41ebbf788a",
            status="associated",
            payload={
                "associated_group_id": "g-12102",
                "associated_by": reconcile.ACTOR,
            },
        )
        self.group = SimpleNamespace(
            id=31,
            legacy_id="g-12102",
            team_id="team-1",
            display_meter_no="120000912473",
            photo_count=4 if replayed else 1,
        )
        photo_count = 4 if replayed else 1
        self.photos = [self.photo_for_evidence(index) for index in range(photo_count)]
        self.photos[0].source_fingerprint = "review-1"
        self.photos[0].raw_data = {"source_fingerprint": "review-2"}
        if production_shape:
            self.apply_production_shape()
        self.audits: list[SimpleNamespace] = []
        self.locks: list[str] = []
        self.add_calls = 0
        self.received_photo_count = 0
        self.commits = 0
        self.verifications = 0
        self.fail_validation = False
        self.fail_post_commit_observation = False

    def photo_for_evidence(self, index: int) -> SimpleNamespace:
        source_url = self.review_rows[index]["source_url"]
        return SimpleNamespace(
            team_id="team-1",
            group_id=31,
            legacy_id=self.migrated_rows[index]["id"],
            source_fingerprint=str(self.evidence[index]["id"]),
            raw_data={"source_fingerprint": str(self.evidence[index]["id"])},
            sha256=hashlib.sha256(source_url.encode("utf-8")).hexdigest(),
            storage_type="",
            storage_bucket="",
            storage_key="",
            object_key=source_url,
            source_file_id="",
            image_file_id="",
            original_filename="",
            content_type="",
            source_url=source_url,
            image_url=source_url,
            source_url_hash=self.evidence[index]["source_url_hash"],
            category=self.review_rows[index]["category"],
            is_active=True,
        )

    def apply_production_shape(self) -> None:
        survivor = self.photos[0]
        first = self.migrated_rows[0]
        last = self.migrated_rows[-1]
        survivor.source_fingerprint = first["source_fingerprint"]
        survivor.sha256 = hashlib.sha256(first["image_url"].encode("utf-8")).hexdigest()
        survivor.image_url = first["image_url"]
        survivor.source_url = last["source_url"]
        survivor.source_url_hash = self.evidence[-1]["source_url_hash"]
        survivor.category = last["category"]
        survivor.raw_data = {
            "source_fingerprint": last["source_fingerprint"],
            "source_url": last["source_url"],
            "category": last["category"],
            "qr_values": ["LAST-PHOTO-EVIDENCE"],
        }
        survivor.storage_type = "oss"
        survivor.storage_bucket = "legacy-bucket"
        survivor.storage_key = "first-photo-object"
        survivor.object_key = "first-photo-object"
        survivor.source_file_id = "first-photo-file"
        survivor.image_file_id = "first-image-file"
        survivor.original_filename = "first-photo.jpg"
        survivor.content_type = "image/jpeg"

    def survivor_identity(self) -> dict[str, object]:
        survivor = self.photos[0]
        return {
            "legacy_id": survivor.legacy_id,
            "source_fingerprint": survivor.source_fingerprint,
            "raw_data": deepcopy(survivor.raw_data),
            "source_url": survivor.source_url,
            "source_url_hash": survivor.source_url_hash,
            "image_url": survivor.image_url,
            "sha256": survivor.sha256,
            "category": survivor.category,
            "storage_type": survivor.storage_type,
            "storage_bucket": survivor.storage_bucket,
            "storage_key": survivor.storage_key,
            "object_key": survivor.object_key,
            "source_file_id": survivor.source_file_id,
            "image_file_id": survivor.image_file_id,
            "original_filename": survivor.original_filename,
            "content_type": survivor.content_type,
        }


class RepairScalars:
    def __init__(self, rows) -> None:
        self.rows = rows

    def all(self):
        return list(self.rows)


class RepairSession:
    def __init__(self, state: RepairState, *_args, **_kwargs) -> None:
        self.state = state

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> bool:
        return False

    def close(self) -> None:
        pass

    def flush(self) -> None:
        pass

    def scalar(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if getattr(statement, "_for_update_arg", None) is not None:
            self.state.locks.append(entity.__name__)
        if entity is reconcile.UnmatchedRecord:
            return self.state.record
        if entity is reconcile.MaterialGroup:
            return self.state.group
        if entity is reconcile.Photo:
            return len([photo for photo in self.state.photos if getattr(photo, "is_active", True) is not False])
        raise AssertionError(f"unexpected scalar entity: {entity}")

    def scalars(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if getattr(statement, "_for_update_arg", None) is not None:
            self.state.locks.append(entity.__name__)
        if entity is reconcile.Photo:
            return RepairScalars(
                [photo for photo in self.state.photos if getattr(photo, "is_active", True) is not False]
            )
        if entity is reconcile.AuditLog:
            return RepairScalars(self.state.audits)
        raise AssertionError(f"unexpected scalars entity: {entity}")

    def add(self, value) -> None:
        if not isinstance(value, reconcile.Photo):
            raise AssertionError(f"unexpected staged value: {value}")
        duplicate_legacy_id = any(
            str(getattr(photo, "team_id", "") or "")
            == str(getattr(value, "team_id", "") or "")
            and str(getattr(photo, "group_id", "") or "")
            == str(getattr(value, "group_id", "") or "")
            and str(getattr(photo, "legacy_id", "") or "")
            == str(getattr(value, "legacy_id", "") or "")
            for photo in self.state.photos
        )
        if duplicate_legacy_id:
            raise RuntimeError(f"duplicate group legacy_id: {value.legacy_id}")
        self.state.photos.append(value)


class RepairRepository:
    def __init__(self, state: RepairState) -> None:
        self.state = state

    def _add_photo_records_to_group(self, _session, _group, *, photos, **_kwargs):
        self.state.add_calls += 1
        self.state.received_photo_count = len(photos)
        self.state.photos[0].source_fingerprint = "review-1-merged"
        self.state.photos[0].raw_data["source_fingerprint"] = "review-4-merged"
        for index in range(1, 4):
            self.state.photos.append(self.state.photo_for_evidence(index))
        return {"added": 3, "skipped_duplicates": 0, "merged_duplicates": 0}


def _matching_repair_audit(state: RepairState) -> SimpleNamespace:
    return SimpleNamespace(
        id=93,
        legacy_id="repair-audit-93",
        before_data={"unmatched_id": state.record.legacy_id, "group_id": state.group.legacy_id},
        after_data={"group_id": state.group.legacy_id, "active_photo_count": 4},
        payload={"review_photo_count": 4},
    )


def install_repair_fakes(
    monkeypatch: pytest.MonkeyPatch,
    state: RepairState,
    repository=None,
):
    @contextmanager
    def guarded_transaction(_repository):
        before_photos = deepcopy(state.photos)
        before_audits = list(state.audits)
        try:
            yield object()
        except Exception:
            state.photos[:] = deepcopy(before_photos)
            state.audits[:] = before_audits
            raise
        else:
            state.commits += 1

    def stage_audit(_session, **_kwargs):
        audit = _matching_repair_audit(state)
        state.audits.append(audit)
        return audit

    def verify(_session, _team_id, _snapshot, *, groups_before, placeholders_before, result=None):
        state.verifications += 1
        if state.fail_post_commit_observation and state.verifications > 1:
            raise RuntimeError("post-commit observation failed")
        if state.fail_validation:
            raise RuntimeError("failed repair invariant")
        assert len(
            [photo for photo in state.photos if getattr(photo, "is_active", True) is not False]
        ) == 4
        if groups_before is None:
            assert placeholders_before is None
        else:
            assert groups_before == 12
            assert placeholders_before == 0
        assert len(state.audits) == 1
        return {
            "target_photo_count_after": 4,
            "group_count_before": groups_before,
            "group_count_after": 12,
            "placeholder_count_before": placeholders_before,
            "placeholder_count_after": 0,
        }

    snapshot = {
        "unmatched_id": state.record.legacy_id,
        "target_group_id": state.group.legacy_id,
        "target_before": {"db_id": state.group.id, "photo_count": 1},
        "review_photo_ids": [item["id"] for item in state.evidence],
        "review_photo_evidence": state.evidence,
        "unique_review_photo_source_count": 4,
    }
    monkeypatch.setattr(reconcile, "associated_snapshot", lambda _team_id, _unmatched_id: snapshot)
    monkeypatch.setattr(reconcile, "group_count", lambda _team_id: 12)
    monkeypatch.setattr(reconcile, "placeholder_group_count", lambda _team_id: 0)
    monkeypatch.setattr(reconcile, "repository_commit_guard", guarded_transaction)
    monkeypatch.setattr(reconcile, "Session", lambda *_args, **_kwargs: RepairSession(state))
    monkeypatch.setattr(reconcile, "SessionLocal", lambda: RepairSession(state))
    monkeypatch.setattr(reconcile, "_stage_transactional_audit", stage_audit)
    monkeypatch.setattr(reconcile, "_unmatched_payload", lambda _record: {})
    monkeypatch.setattr(reconcile.unmatched_review, "build_review", lambda _payload: {"reviewer": "repairer"})
    monkeypatch.setattr(
        reconcile.unmatched_review,
        "migrate_review_to_photo_rows",
        lambda _review: deepcopy(state.migrated_rows),
    )
    monkeypatch.setattr(reconcile, "verify_associated_in_session", verify)
    return repository or RepairRepository(state)


def test_review_photo_evidence_normalizes_nested_download_urls_without_erasing_stable_identity() -> None:
    evidence = reconcile.build_review_photo_evidence(
        [
            {
                "id": "review-a",
                "source_url": "https://wrapper.example/open?downloadImg=https%3A%2F%2Fcdn.example%2Fphotos%2Fa.jpg%3Fsignature%3Done%26token%3Dfirst%26variant%3Dfull",
            },
            {
                "id": "review-b",
                "source_url": "https://wrapper.example/open?downloadImg=https%3A%2F%2Fcdn.example%2Fphotos%2Fa.jpg%3Fsignature%3Dtwo%26token%3Dsecond%26variant%3Dfull",
            },
            {
                "id": "review-c",
                "source_url": "https://wrapper.example/open?downloadImg=https%3A%2F%2Fcdn.example%2Fphotos%2Fb.jpg%3Fvariant%3Dfull",
            },
            {
                "id": "review-d",
                "source_url": "https://wrapper.example/open?downloadImg=https%3A%2F%2Fcdn.example%2Fphotos%2Fa.jpg%3Fvariant%3Dthumbnail",
            },
        ]
    )

    assert evidence[0]["source_url_hash"] == evidence[1]["source_url_hash"]
    assert evidence[0]["source_url_hash"] != evidence[2]["source_url_hash"]
    assert evidence[0]["source_url_hash"] != evidence[3]["source_url_hash"]


def test_photo_repair_transitions_one_active_photo_to_four_with_locks_and_sanitized_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = RepairState()
    repository = install_repair_fakes(monkeypatch, state)

    assert reconcile.matched_review_photo_ids(state.photos, state.evidence) == {"review-1", "review-2"}

    result = reconcile.repair_associated_photo_evidence(repository, "team-1", state.record.legacy_id)

    assert len(state.photos) == 4
    assert state.add_calls == 1
    assert state.received_photo_count == 4
    assert state.commits == 1
    assert state.locks == ["UnmatchedRecord", "MaterialGroup", "Photo"]
    assert len(state.audits) == 1
    assert result["repair_added_photo_count"] == 3
    assert result.get("repair_broad_matched_review_photo_count_before") == 2
    assert result.get("repair_physical_source_matched_review_photo_count_before") == 1
    assert result["group_count_before"] == result["group_count_after"] == 12
    assert result["placeholder_count_before"] == result["placeholder_count_after"] == 0
    rendered = json.dumps(result, sort_keys=True)
    assert state.raw_url not in rendered
    assert "signature=" not in rendered


def test_real_postgres_repository_reproduces_production_survivor_duplicate_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = RepairState(production_shape=True)
    session = RepairSession(state)
    monkeypatch.setattr(
        state_repository_module,
        "_reset_group_after_photo_evidence_change",
        lambda _session, _group: None,
    )

    result = reconcile.PostgresStateRepository()._add_photo_records_to_group(
        session,
        state.group,
        actor=reconcile.REPAIR_ACTOR,
        photos=deepcopy(state.migrated_rows),
        source="unmatched-review-finalize",
    )

    assert result == {"added": 2, "skipped_duplicates": 2, "merged_duplicates": 2}
    assert len(state.photos) == 3


def test_photo_repair_canonicalizes_production_survivor_before_real_repository_insertion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = RepairState(production_shape=True)
    repository = install_repair_fakes(
        monkeypatch,
        state,
        repository=reconcile.PostgresStateRepository(),
    )
    monkeypatch.setattr(
        state_repository_module,
        "_reset_group_after_photo_evidence_change",
        lambda _session, _group: None,
    )

    assert reconcile.matched_review_photo_ids(state.photos, state.evidence) == {"review-1", "review-4"}
    assert reconcile.physical_source_matched_review_photo_ids(state.photos, state.evidence) == {"review-4"}

    result = reconcile.repair_associated_photo_evidence(repository, "team-1", state.record.legacy_id)

    canonical = state.migrated_rows[-1]
    survivor = state.photos[0]
    assert result["repair_added_photo_count"] == 3
    assert result["repair_replayed"] is False
    assert len(state.photos) == 4
    assert reconcile.physical_source_matched_review_photo_ids(state.photos, state.evidence) == {
        "review-1",
        "review-2",
        "review-3",
        "review-4",
    }
    assert survivor.legacy_id == canonical["id"]
    assert survivor.source_fingerprint == canonical["source_fingerprint"]
    assert survivor.raw_data["source_fingerprint"] == canonical["source_fingerprint"]
    assert survivor.raw_data["source_url"] == canonical["source_url"]
    assert survivor.raw_data["category"] == canonical["category"]
    assert survivor.source_url == canonical["source_url"]
    assert survivor.source_url_hash == state.evidence[-1]["source_url_hash"]
    assert survivor.image_url == canonical["image_url"]
    assert survivor.sha256 == hashlib.sha256(canonical["image_url"].encode("utf-8")).hexdigest()
    assert survivor.category == canonical["category"]
    assert survivor.storage_type == ""
    assert survivor.storage_bucket == ""
    assert survivor.storage_key == ""
    assert survivor.object_key == canonical["image_url"]
    assert survivor.source_file_id == ""
    assert survivor.image_file_id == ""
    assert survivor.original_filename == ""
    assert survivor.content_type == ""
    assert len(state.audits) == 1
    rendered = json.dumps(result, sort_keys=True)
    assert "photos.example" not in rendered
    assert "signature=" not in rendered
    assert "stable=identity" not in rendered

    replay = reconcile.repair_associated_photo_evidence(repository, "team-1", state.record.legacy_id)

    assert replay["repair_replayed"] is True
    assert replay["repair_added_photo_count"] == 0
    assert len(state.photos) == 4
    assert len(state.audits) == 1


def test_photo_repair_rolls_back_every_canonicalized_production_survivor_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = RepairState(production_shape=True)
    before = state.survivor_identity()
    state.fail_validation = True
    repository = install_repair_fakes(
        monkeypatch,
        state,
        repository=reconcile.PostgresStateRepository(),
    )
    monkeypatch.setattr(
        state_repository_module,
        "_reset_group_after_photo_evidence_change",
        lambda _session, _group: None,
    )

    with pytest.raises(RuntimeError, match="failed repair invariant"):
        reconcile.repair_associated_photo_evidence(repository, "team-1", state.record.legacy_id)

    assert len(state.photos) == 1
    assert state.survivor_identity() == before
    assert state.audits == []
    assert state.commits == 0


def test_photo_repair_rejects_duplicate_audit_without_adding_photos(monkeypatch: pytest.MonkeyPatch) -> None:
    state = RepairState()
    state.audits.append(_matching_repair_audit(state))
    repository = install_repair_fakes(monkeypatch, state)

    with pytest.raises(RuntimeError, match="photo repair audit exists before repair"):
        reconcile.repair_associated_photo_evidence(repository, "team-1", state.record.legacy_id)

    assert len(state.photos) == 1
    assert len(state.audits) == 1
    assert state.add_calls == 0
    assert state.commits == 0


def test_photo_repair_rolls_back_added_photos_and_audit_when_an_invariant_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = RepairState()
    state.fail_validation = True
    repository = install_repair_fakes(monkeypatch, state)

    with pytest.raises(RuntimeError, match="failed repair invariant"):
        reconcile.repair_associated_photo_evidence(repository, "team-1", state.record.legacy_id)

    assert len(state.photos) == 1
    assert state.photos[0].source_fingerprint == "review-1"
    assert state.photos[0].raw_data["source_fingerprint"] == "review-2"
    assert state.audits == []
    assert state.add_calls == 1
    assert state.commits == 0


def test_photo_repair_replays_idempotently_with_exactly_one_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    state = RepairState(replayed=True)
    state.audits.append(_matching_repair_audit(state))
    repository = install_repair_fakes(monkeypatch, state)

    result = reconcile.repair_associated_photo_evidence(repository, "team-1", state.record.legacy_id)

    assert len(state.photos) == 4
    assert state.add_calls == 0
    assert len(state.audits) == 1
    assert result["repair_replayed"] is True
    assert result["repair_added_photo_count"] == 0
    assert result.get("repair_physical_source_matched_review_photo_count_before") == 4


def test_repair_dry_run_distinguishes_legacy_alias_matches_from_physical_source_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = RepairState(production_shape=True)
    install_repair_fakes(monkeypatch, state)

    result = reconcile.repair_dry_run_record("team-1", state.record.legacy_id)

    assert result.get("historical_alias_matched_review_photo_count") == 2
    assert result.get("historical_alias_missing_review_photo_count") == 2
    assert result.get("physical_source_matched_review_photo_count") == 1
    assert result.get("physical_source_missing_review_photo_count") == 3
    rendered = json.dumps(result, sort_keys=True)
    assert state.raw_url not in rendered
    assert "signature=" not in rendered
    assert "stable=identity" not in rendered


@pytest.mark.parametrize("physical_match_count", [0, 2])
def test_photo_repair_rejects_zero_or_multiple_physical_source_matches(
    monkeypatch: pytest.MonkeyPatch,
    physical_match_count: int,
) -> None:
    state = RepairState()
    if physical_match_count == 0:
        state.photos[0].source_url = "https://photos.example/not-a-review-photo.jpg"
        state.photos[0].source_url_hash = "unmatched-source-hash"
    else:
        state.photos.append(state.photo_for_evidence(1))
    repository = install_repair_fakes(monkeypatch, state)

    with pytest.raises(RuntimeError, match="physical-source matched review photo count is not one"):
        reconcile.repair_associated_photo_evidence(repository, "team-1", state.record.legacy_id)

    assert state.add_calls == 0
    assert state.commits == 0


def test_photo_repair_treats_post_commit_reads_as_observational(monkeypatch: pytest.MonkeyPatch) -> None:
    state = RepairState()
    state.fail_post_commit_observation = True
    repository = install_repair_fakes(monkeypatch, state)

    result = reconcile.repair_associated_photo_evidence(repository, "team-1", state.record.legacy_id)

    assert result["repair_added_photo_count"] == 3
    assert state.commits == 1


def test_dry_run_requires_nonempty_photo_evidence() -> None:
    source = inspect.getsource(reconcile.dry_run_record)

    assert 'require(bool(review_photo_ids), f"review has no photo evidence:' in source


def test_placeholder_guard_normalizes_terminal_and_legacy_identity() -> None:
    source = inspect.getsource(reconcile._placeholder_group_count)

    assert "func.btrim(func.coalesce(MaterialGroup.terminal" in source
    assert "func.lower(func.btrim(func.coalesce(MaterialGroup.legacy_id" in source
