from __future__ import annotations

import ast
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import inspect
import logging
from typing import get_type_hints
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.models import AuditLog, GroupBarcodeVerification
from app.services import state_repository as repository
from app.services.construction_priority_import import PriorityImportRow
from app.services.group_barcode_verification import GroupScanResult, evaluate_group_eligibility
from app.services.final_delivery_export import LeasedDeliveryPackage
from app.services.export_retirement import ExportCenterRetiredError, RETIREMENT_MESSAGE


class _ExplodingRetiredDeliveryDependency:
    def __getattribute__(self, _name):
        raise AssertionError("retired delivery producer touched a dependency")

    def __iter__(self):
        raise AssertionError("retired delivery producer iterated a dependency")


class _TrackingRetiredDeliveryDependency:
    def __init__(self) -> None:
        self.touched = False

    def __getattribute__(self, name):
        if name == "touched":
            return object.__getattribute__(self, name)
        object.__setattr__(self, "touched", True)
        raise RuntimeError("retired delivery producer touched a dependency")


def test_task_payload_project_identity_is_not_hard_coded() -> None:
    project_id = uuid4()
    task = SimpleNamespace(
        id=uuid4(),
        legacy_id=7,
        project_id=project_id,
        terminal="T-007",
        title="终端 7",
        status="published",
        review_claimed_by=None,
        claimed_at=None,
        released_at=None,
        construction_enabled=True,
        construction_claimed_by=None,
        construction_claimed_at=None,
        construction_priority=False,
        construction_priority_updated_by=None,
        construction_priority_updated_at=None,
    )
    assert repository._task_payload(task)["project_id"] == str(project_id)


def test_postgres_delivery_enqueue_compatibility_hook_is_noop_before_dependencies() -> None:
    dependency = _TrackingRetiredDeliveryDependency()
    assert (
        repository.PostgresStateRepository._enqueue_delivery_cache_after_commit(
            dependency,
            "group-1",
            actor="tester",
            reason="photo changed",
            require_eligible=True,
        )
        is None
    )
    assert dependency.touched is False


@pytest.mark.parametrize(
    "repository_type",
    [
        repository.StateRepository,
        repository.JsonStateRepository,
        repository.PostgresStateRepository,
        repository.DualWriteStateRepository,
    ],
)
def test_direct_delivery_create_export_job_is_retired_before_dependencies(repository_type) -> None:
    with pytest.raises(ExportCenterRetiredError, match=RETIREMENT_MESSAGE):
        repository_type.create_export_job(
            _ExplodingRetiredDeliveryDependency(),
            job_type="final_delivery",
            filters=_ExplodingRetiredDeliveryDependency(),
            actor="tester",
        )


@pytest.mark.parametrize(
    "repository_type",
    [
        repository.StateRepository,
        repository.JsonStateRepository,
        repository.PostgresStateRepository,
        repository.DualWriteStateRepository,
    ],
)
@pytest.mark.parametrize(
    "method_name",
    [
        "request_final_delivery_export",
        "build_final_delivery_export",
        "build_final_delivery_manifest",
    ],
)
def test_direct_final_delivery_service_calls_are_retired_before_dependencies(
    repository_type,
    method_name: str,
) -> None:
    with pytest.raises(ExportCenterRetiredError, match=RETIREMENT_MESSAGE):
        getattr(repository_type, method_name)(_ExplodingRetiredDeliveryDependency())


def group_scan_result(*, status: str = "partial", passed_count: int = 2) -> GroupScanResult:
    matched_fields = {
        3: ["meter", "module", "collector"],
        2: ["meter", "collector"],
        1: ["meter"],
    }.get(passed_count, [])
    return GroupScanResult(
        status=status,
        passed_count=passed_count,
        machine_barcode_values=["M-VERIFY-001", "C-VERIFY-001"],
        machine_qr_values=[],
        ocr_candidates=["MOD-VERIFY-001"],
        matched_fields=matched_fields,
        missing_fields=[field for field in ("meter", "module", "collector") if field not in matched_fields],
        unmatched_machine_values=[],
        matched_ocr_candidates=["MOD-VERIFY-001"],
        unmatched_ocr_candidates=[],
    )


@pytest.mark.parametrize(
    "repository_type",
    [
        repository.StateRepository,
        repository.JsonStateRepository,
        repository.PostgresStateRepository,
        repository.DualWriteStateRepository,
    ],
)
def test_final_delivery_export_public_return_type_is_leased_package(repository_type) -> None:
    annotation = get_type_hints(repository_type.build_final_delivery_export)["return"]
    assert annotation is LeasedDeliveryPackage


def test_data_center_contract_is_available_on_all_repository_backends() -> None:
    from app.schemas.data_center import DataCenterQuery

    query = DataCenterQuery(page=1, page_size=20)
    assert query.page_size == 20
    for repository_type in (
        repository.StateRepository,
        repository.JsonStateRepository,
        repository.PostgresStateRepository,
        repository.DualWriteStateRepository,
    ):
        assert hasattr(repository_type, "list_data_center_rows")
        assert hasattr(repository_type, "get_data_center_detail")
        hints = get_type_hints(repository_type.list_data_center_rows)
        assert hints["query"] is DataCenterQuery


def test_postgres_group_payload_exposes_persisted_anomaly_resolution_history() -> None:
    resolutions = {
        "module_missing": {
            "evidence_fingerprint": "a" * 64,
            "resolved_by": "admin-a",
            "resolved_at": "2026-08-29T10:00:00+08:00",
        }
    }
    group = SimpleNamespace(
        id=uuid4(),
        legacy_id="g-anomaly",
        legacy_task_id=1,
        display_meter_no="METER-001",
        meter_match_key="METER-001",
        terminal="350000000001",
        installation_address="一号路 1 号",
        status=repository.GroupStatus.UNREVIEWED,
        photo_count=0,
        reviewer=None,
        reviewed_at=None,
        review_note="",
        exception_note="",
        exception_reasons=[],
        has_archive_blocker=False,
        task_id=None,
        raw_data={repository.data_center_service.ANOMALY_RESOLUTIONS_KEY: resolutions},
    )

    payload = repository._group_payload(object(), group, include_photos=False, verification=None)

    assert payload[repository.data_center_service.ANOMALY_RESOLUTIONS_KEY] == resolutions


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


@pytest.mark.parametrize(
    ("operation", "args", "kwargs"),
    [
        ("clear_scan_data", (), {}),
        (
            "submit_construction_exception_order",
            ("order-json",),
            {"actor": "constructor-a", "updates": {}, "note": "done"},
        ),
        (
            "reset_group_to_unconstructed",
            ("group-json",),
            {"actor": "admin-a", "reason": "reset", "force": True},
        ),
        (
            "reset_group_to_unreviewed",
            ("group-json",),
            {"actor": "admin-a", "reason": "reset", "force": True},
        ),
        (
            "bulk_archive_groups",
            (["group-json"],),
            {"actor": "admin-a", "reason": "archive"},
        ),
        (
            "return_group_to_exception_order",
            ("group-json",),
            {
                "actor": "admin-a",
                "category": "other",
                "note": "needs work",
                "force": True,
            },
        ),
    ],
)
def test_json_delivery_mutations_roll_back_when_authoritative_persistence_fails(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    args: tuple,
    kwargs: dict,
) -> None:
    team_id = f"json-authoritative-{operation}-{uuid4()}"
    state = repository.local_simulation.blank_state(team_id)
    before = deepcopy(state)
    monkeypatch.setitem(repository.local_simulation._team_states, team_id, state)
    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: team_id)

    def mutate_private_state(*_args, **_kwargs):
        repository.local_simulation.get_state()["audit_events"].append(
            {"id": operation, "action": operation, "actor": "test", "payload": {}}
        )
        if operation == "clear_scan_data":
            return {"summary": {}, "paths": {}}
        return {"operation": operation}

    monkeypatch.setattr(repository.local_simulation, operation, mutate_private_state)
    monkeypatch.setattr(
        repository.local_simulation,
        "save_all_team_states",
        lambda: (_ for _ in ()).throw(RuntimeError("injected authoritative persistence failure")),
    )

    with pytest.raises(RuntimeError, match="injected authoritative persistence failure"):
        getattr(repository.JsonStateRepository(), operation)(*args, **kwargs)

    assert repository.local_simulation._team_states[team_id] == before


def test_postgres_delivery_invalidation_is_retired_before_batch_queries() -> None:
    from app.services import delivery_cache

    assert hasattr(delivery_cache, "invalidate_postgres_delivery_cache_for_group_changes")
    team_id = "batch-invalidation-team"
    groups = [
        SimpleNamespace(id=uuid4(), legacy_id=f"group-{index}", team_id=team_id, raw_data={})
        for index in range(2)
    ]
    photos = [
        SimpleNamespace(group_id=group.id, raw_data={"delivery_cache_status": "ready"})
        for group in groups
    ]
    jobs = [
        SimpleNamespace(
            group_id=group.id,
            status="ready",
            evidence_version=1,
            lease_owner="worker",
            lease_token="lease",
            lease_expires_at=datetime.now(UTC),
            last_error=None,
            completed_at=datetime.now(UTC),
        )
        for group in groups
    ]
    package_job = SimpleNamespace(
        group_ids=[str(groups[0].id), groups[1].legacy_id],
        status="ready",
        lease_owner="worker",
        lease_token="lease",
        lease_expires_at=datetime.now(UTC),
        package_path="package.zip",
        content_sha256="a" * 64,
        size_bytes=123,
        last_error=None,
        completed_at=datetime.now(UTC),
    )

    class Scalars:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

    class BatchInvalidationSession:
        def __init__(self):
            self.statements = []
            self.results = iter((photos, jobs, [package_job]))
            self.flushes = 0

        def scalars(self, statement):
            self.statements.append(statement)
            return Scalars(next(self.results))

        def flush(self):
            self.flushes += 1

    session = BatchInvalidationSession()

    delivery_cache.invalidate_postgres_delivery_cache_for_group_changes(
        session,
        groups,
        actor="scan-import",
        reason="scan_import_changed",
    )

    assert session.statements == []
    assert session.flushes == 0
    assert all(group.raw_data == {} for group in groups)
    assert all(photo.raw_data["delivery_cache_status"] == "ready" for photo in photos)
    assert all(job.status == "ready" for job in jobs)
    assert package_job.status == "ready"


def test_postgres_unified_invalidation_preserves_history_and_clears_passed_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    group_id = uuid4()
    photos = [
        SimpleNamespace(
            id=uuid4(),
            legacy_id=f"photo-{index}",
            sha256=f"{index + 1:x}" * 64,
            category=category,
            is_active=True,
            raw_data={
                "construction_slot": category,
                "delivery_cache_path": f"objects/{index}/photo.jpg",
                "delivery_cache_status": "ready",
            },
        )
        for index, category in enumerate(
            ["before_box", "collector_barcode", "module_meter", "after_box"]
        )
    ]
    group = SimpleNamespace(
        id=group_id,
        legacy_id="group-verify",
        team_id="verify-team",
        terminal="T-VERIFY-001",
        display_meter_no="M-VERIFY-001",
        raw_data={
            "collector": "C-VERIFY-001",
            "module_asset_no": "MOD-VERIFY-001",
            "delivery_cache_status": "ready",
            "group_barcode_manual_confirmed": False,
            "group_barcode_manual_confirmed_fields": [],
            "group_barcode_manual_confirmed_by": "",
            "group_barcode_manual_confirmed_at": "",
            "group_barcode_manual_confirmation_reason": "",
            "group_barcode_manual_confirmation_photo_ids": [],
        },
    )
    delivery_group_before = deepcopy(group.raw_data)
    delivery_photos_before = [deepcopy(photo.raw_data) for photo in photos]
    verification = GroupBarcodeVerification(
        team_id="verify-team",
        group_id=group_id,
        status="passed",
        evidence_fingerprint="old-fingerprint",
        evidence_version=4,
        meter_matched=True,
        module_matched=True,
        collector_matched=True,
        recognition_source="legacy-worker",
        attempt_count=2,
    )
    previous_audit = AuditLog(
        team_id="verify-team",
        legacy_id="verification-passed-history",
        actor_username="worker-a",
        action="group_barcode_verification_passed",
        entity_type="material_group",
        entity_id=group_id,
        before_data={},
        after_data={},
        payload={},
    )

    class FakeScalars:
        def all(self):
            return photos

    class FakeSession:
        def __init__(self) -> None:
            self.staged = [previous_audit]
            self.photo_queries = 0

        def scalar(self, statement):
            sql = str(statement)
            if "group_barcode_verifications" in sql:
                return verification
            raise AssertionError(sql)

        def scalars(self, statement):
            assert "FROM photos" in str(statement)
            self.photo_queries += 1
            if self.photo_queries > 1:
                raise AssertionError("verification invalidation queried retired delivery photos")
            return FakeScalars()

        def add(self, value) -> None:
            self.staged.append(value)

        def flush(self) -> None:
            return None

    session = FakeSession()
    monkeypatch.setattr(
        delivery_cache,
        "postgres_delivery_group_payload",
        _ExplodingRetiredDeliveryDependency(),
    )
    monkeypatch.setattr(
        delivery_cache,
        "sync_postgres_delivery_cache_job_for_group",
        _ExplodingRetiredDeliveryDependency(),
    )

    result = repository.invalidate_verification_for_group(
        session,
        group,
        actor="reviewer-a",
        reason="photo_replaced",
    )

    assert result["status"] == "pending"
    assert verification.status == "pending"
    assert verification.evidence_version == 5
    assert verification.meter_matched is None
    assert verification.module_matched is None
    assert verification.collector_matched is None
    assert verification.recognition_source is None
    assert verification.invalidation_reason == "photo_replaced"
    assert verification.invalidated_by == "reviewer-a"
    assert verification.invalidated_at is not None
    assert group.raw_data == delivery_group_before
    assert [photo.raw_data for photo in photos] == delivery_photos_before
    assert previous_audit in session.staged
    invalidation_audit = next(
        event for event in session.staged if event.action == "group_barcode_verification_invalidated"
    )
    assert invalidation_audit.payload["group_id"] == "group-verify"
    assert invalidation_audit.payload["reason"] == "photo_replaced"


def test_json_unified_invalidation_preserves_completed_delivery_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    group = {
        "id": "json-cache-invalidation",
        "terminal": "00112233",
        "meter_no": "000011112222",
        "collector": "00005555",
        "module_asset_no": "000033334444",
        "barcode_verification": {
            "status": "passed",
            "evidence_fingerprint": "a" * 64,
            "evidence_version": 3,
        },
        "delivery_cache_status": "ready",
        "photos": [
            {
                "id": f"photo-{index}",
                "sha256": f"{index:x}" * 64,
                "category": category,
                "is_active": True,
                "delivery_cache_path": f"objects/{index}/photo.jpg",
                "delivery_cache_status": "ready",
            }
            for index, category in enumerate(
                ("before_box", "collector_barcode", "module_meter", "after_box"),
                start=1,
            )
        ],
    }
    delivery_before = deepcopy(
        {
            "delivery_cache_status": group["delivery_cache_status"],
            "photos": group["photos"],
        }
    )
    monkeypatch.setattr(
        repository.local_simulation,
        "mark_delivery_cache_stale",
        _ExplodingRetiredDeliveryDependency(),
    )
    monkeypatch.setattr(
        delivery_cache,
        "sync_json_delivery_cache_job_for_group",
        _ExplodingRetiredDeliveryDependency(),
    )

    repository.invalidate_verification_for_group(None, group, actor="reviewer-a", reason="photo_category_changed")

    assert group["barcode_verification"]["status"] == "pending"
    assert {
        "delivery_cache_status": group["delivery_cache_status"],
        "photos": group["photos"],
    } == delivery_before


@pytest.mark.parametrize(
    "historical_photo",
    [
        {"id": "inactive", "sha256": "e" * 64, "category": "other", "is_active": False},
        {"id": "invalid", "sha256": "e" * 64, "category": "other", "upload_status": "invalid"},
    ],
    ids=["inactive", "invalid"],
)
def test_json_and_postgres_verification_payloads_ignore_historical_non_evidence_photos(
    historical_photo: dict,
) -> None:
    categories = ["before_box", "collector_barcode", "module_meter", "after_box"]
    json_group = {
        "terminal": "T-VERIFY-001",
        "meter_no": "M-VERIFY-001",
        "collector": "C-VERIFY-001",
        "module_asset_no": "MOD-VERIFY-001",
        "photos": [
            {"id": category, "sha256": f"{index + 1:x}" * 64, "category": category}
            for index, category in enumerate(categories)
        ] + [historical_photo],
    }
    postgres_group = SimpleNamespace(
        id="group-verify",
        team_id="verify-team",
        terminal="T-VERIFY-001",
        display_meter_no="M-VERIFY-001",
        raw_data={"construction_collector": "C-VERIFY-001", "construction_module_asset_no": "MOD-VERIFY-001"},
    )
    postgres_photos = [
        SimpleNamespace(
            id=f"pg-{category}",
            legacy_id=f"pg-{category}",
            sha256=f"{index + 1:x}" * 64,
            category=category,
            is_active=True,
            upload_status="uploaded",
        )
        for index, category in enumerate(categories)
    ]
    postgres_photos.append(
        SimpleNamespace(
            id="pg-history",
            legacy_id="pg-history",
            sha256="e" * 64,
            category="other",
            is_active=historical_photo.get("is_active", True),
            upload_status=historical_photo.get("upload_status", "uploaded"),
        )
    )

    class FakeSession:
        def scalars(self, _statement):
            return SimpleNamespace(all=lambda: postgres_photos)

    assert evaluate_group_eligibility(repository._verification_group_payload(None, json_group)).status == "pending"
    assert evaluate_group_eligibility(
        repository._verification_group_payload(FakeSession(), postgres_group)
    ).status == "pending"


