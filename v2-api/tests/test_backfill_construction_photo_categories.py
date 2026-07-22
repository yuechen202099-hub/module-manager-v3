from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.models import GroupStatus
from scripts.backfill_construction_photo_categories import backfill_construction_photo_categories


class RowsResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class BackfillSession:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.commits = 0
        self.rollbacks = 0
        self.staged = []

    def execute(self, _statement):
        return RowsResult(self.rows)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def flush(self) -> None:
        return None

    def add(self, value) -> None:
        self.staged.append(value)


def photo(group_id, *, category="unclassified", slot="before_box", active=True, classified_by=""):
    return SimpleNamespace(
        id=uuid4(),
        legacy_id=f"photo-{uuid4()}",
        group_id=group_id,
        team_id="team-a",
        category=category,
        is_active=active,
        classified_by=classified_by,
        classified_at=None,
        raw_data={"construction_slot": slot},
    )


def group(*, archived=False):
    return SimpleNamespace(
        id=uuid4(),
        legacy_id=f"group-{uuid4()}",
        team_id="team-a",
        status=GroupStatus.APPROVED if archived else GroupStatus.UNREVIEWED,
        raw_data={},
    )


def build_rows():
    eligible_group = group()
    conflict_group = group()
    archived_group = group(archived=True)
    inactive_group = group()
    eligible = photo(eligible_group.id, slot="before_box")
    manual = photo(eligible_group.id, category="module_meter", slot="module_meter", classified_by="reviewer-a")
    conflict_a = photo(conflict_group.id, slot="collector_barcode")
    conflict_b = photo(conflict_group.id, slot="collector_barcode")
    archived = photo(archived_group.id, slot="after_box")
    inactive = photo(inactive_group.id, slot="module_meter", active=False)
    invalid_slot = photo(inactive_group.id, slot="legacy-overview")
    return [
        (eligible, eligible_group),
        (manual, eligible_group),
        (conflict_a, conflict_group),
        (conflict_b, conflict_group),
        (archived, archived_group),
        (inactive, inactive_group),
        (invalid_slot, inactive_group),
    ], eligible


def test_backfill_preview_is_read_only_and_reports_skips() -> None:
    rows, eligible = build_rows()
    session = BackfillSession(rows)

    report = backfill_construction_photo_categories(session, apply_changes=False, actor="task-2-backfill")

    assert eligible.category == "unclassified"
    assert report == {
        "mode": "preview",
        "candidates": 1,
        "updated": 0,
        "skipped_manual_category": 1,
        "skipped_conflict": 2,
        "skipped_archived_group": 1,
        "skipped_inactive": 1,
        "skipped_invalid_slot": 1,
        "affected_groups": 1,
    }
    assert session.commits == 0
    assert session.rollbacks == 1


def test_backfill_apply_updates_only_safe_candidates_and_invalidates_once(monkeypatch) -> None:
    rows, eligible = build_rows()
    session = BackfillSession(rows)
    invalidations = []
    monkeypatch.setattr(
        "scripts.backfill_construction_photo_categories.invalidate_verification_for_group",
        lambda checked_session, checked_group, actor, reason: invalidations.append(
            (checked_session, checked_group, actor, reason)
        ),
    )

    report = backfill_construction_photo_categories(session, apply_changes=True, actor="task-2-backfill")

    assert eligible.category == "before_box"
    assert eligible.raw_data["category"] == "before_box"
    assert eligible.raw_data["category_label"]
    assert eligible.classified_by == "task-2-backfill"
    assert eligible.classified_at is not None
    assert report["updated"] == 1
    assert session.commits == 1
    assert session.rollbacks == 0
    assert len(invalidations) == 1
    assert invalidations[0][2:] == ("task-2-backfill", "construction_category_backfill")
    audit = next(item for item in session.staged if item.action == "photo_category_corrected")
    assert audit.payload["previous_category"] == "unclassified"
    assert audit.payload["next_category"] == "before_box"
