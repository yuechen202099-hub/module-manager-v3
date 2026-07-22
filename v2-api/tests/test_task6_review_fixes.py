from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.services import photo_barcode_check
from app.services import state_repository as repository


TERMINAL_STATUSES = ("passed", "manual_confirmed", "partial", "unreadable", "mismatch", "failed")
ALL_STATUSES = ("not_eligible", "pending", "processing", *TERMINAL_STATUSES)
REQUIRED_CATEGORIES = ("before_box", "collector_barcode", "module_meter", "after_box")


def eligible_photos(prefix: str = "photo") -> list[dict]:
    return [
        {
            "id": f"{prefix}-{index}",
            "sha256": f"{index:x}" * 64,
            "category": category,
            "is_active": True,
            "upload_status": "uploaded",
        }
        for index, category in enumerate(REQUIRED_CATEGORIES, start=1)
    ]


def durable_verification(status: str, *, passed_count: int = 0, source: str = "machine_barcode") -> dict:
    return {
        "status": status,
        "evidence_fingerprint": "a" * 64,
        "evidence_version": 7,
        "meter_matched": passed_count >= 1,
        "module_matched": passed_count >= 2,
        "collector_matched": passed_count >= 3,
        "recognition_source": source,
        "attempt_count": 2,
        "invalidation_reason": None,
        "result": {
            "passed_count": passed_count,
            "machine_barcode_values": ["METER-001"],
            "machine_qr_values": ["MODULE-001"],
            "ocr_candidates": ["COLLECTOR-001"],
            "matched_fields": list(photo_barcode_check.GROUP_BARCODE_TYPES[:passed_count]),
            "missing_fields": list(photo_barcode_check.GROUP_BARCODE_TYPES[passed_count:]),
            "unmatched_machine_values": [],
            "matched_ocr_candidates": [],
            "unmatched_ocr_candidates": [],
        },
    }


@pytest.mark.parametrize("status", ALL_STATUSES)
def test_group_target_summary_exposes_every_nested_durable_status(status: str) -> None:
    group = {
        "id": f"group-{status}",
        "terminal": "TERMINAL-001",
        "meter_no": "METER-001",
        "module_asset_no": "MODULE-001",
        "collector": "COLLECTOR-001",
        "status": "pending",
        "photo_count": 4,
        "photos": eligible_photos(status),
        "barcode_verification": durable_verification(
            status,
            passed_count=3 if status in {"passed", "manual_confirmed"} else 1,
            source="manual_confirmed" if status == "manual_confirmed" else "machine_qr",
        ),
        "group_barcode_check_status": "matched" if status != "passed" else "unreadable",
    }

    payload = repository._group_target_summary(group, include_photos=True)

    assert payload["barcode_verification"]["status"] == status
    assert payload["barcode_verification_status"] == status
    assert payload["barcode_verification_total_count"] == 3