def test_postgres_verification_payload_defers_blank_identity_selection_to_shared_normalizer() -> None:
    group = SimpleNamespace(
        id=uuid4(),
        legacy_id="blank-construction-identity",
        team_id="verify-team",
        terminal="T-VERIFY-002",
        display_meter_no="M-VERIFY-002",
        raw_data={
            "construction_collector": "   ",
            "collector": "COL-TOP",
            "construction_module_asset_no": "\t",
            "module_asset_no": "MOD-TOP",
        },
    )

    payload = repository._verification_group_payload(None, group, prefetched_photos=[])

    assert payload["collector"] == "COL-TOP"
    assert payload["module_asset_no"] == "MOD-TOP"


def test_postgres_verification_payload_uses_photo_identity_fallbacks() -> None:
    group = SimpleNamespace(
        id=uuid4(),
        legacy_id="photo-identity-fallback",
        team_id="verify-team",
        terminal="T-VERIFY-003",
        display_meter_no="M-VERIFY-003",
        raw_data={},
    )
    categories = ("before_box", "collector_barcode", "module_meter", "after_box")
    photos = [
        SimpleNamespace(
            id=uuid4(),
            legacy_id=f"photo-identity-{index}",
            sha256=f"{index:x}" * 64,
            category=category,
            is_active=True,
            upload_status="uploaded",
            collector="COL-PHOTO" if index == 1 else "",
            asset_no="MOD-PHOTO" if index == 1 else "",
            image_url="",
            source_url="",
            storage_type="",
            storage_bucket="",
            storage_key="",
        )
        for index, category in enumerate(categories, start=1)
    ]

    payload = repository._verification_group_payload(None, group, prefetched_photos=photos)
    eligibility = evaluate_group_eligibility(payload)

    assert payload["collector"] == "COL-PHOTO"
    assert payload["module_asset_no"] == "MOD-PHOTO"
    assert eligibility.status == "pending"
    assert eligibility.evidence_fingerprint


def _postgres_barcode_claim_fixture():
    group_id = uuid4()
    group = SimpleNamespace(
        id=group_id,
        legacy_id="group-claim",
        team_id="claim-team",
        terminal="T-VERIFY-001",
        display_meter_no="M-VERIFY-001",
        raw_data={"collector": "C-VERIFY-001", "module_asset_no": "MOD-VERIFY-001"},
    )
    categories = ["before_box", "collector_barcode", "module_meter", "after_box"]
    photos = [
        SimpleNamespace(
            id=uuid4(),
            legacy_id=f"claim-photo-{index}",
            team_id="claim-team",
            group_id=group_id,
            sha256=f"{index + 1:x}" * 64,
            category=category,
            is_active=True,
            upload_status="uploaded",
        )
        for index, category in enumerate(categories)
    ]
    payload = repository._verification_group_payload(
        SimpleNamespace(scalars=lambda _statement: SimpleNamespace(all=lambda: photos)),
        group,
    )
    fingerprint = evaluate_group_eligibility(payload).evidence_fingerprint
    assert fingerprint
    verification = SimpleNamespace(
        status="processing",
        evidence_fingerprint=fingerprint,
        evidence_version=7,
        meter_matched=None,
        module_matched=None,
        collector_matched=None,
        recognition_source=None,
        attempt_count=1,
        lease_owner="worker-new",
        lease_token="lease-new",
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        invalidation_reason=None,
        invalidated_by=None,
        invalidated_at=None,
    )
    return group, photos, verification, fingerprint


def test_postgres_apply_group_scan_result_rejects_stale_claim_under_row_lock() -> None:
    group, photos, verification, fingerprint = _postgres_barcode_claim_fixture()

    class FakeSession:
        def __init__(self) -> None:
            self.commits = 0
            self.verification_locked = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, statement):
            self.verification_locked = getattr(statement, "_for_update_arg", None) is not None
            return verification

        def scalars(self, _statement):
            return SimpleNamespace(all=lambda: photos)

        def commit(self) -> None:
            self.commits += 1

        def refresh(self, _value) -> None:
            return None

    session = FakeSession()

    class TestRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

        def _group_by_legacy_id(self, _session, group_id: str, *, lock: bool = False):
            assert group_id == "group-claim"
            assert lock is True
            return group

    before = deepcopy(vars(verification))
    applied = TestRepository().apply_group_scan_result(
        "group-claim",
        group_scan_result(),
        claimed_evidence_fingerprint=fingerprint,
        claimed_evidence_version=6,
        lease_owner="worker-old",
        lease_token="lease-old",
        actor="barcode-worker",
    )

    assert applied["applied"] is False
    assert vars(verification) == before
    assert session.verification_locked is True
    assert session.commits == 0


def test_postgres_apply_group_scan_result_persists_only_the_locked_matching_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group, photos, verification, fingerprint = _postgres_barcode_claim_fixture()
    staged_audits = []

    class FakeSession:
        def __init__(self) -> None:
            self.commits = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, statement):
            assert getattr(statement, "_for_update_arg", None) is not None
            return verification

        def scalars(self, _statement):
            return SimpleNamespace(all=lambda: photos)

        def add(self, _value) -> None:
            return None

        def commit(self) -> None:
            self.commits += 1

        def refresh(self, _value) -> None:
            return None

    session = FakeSession()

    class TestRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

        def _group_by_legacy_id(self, _session, _group_id: str, *, lock: bool = False):
            assert lock is True
            return group

    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: "claim-team")
    monkeypatch.setattr(repository, "_stage_transactional_audit", lambda *_args, **kwargs: staged_audits.append(kwargs))

    applied = TestRepository().apply_group_scan_result(
        "group-claim",
        group_scan_result(),
        claimed_evidence_fingerprint=fingerprint,
        claimed_evidence_version=7,
        lease_owner="worker-new",
        lease_token="lease-new",
        actor="barcode-worker",
    )

    assert applied["applied"] is True
    assert verification.status == "partial"
    assert verification.evidence_version == 7
    assert verification.meter_matched is True
    assert verification.module_matched is False
    assert verification.collector_matched is True
    assert verification.lease_owner is None
    assert verification.lease_token is None
    assert verification.lease_expires_at is None
    assert group.raw_data["barcode_verification"]["result"]["passed_count"] == 2
    assert session.commits == 1
    assert staged_audits[0]["before_data"]["verification"]["status"] == "processing"
    assert staged_audits[0]["after_data"]["verification"]["status"] == "partial"


def _json_barcode_state(team_id: str) -> dict:
    categories = ["before_box", "collector_barcode", "module_meter", "after_box"]
    group = {
        "id": "group-json-barcode",
        "task_id": 17,
        "terminal": "T-VERIFY-001",
        "meter_no": "M-VERIFY-001",
        "collector": "C-VERIFY-001",
        "module_asset_no": "MOD-VERIFY-001",
        "photo_count": 4,
        "status": "pending",
        "reviewer": None,
        "review_note": "",
        "exception_note": "",
        "has_archive_blocker": False,
        "exception_reasons": [],
        "photos": [
            {
                "id": f"json-photo-{index}",
                "sha256": f"{index + 1:x}" * 64,
                "category": category,
                "is_active": True,
            }
            for index, category in enumerate(categories)
        ],
    }
    fingerprint = evaluate_group_eligibility(group).evidence_fingerprint
    assert fingerprint
    group["barcode_verification"] = {
        "status": "processing",
        "evidence_fingerprint": fingerprint,
        "evidence_version": 7,
        "lease_owner": "worker-json",
        "lease_token": "lease-json",
        "lease_expires_at": "2026-07-22T12:00:00+00:00",
    }
    state = repository.local_simulation.blank_state(team_id)
    state.update(
        {
            "tasks": [{"id": 17, "terminal": "T-VERIFY-001", "claimed_by": "reviewer-a"}],
            "groups": [group],
            "audit_log": [],
            "summary": repository.local_simulation.empty_summary(),
        }
    )
    return state


def test_json_apply_group_scan_result_compares_and_writes_inside_authoritative_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id = f"json-cas-{uuid4()}"
    state = _json_barcode_state(team_id)
    monkeypatch.setitem(repository.local_simulation._team_states, team_id, state)
    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: team_id)
    original_begin = repository.local_simulation.begin_authoritative_json_write
    original_finish = repository.local_simulation.finish_authoritative_json_write
    calls = []

    def tracked_begin(checked_team_id=None):
        calls.append("begin")
        return original_begin(checked_team_id)

    def tracked_finish(transaction, token, **kwargs):
        calls.append("finish")
        return original_finish(transaction, token, **kwargs)

    monkeypatch.setattr(repository.local_simulation, "begin_authoritative_json_write", tracked_begin)
    monkeypatch.setattr(repository.local_simulation, "finish_authoritative_json_write", tracked_finish)
    fingerprint = state["groups"][0]["barcode_verification"]["evidence_fingerprint"]

    result = repository.JsonStateRepository().apply_group_scan_result(
        "group-json-barcode",
        group_scan_result(),
        claimed_evidence_fingerprint=fingerprint,
        claimed_evidence_version=7,
        lease_owner="worker-json",
        lease_token="lease-json",
        actor="barcode-worker",
    )

    assert result["applied"] is True
    assert repository.local_simulation._team_states[team_id]["groups"][0]["barcode_verification"]["status"] == "partial"
    assert calls == ["begin", "finish"]


def test_json_pass_persists_archive_pending_before_worker_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id = f"json-pass-{uuid4()}"
    state = _json_barcode_state(team_id)
    monkeypatch.setitem(repository.local_simulation._team_states, team_id, state)
    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: team_id)
    fingerprint = state["groups"][0]["barcode_verification"]["evidence_fingerprint"]

    result = repository.JsonStateRepository().apply_group_scan_result(
        "group-json-barcode",
        group_scan_result(status="passed", passed_count=3),
        claimed_evidence_fingerprint=fingerprint,
        claimed_evidence_version=7,
        lease_owner="worker-json",
        lease_token="lease-json",
        actor="barcode-worker",
    )

    verification = repository.local_simulation._team_states[team_id]["groups"][0]["barcode_verification"]
    assert result["applied"] is True
    assert verification["status"] == "passed"
    assert verification["auto_archive_status"] == "pending"
    assert verification["auto_archive_attempt_count"] == 0
    assert verification["auto_archive_lease_owner"] is None
    assert verification["auto_archive_lease_token"] is None
    assert verification["auto_archive_lease_expires_at"] is None


def test_json_manual_confirmation_increments_version_and_invalidates_every_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id = f"json-confirm-{uuid4()}"
    state = _json_barcode_state(team_id)
    monkeypatch.setitem(repository.local_simulation._team_states, team_id, state)
    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: team_id)

    repository.JsonStateRepository().confirm_group_barcode_manually(
        "group-json-barcode",
        actor="reviewer-a",
        meter_no="110000288056",
        module_asset_no="MOD001",
        collector="COLLECTOR001",
        reason="现场核验",
        photo_ids=[f"json-photo-{index}" for index in range(4)],
    )

    verification = repository.local_simulation._team_states[team_id]["groups"][0]["barcode_verification"]
    assert verification["status"] == "manual_confirmed"
    assert verification["evidence_version"] == 8
    assert verification["lease_owner"] is None
    assert verification["lease_token"] is None
    assert verification["lease_expires_at"] is None
    assert verification["auto_archive_status"] == "pending"
    assert verification["auto_archive_attempt_count"] == 0
    assert verification["auto_archive_lease_owner"] is None
    assert verification["auto_archive_lease_token"] is None
    assert verification["auto_archive_lease_expires_at"] is None


def test_dual_manual_confirmation_fails_before_either_backend_or_archive_queue_mutates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id = f"dual-confirm-{uuid4()}"
    state = _json_barcode_state(team_id)
    before = deepcopy(state)
    monkeypatch.setitem(repository.local_simulation._team_states, team_id, state)
    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: team_id)

    monkeypatch.setattr(
        repository.DualWriteStateRepository,
        "postgres_repository_factory",
        staticmethod(lambda: pytest.fail("dual fail-closed must not construct the PostgreSQL writer")),
    )

    with pytest.raises(repository.StateBackendNotReady, match="before either backend mutated"):
        repository.DualWriteStateRepository().confirm_group_barcode_manually(
            "group-json-barcode",
            actor="reviewer-a",
            meter_no="110000288056",
            module_asset_no="MOD001",
            collector="COLLECTOR001",
            reason="现场核验",
            photo_ids=[f"json-photo-{index}" for index in range(4)],
        )

    assert repository.local_simulation._team_states[team_id] == before


def _prepare_json_review_cache_state(monkeypatch: pytest.MonkeyPatch, team_id: str) -> dict:
    state = _json_barcode_state(team_id)
    group = state["groups"][0]
    group["address"] = "测试地址"
    group["barcode_verification"].update(
        {
            "status": "passed",
            "meter_matched": True,
            "module_matched": True,
            "collector_matched": True,
            "result": {
                "passed_count": 3,
                "matched_fields": ["meter", "module", "collector"],
                "missing_fields": [],
            },
        }
    )
    state["delivery_cache_jobs"] = []
    monkeypatch.setitem(repository.local_simulation._team_states, team_id, state)
    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: team_id)
    return state


def test_json_review_group_persistence_failure_submits_no_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id = f"json-review-rollback-{uuid4()}"
    state = _prepare_json_review_cache_state(monkeypatch, team_id)
    before = deepcopy(state)

    def fail_persistence() -> None:
        raise RuntimeError("injected JSON review persistence failure")

    monkeypatch.setattr(repository.local_simulation, "save_all_team_states", fail_persistence)

    with pytest.raises(RuntimeError, match="injected JSON review persistence failure"):
        repository.JsonStateRepository().review_group(
            "group-json-barcode",
            "approved",
            "reviewer-a",
            "ready",
        )

    assert repository.local_simulation._team_states[team_id] == before


def test_dual_review_group_fails_before_either_backend_or_cache_queue_mutates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id = f"dual-review-rollback-{uuid4()}"
    state = _prepare_json_review_cache_state(monkeypatch, team_id)
    before = deepcopy(state)

    monkeypatch.setattr(
        repository.DualWriteStateRepository,
        "postgres_repository_factory",
        staticmethod(lambda: pytest.fail("dual fail-closed must not construct the PostgreSQL writer")),
    )

    with pytest.raises(repository.StateBackendNotReady, match="before either backend mutated"):
        repository.DualWriteStateRepository().review_group(
            "group-json-barcode",
            "approved",
            "reviewer-a",
            "ready",
        )

    assert repository.local_simulation._team_states[team_id] == before


def test_postgres_nonapproved_review_invalidates_delivery_cache_before_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models import GroupStatus
    from app.services import delivery_cache

    events: list[str] = []
    group = SimpleNamespace(
        id=uuid4(),
        team_id="team-a",
        legacy_id="group-a",
        status=GroupStatus.APPROVED,
        reviewer="reviewer-a",
        review_note="",
        exception_note="",
        reviewed_at=None,
        raw_data={"status": "approved", "delivery_cache_status": "ready"},
    )

    class Session:
        def commit(self):
            events.append("commit")

        def refresh(self, _value):
            return None

    session = Session()

    class ReviewRepository(repository.PostgresStateRepository):
        def _session(self):
            return nullcontext(session)

        def _group_by_legacy_id(self, checked_session, group_id: str, *, lock: bool = False):
            assert checked_session is session
            assert group_id == "group-a"
            assert lock is True
            return group

        def _ensure_task_claimed_by(self, checked_session, checked_group, actor: str, *, force: bool = False):
            assert checked_session is session
            assert checked_group is group
            assert actor == "reviewer-a"

    def invalidate(checked_session, checked_group, *, actor: str, reason: str):
        assert checked_session is session
        assert checked_group is group
        assert group.status == GroupStatus.REJECTED
        assert events == []
        assert actor == "reviewer-a"
        assert reason == "review_rejected"
        events.append("invalidate")

    monkeypatch.setattr(delivery_cache, "invalidate_postgres_delivery_cache_for_group_change", invalidate)
    monkeypatch.setattr(
        repository,
        "_group_payload",
        lambda _session, checked_group: {"id": checked_group.legacy_id, "status": "rejected"},
    )

    result = ReviewRepository().review_group("group-a", "rejected", "reviewer-a")

    assert result["status"] == "rejected"
    assert events == ["invalidate", "commit"]


def _postgres_exception_review_fixture(*, resolved: bool):
    photos = [
        {
            "id": f"photo-{category}",
            "legacy_id": f"photo-{category}",
            "category": category,
            "sha256": category,
            "is_active": True,
        }
        for category in ("before_box", "collector_barcode", "module_meter", "after_box")
    ]
    group = SimpleNamespace(
        id=uuid4(),
        team_id="approved-exception-team",
        legacy_id="approved-exception-group",
        status=repository.GroupStatus.REJECTED,
        reviewer="reviewer-a",
        review_note="",
        exception_status="open",
        exception_note="人工异常",
        exception_reasons=["manual_quality"],
        has_archive_blocker=True,
        reviewed_at=None,
        raw_data={"status": "exception"},
    )

    def payload():
        return {
            "id": group.legacy_id,
            "status": repository._status_value(group.status),
            "terminal": "350000441152",
            "meter_no": "3130001201100256152333",
            "module_asset_no": "MODULE-001",
            "collector": "COLLECTOR-001",
            "address": "测试地址",
            "photo_count": len(photos),
            "photos": photos,
            "barcode_verification": {"status": "passed"},
            "exception_status": str(group.exception_status or ""),
            "exception_note": group.exception_note,
            "exception_reasons": list(group.exception_reasons),
            "has_archive_blocker": group.has_archive_blocker,
            repository.data_center_service.ANOMALY_RESOLUTIONS_KEY: dict(
                group.raw_data.get(repository.data_center_service.ANOMALY_RESOLUTIONS_KEY) or {}
            ),
        }

    anomalies = repository.data_center_service.group_anomalies(payload())
    if resolved:
        fingerprint = anomalies[0]["evidence_fingerprint"]
        group.raw_data[repository.data_center_service.ANOMALY_RESOLUTIONS_KEY] = {
            anomaly["code"]: {
                "evidence_fingerprint": fingerprint,
                "message": anomaly["message"],
                "resolved_by": "module_admin",
                "resolved_at": "2026-08-29T18:47:02+08:00",
                "source_page": "review_rephoto_workbench",
            }
            for anomaly in anomalies
        }
    return group, payload


