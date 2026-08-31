from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

from app.models import GroupStatus
from scripts.repair_missing_collector_photo_exceptions import (
    repair_missing_collector_photo_exceptions,
)


class ScalarRows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class RepairSession:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.commits = 0
        self.rollbacks = 0
        self.staged = []

    def scalars(self, _statement):
        return ScalarRows(self.rows)

    def add(self, value) -> None:
        self.staged.append(value)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def stale_group(*, reasons=None, note="缺采集器照片", raw_reasons=None):
    resolved_reasons = ["missing_collector_photo"] if reasons is None else list(reasons)
    resolved_raw_reasons = resolved_reasons if raw_reasons is None else list(raw_reasons)
    return SimpleNamespace(
        id=uuid4(),
        legacy_id=f"group-{uuid4()}",
        team_id="team-a",
        status=GroupStatus.REJECTED,
        exception_status="open",
        exception_note=note,
        exception_reasons=resolved_reasons,
        has_archive_blocker=True,
        raw_data={
            "status": "exception",
            "exception_status": "open",
            "exception_note": note,
            "exception_reasons": resolved_raw_reasons,
        },
    )


def snapshot(group):
    return {
        "status": group.status,
        "exception_status": group.exception_status,
        "exception_note": group.exception_note,
        "exception_reasons": list(group.exception_reasons),
        "has_archive_blocker": group.has_archive_blocker,
        "raw_data": deepcopy(group.raw_data),
    }


def test_repair_preview_is_read_only_and_reports_only_safe_candidates() -> None:
    safe = stale_group()
    mixed = stale_group(reasons=["missing_collector_photo", "missing_module_asset_no"])
    manual_note = stale_group(note="人工异常：模块号无法确认")
    raw_mixed = stale_group(raw_reasons=["missing_collector_photo", "missing_module_asset_no"])
    rows = [safe, mixed, manual_note, raw_mixed]
    before = {str(group.id): snapshot(group) for group in rows}
    session = RepairSession(rows)

    report = repair_missing_collector_photo_exceptions(session, apply_changes=False)

    assert report == {
        "mode": "preview",
        "team_id": "",
        "scanned": 4,
        "candidates": 1,
        "updated": 0,
        "status_restored": 0,
        "skipped_not_single_reason": 1,
        "skipped_nonstandard_note": 1,
        "skipped_raw_mixed_reasons": 1,
    }
    assert {str(group.id): snapshot(group) for group in rows} == before
    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.staged == []


def test_repair_apply_clears_only_retired_exception_and_is_idempotent() -> None:
    safe = stale_group()
    mixed = stale_group(reasons=["missing_collector_photo", "missing_module_asset_no"])
    session = RepairSession([safe, mixed])

    report = repair_missing_collector_photo_exceptions(
        session,
        apply_changes=True,
        actor="missing-collector-photo-repair-test",
    )

    assert report["candidates"] == 1
    assert report["updated"] == 1
    assert report["status_restored"] == 1
    assert safe.status == GroupStatus.UNREVIEWED
    assert safe.exception_status == ""
    assert safe.exception_note == ""
    assert safe.exception_reasons == []
    assert safe.has_archive_blocker is False
    assert safe.raw_data["status"] == "pending"
    assert safe.raw_data["exception_status"] == ""
    assert safe.raw_data["exception_note"] == ""
    assert safe.raw_data["exception_reasons"] == []
    assert mixed.exception_reasons == ["missing_collector_photo", "missing_module_asset_no"]
    assert session.commits == 1
    assert session.rollbacks == 0
    audit = next(item for item in session.staged if item.action == "missing_collector_photo_exception_repaired")
    assert audit.entity_id == safe.id
    assert audit.before_data["status"] == "rejected"
    assert audit.after_data["status"] == "unreviewed"

    second_report = repair_missing_collector_photo_exceptions(session, apply_changes=True)

    assert second_report["candidates"] == 0
    assert second_report["updated"] == 0
    assert session.commits == 2
    assert len([item for item in session.staged if item.action == "missing_collector_photo_exception_repaired"]) == 1


def test_repair_keeps_approved_status_while_removing_retired_reason() -> None:
    approved = stale_group()
    approved.status = GroupStatus.APPROVED
    approved.raw_data["status"] = "approved"
    session = RepairSession([approved])

    report = repair_missing_collector_photo_exceptions(session, apply_changes=True)

    assert report["updated"] == 1
    assert report["status_restored"] == 0
    assert approved.status == GroupStatus.APPROVED
    assert approved.raw_data["status"] == "approved"
    assert approved.exception_reasons == []
    assert approved.has_archive_blocker is False