def test_postgres_group_payload_prefers_current_verification_row_over_stale_raw_json() -> None:
    group_id = uuid4()
    group = SimpleNamespace(
        id=group_id,
        legacy_id="group-pg-current",
        team_id="team-current",
        task_id=None,
        legacy_task_id=1,
        display_meter_no="METER-001",
        meter_match_key="METER-001",
        terminal="TERMINAL-001",
        installation_address="Address",
        status=repository.GroupStatus.UNREVIEWED,
        photo_count=4,
        reviewer=None,
        reviewed_at=None,
        review_note="",
        exception_note="",
        exception_reasons=[],
        has_archive_blocker=False,
        raw_data={
            "collector": "COLLECTOR-001",
            "module_asset_no": "MODULE-001",
            "barcode_verification": durable_verification("passed", passed_count=3),
            "group_barcode_check_status": "matched",
        },
    )
    verification = SimpleNamespace(
        status="processing",
        evidence_fingerprint="b" * 64,
        evidence_version=8,
        meter_matched=None,
        module_matched=None,
        collector_matched=None,
        recognition_source=None,
        attempt_count=3,
        lease_owner="worker-a",
        lease_token="secret-token",
        lease_expires_at=datetime.now(UTC),
        invalidation_reason="photo_replaced",
        invalidated_by="reviewer-a",
        invalidated_at=datetime.now(UTC),
        auto_archive_status=None,
        auto_archived_at=None,
        auto_archive_error=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    class FakeSession:
        def scalar(self, _statement):
            return verification

    payload = repository._group_payload(FakeSession(), group, include_photos=False)

    assert payload["barcode_verification"]["status"] == "processing"
    assert payload["barcode_verification"]["evidence_version"] == 8
    assert payload["barcode_verification"]["attempt_count"] == 3
    assert payload["barcode_verification"]["result"]["passed_count"] == 0
    assert payload["barcode_verification_status"] == "processing"


def test_json_durable_verification_preserves_current_machine_and_ocr_result_details() -> None:
    source = durable_verification("partial", passed_count=2, source="machine_qr")
    source["result"].update(
        {
            "machine_barcode_values": ["METER-001"],
            "machine_qr_values": ["MODULE-001"],
            "ocr_candidates": ["COLLECTOR-001"],
            "unmatched_machine_values": ["OTHER-001"],
            "matched_ocr_candidates": ["COLLECTOR-001"],
            "unmatched_ocr_candidates": ["OTHER-OCR"],
        }
    )

    payload = repository.normalize_barcode_verification(source)

    assert payload is not None
    assert payload["result"] == source["result"]


def test_postgres_group_payloads_load_durable_rows_once_for_a_list(monkeypatch: pytest.MonkeyPatch) -> None:
    groups = [
        SimpleNamespace(id=uuid4(), legacy_id=f"group-{index}", team_id="bulk-team", task_id=None, raw_data={})
        for index in range(25)
    ]
    verifications = [
        SimpleNamespace(
            group_id=group.id,
            status="passed",
            evidence_fingerprint="a" * 64,
            evidence_version=1,
            meter_matched=True,
            module_matched=True,
            collector_matched=True,
            recognition_source="machine_barcode",
            attempt_count=1,
            invalidation_reason=None,
            invalidated_by=None,
            invalidated_at=None,
            auto_archive_status=None,
            auto_archived_at=None,
            auto_archive_error=None,
            updated_at=None,
        )
        for group in groups
    ]
    statements = []

    class FakeSession:
        def scalars(self, statement):
            statements.append(statement)
            return SimpleNamespace(all=lambda: verifications)

        def scalar(self, _statement):
            raise AssertionError("list payloads must not issue per-group verification queries")

    def minimal_payload(_session, group, include_photos=True, *, verification=None):
        assert include_photos is False
        return {
            "id": group.legacy_id,
            "barcode_verification": repository.normalize_barcode_verification(verification),
        }

    monkeypatch.setattr(repository, "_group_payload", minimal_payload)

    payloads = repository._group_payloads(FakeSession(), groups, include_photos=False)

    assert len(statements) == 1
    assert len(payloads) == 25
    assert {item["barcode_verification"]["status"] for item in payloads} == {"passed"}


def test_dashboard_accuracy_uses_only_currently_eligible_terminal_durable_results() -> None:
    groups = []
    expected_statuses = [
        "passed",
        "manual_confirmed",
        "partial",
        "unreadable",
        "mismatch",
        "failed",
        "pending",
        "processing",
        "not_eligible",
    ]
    for index, status in enumerate(expected_statuses, start=1):
        groups.append(
            {
                "id": f"group-{status}",
                "terminal": f"TERMINAL-{index:03d}",
                "meter_no": f"METER-{index:03d}",
                "module_asset_no": f"MODULE-{index:03d}",
                "collector": f"COLLECTOR-{index:03d}",
                "photos": eligible_photos(status),
                "barcode_verification": durable_verification(
                    status,
                    passed_count=3 if status in {"passed", "manual_confirmed"} else 1,
                    source="manual_confirmed" if status == "manual_confirmed" else "machine_barcode",
                ),
            }
        )
    duplicate = dict(groups[0], id="duplicate-category", photos=eligible_photos("duplicate"))
    duplicate["photos"][1]["category"] = "before_box"
    missing = dict(groups[0], id="missing-category", photos=eligible_photos("missing")[:-1])
    groups.extend([duplicate, missing])

    summary = photo_barcode_check.summarize_group_barcode_accuracy(groups)

    assert summary == {
        "group_barcode_accuracy_checked": 6,
        "group_barcode_accuracy_passed": 2,
        "group_barcode_accuracy_failed": 3,
        "group_barcode_accuracy_unreadable": 1,
        "group_barcode_accuracy_not_required": 3,
        "group_barcode_accuracy_rate": round(2 / 6, 4),
        "group_barcode_accuracy_machine_passed": 1,
        "group_barcode_accuracy_manual_confirmed": 1,
        "group_barcode_accuracy_partial": 1,
        "group_barcode_accuracy_mismatch": 1,
        "group_barcode_accuracy_terminal_failed": 1,
        "group_barcode_accuracy_not_eligible": 3,
        "group_barcode_accuracy_pending": 1,
        "group_barcode_accuracy_processing": 1,
    }


def test_postgres_dashboard_summary_never_recomputes_legacy_barcode_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    groups = [
        {
            "id": "pg-passed",
            "terminal": "TERMINAL-001",
            "meter_no": "METER-001",
            "module_asset_no": "MODULE-001",
            "collector": "COLLECTOR-001",
            "barcode_verification": durable_verification("passed", passed_count=3),
        },
        {
            "id": "pg-processing",
            "terminal": "TERMINAL-002",
            "meter_no": "METER-002",
            "module_asset_no": "MODULE-002",
            "collector": "COLLECTOR-002",
            "barcode_verification": durable_verification("processing", passed_count=0),
        },
    ]
    photos_by_group_id = {
        "pg-passed": eligible_photos("pg-passed"),
        "pg-processing": eligible_photos("pg-processing"),
    }
    monkeypatch.setattr(
        repository.photo_barcode_check,
        "build_group_barcode_check",
        lambda _group: (_ for _ in ()).throw(AssertionError("durable summary must not recompute legacy status")),
    )

    summary = repository._group_barcode_accuracy_summary(
        groups,
        photos_by_group_id,
        total_groups=3,
    )

    assert summary["group_barcode_accuracy_checked"] == 1
    assert summary["group_barcode_accuracy_passed"] == 1
    assert summary["group_barcode_accuracy_processing"] == 1
    assert summary["group_barcode_accuracy_not_eligible"] == 1


def test_postgres_dashboard_joined_row_carries_current_durable_verification() -> None:
    row = {
        "group_id": "joined-group",
        "legacy_id": "joined-legacy",
        "legacy_task_id": 1,
        "display_meter_no": "METER-001",
        "meter_match_key": "METER-001",
        "terminal": "TERMINAL-001",
        "installation_address": "Address",
        "status": "approved",
        "photo_count": 4,
        "raw_data": {"barcode_verification": durable_verification("passed", passed_count=3)},
        "verification_status": "mismatch",
        "verification_evidence_fingerprint": "b" * 64,
        "verification_evidence_version": 8,
        "verification_meter_matched": True,
        "verification_module_matched": False,
        "verification_collector_matched": False,
        "verification_recognition_source": "machine_qr",
        "verification_attempt_count": 4,
        "verification_invalidation_reason": "",
        "verification_invalidated_by": "",
        "verification_invalidated_at": None,
        "verification_auto_archive_status": "",
        "verification_auto_archived_at": None,
        "verification_auto_archive_error": "",
        "verification_updated_at": None,
    }

    payload = repository._group_barcode_payload_from_row(row)

    assert payload["barcode_verification"]["status"] == "mismatch"
    assert payload["barcode_verification"]["result"]["passed_count"] == 1
    assert payload["barcode_verification"]["attempt_count"] == 4


@pytest.mark.parametrize(
    ("status", "legacy_status"),
    [
        ("passed", "matched"),
        ("manual_confirmed", "matched"),
        ("partial", "mismatched"),
        ("unreadable", "unreadable"),
        ("mismatch", "mismatched"),
        ("failed", "mismatched"),
    ],
)
def test_review_items_derive_legacy_filter_status_from_nested_durable_state(
    status: str,
    legacy_status: str,
) -> None:
    group = {
        "id": f"review-{status}",
        "terminal": "TERMINAL-001",
        "meter_no": "METER-001",
        "module_asset_no": "MODULE-001",
        "collector": "COLLECTOR-001",
        "status": "approved",
        "photo_count": 4,
        "photos": eligible_photos(status),
        "barcode_verification": durable_verification(
            status,
            passed_count=3 if status in {"passed", "manual_confirmed"} else 1,
            source="manual_confirmed" if status == "manual_confirmed" else "machine_barcode",
        ),
        "group_barcode_check_status": "unreadable",
    }

    items = photo_barcode_check.list_group_barcode_review_items(
        [group],
        statuses={"matched", "unreadable", "mismatched"},
    )

    assert len(items) == 1
    assert items[0]["status"] == legacy_status
    assert items[0]["barcode_verification"]["status"] == status
    assert items[0]["barcode_verification_total_count"] == 3
    assert items[0]["photo_category_complete"] is True


@pytest.mark.parametrize(
    ("offset", "expected_ids"),
    [
        (0, [f"group-{index:02d}" for index in range(20)]),
        (20, [f"group-{index:02d}" for index in range(20, 40)]),
        (40, [f"group-{index:02d}" for index in range(40, 45)]),
    ],
)
def test_postgres_review_pagination_limits_groups_before_bulk_photo_load(
    monkeypatch: pytest.MonkeyPatch,
    offset: int,
    expected_ids: list[str],
) -> None:
    team_id = "pagination-team"
    groups = []
    verification_by_group_id = {}
    photos_by_group_id = {}
    for index in range(45):
        group_id = uuid4()
        group = SimpleNamespace(
            id=group_id,
            legacy_id=f"group-{index:02d}",
            legacy_task_id=1,
            team_id=team_id,
            display_meter_no=f"METER-{index:02d}",
            meter_match_key=f"METER-{index:02d}",
            terminal=f"TERMINAL-{index:02d}",
            installation_address=f"Address {index:02d}",
            status=repository.GroupStatus.APPROVED,
            photo_count=4,
            raw_data={"collector": f"COLLECTOR-{index:02d}", "module_asset_no": f"MODULE-{index:02d}"},
        )
        groups.append(group)
        verification_by_group_id[str(group_id)] = SimpleNamespace(
            group_id=group_id,
            status="passed",
            evidence_fingerprint=f"{index % 16:x}" * 64,
            evidence_version=1,
            meter_matched=True,
            module_matched=True,
            collector_matched=True,
            recognition_source="machine_barcode",
            attempt_count=1,
            invalidation_reason=None,
            invalidated_by=None,
            invalidated_at=None,
            auto_archive_status=None,
            auto_archived_at=None,
            auto_archive_error=None,
            updated_at=None,
        )
        photos_by_group_id[str(group_id)] = [
            SimpleNamespace(
                id=uuid4(),
                legacy_id=f"photo-{index:02d}-{photo_index}",
                group_id=group_id,
                category=category,
                sha256=f"{photo_index:x}" * 64,
                is_active=True,
                upload_status="uploaded",
                barcode="",
                collector="",
                asset_no="",
                raw_data={},
            )
            for photo_index, category in enumerate(REQUIRED_CATEGORIES, start=1)
        ]

    statements = []
    loaded_photo_group_ids: set[str] = set()

    class Result:
        def __init__(self, items):
            self.items = list(items)

        def all(self):
            return self.items

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, statement):
            statements.append(statement)
            return 45

        def scalars(self, statement):
            statements.append(statement)
            sql = str(statement)
            if "FROM material_groups" in sql:
                page_offset = int(getattr(getattr(statement, "_offset_clause", None), "value", 0) or 0)
                page_limit = int(getattr(getattr(statement, "_limit_clause", None), "value", len(groups)) or len(groups))
                return Result(groups[page_offset : page_offset + page_limit])
            if "FROM group_barcode_verifications" in sql:
                selected = _statement_group_ids(statement)
                return Result(verification_by_group_id[str(group_id)] for group_id in selected)
            if "FROM photos" in sql:
                selected = _statement_group_ids(statement)
                loaded_photo_group_ids.update(str(group_id) for group_id in selected)
                return Result(photo for group_id in selected for photo in photos_by_group_id[str(group_id)])
            raise AssertionError(sql)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return FakeSession()

    def photo_payload(photo):
        return {
            "id": photo.legacy_id,
            "category": photo.category,
            "sha256": photo.sha256,
            "is_active": photo.is_active,
            "upload_status": photo.upload_status,
        }

    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: team_id)
    monkeypatch.setattr(repository, "_photo_payload", photo_payload)

    result = TestPostgresRepository().list_photo_barcode_review_groups(
        status="all",
        query="",
        limit=20,
        offset=offset,
    )

    assert result["total"] == 45
    assert [item["group_id"] for item in result["items"]] == expected_ids
    assert len(statements) == 4
    compiled = "\n".join(
        str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for statement in statements
    )
    assert "JOIN group_barcode_verifications" in compiled
    assert "LIMIT 20" in compiled
    assert f"OFFSET {offset}" in compiled
    assert loaded_photo_group_ids == {str(groups[index].id) for index in range(offset, min(offset + 20, 45))}


def test_postgres_review_eligibility_counts_every_valid_photo_before_category_matching() -> None:
    subquery = repository._eligible_group_photo_set_subquery("eligibility-team")

    compiled = str(
        subquery.select().compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    where_sql, having_sql = compiled.split("HAVING", maxsplit=1)

    assert "count(photos.id) = 4" in having_sql
    assert "count(DISTINCT photos.category) = 4" in having_sql
    assert "sum(CASE WHEN (photos.category IN" in having_sql
    assert "photos.category IN" not in where_sql


def _statement_group_ids(statement) -> list:
    for criterion in getattr(statement, "_where_criteria", ()):
        right = getattr(criterion, "right", None)
        value = getattr(right, "value", None)
        if isinstance(value, (list, tuple, set)):
            return list(value)
    raise AssertionError("expected a bounded group_id IN predicate")