def test_postgres_approved_review_closes_resolved_exception_state_and_keeps_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group, payload = _postgres_exception_review_fixture(resolved=True)

    class Session:
        def commit(self):
            return None

        def refresh(self, _value):
            return None

    session = Session()

    class ReviewRepository(repository.PostgresStateRepository):
        def _session(self):
            return nullcontext(session)

        def _group_by_legacy_id(self, checked_session, group_id: str, *, lock: bool = False):
            assert checked_session is session
            assert group_id == group.legacy_id
            assert lock is True
            return group

        def _ensure_task_claimed_by(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(repository, "_group_payload", lambda _session, _group: payload())

    ReviewRepository().review_group(group.legacy_id, "approved", "module_admin", "资料核对完成")

    assert group.status == repository.GroupStatus.APPROVED
    assert group.exception_status in {None, ""}
    assert group.has_archive_blocker is False
    assert group.exception_reasons == ["manual_quality"]
    assert group.exception_note == "人工异常"
    assert group.raw_data["exception_status"] == ""
    assert group.raw_data["has_archive_blocker"] is False
    history = group.raw_data[repository.data_center_service.ANOMALY_RESOLUTIONS_KEY]
    assert history
    assert all(item["resolved_by"] == "module_admin" for item in history.values())
    assert all(item["status"] == "resolved" for item in repository.data_center_service.group_anomalies(payload()))


def test_postgres_approval_is_not_blocked_by_collector_only_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches PostgreSQL approval requiring confirmation for a retired collector-only gap."""
    group, base_payload = _postgres_exception_review_fixture(resolved=False)
    group.exception_note = "缺少采集器信息"
    group.exception_reasons = ["missing_collector_info"]

    def payload():
        value = base_payload()
        value.update(
            {
                "collector": "",
                "construction_collector": "",
                "barcode_verification": {
                    "status": "mismatch",
                    "result": {
                        "matched_fields": ["meter", "module"],
                        "missing_fields": ["collector"],
                    },
                },
            }
        )
        return value

    class Session:
        committed = False

        def commit(self):
            self.committed = True

        def refresh(self, _value):
            return None

    session = Session()

    class ReviewRepository(repository.PostgresStateRepository):
        def _session(self):
            return nullcontext(session)

        def _group_by_legacy_id(self, checked_session, group_id: str, *, lock: bool = False):
            assert checked_session is session
            assert group_id == group.legacy_id
            assert lock is True
            return group

    monkeypatch.setattr(repository, "_group_payload", lambda _session, _group: payload())

    reviewed = ReviewRepository().review_group(group.legacy_id, "approved", "module_admin")

    assert session.committed is True
    assert reviewed["status"] == "approved"
    assert group.exception_status in {None, ""}
    assert group.has_archive_blocker is False
    assert repository.data_center_service.group_anomalies(payload()) == []


def test_postgres_approved_review_rejects_unconfirmed_current_anomaly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group, payload = _postgres_exception_review_fixture(resolved=False)

    class Session:
        def commit(self):
            pytest.fail("unconfirmed approval must not commit")

        def refresh(self, _value):
            return None

    session = Session()

    class ReviewRepository(repository.PostgresStateRepository):
        def _session(self):
            return nullcontext(session)

        def _group_by_legacy_id(self, *_args, **_kwargs):
            return group

        def _ensure_task_claimed_by(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(repository, "_group_payload", lambda _session, _group: payload())

    with pytest.raises(ValueError, match="未确认"):
        ReviewRepository().review_group(group.legacy_id, "approved", "module_admin")

    assert group.status == repository.GroupStatus.REJECTED
    assert group.exception_status == "open"
    assert group.has_archive_blocker is True


def test_postgres_approved_review_bulk_resolves_current_anomalies_and_stages_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches PostgreSQL approval committing without atomic anomaly resolutions and audit."""
    group, payload = _postgres_exception_review_fixture(resolved=False)
    anomalies = repository.data_center_service.group_anomalies(payload())
    expected = {item["code"]: item["evidence_fingerprint"] for item in anomalies}
    audits: list[dict[str, object]] = []

    class Session:
        committed = False

        def commit(self):
            self.committed = True

        def refresh(self, _value):
            return None

    session = Session()

    class ReviewRepository(repository.PostgresStateRepository):
        def _session(self):
            return nullcontext(session)

        def _group_by_legacy_id(self, checked_session, group_id: str, *, lock: bool = False):
            assert checked_session is session
            assert group_id == group.legacy_id
            assert lock is True
            return group

    monkeypatch.setattr(repository, "_group_payload", lambda _session, _group: payload())
    monkeypatch.setattr(repository, "_stage_transactional_audit", lambda _session, **kwargs: audits.append(kwargs))

    reviewed = ReviewRepository().review_group(
        group.legacy_id,
        "approved",
        "module_admin",
        "全部异常已人工核实",
        resolve_all_anomalies=True,
        expected_open_anomalies=expected,
        source_page="review_rephoto_workbench",
    )

    assert session.committed is True
    assert reviewed["status"] == "approved"
    resolutions = group.raw_data[repository.data_center_service.ANOMALY_RESOLUTIONS_KEY]
    assert set(resolutions) == set(expected)
    assert all(item["resolved_by"] == "module_admin" for item in resolutions.values())
    assert all(item["source_page"] == "review_rephoto_workbench" for item in resolutions.values())
    assert {
        code: item["confirmed_evidence_fingerprint"]
        for code, item in resolutions.items()
    } == expected
    per_anomaly_audits = [
        audit for audit in audits if audit["action"] == "data_center_anomaly_resolved"
    ]
    assert len(per_anomaly_audits) == len(expected)
    assert {
        audit["payload"]["anomaly_code"]: audit["payload"]["confirmed_evidence_fingerprint"]
        for audit in per_anomaly_audits
    } == expected
    bulk_audits = [
        audit
        for audit in audits
        if audit["action"] == "data_center_anomalies_bulk_resolved_on_approval"
    ]
    assert len(bulk_audits) == 1
    assert bulk_audits[0]["payload"]["anomaly_count"] == len(expected)
    assert bulk_audits[0]["payload"]["anomaly_codes"] == sorted(expected)


def test_postgres_approved_review_bulk_rejects_changed_snapshot_before_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches PostgreSQL accepting a bulk decision for evidence the admin did not confirm."""
    group, payload = _postgres_exception_review_fixture(resolved=False)
    anomalies = repository.data_center_service.group_anomalies(payload())
    expected = {item["code"]: item["evidence_fingerprint"] for item in anomalies}
    expected[next(iter(expected))] = "0" * 64
    audits: list[dict[str, object]] = []

    class Session:
        def commit(self):
            pytest.fail("changed anomaly evidence must not commit")

        def refresh(self, _value):
            return None

    session = Session()

    class ReviewRepository(repository.PostgresStateRepository):
        def _session(self):
            return nullcontext(session)

        def _group_by_legacy_id(self, *_args, **_kwargs):
            return group

    monkeypatch.setattr(repository, "_group_payload", lambda _session, _group: payload())
    monkeypatch.setattr(repository, "_stage_transactional_audit", lambda _session, **kwargs: audits.append(kwargs))

    with pytest.raises(repository.AnomalyResolutionConflict, match="变化"):
        ReviewRepository().review_group(
            group.legacy_id,
            "approved",
            "module_admin",
            resolve_all_anomalies=True,
            expected_open_anomalies=expected,
        )

    assert group.status == repository.GroupStatus.REJECTED
    assert group.raw_data == {"status": "exception"}
    assert audits == []


def test_postgres_incomplete_review_rejects_unconfirmed_anomaly_without_exception_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group, payload = _postgres_exception_review_fixture(resolved=False)
    group.status = repository.GroupStatus.INCOMPLETE
    group.exception_status = ""
    group.has_archive_blocker = False
    group.raw_data = {"status": "incomplete"}

    class Session:
        def commit(self):
            pytest.fail("unconfirmed approval must not commit")

        def refresh(self, _value):
            return None

    session = Session()

    class ReviewRepository(repository.PostgresStateRepository):
        def _session(self):
            return nullcontext(session)

        def _group_by_legacy_id(self, *_args, **_kwargs):
            return group

        def _ensure_task_claimed_by(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(repository, "_group_payload", lambda _session, _group: payload())

    with pytest.raises(ValueError, match="未确认"):
        ReviewRepository().review_group(group.legacy_id, "approved", "module_admin")

    assert group.status == repository.GroupStatus.INCOMPLETE
    assert group.exception_status == ""
    assert group.has_archive_blocker is False


def test_postgres_review_does_not_consult_removed_reviewer_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models import GroupStatus
    from app.services import delivery_cache

    group = SimpleNamespace(
        id=uuid4(),
        team_id="team-a",
        legacy_id="group-a",
        status=GroupStatus.REJECTED,
        reviewer="former-reviewer",
        review_note="",
        exception_note="legacy exception",
        reviewed_at=None,
        raw_data={"status": "exception"},
    )

    class Session:
        def commit(self):
            return None

        def refresh(self, _value):
            return None

    session = Session()

    class ReviewRepository(repository.PostgresStateRepository):
        def _session(self):
            return nullcontext(session)

        def _group_by_legacy_id(self, checked_session, group_id: str, *, lock: bool = False):
            assert checked_session is session
            assert group_id == "group-a"
            assert lock is True
            return group

        def _ensure_task_claimed_by(self, *_args, **_kwargs):
            pytest.fail("review must not consult the removed reviewer claim")

    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        repository,
        "_group_payload",
        lambda _session, checked_group: {
            "id": checked_group.legacy_id,
            "status": "incomplete",
        },
    )

    result = ReviewRepository().review_group(
        "group-a",
        "incomplete",
        "admin-a",
        "管理员复核",
        "资料异常",
    )

    assert result["status"] == "incomplete"
    assert group.reviewer == "admin-a"


def test_dual_scan_cas_fails_before_either_backend_or_archive_queue_mutates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id = f"dual-scan-{uuid4()}"
    state = _json_barcode_state(team_id)
    before = deepcopy(state)
    fingerprint = state["groups"][0]["barcode_verification"]["evidence_fingerprint"]
    monkeypatch.setitem(repository.local_simulation._team_states, team_id, state)
    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: team_id)
    monkeypatch.setattr(
        repository.DualWriteStateRepository,
        "postgres_repository_factory",
        staticmethod(lambda: pytest.fail("dual fail-closed must not construct the PostgreSQL writer")),
    )

    with pytest.raises(repository.StateBackendNotReady, match="before either backend mutated"):
        repository.DualWriteStateRepository().apply_group_scan_result(
            "group-json-barcode",
            group_scan_result(status="passed", passed_count=3),
            claimed_evidence_fingerprint=fingerprint,
            claimed_evidence_version=7,
            lease_owner="worker-json",
            lease_token="lease-json",
            actor="barcode-worker",
        )

    assert repository.local_simulation._team_states[team_id] == before


def _make_json_group_delivery_cache_eligible(state: dict) -> dict:
    group = state["groups"][0]
    group.update(
        {
            "status": "approved",
            "reviewer": "reviewer-a",
            "address": "delivery road",
            "delivery_cache_status": "ready",
        }
    )
    for photo in group["photos"]:
        photo.update(
            {
                "upload_status": "uploaded",
                "image_url": f"oss://bucket/{photo['id']}.jpg",
                "storage_type": "oss",
                "archive_status": "archived",
                "download_status": "downloaded",
            }
        )
    return group


def test_json_identity_invalidation_commit_failure_creates_no_durable_cache_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team_id = f"json-mutation-rollback-{uuid4()}"
    state = _prepare_json_review_cache_state(monkeypatch, team_id)
    group = _make_json_group_delivery_cache_eligible(state)
    before = deepcopy(state)
    monkeypatch.setattr(repository.local_simulation, "validate_group_archive", lambda _group: [])
    monkeypatch.setattr(
        repository.local_simulation,
        "save_all_team_states",
        lambda: (_ for _ in ()).throw(RuntimeError("injected mutation persistence failure")),
    )

    with pytest.raises(RuntimeError, match="injected mutation persistence failure"):
        repository.JsonStateRepository().update_group_metadata(
            group["id"],
            actor="reviewer-a",
            updates={"meter_no": "M-VERIFY-002"},
        )

    assert repository.local_simulation._team_states[team_id] == before


def test_postgres_delivery_package_request_retires_before_transaction_lock_or_scope_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_package_queue

    statements: list[str] = []
    job = SimpleNamespace(
        id=uuid4(),
        status="pending",
        attempt_count=0,
        lease_owner=None,
        lease_token=None,
        lease_expires_at=None,
        package_path=None,
    )

    class Session:
        def scalar(self, statement):
            sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
            statements.append(sql)
            if "pg_advisory_xact_lock" in sql:
                return 0
            return job

        def rollback(self):
            return None

    monkeypatch.setattr(
        delivery_package_queue,
        "prepare_delivery_request",
        lambda *_args, **_kwargs: ([], "f" * 64, ["group-a"]),
    )

    with pytest.raises(ExportCenterRetiredError, match=RETIREMENT_MESSAGE):
        delivery_package_queue.request_postgres_delivery_package(
            Session(),
            groups=[],
            team_id="team-a",
            task_id=17,
            terminal="",
            review_scope="reviewed",
            requested_by="admin-a",
        )

    assert statements == []


def _formal_delivery_group(cache_root: Path, group_id: str = "formal-group-001") -> dict:
    categories = ("before_box", "collector_barcode", "module_meter", "after_box")
    photos = []
    for index, category in enumerate(categories, start=1):
        content = f"{group_id}-{category}".encode()
        sha256 = hashlib.sha256(content).hexdigest()
        relative = Path("objects") / sha256[:2] / f"{sha256}.png"
        path = cache_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        photo = {
            "id": f"{group_id}-photo-{index}",
            "category": category,
            "sha256": sha256,
            "delivery_cache_content_sha256": sha256,
            "delivery_cache_path": str(relative).replace("\\", "/"),
            "delivery_cache_status": "ready",
            "original_filename": f"{category}.png",
            "archive_status": "archived",
            "client_completed_at": "2026-07-22T00:30:00+08:00",
            "is_active": True,
        }
        photo["delivery_cache_version"] = repository.local_simulation.delivery_photo_cache_version(photo)
        photos.append(photo)
    return {
        "id": group_id,
        "task_id": 17,
        "terminal": "00112233",
        "meter_no": "000011112222",
        "module_asset_no": "000033334444",
        "collector": "00005555",
        "address": "南京路 1 号",
        "status": "approved",
        "photos": photos,
        "delivery_cache_status": "ready",
    }


def _write_ready_package(
    cache_root: Path,
    fingerprint: str,
    *,
    content: bytes = b"ready-package",
    filename: str = "",
) -> tuple[Path, str, int]:
    package_path = cache_root / "packages" / (filename or f"{fingerprint}.zip")
    package_path.parent.mkdir(parents=True, exist_ok=True)
    package_path.write_bytes(content)
    return package_path, hashlib.sha256(content).hexdigest(), len(content)


def _postgres_ready_package_session(job: SimpleNamespace):
    class Session:
        def __init__(self) -> None:
            self.scalar_calls = 0
            self.commits = 0
            self.rollbacks = 0

        def scalar(self, _statement):
            self.scalar_calls += 1
            return None if self.scalar_calls == 1 else job

        def add(self, _job):
            pytest.fail("matching ready job must be reused or requeued")

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1

    return Session()


def _patch_postgres_ready_package_request(
    monkeypatch: pytest.MonkeyPatch,
    fingerprint: str,
) -> None:
    from app.services import delivery_package_queue

    monkeypatch.setattr(
        delivery_package_queue,
        "prepare_delivery_request",
        lambda *_args, **_kwargs: ([], fingerprint, ["legacy-group"]),
    )
    monkeypatch.setattr(
        delivery_package_queue,
        "delivery_scope",
        lambda *_args, **_kwargs: (
            "team-a|task=17|terminal=|review_scope=reviewed",
            "scope-hash",
            {"task_id": 17, "terminal": "", "review_scope": "reviewed"},
        ),
    )


def _postgres_ready_job(
    package_path: Path,
    content_sha256: str,
    size_bytes: int,
    evidence_fingerprint: str = "f" * 64,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        status="ready",
        evidence_fingerprint=evidence_fingerprint,
        attempt_count=2,
        lease_owner="old-worker",
        lease_token="old-token",
        lease_expires_at=datetime.now(UTC),
        package_path=str(package_path),
        content_sha256=content_sha256,
        size_bytes=size_bytes,
        requested_by="admin-a",
        request_reason="formal_delivery_requested",
        last_error=None,
        completed_at=datetime.now(UTC),
        scope_payload={"task_id": 17, "terminal": "", "review_scope": "reviewed"},
        group_ids=["legacy-group"],
    )


def test_formal_package_validation_entry_is_retired_before_repair() -> None:
    repairs = []

    def exploding_repair(group_ids, *, reason):
        repairs.append((group_ids, reason))
        raise AssertionError("retired final-delivery service invoked a repair callback")

    with pytest.raises(ExportCenterRetiredError, match=RETIREMENT_MESSAGE):
        repository.local_simulation.build_final_delivery_package_from_groups(
            _ExplodingRetiredDeliveryDependency(),
            scope="retired-repair-callback",
            archived_only=False,
            repair_delivery_cache=exploding_repair,
        )

    assert repairs == []


def test_group_barcode_rescan_audit_payload_has_unique_keys() -> None:
    tree = ast.parse(inspect.getsource(repository.local_simulation.rescan_photo_barcode))
    duplicate_keys = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = [key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)]
        duplicate_keys.extend(key for key in keys if keys.count(key) > 1)

    assert duplicate_keys == []


def test_postgres_barcode_rescan_invalidates_delivery_package_before_commit() -> None:
    source = inspect.getsource(repository.PostgresStateRepository.rescan_photo_barcode)

    invalidation_call = "invalidate_postgres_delivery_cache_for_group_change("
    assert invalidation_call in source
    assert source.index(invalidation_call) < source.index("session.commit()")


def _postgres_manual_confirmation_fixture():
    group_id = uuid4()
    group = SimpleNamespace(
        id=group_id,
        legacy_id="group-manual-pg",
        team_id="manual-team",
        terminal="120000000001",
        display_meter_no="110000288055",
        meter_match_key="0000288055",
        exception_reasons=["条码识别异常", "其他业务异常"],
        has_archive_blocker=True,
        raw_data={
            "collector": "COLLECTOR-OLD",
            "module_asset_no": "MOD-OLD",
            "barcode_verification": {
                "status": "partial",
                "evidence_fingerprint": "fingerprint-before",
                "evidence_version": 7,
                "recognition_source": "machine",
                "result": {
                    "passed_count": 2,
                    "machine_barcode_values": ["110000288055", "COLLECTOROLD"],
                    "machine_qr_values": ["MOD-CANDIDATE"],
                    "ocr_candidates": ["MOD001"],
                    "missing_fields": ["module"],
                    "unmatched_machine_values": ["MOD-CANDIDATE"],
                    "matched_ocr_candidates": ["MOD001"],
                    "unmatched_ocr_candidates": [],
                },
            },
        },
    )
    categories = ["before_box", "collector_barcode", "module_meter", "after_box"]
    photos = [
        SimpleNamespace(
            id=uuid4(),
            legacy_id=f"manual-pg-photo-{index}",
            team_id="manual-team",
            group_id=group_id,
            is_active=True,
            sha256=f"{index + 1:x}" * 64,
            category=category,
            upload_status="uploaded",
            barcode="old-meter",
            collector="old-collector",
            asset_no="old-module",
            raw_data={},
        )
        for index, category in enumerate(categories)
    ]
    verification = SimpleNamespace(
        status="partial",
        evidence_fingerprint="fingerprint-before",
        evidence_version=7,
        meter_matched=True,
        module_matched=False,
        collector_matched=True,
        recognition_source="machine",
        attempt_count=2,
        lease_owner="worker-manual",
        lease_token="lease-manual-secret",
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        invalidation_reason=None,
        invalidated_by=None,
        invalidated_at=None,
    )
    return group, photos, verification


def _patch_postgres_manual_confirmation_helpers(monkeypatch, staged_audits):
    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: "manual-team")
    monkeypatch.setattr(
        repository,
        "_photo_payload",
        lambda photo: {
            "id": photo.legacy_id,
            "category": photo.category,
            "sha256": photo.sha256,
            "is_active": photo.is_active,
            "upload_status": photo.upload_status,
        },
    )
    monkeypatch.setattr(repository, "_stage_transactional_audit", lambda *_args, **kwargs: staged_audits.append(kwargs))
    monkeypatch.setattr(
        repository,
        "_group_payload",
        lambda _session, group, include_photos=True: {
            "id": group.legacy_id,
            "meter_no": group.display_meter_no,
            "meter_match_key": group.meter_match_key,
            **group.raw_data,
        },
    )
    monkeypatch.setattr(repository, "_group_target_summary", lambda payload, include_photos=True: payload)


def test_postgres_manual_confirmation_updates_formal_state_and_complete_redacted_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    group, photos, verification = _postgres_manual_confirmation_fixture()
    staged_audits = []
    cache_events = []
    _patch_postgres_manual_confirmation_helpers(monkeypatch, staged_audits)
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda _session, _group, *, actor, reason: cache_events.append(
            ("invalidate", actor, reason, session.commits)
        ),
    )

    class FakeSession:
        def __init__(self) -> None:
            self.commits = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, statement):
            assert getattr(statement, "_for_update_arg", None) is not None
            return verification

        def scalars(self, statement):
            assert "photos.team_id" in str(statement)
            assert "photos.group_id" in str(statement)
            return SimpleNamespace(all=lambda: photos)

        def add(self, _value) -> None:
            return None

        def commit(self) -> None:
            self.commits += 1

        def refresh(self, _value) -> None:
            return None

    session = FakeSession()

    class TestRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

        def _group_by_legacy_id(self, _session, group_id: str, *, lock: bool = False):
            assert repository.local_simulation.current_team_id() == "manual-team"
            assert group_id == "group-manual-pg"
            assert lock is True
            return group

        def _ensure_task_claimed_by(self, _session, checked_group, actor: str) -> None:
            assert checked_group is group
            assert actor == "reviewer-a"

        def _enqueue_delivery_cache_after_commit(self, group_id: str, *, actor: str, reason: str, **_kwargs) -> None:
            assert group_id == "group-manual-pg"
            cache_events.append(("requeue", actor, reason, session.commits))

    result = TestRepository().confirm_group_barcode_manually(
        "group-manual-pg",
        actor="reviewer-a",
        meter_no="110000288056",
        module_asset_no="MOD001",
        collector="COLLECTOR001",
        reason="现场核验",
        photo_ids=[photo.legacy_id for photo in photos],
    )

    assert result["group"]["meter_no"] == "110000288056"
    assert group.meter_match_key == "0000288056"
    assert all(photo.barcode == "110000288056" for photo in photos)
    assert all(photo.collector == "COLLECTOR001" for photo in photos)
    assert all(photo.asset_no == "MOD001" for photo in photos)
    assert group.exception_reasons == ["其他业务异常"]
    assert verification.status == "manual_confirmed"
    assert verification.evidence_version == 8
    assert verification.lease_owner is None
    assert verification.lease_token is None
    assert verification.lease_expires_at is None
    assert session.commits == 1
    assert cache_events == [
        ("invalidate", "reviewer-a", "manual_barcode_identity_changed", 0),
        ("requeue", "reviewer-a", "manual_barcode_identity_changed", 1),
    ]

    final_payload = repository._verification_group_payload(session, group)
    expected = evaluate_group_eligibility(final_payload)
    assert expected.status == "pending"
    assert verification.evidence_fingerprint == expected.evidence_fingerprint
    assert group.raw_data["barcode_verification"]["evidence_fingerprint"] == expected.evidence_fingerprint
    from app.services.barcode_maintenance_worker import _archive_block_reason

    reason, source = _archive_block_reason(final_payload, group.raw_data["barcode_verification"])
    assert reason == ""
    assert source == "manual_confirmed"

    audit = staged_audits[0]
    before = audit["before_data"]
    after = audit["after_data"]
    assert before["verification"]["matched_count"] == 2
    assert before["verification"]["evidence_version"] == 7
    assert before["verification"]["fingerprint"] == "fingerprint-before"
    assert before["verification"]["machine_barcode_values"] == ["11***55", "CO***LD"]
    assert before["verification"]["machine_qr_values"] == ["MO***TE"]
    assert before["verification"]["ocr_candidates"] == ["MO***01"]
    assert before["verification"]["lease"]["owner"] == "worker-manual"
    assert before["verification"]["lease"]["token_present"] is True
    assert after["verification"]["status"] == "manual_confirmed"
    assert after["verification"]["matched_count"] == 3
    assert after["verification"]["evidence_version"] == 8
    assert after["verification"]["lease"] == {"owner": "", "token_present": False, "expires_at": ""}
    assert after["manual"]["actor"] == "reviewer-a"
    assert after["manual"]["reason"] == "现场核验"
    assert after["manual"]["photo_ids"] == [photo.legacy_id for photo in photos]
    assert "lease-manual-secret" not in str(audit)


def test_postgres_manual_confirmation_rejects_invalid_evidence_and_wrong_team_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group, photos, verification = _postgres_manual_confirmation_fixture()
    staged_audits = []
    _patch_postgres_manual_confirmation_helpers(monkeypatch, staged_audits)

    class FakeSession:
        def __init__(self) -> None:
            self.commits = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, _statement):
            return verification

        def scalars(self, _statement):
            return SimpleNamespace(all=lambda: photos)

        def commit(self) -> None:
            self.commits += 1

    session = FakeSession()

    class TestRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

        def _group_by_legacy_id(self, _session, _group_id: str, *, lock: bool = False):
            assert lock is True
            if repository.local_simulation.current_team_id() != group.team_id:
                raise KeyError("wrong-team")
            return group

        def _ensure_task_claimed_by(self, *_args):
            return None

    repo = TestRepository()
    before = deepcopy(group.raw_data)
    with pytest.raises(ValueError, match="照片证据无效"):
        repo.confirm_group_barcode_manually(
            "group-manual-pg",
            actor="reviewer-a",
            meter_no="110000288056",
            module_asset_no="MOD001",
            collector="COLLECTOR001",
            reason="现场核验",
            photo_ids=[photos[0].legacy_id, photos[0].legacy_id],
        )

    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: "other-team")
    with pytest.raises(KeyError, match="wrong-team"):
        repo.confirm_group_barcode_manually(
            "group-manual-pg",
            actor="reviewer-a",
            meter_no="110000288056",
            module_asset_no="MOD001",
            collector="COLLECTOR001",
            reason="现场核验",
            photo_ids=[photo.legacy_id for photo in photos],
        )

    assert group.raw_data == before
    assert session.commits == 0
    assert staged_audits == []


def test_postgres_manual_confirmation_rolls_back_every_mutation_on_commit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    group, photos, verification = _postgres_manual_confirmation_fixture()
    staged_audits = []
    cache_events = []
    _patch_postgres_manual_confirmation_helpers(monkeypatch, staged_audits)
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda *_args, **_kwargs: cache_events.append("invalidate"),
    )
    group_before = deepcopy(vars(group))
    photos_before = [deepcopy(vars(photo)) for photo in photos]
    verification_before = deepcopy(vars(verification))

    class FakeSession:
        def __init__(self) -> None:
            self.rollbacks = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, _exc, _tb):
            if exc_type is not None:
                self.rollback()
            return False

        def scalar(self, _statement):
            return verification

        def scalars(self, _statement):
            return SimpleNamespace(all=lambda: photos)

        def add(self, _value) -> None:
            return None

        def commit(self) -> None:
            raise RuntimeError("injected postgres commit failure")

        def refresh(self, _value) -> None:
            return None

        def rollback(self) -> None:
            self.rollbacks += 1
            vars(group).clear()
            vars(group).update(deepcopy(group_before))
            for photo, before in zip(photos, photos_before, strict=True):
                vars(photo).clear()
                vars(photo).update(deepcopy(before))
            vars(verification).clear()
            vars(verification).update(deepcopy(verification_before))

    session = FakeSession()

    class TestRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

        def _group_by_legacy_id(self, _session, _group_id: str, *, lock: bool = False):
            assert lock is True
            return group

        def _ensure_task_claimed_by(self, *_args):
            return None

        def _enqueue_delivery_cache_after_commit(self, *_args, **_kwargs) -> None:
            cache_events.append("requeue")

    with pytest.raises(RuntimeError, match="injected postgres commit failure"):
        TestRepository().confirm_group_barcode_manually(
            "group-manual-pg",
            actor="reviewer-a",
            meter_no="110000288056",
            module_asset_no="MOD001",
            collector="COLLECTOR001",
            reason="现场核验",
            photo_ids=[photo.legacy_id for photo in photos],
        )

    assert session.rollbacks == 1
    assert vars(group) == group_before
    assert [vars(photo) for photo in photos] == photos_before
    assert vars(verification) == verification_before
    assert cache_events == ["invalidate"]


def test_postgres_duplicate_construction_identity_change_invalidates_once_and_rolls_back_commit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    categories = ["before_box", "collector_barcode", "module_meter", "after_box"]
    group = SimpleNamespace(
        id="group-identity",
        legacy_id="group-identity",
        legacy_task_id=12,
        task_id="task-identity",
        team_id="identity-team",
        display_meter_no="M-IDENTITY-001",
        meter_match_key="M-IDENTITY-001",
        installation_address="Identity road",
        photo_count=4,
        photos=[],
        raw_data={
            "construction_collector": "collector-old",
            "construction_module_asset_no": "module-old",
        },
    )
    task = SimpleNamespace(
        id="task-identity",
        legacy_id=12,
        team_id="identity-team",
        terminal="T-IDENTITY-001",
        construction_claimed_by="constructor-a",
        construction_priority=False,
    )
    verification = SimpleNamespace(status="passed", evidence_fingerprint="old", evidence_version=7)
    invalidations = []
    package_invalidations = []

    class FakeSession:
        def __init__(self, *, fail_commit: bool) -> None:
            self.fail_commit = fail_commit
            self.raw_before = deepcopy(group.raw_data)
            self.verification_before = deepcopy(vars(verification))
            self.rollbacks = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            if exc_type is not None:
                self.rollback()
            return False

        def scalar(self, _statement):
            return task

        def flush(self) -> None:
            return None

        def commit(self) -> None:
            if self.fail_commit:
                raise RuntimeError("injected postgres commit failure")

        def refresh(self, _value) -> None:
            return None

        def rollback(self) -> None:
            self.rollbacks += 1
            group.raw_data = deepcopy(self.raw_before)
            for key, value in self.verification_before.items():
                setattr(verification, key, value)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def __init__(self, session) -> None:
            super().__init__()
            self.session = session

        def _session(self):
            return self.session

        def _group_by_legacy_id(self, _session, _group_id: str, *, lock: bool = False):
            assert lock is True
            return group

        def _add_photo_records_to_group(self, *_args, **_kwargs):
            return {"added": 0, "skipped_duplicates": 4, "merged_duplicates": 0}

        def _task_stats(self, _session, _task):
            return {"total_groups": 1, "uploaded_count": 1, "reviewed_count": 0, "unreviewed_count": 1}

        def _task_payload_stats(self, session, checked_task):
            return self._task_stats(session, checked_task)

        def _add_construction_activity_audit(self, *_args, **_kwargs):
            return None

    def tracked_invalidate(_session, checked_group, actor: str, reason: str):
        invalidations.append((checked_group, actor, reason))
        evaluation = evaluate_group_eligibility(
            {
                "terminal": task.terminal,
                "meter_no": checked_group.display_meter_no,
                "collector": checked_group.raw_data["construction_collector"],
                "module_asset_no": checked_group.raw_data["construction_module_asset_no"],
                "photos": [
                    {"id": category, "sha256": f"{index + 1:x}" * 64, "category": category}
                    for index, category in enumerate(categories)
                ],
            }
        )
        verification.status = evaluation.status
        verification.evidence_fingerprint = evaluation.evidence_fingerprint
        verification.evidence_version += 1
        return {"status": verification.status, "evidence_fingerprint": verification.evidence_fingerprint}

    def tracked_package_invalidate(_session, checked_group, *, actor: str, reason: str) -> None:
        package_invalidations.append((checked_group, actor, reason))
        raw = dict(checked_group.raw_data or {})
        raw["delivery_package_invalidation_epoch"] = int(
            raw.get("delivery_package_invalidation_epoch") or 0
        ) + 1
        checked_group.raw_data = raw

    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: "identity-team")
    monkeypatch.setattr(repository.local_simulation, "assert_not_placeholder_construction_group", lambda **_kwargs: None)
    monkeypatch.setattr(repository, "invalidate_verification_for_group", tracked_invalidate)
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        tracked_package_invalidate,
    )
    monkeypatch.setattr(
        repository,
        "_group_payload",
        lambda _session, checked_group: {
            "construction_collector": checked_group.raw_data["construction_collector"],
            "construction_module_asset_no": checked_group.raw_data["construction_module_asset_no"],
        },
    )
    monkeypatch.setattr(repository, "_construction_task_payload", lambda *_args: {})

    result = TestPostgresRepository(FakeSession(fail_commit=False)).upload_construction_group_batch(
        "group-identity",
        actor="constructor-a",
        client_batch_id="duplicate-identity-postgres",
        collector="collector-new",
        module_asset_no="module-new",
        photos=[{"url": "https://example.test/duplicate.jpg", "sha256": "a" * 64}],
    )

    assert result["added"] == 0
    assert result["skipped_duplicates"] == 4
    assert result["group"] == {
        "construction_collector": "collector-new",
        "construction_module_asset_no": "module-new",
    }
    assert verification.status == "pending"
    assert verification.evidence_version == 8
    assert verification.evidence_fingerprint == evaluate_group_eligibility(
        {
            "terminal": task.terminal,
            "meter_no": group.display_meter_no,
            "collector": "collector-new",
            "module_asset_no": "module-new",
            "photos": [
                {"id": category, "sha256": f"{index + 1:x}" * 64, "category": category}
                for index, category in enumerate(categories)
            ],
        }
    ).evidence_fingerprint
    assert invalidations == [(group, "constructor-a", "construction_identity_changed")]
    assert package_invalidations == [(group, "constructor-a", "construction_identity_changed")]

    group.raw_data = {
        "construction_collector": "collector-old",
        "construction_module_asset_no": "module-old",
    }
    verification.status = "passed"
    verification.evidence_fingerprint = "old"
    verification.evidence_version = 7
    failing_session = FakeSession(fail_commit=True)
    with pytest.raises(RuntimeError, match="injected postgres commit failure"):
        TestPostgresRepository(failing_session).upload_construction_group_batch(
            "group-identity",
            actor="constructor-a",
            client_batch_id="duplicate-identity-postgres-failure",
            collector="collector-failed",
            module_asset_no="module-failed",
            photos=[{"url": "https://example.test/duplicate.jpg", "sha256": "a" * 64}],
        )

    assert failing_session.rollbacks == 1
    assert group.raw_data == {
        "construction_collector": "collector-old",
        "construction_module_asset_no": "module-old",
    }
    assert vars(verification) == {"status": "passed", "evidence_fingerprint": "old", "evidence_version": 7}
    assert package_invalidations == [
        (group, "constructor-a", "construction_identity_changed"),
        (group, "constructor-a", "construction_identity_changed"),
    ]


def test_postgres_construction_upload_rejects_zero_terminal_before_mutation() -> None:
    group = SimpleNamespace(
        legacy_id="g-zero-terminal",
        id="group-uuid",
        task_id="task-uuid",
        display_meter_no="120000000001",
        meter_match_key="0000000001",
        installation_address="test address",
    )
    task = SimpleNamespace(terminal="00000000", construction_claimed_by="another-constructor")

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, _statement):
            return task

    session = FakeSession()

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

        def _group_by_legacy_id(self, _session, group_id: str, *, lock: bool = False):
            assert group_id == "g-zero-terminal"
            assert lock is True
            return group

    with pytest.raises(ValueError, match="00000000"):
        TestPostgresRepository().upload_construction_group_batch(
            "g-zero-terminal",
            actor="constructor-a",
            client_batch_id="zero-terminal-postgres",
            collector="collector-a",
            module_asset_no="module-a",
            photos=[],
        )


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
            self.identity_seen_during_photo_write = (
                group.raw_data.get("construction_collector"),
                group.raw_data.get("construction_module_asset_no"),
            )
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
    successful_repo = TestPostgresRepository(successful_session)
    result = successful_repo.upload_construction_group_batch(
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
    assert successful_repo.identity_seen_during_photo_write == ("collector-a", "module-a")

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


def test_postgres_manual_photo_import_rejects_placeholder_group_before_photo_write() -> None:
    group = SimpleNamespace(
        id=1,
        legacy_id="00000000",
        terminal="00000000",
        display_meter_no="00000000",
        meter_match_key="00000000",
        installation_address="待导入总清单地址",
    )

    class Session:
        committed = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def commit(self):
            self.committed = True

        def refresh(self, _group):
            return None

    session = Session()

    class TestRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

        def _group_by_legacy_id(self, checked_session, group_id, *, lock=False):
            assert checked_session is session
            assert group_id == "00000000"
            assert lock is True
            return group

        def _add_photo_records_to_group(self, *_args, **_kwargs):
            pytest.fail("placeholder group must fail before photo write")

    with pytest.raises(ValueError, match="00000000"):
        TestRepository().add_photo_urls_to_group(
            "00000000",
            actor="admin",
            photo_urls=["https://example.test/unsafe.jpg"],
        )

    assert session.committed is False


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

    with pytest.raises(repository.StateBackendNotReady, match="before either backend mutated"):
        repo.classify_photo("g-1", "p-1", "after_box", "reviewer-a")
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
        (
            "update_group_metadata",
            ("g-1",),
            {
                "actor": "reviewer-a",
                "updates": {"collector": "c"},
                "audit_action": "update_group_metadata",
                "audit_context": None,
            },
        ),
        (
            "reset_group_to_unconstructed",
            ("g-1",),
            {"actor": "reviewer-a", "reason": "wrong", "force": True, "source_page": ""},
        ),
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
        if "FROM group_barcode_verifications" in sql:
            return None
        if "FROM delivery_cache_jobs" in sql:
            return None
        return 0

    def scalars(self, statement):
        self.statements.append(statement)
        if "FROM photos" in str(statement):
            return FinalizeFakeScalars(
                item
                for item in self.staged
                if isinstance(item, repository.Photo) and item.is_active
            )
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
    assert photos[0].raw_data["sha256_source"] == "image_url"
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
        upload_status="invalid",
        raw_data=evidence,
    )

    payload = repository._photo_payload(photo)

    for key in repository.unmatched_review.PHOTO_EVIDENCE_FIELDS:
        assert payload[key] == evidence[key]
    assert payload["temporary_review_manual_confirmed"] is True
    assert payload["temporary_review_reviewer"] == "reviewer-a"
    assert payload["temporary_review_reviewed_at"] == "2026-07-13T09:00:00+00:00"
    assert payload["upload_status"] == "invalid"


def test_postgres_unmatched_review_locks_and_merges_duplicate_photo_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    monkeypatch.setattr(repository, "invalidate_verification_for_group", lambda *args, **kwargs: {})
    package_invalidations = []
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda *_args, **kwargs: package_invalidations.append((kwargs["actor"], kwargs["reason"])),
    )
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

    assert package_invalidations == [("admin-a", "photo_restored_or_replaced")]

    compiled = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in compiled
    assert result == {"added": 0, "skipped_duplicates": 1, "merged_duplicates": 1}
    assert session.added == []
    assert session.flush_calls == 2
    assert existing.category == "before_box"
    assert existing.raw_data["qr_values"] == ["QR-001"]
    assert existing.raw_data["barcode_rescanned_by"] == "reviewer-a"
    assert existing.raw_data["temporary_review_manual_confirmed"] is True


def test_postgres_duplicate_evidence_resets_formal_review_archive_and_exception_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    monkeypatch.setattr(repository, "invalidate_verification_for_group", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda *_args, **_kwargs: None,
    )
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


def test_postgres_unmatched_review_reactivates_soft_deleted_duplicate_photo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    monkeypatch.setattr(repository, "invalidate_verification_for_group", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda *_args, **_kwargs: None,
    )
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


def test_postgres_unmatched_review_prefers_active_duplicate_over_inactive_equivalent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    monkeypatch.setattr(repository, "invalidate_verification_for_group", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda *_args, **_kwargs: None,
    )
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


def test_dual_data_center_anomaly_resolution_rejects_before_json_or_postgres_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    class MirrorRepository:
        def resolve_data_center_group_anomaly(self, *args, **kwargs):
            calls.append(("postgres", args, kwargs))

    monkeypatch.setattr(repository.DualWriteStateRepository, "postgres_repository_factory", MirrorRepository)
    monkeypatch.setattr(
        repository.JsonStateRepository,
        "resolve_data_center_group_anomaly",
        lambda *args, **kwargs: calls.append(("json", args, kwargs)),
    )

    with pytest.raises(repository.StateBackendNotReady, match="before either backend mutated"):
        repository.DualWriteStateRepository().resolve_data_center_group_anomaly(
            "group-1",
            "module_missing",
            actor="admin-a",
            expected_evidence_fingerprint="f" * 64,
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
    assert [event.action for event in audits].count(expected_action) == 1
    if operation == "associate":
        assert [event.action for event in audits].count("group_barcode_verification_invalidated") == 1
    audit = next(event for event in audits if event.action == expected_action)
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
        for value in ("0", "0000", "00000000", "TEST-001", "未关联终端", "manual-placeholder", "unmatched-placeholder")
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


def test_postgres_list_task_groups_has_no_unrelated_photo_category_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = SimpleNamespace(id="group-uuid", legacy_id="g-1", photo_count=0)

    class ScalarResult:
        def all(self):
            return [group]

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

        def scalars(self, _statement):
            return ScalarResult()

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return FakeSession()

        def _task_by_legacy_id(self, _session, task_id: int):
            assert task_id == 7
            return SimpleNamespace(legacy_id=task_id)

    monkeypatch.setattr(
        repository,
        "_group_payloads",
        lambda _session, _groups, *, include_photos: [
            {"id": "g-1", "meter_no": "M-1"}
        ],
    )
    monkeypatch.setattr(repository, "_review_queue_rank", lambda _group: 0)

    result = TestPostgresRepository().list_task_groups(7)

    assert result["total"] == 1
    assert result["items"][0]["id"] == "g-1"


def test_postgres_classify_photo_persists_archive_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import delivery_cache

    monkeypatch.setattr(repository, "invalidate_verification_for_group", lambda *args, **kwargs: {})
    events = []
    audits: list[dict[str, object]] = []
    monkeypatch.setattr(
        repository,
        "_stage_transactional_audit",
        lambda _session, **kwargs: audits.append(kwargs),
    )
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda *_args, **_kwargs: events.append("invalidate"),
    )
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
        raw_data={
            "classification_manual_confirmation": {
                "actor": "reviewer-a",
                "photo_snapshot": [{"photo_id": "p-1", "category": "unclassified", "sha256": "a" * 64}],
            },
            "status": "approved",
        },
        status=repository.GroupStatus.APPROVED,
        reviewer="reviewer-a",
        review_note="manual classification confirmed",
        reviewed_at=datetime.now(UTC),
        photo_count=1,
    )

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, _statement):
            return photo

        def add(self, _value):
            pass

        def commit(self):
            events.append("commit")

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

        def _enqueue_delivery_cache_after_commit(self, group_id: str, *, actor: str, reason: str, **_kwargs) -> None:
            events.append(("requeue", group_id, actor, reason))

    result = TestPostgresRepository().classify_photo("g-1", "p-1", "after_box", "reviewer-a")

    assert result["category"] == "after_box"
    assert result["archive_status"] == "archived"
    assert result["archive_filename"]
    assert photo.archive_status == "archived"
    assert photo.archive_filename == result["archive_filename"]
    assert photo.archived_at is not None
    assert photo.raw_data["archive_status"] == "archived"
    assert photo.raw_data["category_label"] == repository.local_simulation.PHOTO_CATEGORIES["after_box"]
    assert "classification_manual_confirmation" not in group.raw_data
    assert group.status == repository.GroupStatus.UNREVIEWED
    assert group.reviewer is None
    assert [audit["action"] for audit in audits].count("classification_manual_confirmation_revoked") == 1
    assert events == ["invalidate", "commit", ("requeue", "g-1", "reviewer-a", "photo_category_changed")]


@pytest.mark.parametrize("operation", ["legacy", "data_center"])
@pytest.mark.parametrize(
    ("next_category", "expect_revoked"),
    [("", False), ("before_box", False), ("after_box", True)],
)
def test_postgres_legacy_rescan_preserves_classification_while_data_center_rescan_revokes_on_change(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    next_category: str,
    expect_revoked: bool,
) -> None:
    from app.services import delivery_cache

    marker = {
        "actor": "reviewer-a",
        "photo_snapshot": [
            {"photo_id": "p-1", "category": "before_box", "sha256": "b" * 64}
        ],
    }
    group = SimpleNamespace(
        id="group-uuid",
        legacy_id="g-1",
        team_id="alpha-team",
        raw_data={
            "classification_manual_confirmation": deepcopy(marker),
            "status": "approved",
        },
        status=repository.GroupStatus.APPROVED,
        reviewer="reviewer-a",
        review_note="manual classification confirmed",
        reviewed_at=datetime.now(UTC),
    )
    photo = SimpleNamespace(
        id="photo-uuid",
        legacy_id="p-1",
        category="before_box",
        sha256="b" * 64,
        raw_data={
            "category_label": "表箱整体改造前",
            "construction_slot": "before_box",
            "construction_slot_label": "表箱整体改造前",
        },
        image_url="https://example.test/p-1.jpg",
        source_url="",
        storage_type="external_url",
        storage_bucket="",
        storage_key="",
        archive_filename="",
        archive_status="pending",
        original_filename="p-1.jpg",
        sort_order=1,
        barcode="",
        collector="",
        asset_no="",
        creator="reviewer-a",
        upload_status="uploaded",
    )
    audits: list[dict[str, object]] = []
    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: "alpha-team")
    monkeypatch.setattr(
        repository,
        "invalidate_verification_for_group",
        lambda *_args, **_kwargs: {"status": "pending", "should_enqueue": False},
    )
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        repository,
        "_stage_transactional_audit",
        lambda _session, **kwargs: audits.append(kwargs),
    )
    monkeypatch.setattr(
        repository,
        "_group_payload",
        lambda _session, value, **_kwargs: {
            "id": value.legacy_id,
            "status": value.status.value,
        },
    )
    monkeypatch.setattr(
        repository,
        "_data_center_group_result",
        lambda value, **_kwargs: value,
    )

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

        def scalar(self, _statement):
            return photo

        def commit(self):
            return None

        def refresh(self, _value):
            return None

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return FakeSession()

        def _group_by_legacy_id(self, _session, group_id: str, *, lock: bool = False):
            assert group_id == "g-1"
            assert lock is True
            return group

        def _ensure_task_claimed_by(self, _session, checked_group, actor: str, *, force: bool = False) -> None:
            assert checked_group is group
            assert actor == "reviewer-a"

    if operation == "legacy":
        result = TestPostgresRepository().rescan_photo_barcode(
            "g-1",
            "p-1",
            "reviewer-a",
            next_category,
        )
    else:
        result = TestPostgresRepository().rescan_data_center_group_photo_barcode(
            "g-1",
            "p-1",
            actor="reviewer-a",
            category=next_category,
            reason="rescan regression",
            source_page="data_center",
        )

    revoked_audits = [
        audit
        for audit in audits
        if audit["action"] == "classification_manual_confirmation_revoked"
    ]
    expected_category = next_category if operation == "data_center" and next_category else "before_box"
    expected_label = {
        "before_box": "表箱整体改造前",
        "after_box": "表箱整体改造后",
    }[expected_category]
    expected_revoked = bool(next_category) and expect_revoked and operation == "data_center"
    assert photo.category == expected_category
    assert result["category"] == expected_category
    assert result["category_label"] == expected_label
    if operation == "legacy":
        assert "category" not in photo.raw_data
        assert photo.raw_data["category_label"] == "表箱整体改造前"
    elif next_category:
        assert photo.raw_data["category"] == expected_category
        assert photo.raw_data["category_label"] == expected_label
    if expected_revoked:
        assert "classification_manual_confirmation" not in group.raw_data
        assert group.status == repository.GroupStatus.UNREVIEWED
        assert group.reviewer is None
        assert len(revoked_audits) == 1
    else:
        assert group.raw_data["classification_manual_confirmation"] == marker
        assert group.status == repository.GroupStatus.APPROVED
        assert revoked_audits == []


def test_postgres_data_center_rescan_rejects_unsupported_category_before_transaction() -> None:
    marker = {
        "actor": "reviewer-a",
        "photo_snapshot": [
            {"photo_id": "p-1", "category": "before_box", "sha256": "b" * 64}
        ],
    }
    group = SimpleNamespace(
        raw_data={"classification_manual_confirmation": deepcopy(marker)},
        status=repository.GroupStatus.APPROVED,
    )
    photo = SimpleNamespace(
        category="before_box",
        raw_data={"category_label": "表箱整体改造前"},
    )
    audits: list[dict[str, object]] = []
    session_opens: list[bool] = []
    before_group = deepcopy(group.__dict__)
    before_photo = deepcopy(photo.__dict__)

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            session_opens.append(True)
            raise AssertionError("unsupported category must be rejected before opening a transaction")

    with pytest.raises(ValueError, match="Unsupported photo category"):
        TestPostgresRepository().rescan_data_center_group_photo_barcode(
            "g-1",
            "p-1",
            actor="reviewer-a",
            category="unsupported-category",
            reason="rescan regression",
            source_page="data_center",
        )

    assert session_opens == []
    assert group.__dict__ == before_group
    assert photo.__dict__ == before_photo
    assert audits == []


def test_postgres_data_center_classifies_final_photo_auto_archives_and_enqueues_without_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    events: list[object] = []
    audits: list[dict[str, object]] = []
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda *_args, **_kwargs: events.append("invalidate"),
    )

    def fake_stage_audit(_session, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr(repository, "_stage_transactional_audit", fake_stage_audit)
    group = SimpleNamespace(
        id="group-uuid",
        team_id="alpha-team",
        task_id=None,
        legacy_id="g-1",
        legacy_task_id=1,
        terminal="120000000001",
        display_meter_no="110000288056",
        module_asset_no="MOD001",
        collector="COLLECTOR001",
        meter_match_key="0000288056",
        installation_address="A road",
        has_archive_blocker=False,
        status=repository.GroupStatus.UNREVIEWED,
        reviewer=None,
        review_note="",
        reviewed_at=None,
        exception_note="",
        exception_reasons=[],
        photo_count=4,
        raw_data={
            "meter_no": "110000288056",
            "module_asset_no": "MOD001",
            "collector": "COLLECTOR001",
            "status": "pending",
            "archive_status": "pending",
            "classification_manual_confirmation": {
                "actor": "admin-a",
                "photo_snapshot": [
                    {"photo_id": "p-4", "category": "unclassified", "sha256": "d" * 64}
                ],
            },
        },
        updated_at=None,
    )

    def make_photo(photo_id: str, category: str, sha: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=f"{photo_id}-uuid",
            legacy_id=photo_id,
            team_id="alpha-team",
            group_id="group-uuid",
            image_url=f"https://example.test/{photo_id}.jpg",
            source_url="",
            storage_type="external_url",
            storage_bucket="",
            storage_key="",
            sha256=sha * 64,
            category=category,
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
            raw_data={"upload_status": "uploaded", "is_active": True},
            is_active=True,
        )

    photos = [
        make_photo("p-1", "before_box", "a"),
        make_photo("p-2", "collector_barcode", "b"),
        make_photo("p-3", "module_meter", "c"),
        make_photo("p-4", "unclassified", "d"),
    ]
    target_photo = photos[-1]
    future_payload = {
        **group.raw_data,
        "id": group.legacy_id,
        "terminal": group.terminal,
        "meter_no": group.display_meter_no,
        "meter_match_key": group.meter_match_key,
        "photos": [
            {
                "id": photo.legacy_id,
                "category": "after_box" if photo is target_photo else photo.category,
                "sha256": photo.sha256,
                "upload_status": "uploaded",
                "is_active": True,
            }
            for photo in photos
        ],
    }
    eligibility = evaluate_group_eligibility(future_payload)
    assert eligibility.status == "pending"
    verification = SimpleNamespace(
        id="verification-uuid",
        team_id="alpha-team",
        group_id="group-uuid",
        status="passed",
        evidence_fingerprint=eligibility.evidence_fingerprint,
        evidence_version=3,
        meter_matched=True,
        module_matched=True,
        collector_matched=True,
        recognition_source="machine_barcode",
        result={
            "passed_count": 3,
            "matched_fields": ["meter", "module", "collector"],
            "missing_fields": [],
            "machine_barcode_values": ["110000288056", "MOD001", "COLLECTOR001"],
        },
        auto_archive_status="pending",
        auto_archive_attempt_count=0,
        auto_archive_lease_owner=None,
        auto_archive_lease_token=None,
        auto_archive_lease_expires_at=None,
        auto_archive_error=None,
    )

    class FakeScalarResult:
        def all(self):
            return photos

    class FakeSession:
        def __init__(self):
            self.scalar_calls = 0
            self.commits = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, _statement):
            self.scalar_calls += 1
            return target_photo if self.scalar_calls == 1 else verification

        def scalars(self, _statement):
            return FakeScalarResult()

        def add(self, _value):
            return None

        def commit(self):
            self.commits += 1
            events.append("commit")

        def refresh(self, _obj):
            return None

    session = FakeSession()

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

        def _group_by_legacy_id(self, _session, group_id: str, *, lock: bool = False):
            assert group_id == "g-1"
            assert lock is True
            return group

        def _ensure_task_claimed_by(self, *_args, **_kwargs) -> None:
            pytest.fail("data center admin classification must not depend on review claim")

        def _stage_data_center_auto_archive_delivery_jobs(
            self,
            _session,
            checked_group,
            *,
            group_payload,
            actor: str,
            reason: str,
        ) -> str:
            assert checked_group is group
            assert group_payload["id"] == "g-1"
            events.append(("stage-delivery", actor, reason, session.commits))
            return "pending"

    result = TestPostgresRepository().classify_data_center_group_photo(
        "g-1",
        "p-4",
        "after_box",
        actor="admin-a",
        reason="补齐最后一张分类",
        source_page="data_center",
    )

    assert result["archive_status"] == "archived"
    assert group.status == repository.GroupStatus.APPROVED
    assert group.raw_data["archive_status"] == "archived"
    assert "classification_manual_confirmation" not in group.raw_data
    assert verification.auto_archive_status == "archived"
    assert all(photo.archive_status == "archived" for photo in photos)
    assert events == ["invalidate", ("stage-delivery", "admin-a", "data_center_auto_archive", 0), "commit"]
    assert result["delivery_package_job_status"] == "pending"
    audit = next(item for item in audits if item["action"] == "data_center_photo_classified")
    revoked = next(
        item
        for item in audits
        if item["action"] == "classification_manual_confirmation_revoked"
    )
    assert revoked["payload"]["photo_id"] == "p-4"
    assert audit["payload"]["source_page"] == "data_center"
    assert audit["payload"]["source"] == "data_center"
    assert audit["payload"]["actor"] == "admin-a"
    assert audit["payload"]["reason"] == "补齐最后一张分类"
    assert audit["before_data"]["category"] == "unclassified"
    assert audit["after_data"]["category"] == "after_box"


def test_postgres_manual_classification_confirmation_is_transactional_and_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches the production backend omitting the confirmation snapshot or audit event."""
    group = SimpleNamespace(
        id="group-uuid",
        team_id="alpha-team",
        legacy_id="g-1",
        terminal="120000000001",
        display_meter_no="110000288056",
        module_asset_no="MOD001",
        collector="COLLECTOR001",
        installation_address="A road",
        status=repository.GroupStatus.UNREVIEWED,
        reviewer=None,
        review_note="",
        reviewed_at=None,
        raw_data={"status": "pending"},
    )
    photos = [
        SimpleNamespace(id=f"p-{index}-uuid", legacy_id=f"p-{index}", category=category, sha256=str(index) * 64, is_active=True)
        for index, category in enumerate(
            ("before_box", "collector_barcode", "module_meter", "after_box"),
            start=1,
        )
    ]
    verification = SimpleNamespace(status="passed")
    audits: list[dict[str, object]] = []

    class ScalarResult:
        def all(self):
            return photos

    class Session:
        committed = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalars(self, _statement):
            return ScalarResult()

        def scalar(self, _statement):
            return verification

        def commit(self):
            self.committed = True

        def refresh(self, _value):
            return None

    session = Session()

    class TestRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

        def _group_by_legacy_id(self, _session, group_id: str, *, lock: bool = False):
            assert group_id == "g-1"
            assert lock is True
            return group

    def group_payload(_session, value, **_kwargs):
        status = value.status.value if hasattr(value.status, "value") else str(value.status)
        return {
            "id": value.legacy_id,
            "terminal": value.terminal,
            "meter_no": value.display_meter_no,
            "module_asset_no": value.module_asset_no,
            "collector": value.collector,
            "address": value.installation_address,
            "status": status,
            "reviewer": value.reviewer or "",
            "review_note": value.review_note,
            "barcode_verification": {"status": verification.status},
        }

    monkeypatch.setattr(repository, "_group_payload", group_payload)
    monkeypatch.setattr(
        repository,
        "_photo_payload",
        lambda photo: {
            "id": photo.legacy_id,
            "category": photo.category,
            "sha256": photo.sha256,
            "is_active": photo.is_active,
        },
    )
    monkeypatch.setattr(repository, "_stage_transactional_audit", lambda _session, **kwargs: audits.append(kwargs))

    snapshot, anomalies = repository._manual_classification_snapshot(
        {**group_payload(session, group), "address": group.installation_address},
        [repository._photo_payload(photo) for photo in photos],
    )
    before_group_raw = deepcopy(group.raw_data)
    with pytest.raises(repository.ClassificationConfirmationConflict, match="重新加载"):
        TestRepository().manual_confirm_group_classification(
            "g-1",
            actor="admin-a",
            acknowledge_anomalies=False,
            expected_evidence_fingerprint="0" * 64,
            source_page="review_rephoto_workbench",
        )
    assert group.raw_data == before_group_raw
    assert audits == []
    assert session.committed is False

    result = TestRepository().manual_confirm_group_classification(
        "g-1",
        actor="admin-a",
        acknowledge_anomalies=False,
        expected_evidence_fingerprint=repository.data_center_service.manual_classification_fingerprint(
            snapshot, anomalies
        ),
        source_page="review_rephoto_workbench",
    )

    assert session.committed is True
    assert result["status"] == "approved"
    assert group.raw_data["classification_manual_confirmation"]["photo_snapshot"][0]["photo_id"] == "p-1"
    audit = next(item for item in audits if item["action"] == "classification_manual_confirmed")
    assert audit["payload"]["actor"] == "admin-a"
    assert audit["payload"]["anomalies"] == []
    assert len(audit["payload"]["photo_snapshot"]) == 4


def test_postgres_data_center_classify_rolls_back_archive_when_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    events: list[object] = []
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda *_args, **_kwargs: events.append("invalidate"),
    )

    group = SimpleNamespace(
        id="group-uuid",
        team_id="alpha-team",
        task_id=None,
        legacy_id="g-1",
        legacy_task_id=1,
        terminal="120000000001",
        display_meter_no="110000288056",
        module_asset_no="MOD001",
        collector="COLLECTOR001",
        meter_match_key="0000288056",
        installation_address="A road",
        has_archive_blocker=False,
        status=repository.GroupStatus.UNREVIEWED,
        reviewer=None,
        review_note="",
        reviewed_at=None,
        exception_note="",
        exception_reasons=[],
        photo_count=4,
        raw_data={
            "meter_no": "110000288056",
            "module_asset_no": "MOD001",
            "collector": "COLLECTOR001",
            "status": "pending",
            "archive_status": "pending",
        },
        updated_at=None,
    )

    def make_photo(photo_id: str, category: str, sha: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=f"{photo_id}-uuid",
            legacy_id=photo_id,
            team_id="alpha-team",
            group_id="group-uuid",
            image_url=f"https://example.test/{photo_id}.jpg",
            source_url="",
            storage_type="external_url",
            storage_bucket="",
            storage_key="",
            sha256=sha * 64,
            category=category,
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
            raw_data={"upload_status": "uploaded", "is_active": True},
            is_active=True,
        )

    photos = [
        make_photo("p-1", "before_box", "a"),
        make_photo("p-2", "collector_barcode", "b"),
        make_photo("p-3", "module_meter", "c"),
        make_photo("p-4", "unclassified", "d"),
    ]
    target_photo = photos[-1]
    future_payload = {
        **group.raw_data,
        "id": group.legacy_id,
        "terminal": group.terminal,
        "meter_no": group.display_meter_no,
        "meter_match_key": group.meter_match_key,
        "photos": [
            {
                "id": photo.legacy_id,
                "category": "after_box" if photo is target_photo else photo.category,
                "sha256": photo.sha256,
                "upload_status": "uploaded",
                "is_active": True,
            }
            for photo in photos
        ],
    }
    eligibility = evaluate_group_eligibility(future_payload)
    verification = SimpleNamespace(
        id="verification-uuid",
        team_id="alpha-team",
        group_id="group-uuid",
        status="passed",
        evidence_fingerprint=eligibility.evidence_fingerprint,
        evidence_version=3,
        meter_matched=True,
        module_matched=True,
        collector_matched=True,
        recognition_source="machine_barcode",
        result={"passed_count": 3, "matched_fields": ["meter", "module", "collector"], "missing_fields": []},
        auto_archive_status="pending",
        auto_archive_attempt_count=0,
        auto_archive_lease_owner=None,
        auto_archive_lease_token=None,
        auto_archive_lease_expires_at=None,
        auto_archive_error=None,
    )
    group_before = deepcopy(vars(group))
    photos_before = [deepcopy(vars(photo)) for photo in photos]
    verification_before = deepcopy(vars(verification))

    class FakeScalarResult:
        def all(self):
            return photos

    class FakeSession:
        def __init__(self):
            self.scalar_calls = 0
            self.rollbacks = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, _exc, _tb):
            if exc_type is not None:
                self.rollback()
            return False

        def scalar(self, _statement):
            self.scalar_calls += 1
            return target_photo if self.scalar_calls == 1 else verification

        def scalars(self, _statement):
            return FakeScalarResult()

        def add(self, _value):
            return None

        def commit(self):
            raise RuntimeError("injected postgres commit failure")

        def refresh(self, _obj):
            return None

        def rollback(self):
            self.rollbacks += 1
            vars(group).clear()
            vars(group).update(deepcopy(group_before))
            for photo, before in zip(photos, photos_before, strict=True):
                vars(photo).clear()
                vars(photo).update(deepcopy(before))
            vars(verification).clear()
            vars(verification).update(deepcopy(verification_before))

    session = FakeSession()

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

        def _group_by_legacy_id(self, _session, group_id: str, *, lock: bool = False):
            assert group_id == "g-1"
            assert lock is True
            return group

        def _stage_data_center_auto_archive_delivery_jobs(
            self,
            _session,
            checked_group,
            *,
            group_payload,
            actor: str,
            reason: str,
        ) -> str:
            assert checked_group is group
            events.append(("stage-delivery", actor, reason))
            return "pending"

    with pytest.raises(RuntimeError, match="injected postgres commit failure"):
        TestPostgresRepository().classify_data_center_group_photo(
            "g-1",
            "p-4",
            "after_box",
            actor="admin-a",
            reason="补齐最后一张分类",
            source_page="data_center",
        )

    assert session.rollbacks == 1
    assert vars(group) == group_before
    assert [vars(photo) for photo in photos] == photos_before
    assert vars(verification) == verification_before
    assert events == ["invalidate", ("stage-delivery", "admin-a", "data_center_auto_archive")]


