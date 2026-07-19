from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[2]
API_ROOT = ROOT / "v2-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

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


def test_dry_run_requires_nonempty_photo_evidence() -> None:
    source = inspect.getsource(reconcile.dry_run_record)

    assert 'require(bool(review_photo_ids), f"review has no photo evidence:' in source


def test_placeholder_guard_normalizes_terminal_and_legacy_identity() -> None:
    source = inspect.getsource(reconcile._placeholder_group_count)

    assert "func.btrim(func.coalesce(MaterialGroup.terminal" in source
    assert "func.lower(func.btrim(func.coalesce(MaterialGroup.legacy_id" in source