def test_postgres_data_center_manual_confirm_bypasses_review_claim_and_audits_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache
    from app.services import barcode_maintenance_worker

    group, photos, verification = _postgres_manual_confirmation_fixture()
    staged_audits = []
    _patch_postgres_manual_confirmation_helpers(monkeypatch, staged_audits)
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        barcode_maintenance_worker,
        "auto_archive_verified_group",
        lambda *_args, **_kwargs: {"archived": False, "reason": "not_ready"},
    )

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, _statement):
            return verification

        def scalars(self, _statement):
            return SimpleNamespace(all=lambda: photos)

        def add(self, _value) -> None:
            return None

        def commit(self) -> None:
            return None

        def refresh(self, _value) -> None:
            return None

    class TestRepository(repository.PostgresStateRepository):
        def _session(self):
            return FakeSession()

        def _group_by_legacy_id(self, _session, group_id: str, *, lock: bool = False):
            assert group_id == "group-manual-pg"
            assert lock is True
            return group

        def _ensure_task_claimed_by(self, *_args, **_kwargs) -> None:
            raise ValueError("Task is already claimed by another reviewer")

        def _enqueue_delivery_cache_after_commit(self, *_args, **_kwargs) -> None:
            return None

        def get_group(self, group_id: str):
            assert group_id == "group-manual-pg"
            return {
                "id": group.legacy_id,
                "meter_no": group.display_meter_no,
                "meter_match_key": group.meter_match_key,
                **group.raw_data,
            }

    result = TestRepository().manual_confirm_group_barcode(
        "group-manual-pg",
        actor="admin-a",
        reason="数据中台人工确认",
        source_page="data_center",
        meter_no="110000288056",
        module_asset_no="MOD001",
        collector="COLLECTOR001",
        photo_ids=[photo.legacy_id for photo in photos],
    )

    assert result["barcode_status"] == "manual_confirmed"
    audit = staged_audits[0]
    assert audit["payload"]["source_page"] == "data_center"
    assert audit["payload"]["source"] == "data_center"
    assert audit["payload"]["actor"] == "admin-a"
    assert audit["payload"]["reason"] == "数据中台人工确认"
    assert "before" in audit["payload"]
    assert "after" in audit["payload"]


def test_postgres_same_category_rearchive_invalidates_before_commit_and_requeues_after_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    events = []
    monkeypatch.setattr(repository, "invalidate_verification_for_group", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda *_args, **_kwargs: events.append("invalidate"),
    )
    photo = SimpleNamespace(
        id="photo-uuid",
        legacy_id="p-1",
        image_url="https://example.test/photo.jpg",
        source_url="",
        storage_type="external_url",
        storage_bucket="",
        storage_key="",
        sha256="a" * 64,
        category="after_box",
        archive_filename="old-name.jpg",
        archive_status="archived",
        archived_at=datetime(2026, 7, 22, tzinfo=UTC),
        classified_by="reviewer-a",
        classified_at=datetime(2026, 7, 22, tzinfo=UTC),
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
        raw_data={"status": "approved"},
        status=repository.GroupStatus.APPROVED,
        photo_count=1,
    )

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, _statement):
            return photo

        def add(self, _value):
            return None

        def commit(self):
            events.append("commit")

        def refresh(self, _obj):
            return None

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return FakeSession()

        def _group_by_legacy_id(self, _session, _group_id: str, *, lock: bool = False):
            assert lock is True
            return group

        def _ensure_task_claimed_by(self, *_args, **_kwargs) -> None:
            return None

        def _enqueue_delivery_cache_after_commit(self, group_id: str, *, actor: str, reason: str, **_kwargs) -> None:
            events.append(("requeue", group_id, actor, reason))

    result = TestPostgresRepository().classify_photo("g-1", "p-1", "after_box", "reviewer-a")

    assert result["category"] == "after_box"
    assert result["archive_filename"] != "old-name.jpg"
    assert events == ["invalidate", "commit", ("requeue", "g-1", "reviewer-a", "photo_archive_changed")]


@pytest.mark.parametrize("fail_commit", [False, True], ids=["committed", "commit-failure"])
def test_postgres_identity_invalidation_requeues_only_after_commit(
    fail_commit: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    group = SimpleNamespace(
        id=uuid4(),
        legacy_id="postgres-identity-cache",
        team_id="postgres-cache-team",
        display_meter_no="M-OLD",
        meter_match_key="M-OLD",
        terminal="T-001",
        installation_address="delivery road",
        status=repository.GroupStatus.APPROVED,
        reviewer="reviewer-a",
        review_note="ready",
        exception_note="",
        exception_reasons=[],
        has_archive_blocker=False,
        exception_status=None,
        raw_data={"status": "approved", "delivery_cache_status": "ready"},
        updated_at=None,
    )
    events = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalars(self, _statement):
            return SimpleNamespace(all=lambda: [])

        def commit(self):
            events.append("commit")
            if fail_commit:
                raise RuntimeError("injected postgres mutation commit failure")

        def refresh(self, _value):
            return None

    class TestRepository(repository.PostgresStateRepository):
        def _session(self):
            return Session()

        def _group_by_legacy_id(self, _session, group_id: str, *, lock: bool = False):
            assert group_id == group.legacy_id
            assert lock is True
            return group

        def _enqueue_delivery_cache_after_commit(self, group_id: str, *, actor: str, reason: str, **_kwargs) -> None:
            events.append(("requeue", group_id, actor, reason))

    def payload(_session, value, include_photos=False, **_kwargs):
        return {
            "id": value.legacy_id,
            "meter_no": value.display_meter_no,
            "meter_match_key": value.meter_match_key,
            "terminal": value.terminal,
            "address": value.installation_address,
            "status": "approved",
            "reviewer": value.reviewer,
            "review_note": value.review_note,
            "exception_note": value.exception_note,
            "collector": "C-001",
            "module_asset_no": "MOD-001",
            "creator": "installer-a",
            "construction_collector": "C-001",
            "construction_module_asset_no": "MOD-001",
            "photos": [],
        }

    monkeypatch.setattr(repository, "_group_payload", payload)
    monkeypatch.setattr(repository.local_simulation, "validate_group_archive", lambda _group: [])
    monkeypatch.setattr(repository, "invalidate_verification_for_group", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(repository, "_stage_transactional_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda *_args, **_kwargs: events.append("invalidate"),
    )

    if fail_commit:
        with pytest.raises(RuntimeError, match="injected postgres mutation commit failure"):
            TestRepository().update_group_metadata(
                group.legacy_id,
                actor="reviewer-a",
                updates={"meter_no": "M-NEW"},
            )
        assert events == ["invalidate", "commit"]
    else:
        TestRepository().update_group_metadata(
            group.legacy_id,
            actor="reviewer-a",
            updates={"meter_no": "M-NEW"},
        )
        assert events == [
            "invalidate",
            "commit",
            ("requeue", group.legacy_id, "reviewer-a", "group_identity_changed"),
        ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("address", "updated delivery address"),
        ("status", "exception"),
        ("reviewer", "reviewer-b"),
        ("review_note", "updated review note"),
        ("exception_note", "updated exception note"),
    ],
)
def test_postgres_delivery_metadata_changes_invalidate_and_requeue_after_commit(
    field: str,
    value: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    group = SimpleNamespace(
        id=uuid4(),
        legacy_id=f"postgres-metadata-cache-{field}",
        team_id="postgres-cache-team",
        display_meter_no="M-OLD",
        meter_match_key="M-OLD",
        terminal="T-001",
        installation_address="delivery road",
        status=repository.GroupStatus.APPROVED,
        reviewer="reviewer-a",
        review_note="ready",
        exception_note="",
        exception_reasons=[],
        has_archive_blocker=False,
        exception_status=None,
        raw_data={"status": "approved", "delivery_cache_status": "ready"},
        updated_at=None,
    )
    events = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def commit(self):
            events.append("commit")

        def refresh(self, _value):
            return None

    class TestRepository(repository.PostgresStateRepository):
        def _session(self):
            return Session()

        def _group_by_legacy_id(self, _session, group_id: str, *, lock: bool = False):
            assert group_id == group.legacy_id
            assert lock is True
            return group

        def _enqueue_delivery_cache_after_commit(self, group_id: str, *, actor: str, reason: str, **_kwargs) -> None:
            events.append(("requeue", group_id, actor, reason))

    def payload(_session, value, include_photos=False, **_kwargs):
        status = value.status.value if hasattr(value.status, "value") else str(value.status)
        return {
            "id": value.legacy_id,
            "meter_no": value.display_meter_no,
            "meter_match_key": value.meter_match_key,
            "terminal": value.terminal,
            "address": value.installation_address,
            "status": status,
            "reviewer": value.reviewer,
            "review_note": value.review_note,
            "exception_note": value.exception_note,
            "collector": "C-001",
            "module_asset_no": "MOD-001",
            "creator": "installer-a",
            "construction_collector": "C-001",
            "construction_module_asset_no": "MOD-001",
            "photos": [],
        }

    monkeypatch.setattr(repository, "_group_payload", payload)
    monkeypatch.setattr(repository.local_simulation, "validate_group_archive", lambda _group: [])
    monkeypatch.setattr(repository, "invalidate_verification_for_group", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(repository, "_stage_transactional_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda *_args, **kwargs: events.append(("invalidate", kwargs["reason"])),
    )

    TestRepository().update_group_metadata(
        group.legacy_id,
        actor="reviewer-a",
        updates={field: value},
    )

    assert events[0] == ("invalidate", "group_metadata_changed")
    assert events[1] == "commit"
    assert events[2] == (
        "requeue",
        group.legacy_id,
        "reviewer-a",
        "group_metadata_changed",
    )


def test_postgres_data_center_group_update_audits_source_reason_and_state_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    group = SimpleNamespace(
        id=uuid4(),
        legacy_id="postgres-data-center-audit",
        team_id="postgres-data-center-team",
        display_meter_no="M-001",
        meter_match_key="M-001",
        terminal="T-001",
        installation_address="delivery road",
        status=repository.GroupStatus.APPROVED,
        reviewer="reviewer-a",
        review_note="ready",
        reviewed_at=datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
        exception_note="",
        exception_reasons=[],
        has_archive_blocker=False,
        exception_status=None,
        raw_data={
            "status": "approved",
            "archive_status": "archived",
            "delivery_cache_status": "ready",
            "barcode_verification": {"status": "passed"},
            "construction_collector": "C-001",
            "construction_module_asset_no": "MOD-001",
        },
        updated_at=None,
    )
    photos = [
        SimpleNamespace(
            id=uuid4(),
            legacy_id=f"p-{index}",
            team_id=group.team_id,
            group_id=group.id,
            is_active=True,
            barcode="M-001",
            collector="C-001",
            asset_no="MOD-001",
            creator="installer-a",
            raw_data={
                "barcode": "M-001",
                "collector": "C-001",
                "module_asset_no": "MOD-001",
            },
            archive_status="archived",
            archived_at=datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
            archive_filename=f"{index}.jpg",
        )
        for index in range(2)
    ]
    staged_audits = []

    class ScalarResult:
        def all(self):
            return photos

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalars(self, _statement):
            return ScalarResult()

        def commit(self):
            return None

        def refresh(self, _value):
            return None

    class TestRepository(repository.PostgresStateRepository):
        def _session(self):
            return Session()

        def _group_by_legacy_id(self, _session, group_id: str, *, lock: bool = False):
            assert group_id == group.legacy_id
            assert lock is True
            return group

        def _enqueue_delivery_cache_after_commit(self, *_args, **_kwargs) -> None:
            return None

        def get_group(self, group_id: str):
            assert group_id == group.legacy_id
            return payload(None, group, include_photos=True)

    def payload(_session, value, include_photos=False, **_kwargs):
        photo_items = photos if include_photos else []
        status = value.status.value if hasattr(value.status, "value") else str(value.status)
        archived = photo_items and all(str(photo.archive_status or "") == "archived" for photo in photo_items)
        return {
            "id": value.legacy_id,
            "meter_no": value.display_meter_no,
            "meter_match_key": value.meter_match_key,
            "terminal": value.terminal,
            "address": value.installation_address,
            "status": status,
            "archive_status": "archived" if archived else str(value.raw_data.get("archive_status") or "pending"),
            "delivery_cache_status": str(value.raw_data.get("delivery_cache_status") or ""),
            "barcode_status": str((value.raw_data.get("barcode_verification") or {}).get("status") or ""),
            "reviewer": value.reviewer,
            "review_note": value.review_note,
            "exception_note": value.exception_note,
            "collector": photos[0].collector,
            "module_asset_no": photos[0].asset_no,
            "creator": photos[0].creator,
            "construction_collector": value.raw_data.get("construction_collector", ""),
            "construction_module_asset_no": value.raw_data.get("construction_module_asset_no", ""),
            "photos": [
                {
                    "id": photo.legacy_id,
                    "archive_status": photo.archive_status,
                    "module_asset_no": photo.asset_no,
                }
                for photo in photo_items
            ],
        }

    def capture_audit(_session, **kwargs):
        staged_audits.append(kwargs)

    def invalidate_cache(_session, group_value, *, actor: str, reason: str):
        raw = dict(group_value.raw_data or {})
        raw["delivery_cache_status"] = "stale"
        group_value.raw_data = raw

    monkeypatch.setattr(repository, "_group_payload", payload)
    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: group.team_id)
    monkeypatch.setattr(repository.local_simulation, "validate_group_archive", lambda _group: [])
    monkeypatch.setattr(repository, "invalidate_verification_for_group", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(repository, "_stage_transactional_audit", capture_audit)
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        invalidate_cache,
    )

    TestRepository().update_data_center_group(
        group.legacy_id,
        patch={
            "meter_no": "M-002",
            "module_asset_no": "MOD-002",
            "collector": "C-002",
        },
        actor="admin-a",
        reason="核对三项号码",
        source_page="data_center",
    )

    update_audit = next(item for item in staged_audits if item["action"] == "data_center_group_updated")
    update_payload = update_audit["payload"]
    assert update_payload["source"] == "data_center"
    assert update_payload["source_page"] == "data_center"
    assert update_payload["actor"] == "admin-a"
    assert update_payload["reason"] == "核对三项号码"
    assert update_payload["before"] == {
        "collector": "C-001",
        "construction_collector": "C-001",
        "construction_module_asset_no": "MOD-001",
        "meter_match_key": "M-001",
        "meter_no": "M-001",
        "module_asset_no": "MOD-001",
    }
    assert update_payload["after"] == {
        "collector": "C-002",
        "construction_collector": "C-002",
        "construction_module_asset_no": "MOD-002",
        "meter_match_key": "M-002",
        "meter_no": "M-002",
        "module_asset_no": "MOD-002",
    }
    assert group.display_meter_no == "M-002"
    assert group.meter_match_key == "M-002"
    assert group.raw_data["meter_no"] == "M-002"
    assert group.raw_data["meter_match_key"] == "M-002"
    assert group.raw_data["collector"] == "C-002"
    assert group.raw_data["module_asset_no"] == "MOD-002"
    assert group.raw_data["construction_collector"] == "C-002"
    assert group.raw_data["construction_module_asset_no"] == "MOD-002"
    for photo in photos:
        assert photo.barcode == "M-002"
        assert photo.collector == "C-002"
        assert photo.asset_no == "MOD-002"
        assert photo.raw_data["meter_no"] == "M-002"
        assert photo.raw_data["barcode"] == "M-002"
        assert photo.raw_data["collector"] == "C-002"
        assert photo.raw_data["module_asset_no"] == "MOD-002"

    invalidation_audit = next(item for item in staged_audits if item["action"] == "data_center_archive_invalidated")
    invalidation_payload = invalidation_audit["payload"]
    assert invalidation_payload["source"] == "data_center"
    assert invalidation_payload["source_page"] == "data_center"
    assert invalidation_payload["actor"] == "admin-a"
    assert invalidation_payload["reason"] == "核对三项号码"
    assert invalidation_payload["before"] == {
        "archive_status": "archived",
        "barcode_status": "passed",
        "delivery_cache_status": "ready",
    }
    assert invalidation_payload["after"] == {
        "archive_status": "pending",
        "barcode_status": "passed",
        "delivery_cache_status": "stale",
    }


def test_postgres_manual_photo_upload_builds_response_before_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = SimpleNamespace(
        id=uuid4(),
        legacy_id="postgres-manual-photo",
        team_id="postgres-cache-team",
        terminal="T-001",
        display_meter_no="M-001",
        meter_match_key="M-001",
        installation_address="delivery road",
    )
    events = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def flush(self):
            return None

        def commit(self):
            events.append("commit")

        def refresh(self, _value):
            events.append("refresh")

    class TestRepository(repository.PostgresStateRepository):
        def _session(self):
            return Session()

        def _group_by_legacy_id(self, _session, group_id: str, *, lock: bool = False):
            assert group_id == group.legacy_id
            assert lock is True
            return group

        def _add_photo_records_to_group(self, *_args, **_kwargs):
            return {
                "added": 1,
                "skipped_duplicates": 0,
                "merged_duplicates": 0,
                "retained_photo_urls": ["/static/uploads/manual/new.jpg"],
            }

    monkeypatch.setattr(repository.local_simulation, "assert_not_placeholder_construction_group", lambda **_kwargs: None)

    def payload(_session, _group):
        events.append("payload")
        return {"id": group.legacy_id}

    monkeypatch.setattr(repository, "_group_payload", payload)

    result = TestRepository().add_photo_urls_to_group(
        group.legacy_id,
        actor="reviewer-a",
        photo_urls=["/static/uploads/manual/new.jpg"],
    )

    assert events == ["payload", "commit"]
    assert result["retained_photo_urls"] == ["/static/uploads/manual/new.jpg"]


def test_postgres_classify_photo_rejects_unknown_category_before_opening_a_transaction() -> None:
    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            pytest.fail("unsupported category must be rejected before any PostgreSQL mutation or audit")

    with pytest.raises(ValueError, match="Unsupported photo category"):
        TestPostgresRepository().classify_photo("g-1", "p-1", "unsupported-category", "reviewer-a")


def test_postgres_photo_deletion_requeues_delivery_cache_only_after_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    photo = SimpleNamespace(
        id=uuid4(),
        legacy_id="p-delete-cache",
        image_url="https://example.test/delete.jpg",
        source_url="",
        storage_type="external_url",
        storage_bucket="",
        storage_key="",
        sha256="a" * 64,
        category="before_box",
        archive_filename="before.jpg",
        archive_status="archived",
        sort_order=1,
        barcode="",
        collector="",
        asset_no="",
        creator="",
        upload_status="uploaded",
        raw_data={},
        is_active=True,
        deleted_at=None,
        deleted_by="",
        delete_reason="",
    )
    group = SimpleNamespace(
        id=uuid4(),
        legacy_id="g-delete-cache",
        team_id="postgres-cache-team",
        status=repository.GroupStatus.APPROVED,
        photo_count=4,
        reviewer="reviewer-a",
        review_note="ready",
        exception_note="",
        reviewed_at=datetime.now(UTC),
        raw_data={"status": "approved", "delivery_cache_status": "ready"},
    )
    events = []

    class Session:
        scalar_calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, _statement):
            self.scalar_calls += 1
            return photo if self.scalar_calls == 1 else 3

        def commit(self):
            events.append("commit")

        def refresh(self, _value):
            return None

    class TestRepository(repository.PostgresStateRepository):
        def _session(self):
            return Session()

        def _group_by_legacy_id(self, _session, _group_id: str, *, lock: bool = False):
            assert lock is True
            return group

        def _ensure_task_claimed_by(self, *_args, **_kwargs):
            return None

        def _enqueue_delivery_cache_after_commit(self, group_id: str, *, actor: str, reason: str, **_kwargs):
            events.append(("requeue", group_id, actor, reason))

    monkeypatch.setattr(repository, "_apply_photo_quality_exception_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(repository, "invalidate_verification_for_group", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(repository, "_group_payload", lambda *_args, **_kwargs: {"id": group.legacy_id})
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda *_args, **_kwargs: events.append("invalidate"),
    )

    TestRepository().delete_photo(group.legacy_id, photo.legacy_id, "reviewer-a")

    assert events == ["invalidate", "commit", ("requeue", group.legacy_id, "reviewer-a", "photo_deleted")]


def test_postgres_reset_group_to_unconstructed_clears_barcode_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    monkeypatch.setattr(repository, "invalidate_verification_for_group", lambda *args, **kwargs: {})
    invalidations = []
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda *_args, **kwargs: invalidations.append((kwargs["actor"], kwargs["reason"])),
    )
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

        def scalar(self, _statement):
            return None

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
    assert invalidations == [("admin", "reset_to_unconstructed")]


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


@pytest.mark.parametrize(
    ("reasons", "expected_exception_count", "expected_unreviewed_count"),
    [
        (["missing_collector_photo"], 0, 1),
        (["缺少采集器信息"], 0, 1),
        (["missing_collector_photo", "缺少采集器信息"], 0, 1),
        (["missing_collector_photo", "missing_module_asset_no"], 1, 0),
        (["missing_collector_photo", "缺少采集器信息", "missing_module_asset_no"], 1, 0),
    ],
)
def test_postgres_installer_workload_ignores_only_missing_collector_photo_exception(
    reasons: list[str],
    expected_exception_count: int,
    expected_unreviewed_count: int,
) -> None:
    photo = SimpleNamespace(
        id="photo-uuid",
        raw_data={"client_completed_at": "2026-08-31T09:30:00", "upload_source": "construction-mobile"},
        source="construction",
        created_at=datetime(2026, 8, 31, 9, 30),
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
        status=repository.GroupStatus.REJECTED,
        raw_data={"status": "exception"},
        last_photo_imported_at=None,
        exception_status="open",
        has_archive_blocker=True,
        exception_reasons=reasons,
        exception_note="缺采集器照片",
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

    item = TestPostgresRepository().installer_daily_workload("installer-a")["items"][0]

    assert item["exception_count"] == expected_exception_count
    assert item["unreviewed_count"] == expected_unreviewed_count


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

        def scalar(self, _statement):
            return None

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


def test_postgres_summary_installer_pairs_use_only_valid_construction_photos() -> None:
    captured = []

    class Rows:
        def __init__(self, values=None):
            self.values = values or []

        def all(self):
            return self.values

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

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def scalar(self, statement):
            captured.append(("scalar", statement))
            return 0

        def execute(self, statement):
            captured.append(("execute", statement))
            return Rows()

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return FakeSession()

    TestPostgresRepository().summary()

    compiled_statements = [
        str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).lower()
        for _kind, statement in captured
    ]
    compiled = next(statement for statement in compiled_statements if "select photos.creator" in statement)
    assert "photos.creator" in compiled
    assert "photos.is_active is true" in compiled
    assert "photos.upload_status != 'invalid'" in compiled
    assert "like '%%construction%%'" in compiled
    assert "photos.group_id is not null" in compiled
    assert "photos.creator is not null" in compiled
    assert "nullif(trim(photos.creator), '') is not null" in compiled


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


def test_postgres_quality_status_does_not_require_collector_photo() -> None:
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
        status=repository.GroupStatus.INCOMPLETE,
        exception_status="",
        exception_note="",
        exception_reasons=[],
        has_archive_blocker=False,
        reviewer="reviewer",
        review_note="",
        reviewed_at=datetime(2026, 6, 8, 9, 30),
        raw_data={"status": "incomplete"},
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

    assert group.status == repository.GroupStatus.UNREVIEWED
    assert group.exception_status == ""
    assert group.exception_note == ""
    assert group.exception_reasons == []
    assert group.has_archive_blocker is False
    assert group.raw_data["status"] == "pending"


def test_postgres_quality_status_clears_stale_missing_collector_photo_exception() -> None:
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
        status=repository.GroupStatus.REJECTED,
        exception_status="open",
        exception_note=repository.local_simulation.MISSING_COLLECTOR_PHOTO_LABEL,
        exception_reasons=[repository.local_simulation.MISSING_COLLECTOR_PHOTO_REASON],
        has_archive_blocker=True,
        reviewer=None,
        review_note="",
        reviewed_at=None,
        raw_data={
            "status": "exception",
            "exception_note": repository.local_simulation.MISSING_COLLECTOR_PHOTO_LABEL,
            "exception_reasons": [repository.local_simulation.MISSING_COLLECTOR_PHOTO_REASON],
        },
    )

    class FakeScalars:
        def all(self):
            return photos

    class FakeSession:
        def scalars(self, _statement):
            return FakeScalars()

    repository._apply_photo_quality_exception_status(FakeSession(), group)

    assert group.status == repository.GroupStatus.UNREVIEWED
    assert group.exception_status == ""
    assert group.exception_note == ""
    assert group.exception_reasons == []
    assert group.has_archive_blocker is False
    assert group.raw_data["status"] == "pending"
    assert group.raw_data["exception_reasons"] == []


def test_postgres_exception_listing_is_read_only_for_stale_missing_module_note() -> None:
    """Catches a GET/list projection repairing and committing production records as a side effect."""
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

    assert result["total"] == 1
    assert [item["id"] for item in result["items"]] == ["g-stale-module"]
    assert group.exception_note == "\u7f3a\u5c11\u6a21\u5757\u8d44\u4ea7\u7f16\u53f7"
    assert group.raw_data["exception_note"] == "\u7f3a\u5c11\u6a21\u5757\u8d44\u4ea7\u7f16\u53f7"
    assert group.status == repository.GroupStatus.REJECTED
    assert fake_session.committed is False


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


def test_postgres_dashboard_exception_clause_excludes_only_collector_missing_reasons() -> None:
    compiled = str(
        repository.select(repository._dashboard_exception_clause()).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "jsonb_array_length(material_groups.exception_reasons) > 0" in compiled
    assert "material_groups.exception_reasons <@" in compiled
    assert "missing_collector_photo" in compiled
    assert "missing_collector_info" in compiled
    assert "material_groups.status != 'approved'" in compiled


def test_postgres_problem_group_ignores_collector_missing_reasons_but_keeps_real_exceptions() -> None:
    collector_only = {
        "status": "exception",
        "photo_count": 3,
        "has_archive_blocker": True,
        "exception_reasons": ["missing_collector_photo", "缺少采集器信息"],
    }
    mixed = {
        **collector_only,
        "exception_reasons": ["missing_collector_photo", "缺少采集器信息", "missing_module_asset_no"],
    }

    assert repository._is_problem_group(collector_only) is False
    assert repository._is_problem_group(mixed) is True


def test_postgres_review_queue_status_ignores_only_collector_missing_reasons() -> None:
    compiled = str(
        repository.select(repository._review_queue_status_expression()).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "jsonb_array_length(material_groups.exception_reasons) > 0" in compiled
    assert "material_groups.exception_reasons <@" in compiled
    assert "missing_collector_info" in compiled


def test_postgres_exception_listing_ignores_only_collector_missing_reasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[object] = []

    class FakeScalars:
        def all(self):
            return []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalars(self, statement):
            captured.append(statement)
            return FakeScalars()

        def scalar(self, _statement):
            return 0

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return FakeSession()

    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: "default-team")

    TestPostgresRepository().list_exception_groups()
    compiled = str(
        captured[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "jsonb_array_length(material_groups.exception_reasons) > 0" in compiled
    assert "material_groups.exception_reasons <@" in compiled
    assert "missing_collector_info" in compiled


def test_postgres_archive_validation_does_not_generate_missing_collector_info() -> None:
    group = {
        "id": "group-1",
        "module_asset_no": "MOD-001",
        "photos": [
            {"category": "before_box", "collector": ""},
            {"category": "module_meter", "collector": "", "module_asset_no": "MOD-001"},
            {"category": "after_box", "collector": ""},
        ],
    }

    assert repository._validate_group_archive_with_module_map(group, {}) == []


def test_group_barcode_accuracy_summary_uses_durable_rows_and_skips_legacy_recomputation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_build_group_barcode_check(group: dict) -> dict:
        calls.append(str(group.get("id")))
        return {"group_barcode_check_status": "matched"}

    monkeypatch.setattr(repository.photo_barcode_check, "build_group_barcode_check", fake_build_group_barcode_check)
    categories = ["before_box", "collector_barcode", "module_meter", "after_box"]
    groups = [
        {
            "id": "complete",
            "barcode_verification": {
                "status": "passed",
                "meter_matched": True,
                "module_matched": True,
                "collector_matched": True,
                "recognition_source": "machine_barcode",
            },
            "photos": [{"category": category, "barcode_check_status": "matched"} for category in categories],
        },
        {
            "id": "incomplete",
            "barcode_verification": {
                "status": "passed",
                "meter_matched": True,
                "module_matched": True,
                "collector_matched": True,
                "recognition_source": "machine_barcode",
            },
            "photos": [{"category": category, "barcode_check_status": "matched"} for category in categories[:3]],
        },
    ]

    assert repository._group_barcode_accuracy_summary(groups, {}) == {
        "group_barcode_accuracy_checked": 1,
        "group_barcode_accuracy_passed": 1,
        "group_barcode_accuracy_failed": 0,
        "group_barcode_accuracy_unreadable": 0,
        "group_barcode_accuracy_not_required": 1,
        "group_barcode_accuracy_rate": 1.0,
        "group_barcode_accuracy_machine_passed": 1,
        "group_barcode_accuracy_manual_confirmed": 0,
        "group_barcode_accuracy_partial": 0,
        "group_barcode_accuracy_mismatch": 0,
        "group_barcode_accuracy_terminal_failed": 0,
        "group_barcode_accuracy_not_eligible": 1,
        "group_barcode_accuracy_pending": 0,
        "group_barcode_accuracy_processing": 0,
    }
    assert calls == []


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
    groups = [
        SimpleNamespace(id=f"model-{index}", legacy_id=f"group-{index}", team_id="alpha-team")
        for index in range(45)
    ]
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

        def scalars(self, statement):
            if "group_barcode_verifications" in str(statement):
                return PhotoResult()
            return PageScalars()

    class TestPostgresRepository(repository.PostgresStateRepository):
        def _session(self):
            return FakeSession()

        def _task_by_legacy_id(self, _session, _task_id):
            return SimpleNamespace(id="task-model")

    def minimal_group(_session, group, include_photos=False, *, verification=None):
        assert include_photos is False
        assert verification is None
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


def test_postgres_review_queue_search_includes_reviewer() -> None:
    conditions = repository._review_queue_search_conditions("team-a", "reviewer-alice")

    compiled = str(
        conditions[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    for expected in (
        "material_groups.reviewer ILIKE",
        "CAST(material_groups.status AS VARCHAR) ILIKE",
        "material_groups.raw_data ->> 'status'",
        "material_groups.raw_data ->> 'installer'",
        "material_groups.raw_data ->> 'creator'",
        "photos.creator ILIKE",
        "photos.original_filename ILIKE",
        "photos.source_file_id ILIKE",
    ):
        assert expected in compiled


def test_postgres_review_queue_search_includes_task_level_installer() -> None:
    conditions = repository._review_queue_search_conditions("team-a", "installer-alice")

    compiled = str(
        conditions[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "tasks.construction_claimed_by ILIKE" in compiled
    assert "tasks.id = material_groups.task_id" in compiled
    assert "tasks.team_id = 'team-a'" in compiled


def test_json_state_repository_delegates_review_risk_operations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repository.settings, "state_backend", "json")
    monkeypatch.setattr(
        repository.local_simulation,
        "delete_group_photo",
        lambda group_id, photo_id, reviewer, require_claim=True: {
            "group_id": group_id,
            "photo_id": photo_id,
            "reviewer": reviewer,
            "require_claim": require_claim,
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
        "require_claim": True,
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


def test_postgres_exception_submit_invalidates_delivery_artifacts_before_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    order_id = uuid4()
    group = SimpleNamespace(
        id=uuid4(),
        legacy_id="exception-submit-group",
        team_id="exception-team",
        task_id=uuid4(),
        display_meter_no="M-OLD",
        raw_data={"status": "exception", "delivery_cache_status": "ready"},
        status=repository.GroupStatus.REJECTED,
        reviewer="reviewer-a",
        review_note="old review",
        exception_note="old exception",
        has_archive_blocker=True,
        reviewed_at=datetime.now(UTC),
    )
    order = SimpleNamespace(
        id=order_id,
        group_id=group.id,
        status=repository.ExceptionStatus.OPEN,
        resolved_at=None,
    )
    task = SimpleNamespace(id=group.task_id, construction_claimed_by="constructor-a")
    photos = [SimpleNamespace(collector="C-OLD", asset_no="MOD-OLD")]
    events: list[object] = []

    class Scalars:
        def all(self):
            return photos

    class Session:
        def __init__(self):
            self.scalar_values = [order, group, task]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, _statement):
            return self.scalar_values.pop(0)

        def scalars(self, _statement):
            return Scalars()

        def commit(self):
            events.append("commit")

        def refresh(self, _value):
            return None

    session = Session()

    class TestRepository(repository.PostgresStateRepository):
        def _session(self):
            return session

        def _exception_order_payload(self, _session, checked_order, checked_group):
            return {"id": str(checked_order.id), "group_id": checked_group.legacy_id}

    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: group.team_id)
    monkeypatch.setattr(repository, "_group_payload", lambda *_args, **_kwargs: {"id": group.legacy_id})
    monkeypatch.setattr(
        repository,
        "invalidate_verification_for_group",
        lambda *_args, **_kwargs: events.append("verification"),
    )
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda *_args, **_kwargs: events.append("package"),
    )

    TestRepository().submit_construction_exception_order(
        str(order_id),
        actor="constructor-a",
        updates={"meter_no": "M-NEW", "collector": "C-NEW", "module_asset_no": "MOD-NEW"},
        note="repaired",
    )

    assert events == ["verification", "package", "commit"]


def test_postgres_return_to_exception_invalidates_delivery_artifacts_before_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    group = SimpleNamespace(
        id=uuid4(),
        legacy_id="return-exception-group",
        team_id="exception-team",
        project_id=uuid4(),
        task_id=uuid4(),
        raw_data={"status": "approved", "delivery_cache_status": "ready"},
        status=repository.GroupStatus.APPROVED,
        reviewer="reviewer-a",
        review_note="ready",
        exception_note="",
        exception_reasons=[],
        has_archive_blocker=False,
        reviewed_at=datetime.now(UTC),
    )
    events: list[object] = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def add(self, _value):
            return None

        def commit(self):
            events.append("commit")

        def refresh(self, _value):
            return None

    class TestRepository(repository.PostgresStateRepository):
        def _session(self):
            return Session()

        def _group_by_legacy_id(self, _session, group_id, *, lock=False):
            assert group_id == group.legacy_id
            assert lock is True
            return group

        def _ensure_task_claimed_by(self, *_args, **_kwargs):
            return None

        def _exception_order_payload(self, _session, _order, _group):
            return {"id": "exception-order"}

    monkeypatch.setattr(repository, "_group_payload", lambda *_args, **_kwargs: {"id": group.legacy_id})
    monkeypatch.setattr(
        repository,
        "invalidate_verification_for_group",
        lambda *_args, **_kwargs: events.append("verification"),
    )
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda *_args, **_kwargs: events.append("package"),
    )

    TestRepository().return_group_to_exception_order(
        group.legacy_id,
        actor="reviewer-a",
        category="photo_quality",
        note="needs repair",
    )

    assert events == ["verification", "package", "commit"]


@pytest.mark.parametrize("fail_commit", [False, True], ids=["committed", "commit-failure"])
def test_postgres_bulk_archive_invalidates_before_commit_and_requeues_after_commit(
    fail_commit: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    group = SimpleNamespace(
        id=uuid4(),
        legacy_id="bulk-archive-group",
        team_id="archive-team",
        raw_data={"status": "pending", "delivery_cache_status": "ready"},
        status=repository.GroupStatus.UNREVIEWED,
        reviewer=None,
        review_note="",
        exception_note="",
        exception_reasons=[],
        exception_status=None,
        has_archive_blocker=False,
        reviewed_at=None,
    )
    photo = SimpleNamespace(
        id=uuid4(),
        legacy_id="bulk-photo",
        raw_data={},
        category="before_box",
        image_url="/static/uploads/bulk-photo.jpg",
        source_url="",
        archive_status="pending",
        archive_filename=None,
        archived_at=None,
        classified_by=None,
    )
    events: list[object] = []

    class Scalars:
        def all(self):
            return [photo]

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalars(self, _statement):
            return Scalars()

        def commit(self):
            events.append("commit")
            if fail_commit:
                raise RuntimeError("injected bulk archive commit failure")

        def refresh(self, _value):
            return None

    class TestRepository(repository.PostgresStateRepository):
        def _session(self):
            return Session()

        def _group_by_legacy_id(self, _session, group_id, *, lock=False):
            assert group_id == group.legacy_id
            assert lock is True
            return group

        def _enqueue_delivery_cache_after_commit(self, group_id, *, actor, reason, **_kwargs):
            events.append(("requeue", group_id, actor, reason))

    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: group.team_id)
    monkeypatch.setattr(
        repository,
        "_group_payload",
        lambda *_args, **_kwargs: {"id": group.legacy_id, "photos": [{"id": photo.legacy_id}]},
    )
    monkeypatch.setattr(repository, "_group_barcode_context", lambda _group: {})
    monkeypatch.setattr(repository, "_photo_payload", lambda _photo: {"id": photo.legacy_id})
    monkeypatch.setattr(repository, "_group_target_summary", lambda payload, **_kwargs: payload)
    monkeypatch.setattr(repository, "_stage_transactional_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(repository.photo_barcode_check, "ensure_photo_barcode_check", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(repository.local_simulation, "validate_group_archive", lambda _group: [])
    monkeypatch.setattr(
        repository,
        "invalidate_verification_for_group",
        lambda *_args, **_kwargs: events.append("verification"),
    )
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda *_args, **_kwargs: events.append("package"),
    )

    if fail_commit:
        with pytest.raises(RuntimeError, match="injected bulk archive commit failure"):
            TestRepository().bulk_archive_groups([group.legacy_id], actor="admin-a", reason="manual archive")
        assert events == ["verification", "package", "commit"]
    else:
        TestRepository().bulk_archive_groups([group.legacy_id], actor="admin-a", reason="manual archive")
        assert events == [
            "verification",
            "package",
            "commit",
            ("requeue", group.legacy_id, "admin-a", "bulk_archive_completed"),
        ]


def test_postgres_clear_scan_invalidates_all_group_delivery_artifacts_before_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    group = SimpleNamespace(
        id=uuid4(),
        legacy_id="clear-scan-group",
        team_id="clear-team",
        photo_count=1,
        raw_data={"status": "approved", "delivery_cache_status": "ready"},
        status=repository.GroupStatus.APPROVED,
        reviewer="reviewer-a",
        review_note="ready",
        exception_note="",
        exception_reasons=[],
        has_archive_blocker=False,
        reviewed_at=datetime.now(UTC),
    )
    photo = SimpleNamespace(
        is_active=True,
        deleted_at=None,
        deleted_by=None,
        delete_reason=None,
    )
    unmatched = SimpleNamespace(status="open")
    events: list[object] = []

    class Scalars:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalars(self, statement):
            sql = str(statement)
            if "FROM photos" in sql:
                return Scalars([photo])
            if "FROM material_groups" in sql:
                return Scalars([group])
            if "FROM unmatched_records" in sql:
                return Scalars([unmatched])
            raise AssertionError(sql)

        def commit(self):
            events.append("commit")

    class TestRepository(repository.PostgresStateRepository):
        def _session(self):
            return Session()

        def summary(self):
            return {"summary": {"scan_rows": 0}}

    monkeypatch.setattr(repository.local_simulation, "current_team_id", lambda: group.team_id)
    monkeypatch.setattr(
        repository,
        "invalidate_verification_for_group",
        lambda *_args, **_kwargs: events.append("verification"),
    )
    monkeypatch.setattr(
        delivery_cache,
        "invalidate_postgres_delivery_cache_for_group_change",
        lambda *_args, **_kwargs: events.append("package"),
    )

    TestRepository().clear_scan_data()

    assert events == ["verification", "package", "commit"]
