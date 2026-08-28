from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy.dialects import postgresql

from app.services import local_simulation
from app.services.group_barcode_verification import evaluate_group_eligibility
from app.services.export_retirement import ExportCenterRetiredError


REQUIRED_CATEGORIES = ("before_box", "collector_barcode", "module_meter", "after_box")


def _explode_retired_delivery_path(*_args, **_kwargs):
    raise AssertionError("retired delivery path was called")


def test_delivery_worker_claims_only_verification_and_auto_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import barcode_maintenance_worker as worker

    calls: list[str] = []
    monkeypatch.setattr(worker, "_next_claim_kind", "delivery_package")
    monkeypatch.setattr(
        worker,
        "claim_next_verification_job",
        lambda **_kwargs: calls.append("verification"),
    )
    monkeypatch.setattr(
        worker,
        "claim_next_archive_job",
        lambda **_kwargs: calls.append("auto_archive"),
    )
    monkeypatch.setattr(worker, "claim_next_delivery_cache_job", _explode_retired_delivery_path)
    monkeypatch.setattr(worker, "claim_next_delivery_package_job", _explode_retired_delivery_path)

    assert worker._claim_next_work("worker-1") is None
    assert set(calls) == {"verification", "auto_archive"}


def test_worker_batch_never_runs_delivery_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import barcode_maintenance_worker as worker

    calls: list[str] = []
    monkeypatch.setattr(worker, "_claim_next_work", lambda _worker_id: None)
    monkeypatch.setattr(
        worker,
        "process_storage_cleanup_jobs",
        lambda **_kwargs: {"processed": 0, "completed": 0, "failed": 0},
    )
    monkeypatch.setattr(
        worker,
        "run_delivery_cache_cleanup_if_due",
        lambda: calls.append("cleanup") or {"status": "unexpected"},
    )
    monkeypatch.setattr(
        worker,
        "reconcile_delivery_cache_jobs",
        lambda **_kwargs: calls.append("reconcile"),
    )

    report = worker.run_worker_batch(batch_size=1, batch_pause_seconds=0, can_claim=lambda: True)

    assert calls == []
    assert report["processed"] == report["failed"] == 0
    assert report["status"] == "complete"
    assert "cleanup" not in report


@pytest.mark.parametrize("kind", ["delivery_cache", "delivery_package"])
def test_worker_rejects_retired_delivery_jobs(kind: str) -> None:
    from app.services import barcode_maintenance_worker as worker

    with pytest.raises(ExportCenterRetiredError):
        worker._process_job(worker.MaintenanceJob(kind=kind, team_id="team", group_id="job"))


@pytest.mark.parametrize("kind", ["delivery_cache", "delivery_package"])
def test_worker_batch_rejects_stale_delivery_job_without_failure_mutation(kind: str) -> None:
    from app.services import barcode_maintenance_worker as worker

    job = worker.MaintenanceJob(
        kind=kind,
        team_id="historical-team",
        group_id="historical-group",
        lease_owner="historical-worker",
        lease_token="historical-lease",
    )
    claims = iter([job])

    with pytest.raises(ExportCenterRetiredError):
        worker.run_worker_batch(
            batch_size=1,
            batch_pause_seconds=0,
            claim_next=lambda: next(claims, None),
            can_claim=lambda: True,
            load_too_high=lambda: False,
            fail_job=_explode_retired_delivery_path,
        )


def eligible_group(group_id: str, *, verification_status: str = "pending") -> dict:
    photos = [
        {
            "id": f"{group_id}-photo-{index}",
            "sha256": f"{index + 1:x}" * 64,
            "category": category,
            "is_active": True,
            "upload_status": "uploaded",
            "image_url": f"oss://bucket/{group_id}-{index}.jpg",
        }
        for index, category in enumerate(REQUIRED_CATEGORIES)
    ]
    group = {
        "id": group_id,
        "legacy_id": group_id,
        "task_id": 17,
        "terminal": f"T-{group_id}",
        "meter_no": f"METER-{group_id}",
        "module_asset_no": f"MODULE-{group_id}",
        "collector": f"COLLECTOR-{group_id}",
        "status": "unreviewed",
        "photo_count": 4,
        "reviewer": "",
        "review_note": "",
        "exception_note": "",
        "exception_reasons": [],
        "has_archive_blocker": False,
        "photos": photos,
    }
    fingerprint = evaluate_group_eligibility(group).evidence_fingerprint
    assert fingerprint
    group["barcode_verification"] = {
        "status": verification_status,
        "evidence_fingerprint": fingerprint,
        "evidence_version": 1,
        "attempt_count": 0,
        "lease_owner": None,
        "lease_token": None,
        "lease_expires_at": None,
        "meter_matched": verification_status in {"passed", "manual_confirmed"},
        "module_matched": verification_status in {"passed", "manual_confirmed"},
        "collector_matched": verification_status in {"passed", "manual_confirmed"},
        "recognition_source": "manual_confirmed" if verification_status == "manual_confirmed" else "machine_barcode",
        "result": {
            "passed_count": 3 if verification_status in {"passed", "manual_confirmed"} else 0,
            "matched_fields": ["meter", "module", "collector"] if verification_status in {"passed", "manual_confirmed"} else [],
            "missing_fields": [] if verification_status in {"passed", "manual_confirmed"} else ["meter", "module", "collector"],
            "machine_barcode_values": [group["meter_no"], group["module_asset_no"], group["collector"]],
            "machine_qr_values": [],
            "ocr_candidates": [],
        },
    }
    return group


def test_worker_batch_processes_durable_storage_cleanup_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import barcode_maintenance_worker as worker

    assert hasattr(worker, "process_storage_cleanup_jobs")
    monkeypatch.setattr(worker, "_maintenance_can_claim", lambda: True)
    monkeypatch.setattr(worker, "_claim_next_work", lambda _worker_id: None)
    monkeypatch.setattr(worker, "run_delivery_cache_cleanup_if_due", lambda: {"status": "skipped"})
    monkeypatch.setattr(worker, "reconcile_delivery_cache_jobs", lambda **_kwargs: {})
    monkeypatch.setattr(
        worker,
        "process_storage_cleanup_jobs",
        lambda **_kwargs: {"processed": 1, "completed": 1, "failed": 0},
    )

    report = worker.run_worker_batch(batch_size=20, batch_pause_seconds=0)

    assert report["storage_cleanup"] == {"processed": 1, "completed": 1, "failed": 0}


def postgres_eligible_photos(group) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            id=uuid4(),
            legacy_id=f"{group.id}-photo-{index}",
            team_id=group.team_id,
            group_id=group.id,
            is_active=True,
            upload_status="uploaded",
            category=category,
            image_url=f"oss://bucket/{group.id}-{index}.jpg",
            source_url=f"oss://bucket/{group.id}-{index}.jpg",
            storage_type="oss",
            storage_bucket="bucket",
            storage_key=f"{group.id}-{index}.jpg",
            sha256=f"{index + 1:x}" * 64,
            raw_data={"construction_slot": category},
        )
        for index, category in enumerate(REQUIRED_CATEGORIES)
    ]


def _write_machine_code_image(path: Path, value: str = "") -> None:
    if value:
        import zxingcpp

        barcode = zxingcpp.create_barcode(value, zxingcpp.BarcodeFormat.Code128)
        bitmap = zxingcpp.write_barcode_to_image(
            barcode,
            scale=4,
            add_hrt=False,
            add_quiet_zones=True,
        )
        image = Image.frombytes("L", (bitmap.shape[1], bitmap.shape[0]), bytes(memoryview(bitmap)))
    else:
        image = Image.new("L", (900, 180), color=255)
    try:
        image.save(path, format="PNG")
    finally:
        image.close()


def _production_scan_fixture(tmp_path: Path, *, photo_count: int = 4):
    group = SimpleNamespace(
        id=uuid4(),
        legacy_id="production-worker-group",
        team_id="production-worker-team",
        terminal="120000000001",
        display_meter_no="110000288056",
        raw_data={
            "construction_collector": "COLLECTOR001",
            "construction_module_asset_no": "MODULE001",
        },
    )
    machine_values = (group.display_meter_no, "COLLECTOR001", "MODULE001", "")
    photos: list[SimpleNamespace] = []
    for index, (category, machine_value) in enumerate(zip(REQUIRED_CATEGORIES, machine_values)):
        if index >= photo_count:
            break
        filename = f"production-worker-{index}.png"
        image_path = tmp_path / filename
        _write_machine_code_image(image_path, machine_value)
        content = image_path.read_bytes()
        photos.append(
            SimpleNamespace(
                id=uuid4(),
                legacy_id=f"production-worker-photo-{index}",
                team_id=group.team_id,
                group_id=group.id,
                is_active=True,
                upload_status="uploaded",
                category=category,
                image_url=f"/static/uploads/{filename}",
                source_url=f"/static/uploads/{filename}",
                storage_type="local_upload",
                storage_bucket="",
                storage_key=filename,
                sha256=hashlib.sha256(content).hexdigest(),
                raw_data={"private_secret": "must-not-enter-worker-payload"},
            )
        )
    return group, photos


def _install_production_worker_repository(
    monkeypatch: pytest.MonkeyPatch,
    group: SimpleNamespace,
    photos: list[SimpleNamespace],
):
    from app.services import barcode_maintenance_worker as worker
    from app.services import state_repository

    class Rows:
        def all(self):
            return photos

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, _statement):
            return group

        def scalars(self, _statement):
            return Rows()

    class LoadRepository:
        def _session(self):
            return Session()

    applied: list[object] = []

    class ApplyRepository:
        def apply_group_scan_result(self, _group_id, result, **_kwargs):
            assert _group_id == group.legacy_id
            applied.append(result)

    monkeypatch.setattr(worker, "_backend", lambda: "postgres")
    monkeypatch.setattr(state_repository, "PostgresStateRepository", LoadRepository)
    monkeypatch.setattr(state_repository, "get_state_repository", lambda: ApplyRepository())
    return worker, applied


def test_production_worker_scans_real_uploaded_photos_through_existing_machine_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import photo_barcode_check

    group, photos = _production_scan_fixture(tmp_path)
    worker, applied = _install_production_worker_repository(monkeypatch, group, photos)
    monkeypatch.setattr(photo_barcode_check, "static_upload_root", lambda: tmp_path)

    worker._process_verification_job(
        worker.MaintenanceJob(
            kind="verification",
            team_id=group.team_id,
            group_id=str(group.id),
            lease_owner="production-worker",
            lease_token="production-lease",
            evidence_fingerprint="f" * 64,
            evidence_version=3,
        )
    )

    assert len(applied) == 1
    result = applied[0]
    assert result.status == "passed"
    assert result.passed_count == 3
    assert set(result.matched_fields) == {"meter", "module", "collector"}
    assert set(result.machine_barcode_values) >= {
        group.display_meter_no,
        "COLLECTOR001",
        "MODULE001",
    }


def test_production_worker_never_passes_ocr_only_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import photo_barcode_check

    group, photos = _production_scan_fixture(tmp_path)
    worker, applied = _install_production_worker_repository(monkeypatch, group, photos)
    monkeypatch.setattr(photo_barcode_check, "static_upload_root", lambda: tmp_path)
    monkeypatch.setattr(
        photo_barcode_check,
        "default_machine_code_scanner",
        lambda _photo: {"barcode": [], "qr": []},
    )
    monkeypatch.setattr(
        photo_barcode_check,
        "default_ocr_reader",
        lambda _photo, _expected: [group.display_meter_no, "COLLECTOR001", "MODULE001"],
    )

    worker._process_verification_job(
        worker.MaintenanceJob(
            kind="verification",
            team_id=group.team_id,
            group_id=str(group.id),
            lease_owner="production-worker",
            lease_token="production-lease",
            evidence_fingerprint="f" * 64,
            evidence_version=3,
        )
    )

    assert len(applied) == 1
    assert applied[0].status != "passed"
    assert applied[0].passed_count == 0
    assert set(applied[0].matched_ocr_candidates) >= {
        group.display_meter_no,
        "COLLECTOR001",
        "MODULE001",
    }


def test_production_worker_rejects_non_exact_photo_set_before_reading_image(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import photo_barcode_check

    group, photos = _production_scan_fixture(tmp_path, photo_count=3)
    worker, applied = _install_production_worker_repository(monkeypatch, group, photos)
    monkeypatch.setattr(
        photo_barcode_check,
        "_photo_image",
        lambda _photo: pytest.fail("ineligible photo set must not read image bytes"),
    )

    with pytest.raises(ValueError, match="not eligible"):
        worker._process_verification_job(
            worker.MaintenanceJob(
                kind="verification",
                team_id=group.team_id,
                group_id=str(group.id),
                lease_owner="production-worker",
                lease_token="production-lease",
                evidence_fingerprint="f" * 64,
                evidence_version=3,
            )
        )

    assert applied == []


def install_json_queue(monkeypatch: pytest.MonkeyPatch, groups: list[dict], *, paused: bool = False) -> str:
    team_id = f"maintenance-{uuid4()}"
    state = local_simulation.blank_state(team_id)
    state.update(
        {
            "groups": groups,
            "summary": local_simulation.empty_summary(),
            "barcode_maintenance_control": {"paused": paused, "last_batch_id": "", "last_batch_progress": 0},
            "delivery_cache_jobs": [],
        }
    )
    monkeypatch.setitem(local_simulation._team_states, team_id, state)
    monkeypatch.setattr(local_simulation, "current_team_id", lambda: team_id)
    monkeypatch.setattr(local_simulation, "save_all_team_states", lambda: None)
    return team_id


def test_worker_batch_is_strictly_serial_caps_at_twenty_and_sleeps_once() -> None:
    from app.services.barcode_maintenance_worker import MaintenanceJob, run_worker_batch

    pending = deque(
        MaintenanceJob(kind="verification", team_id="team-a", group_id=f"group-{index}")
        for index in range(21)
    )
    active = 0
    maximum_active = 0
    processed: list[str] = []
    sleeps: list[float] = []

    def claim_next() -> MaintenanceJob | None:
        return pending.popleft() if pending else None

    def process(job: MaintenanceJob) -> None:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        processed.append(job.group_id)
        active -= 1

    report = run_worker_batch(
        batch_size=20,
        batch_pause_seconds=5,
        claim_next=claim_next,
        process_job=process,
        can_claim=lambda: True,
        load_too_high=lambda: False,
        sleeper=sleeps.append,
    )

    assert report["processed"] == 20
    assert processed == [f"group-{index}" for index in range(20)]
    assert maximum_active == 1
    assert len(pending) == 1
    assert sleeps == [5]


def test_worker_does_not_claim_when_paused_or_loaded_and_finishes_current_job() -> None:
    from app.services.barcode_maintenance_worker import MaintenanceJob, run_worker_batch

    claims: list[str] = []
    processed: list[str] = []

    paused_report = run_worker_batch(
        claim_next=lambda: claims.append("claim") or None,
        process_job=lambda job: processed.append(job.group_id),
        can_claim=lambda: False,
        load_too_high=lambda: False,
        sleeper=lambda _seconds: None,
    )
    assert paused_report["processed"] == 0
    assert claims == []

    jobs = deque(
        [
            MaintenanceJob(kind="verification", team_id="team-a", group_id="group-1"),
            MaintenanceJob(kind="verification", team_id="team-a", group_id="group-2"),
        ]
    )
    load_checks = iter([False, False, True])
    loaded_report = run_worker_batch(
        claim_next=lambda: jobs.popleft() if jobs else None,
        process_job=lambda job: processed.append(job.group_id),
        can_claim=lambda: True,
        load_too_high=lambda: next(load_checks),
        sleeper=lambda _seconds: None,
    )
    assert loaded_report["processed"] == 1
    assert processed == ["group-1"]
    assert [job.group_id for job in jobs] == ["group-2"]


def test_json_claim_is_single_owner_and_expired_lease_is_recoverable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.barcode_maintenance_worker import claim_next_verification_job

    now = datetime(2026, 7, 22, 4, 0, tzinfo=UTC)
    pending = eligible_group("pending")
    expired = eligible_group("expired")
    expired["barcode_verification"].update(
        {
            "status": "processing",
            "attempt_count": 1,
            "lease_owner": "dead-worker",
            "lease_token": "dead-token",
            "lease_expires_at": (now - timedelta(seconds=1)).isoformat(),
        }
    )
    live = eligible_group("live")
    live["barcode_verification"].update(
        {
            "status": "processing",
            "attempt_count": 1,
            "lease_owner": "live-worker",
            "lease_token": "live-token",
            "lease_expires_at": (now + timedelta(minutes=5)).isoformat(),
        }
    )
    install_json_queue(monkeypatch, [pending, expired, live])
    gate = Lock()

    def compete(worker_id: str):
        with gate:
            return claim_next_verification_job(worker_id=worker_id, now=now)

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(compete, ["worker-a", "worker-b"]))

    claimed_ids = [claim.group_id for claim in claims if claim is not None]
    assert sorted(claimed_ids) == ["expired", "pending"]
    assert len(claimed_ids) == len(set(claimed_ids))
    assert "live" not in claimed_ids


def test_failed_claim_retries_after_restart_then_moves_to_manual_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.barcode_maintenance_worker import (
        MAX_VERIFICATION_ATTEMPTS,
        claim_next_verification_job,
        fail_verification_job,
    )

    group = eligible_group("retry")
    team_id = install_json_queue(monkeypatch, [group])
    now = datetime(2026, 7, 22, 5, 0, tzinfo=UTC)

    for attempt in range(1, MAX_VERIFICATION_ATTEMPTS + 1):
        claim = claim_next_verification_job(worker_id=f"worker-{attempt}", now=now)
        assert claim is not None
        fail_verification_job(claim, RuntimeError(f"failure-{attempt}"), now=now)
        committed_group = local_simulation._team_states[team_id]["groups"][0]
        verification = committed_group["barcode_verification"]
        assert verification["attempt_count"] == attempt
        assert verification["lease_owner"] is None
        if attempt < MAX_VERIFICATION_ATTEMPTS:
            assert verification["status"] == "failed"
            assert verification["retryable"] is True
        else:
            assert verification["status"] == "failed"
            assert verification["retryable"] is False
            assert verification["manual_review_required"] is True

    assert claim_next_verification_job(worker_id="worker-final", now=now) is None


def test_postgres_claim_statement_uses_skip_locked_and_retryable_statuses() -> None:
    from app.services.barcode_maintenance_worker import build_postgres_verification_claim_statement

    statement = build_postgres_verification_claim_statement(
        team_id="team-a",
        now=datetime(2026, 7, 22, 5, 0, tzinfo=UTC),
    )
    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "group_barcode_verifications.status = 'pending'" in sql
    assert "group_barcode_verifications.status = 'failed'" in sql
    assert "group_barcode_verifications.status = 'processing'" in sql
    assert "group_barcode_verifications.lease_expires_at" in sql


@pytest.mark.parametrize("verification_status", ["passed", "manual_confirmed"])
def test_json_archive_claim_recovers_committed_pass_after_restart_with_a_lease(
    monkeypatch: pytest.MonkeyPatch,
    verification_status: str,
) -> None:
    from app.services import barcode_maintenance_worker as worker

    assert hasattr(worker, "claim_next_archive_job"), "archive-pending work must have a durable worker claim path"
    now = datetime(2026, 7, 22, 5, 30, tzinfo=UTC)
    group = eligible_group(f"recover-{verification_status}", verification_status=verification_status)
    group["barcode_verification"].pop("auto_archive_status", None)
    team_id = install_json_queue(monkeypatch, [group])

    first = worker.claim_next_archive_job(worker_id="restarted-worker", now=now, lease_seconds=60)
    second = worker.claim_next_archive_job(worker_id="competing-worker", now=now, lease_seconds=60)

    assert first is not None
    assert first.kind == "auto_archive"
    assert first.group_id == group["id"]
    assert second is None
    persisted = local_simulation._team_states[team_id]["groups"][0]["barcode_verification"]
    assert persisted["status"] == verification_status
    assert persisted["auto_archive_status"] == "processing"
    assert persisted["auto_archive_attempt_count"] == 1
    assert persisted["auto_archive_lease_owner"] == "restarted-worker"
    assert persisted["auto_archive_lease_token"] == first.lease_token
    assert persisted["auto_archive_lease_expires_at"] == (now + timedelta(seconds=60)).isoformat()
    reconciled = [
        event
        for event in local_simulation._team_states[team_id]["audit_events"]
        if event["action"] == "group_barcode_auto_archive_reconciled"
    ]
    assert len(reconciled) == 1


def test_json_archive_failure_retries_then_requires_manual_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import barcode_maintenance_worker as worker

    assert hasattr(worker, "claim_next_archive_job")
    assert hasattr(worker, "fail_archive_job")
    group = eligible_group("archive-retry", verification_status="passed")
    group["barcode_verification"]["auto_archive_status"] = "pending"
    team_id = install_json_queue(monkeypatch, [group])
    now = datetime(2026, 7, 22, 5, 45, tzinfo=UTC)

    for attempt in range(1, worker.MAX_AUTO_ARCHIVE_ATTEMPTS + 1):
        claim = worker.claim_next_archive_job(worker_id=f"archive-worker-{attempt}", now=now)
        assert claim is not None
        worker.fail_archive_job(claim, RuntimeError(f"archive-failure-{attempt}"), now=now)
        persisted = local_simulation._team_states[team_id]["groups"][0]["barcode_verification"]
        assert persisted["auto_archive_attempt_count"] == attempt
        assert persisted["auto_archive_lease_owner"] is None
        if attempt < worker.MAX_AUTO_ARCHIVE_ATTEMPTS:
            assert persisted["auto_archive_status"] == "retry_pending"
        else:
            assert persisted["auto_archive_status"] == "manual_required"

    assert worker.claim_next_archive_job(worker_id="archive-worker-final", now=now) is None


def test_worker_claim_rotation_includes_durable_archive_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import barcode_maintenance_worker as worker

    archive_job = worker.MaintenanceJob(
        kind="auto_archive",
        team_id="team-a",
        group_id="group-a",
        lease_owner="worker-a",
        lease_token="lease-a",
    )
    calls: list[str] = []
    monkeypatch.setattr(worker, "_next_claim_kind", "verification")
    monkeypatch.setattr(
        worker,
        "claim_next_verification_job",
        lambda *, worker_id: calls.append(f"verification:{worker_id}"),
    )
    monkeypatch.setattr(
        worker,
        "claim_next_archive_job",
        lambda *, worker_id: calls.append(f"auto_archive:{worker_id}") or archive_job,
    )
    monkeypatch.setattr(
        worker,
        "claim_next_delivery_cache_job",
        lambda *, worker_id: calls.append(f"delivery_cache:{worker_id}"),
    )

    assert worker._claim_next_work("worker-a") == archive_job
    assert calls == ["verification:worker-a", "auto_archive:worker-a"]


def test_worker_processes_archive_only_through_the_claimed_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import barcode_maintenance_worker as worker

    calls: list[dict[str, str]] = []
    monkeypatch.setattr(worker.settings, "state_backend", "json")
    monkeypatch.setattr(
        worker,
        "auto_archive_verified_group",
        lambda group_id, **kwargs: calls.append({"group_id": group_id, **kwargs})
        or {"archived": True, "group_id": group_id},
    )
    job = worker.MaintenanceJob(
        kind="auto_archive",
        team_id="team-a",
        group_id="group-a",
        lease_owner="worker-a",
        lease_token="lease-a",
    )

    worker._process_job(job)

    assert calls == [
        {
            "group_id": "group-a",
            "actor": worker.WORKER_ACTOR,
            "lease_owner": "worker-a",
            "lease_token": "lease-a",
        }
    ]


def test_postgres_archive_claim_uses_skip_locked_and_dedicated_lease_state() -> None:
    from app.services import barcode_maintenance_worker as worker

    assert hasattr(worker, "build_postgres_archive_claim_statement")
    statement = worker.build_postgres_archive_claim_statement(
        team_id="team-a",
        now=datetime(2026, 7, 22, 6, 0, tzinfo=UTC),
    )
    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "group_barcode_verifications.status IN ('passed', 'manual_confirmed')" in sql
    assert "group_barcode_verifications.auto_archive_status" in sql
    assert "group_barcode_verifications.auto_archive_attempt_count" in sql
    assert "group_barcode_verifications.auto_archive_lease_expires_at" in sql


def test_postgres_archive_claim_carries_legacy_id_into_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import barcode_maintenance_worker as worker

    now = datetime(2026, 7, 23, 16, 0, tzinfo=UTC)
    group = SimpleNamespace(id=uuid4(), legacy_id="archive-business-id", team_id="team-a")
    control = SimpleNamespace(paused=False)
    verification = SimpleNamespace(
        group_id=group.id,
        status="passed",
        evidence_fingerprint="f" * 64,
        evidence_version=4,
        auto_archive_status="pending",
        auto_archive_attempt_count=0,
        auto_archive_lease_owner=None,
        auto_archive_lease_token=None,
        auto_archive_lease_expires_at=None,
        auto_archive_error=None,
    )

    class Rows:
        def all(self):
            return []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalars(self, _statement):
            return Rows()

        def scalar(self, statement):
            sql = str(statement.compile(dialect=postgresql.dialect()))
            if "FROM barcode_maintenance_controls" in sql:
                return control
            if "FROM group_barcode_verifications" in sql:
                return verification
            if "FROM material_groups" in sql:
                return group
            pytest.fail(f"unexpected archive claim statement: {sql}")

        def commit(self):
            return None

        def rollback(self):
            return None

    monkeypatch.setattr(worker, "SessionLocal", Session)
    claim = worker._claim_postgres_archive(
        worker_id="archive-worker",
        team_id=group.team_id,
        now=now,
        lease_seconds=60,
    )
    assert claim is not None
    assert claim.group_id == str(group.id)
    assert claim.business_group_id == group.legacy_id

    calls: list[str] = []
    monkeypatch.setattr(
        worker,
        "auto_archive_verified_group",
        lambda group_id, **_kwargs: calls.append(group_id) or {"archived": True, "group_id": group_id},
    )
    worker._process_archive_job(claim)

    assert calls == [group.legacy_id]


def test_postgres_delivery_package_claim_uses_skip_locked_and_persistent_lease_state() -> None:
    from app.services import barcode_maintenance_worker as worker

    assert hasattr(worker, "build_postgres_delivery_package_claim_statement")
    statement = worker.build_postgres_delivery_package_claim_statement(
        team_id="team-a",
        now=datetime(2026, 7, 23, 2, 0, tzinfo=UTC),
    )
    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "delivery_package_jobs.status" in sql
    assert "delivery_package_jobs.lease_expires_at" in sql


def test_postgres_delivery_package_claim_terminalizes_expired_exhausted_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_package_queue

    now = datetime(2026, 7, 23, 2, 0, tzinfo=UTC)
    exhausted = SimpleNamespace(
        id=uuid4(),
        status="processing",
        attempt_count=delivery_package_queue.MAX_DELIVERY_PACKAGE_ATTEMPTS,
        lease_owner="stopped-worker",
        lease_token="stopped-token",
        lease_expires_at=now - timedelta(seconds=1),
        last_error=None,
    )
    statements: list[str] = []

    class Rows:
        def all(self):
            return [exhausted]

    class Session:
        committed = False
        rolled_back = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, statement):
            sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
            statements.append(sql)
            if "FROM barcode_maintenance_controls" in sql:
                return SimpleNamespace(paused=False)
            return None

        def scalars(self, statement):
            statements.append(str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})))
            return Rows()

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

    session = Session()
    monkeypatch.setattr(delivery_package_queue, "SessionLocal", lambda: session)

    claim = delivery_package_queue.claim_postgres_delivery_package_job(
        worker_id="new-worker",
        team_id="team-expired-package",
        now=now,
    )

    assert claim is None
    assert exhausted.status == "failed"
    assert exhausted.lease_owner is None
    assert exhausted.lease_token is None
    assert exhausted.lease_expires_at is None
    assert "maximum attempts" in exhausted.last_error
    assert session.committed is True
    assert session.rolled_back is False
    assert any("delivery_package_jobs.status = 'processing'" in sql for sql in statements)


def test_json_delivery_package_job_is_rejected_by_serial_worker_after_stale_direct_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import barcode_maintenance_worker as worker
    from app.services import state_repository

    assert hasattr(worker, "claim_next_delivery_package_job")
    team_id = install_json_queue(monkeypatch, [])
    package_path = tmp_path / "packages" / f"{'a' * 64}.zip"
    package_path.parent.mkdir(parents=True, exist_ok=True)
    package_path.write_bytes(b"formal-package")
    local_simulation._team_states[team_id]["delivery_package_jobs"] = [
        {
            "id": "package-job-a",
            "team_id": team_id,
            "scope_payload": {"task_id": 17, "terminal": "", "review_scope": "reviewed"},
            "evidence_fingerprint": "a" * 64,
            "status": "pending",
            "attempt_count": 0,
            "updated_at": "2026-07-23T02:00:00+00:00",
        }
    ]
    releases: list[Path] = []

    class Package:
        path = package_path

        def release(self):
            releases.append(self.path)

    class Repository:
        def build_final_delivery_export(self, **kwargs):
            assert kwargs == {"task_id": 17, "terminal": "", "review_scope": "reviewed"}
            return Package()

    monkeypatch.setattr(state_repository, "get_state_repository", lambda: Repository())
    now = datetime(2026, 7, 23, 2, 5, tzinfo=UTC)

    claim = worker.claim_next_delivery_package_job(worker_id="package-worker", now=now)
    competing = worker.claim_next_delivery_package_job(worker_id="other-worker", now=now)
    assert claim is not None
    assert claim.kind == "delivery_package"
    assert competing is None

    with pytest.raises(ExportCenterRetiredError):
        worker._process_job(claim)

    job = local_simulation._team_states[team_id]["delivery_package_jobs"][0]
    assert job["status"] == "processing"
    assert "package_path" not in job
    assert job["lease_owner"] == "package-worker"
    assert job["lease_token"]
    assert releases == []


def test_json_delivery_package_failures_stop_after_retry_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import barcode_maintenance_worker as worker

    team_id = install_json_queue(monkeypatch, [])
    local_simulation._team_states[team_id]["delivery_package_jobs"] = [
        {
            "id": "package-job-retry",
            "team_id": team_id,
            "scope_payload": {"task_id": 17, "terminal": "", "review_scope": "reviewed"},
            "evidence_fingerprint": "b" * 64,
            "status": "pending",
            "attempt_count": 0,
            "updated_at": "2026-07-23T02:00:00+00:00",
        }
    ]
    now = datetime(2026, 7, 23, 2, 10, tzinfo=UTC)

    for attempt in range(1, worker.MAX_DELIVERY_PACKAGE_ATTEMPTS + 1):
        claim = worker.claim_next_delivery_package_job(worker_id=f"package-worker-{attempt}", now=now)
        assert claim is not None
        worker.fail_delivery_package_job(claim, RuntimeError(f"failure-{attempt}"), now=now)

    job = local_simulation._team_states[team_id]["delivery_package_jobs"][0]
    assert job["status"] == "failed"
    assert job["attempt_count"] == worker.MAX_DELIVERY_PACKAGE_ATTEMPTS
    assert job["lease_owner"] is None
    assert worker.claim_next_delivery_package_job(worker_id="package-worker-final", now=now) is None


def test_json_delivery_package_expired_exhausted_lease_is_persistently_terminalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import barcode_maintenance_worker as worker

    team_id = install_json_queue(monkeypatch, [])
    now = datetime(2026, 7, 23, 2, 10, tzinfo=UTC)
    local_simulation._team_states[team_id]["delivery_package_jobs"] = [
        {
            "id": "expired-exhausted-package",
            "team_id": team_id,
            "scope_payload": {"task_id": 17, "terminal": "", "review_scope": "reviewed"},
            "evidence_fingerprint": "c" * 64,
            "status": "processing",
            "attempt_count": worker.MAX_DELIVERY_PACKAGE_ATTEMPTS,
            "lease_owner": "stopped-worker",
            "lease_token": "stopped-token",
            "lease_expires_at": (now - timedelta(seconds=1)).isoformat(),
            "updated_at": "2026-07-23T02:00:00+00:00",
        }
    ]

    claim = worker.claim_next_delivery_package_job(worker_id="replacement-worker", now=now)

    assert claim is None
    job = local_simulation._team_states[team_id]["delivery_package_jobs"][0]
    assert job["status"] == "failed"
    assert job["lease_owner"] is None
    assert job["lease_token"] is None
    assert job["lease_expires_at"] is None
    assert "maximum attempts" in job["last_error"]


def test_postgres_auto_archive_block_records_transactional_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models import AuditLog, GroupStatus
    from app.services import barcode_maintenance_worker as worker
    from app.services import state_repository

    group = SimpleNamespace(
        id=uuid4(),
        legacy_id="postgres-blocked-archive",
        status=GroupStatus.UNREVIEWED,
        raw_data={},
    )
    verification = SimpleNamespace(
        status="partial",
        evidence_fingerprint="fingerprint",
        evidence_version=1,
        meter_matched=False,
        module_matched=False,
        collector_matched=False,
        recognition_source="machine_barcode",
        auto_archive_status="pending",
        auto_archive_lease_owner=None,
        auto_archive_lease_token=None,
        auto_archive_lease_expires_at=None,
        auto_archive_error=None,
    )
    staged: list[object] = []

    class Rows:
        def all(self):
            return []

    class Session:
        committed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, _statement):
            return verification

        def scalars(self, _statement):
            return Rows()

        def add(self, value):
            staged.append(value)

        def commit(self):
            self.committed = True

    session = Session()

    class Repository:
        def _session(self):
            return session

        def _group_by_legacy_id(self, checked_session, group_id, lock=False):
            assert checked_session is session
            assert group_id == group.legacy_id
            assert lock is True
            return group

    monkeypatch.setattr(state_repository, "PostgresStateRepository", Repository)
    monkeypatch.setattr(
        state_repository,
        "_verification_group_payload",
        lambda *_args, **_kwargs: {"id": group.legacy_id, "photos": [], "status": "unreviewed"},
    )

    result = worker._auto_archive_postgres(
        group.legacy_id,
        actor="barcode-maintenance",
        team_id="postgres-audit-team",
    )

    assert result["reason"] == "verification_not_passed"
    audits = [value for value in staged if isinstance(value, AuditLog)]
    assert len(audits) == 1
    assert audits[0].action == "group_barcode_auto_archive_blocked"
    assert audits[0].entity_id == group.id
    assert audits[0].payload == {"group_id": group.legacy_id, "reason": "verification_not_passed"}
    assert session.committed is True


@pytest.mark.parametrize("status", ["partial", "unreadable", "mismatch", "failed"])
def test_auto_archive_rejects_nonpassing_verification_states(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    from app.services.barcode_maintenance_worker import auto_archive_verified_group

    group = eligible_group(f"blocked-{status}", verification_status=status)
    install_json_queue(monkeypatch, [group])

    result = auto_archive_verified_group(group["id"], actor="barcode-maintenance")

    assert result == {"archived": False, "group_id": group["id"], "reason": "verification_not_passed"}
    assert group["status"] == "unreviewed"


def test_auto_archive_rejects_ocr_only_and_incomplete_categories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.barcode_maintenance_worker import auto_archive_verified_group

    ocr_group = eligible_group("ocr-only", verification_status="passed")
    ocr_group["barcode_verification"]["recognition_source"] = "ocr_candidate"
    incomplete = eligible_group("incomplete-categories", verification_status="passed")
    incomplete["photos"][3]["category"] = "unclassified"
    install_json_queue(monkeypatch, [ocr_group, incomplete])

    assert auto_archive_verified_group("ocr-only", actor="barcode-maintenance")["reason"] == "ocr_only"
    assert auto_archive_verified_group("incomplete-categories", actor="barcode-maintenance")["reason"] == "incomplete_categories"


@pytest.mark.parametrize(
    ("verification_status", "recognition_source", "expected_source"),
    [
        ("passed", "machine_barcode", "machine_barcode"),
        ("passed", "machine_qr", "machine_qr"),
        ("manual_confirmed", "manual_confirmed", "manual_confirmed"),
    ],
)
def test_auto_archive_is_transactional_idempotent_without_delivery_enqueue(
    monkeypatch: pytest.MonkeyPatch,
    verification_status: str,
    recognition_source: str,
    expected_source: str,
) -> None:
    from app.services.barcode_maintenance_worker import auto_archive_verified_group

    group = eligible_group(f"archive-{expected_source}", verification_status=verification_status)
    group["barcode_verification"]["recognition_source"] = recognition_source
    team_id = install_json_queue(monkeypatch, [group])

    first = auto_archive_verified_group(group["id"], actor="barcode-maintenance")
    second = auto_archive_verified_group(group["id"], actor="barcode-maintenance")

    state = local_simulation._team_states[team_id]
    committed_group = state["groups"][0]
    archive_audits = [event for event in state["audit_events"] if event["action"] == "group_barcode_auto_archived"]
    assert first["archived"] is True
    assert first["source"] == expected_source
    assert second == {"archived": False, "group_id": group["id"], "reason": "already_archived"}
    assert committed_group["status"] == "approved"
    assert all(photo["archive_status"] == "archived" for photo in committed_group["photos"])
    assert len(archive_audits) == 1
    assert archive_audits[0]["payload"]["source"] == expected_source
    assert state["delivery_cache_jobs"] == []


def test_delivery_cache_reuses_sha_across_groups_and_retries_after_failure(tmp_path: Path) -> None:
    from app.services.delivery_cache import cache_group_photos

    shared_content = b"same-original"
    shared_sha = hashlib.sha256(shared_content).hexdigest()
    group_a = eligible_group("cache-a")
    group_b = eligible_group("cache-b")
    group_a["status"] = "approved"
    group_b["status"] = "approved"
    group_a["photos"] = [group_a["photos"][0]]
    group_b["photos"] = [group_b["photos"][0]]
    group_a["photos"][0]["sha256"] = shared_sha
    group_b["photos"][0]["sha256"] = shared_sha
    fetches: list[str] = []

    def fetch(photo: dict) -> tuple[bytes, str]:
        fetches.append(photo["id"])
        return shared_content, "image/jpeg"

    first = cache_group_photos(group_a, cache_root=tmp_path, fetch_photo=fetch)
    second = cache_group_photos(group_b, cache_root=tmp_path, fetch_photo=fetch)

    assert first["status"] == "ready"
    assert second["status"] == "ready"
    assert len(fetches) == 1
    assert group_a["photos"][0]["delivery_cache_path"] == group_b["photos"][0]["delivery_cache_path"]

    retry_group = eligible_group("cache-retry")
    retry_group["status"] = "approved"
    retry_group["photos"] = [retry_group["photos"][0]]
    retry_group["photos"][0]["sha256"] = hashlib.sha256(b"recovered").hexdigest()
    attempts = 0

    def flaky_fetch(_photo: dict) -> tuple[bytes, str]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("OSS unavailable")
        return b"recovered", "image/jpeg"

    failed = cache_group_photos(retry_group, cache_root=tmp_path, fetch_photo=flaky_fetch)
    recovered = cache_group_photos(retry_group, cache_root=tmp_path, fetch_photo=flaky_fetch)

    assert failed["status"] == "failed"
    assert failed["retryable"] is True
    assert recovered["status"] == "ready"
    assert attempts == 2


def test_delivery_cache_accepts_real_default_fetcher_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services.delivery_cache import cache_group_photos

    content = b"default-fetcher-content"
    group = eligible_group("default-fetcher")
    group["status"] = "approved"
    group["photos"] = [group["photos"][0]]
    group["photos"][0]["sha256"] = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(
        local_simulation,
        "download_delivery_photo_content",
        lambda _photo: (content, ".png", "image/png"),
    )

    result = cache_group_photos(group, cache_root=tmp_path)

    assert result["status"] == "ready"
    assert result["built"] == 1
    cached = tmp_path / group["photos"][0]["delivery_cache_path"]
    assert cached.suffix == ".png"
    assert cached.read_bytes() == content


def test_delivery_cache_uses_real_content_sha_for_legacy_url_fingerprint(tmp_path: Path) -> None:
    from app.services.delivery_cache import cache_group_photos

    content = b"legacy-url-hash-content"
    group = eligible_group("legacy-url-hash")
    group["status"] = "approved"
    group["photos"] = [group["photos"][0]]
    photo = group["photos"][0]
    legacy_sha = hashlib.sha256(photo["image_url"].encode("utf-8")).hexdigest()
    content_sha = hashlib.sha256(content).hexdigest()
    photo["sha256"] = legacy_sha

    result = cache_group_photos(
        group,
        cache_root=tmp_path,
        fetch_photo=lambda _photo: (content, ".jpg", "image/jpeg"),
    )

    assert result["status"] == "ready"
    assert photo["sha256"] == legacy_sha
    assert photo["delivery_cache_content_sha256"] == content_sha
    assert content_sha in photo["delivery_cache_path"]
    assert (tmp_path / photo["delivery_cache_path"]).read_bytes() == content


def test_delivery_cache_rejects_mismatched_genuine_content_sha(tmp_path: Path) -> None:
    from app.services.delivery_cache import cache_group_photos

    group = eligible_group("genuine-hash-mismatch")
    group["status"] = "approved"
    group["photos"] = [group["photos"][0]]
    photo = group["photos"][0]
    declared_sha = hashlib.sha256(b"declared-content").hexdigest()
    photo["sha256"] = declared_sha

    result = cache_group_photos(
        group,
        cache_root=tmp_path,
        fetch_photo=lambda _photo: (b"wrong-content", ".jpg", "image/jpeg"),
    )

    assert result["status"] == "failed"
    assert result["retryable"] is True
    assert "SHA256 mismatch" in photo["delivery_cache_error"]
    assert "delivery_cache_content_sha256" not in photo
    assert not list((tmp_path / "objects").rglob("*")) if (tmp_path / "objects").exists() else True


def test_declared_hash_stays_strict_when_it_matches_the_image_url_fingerprint(tmp_path: Path) -> None:
    from app.services.delivery_cache import cache_group_photos

    group = eligible_group("declared-url-shaped-hash")
    group["status"] = "approved"
    group["photos"] = [group["photos"][0]]
    photo = group["photos"][0]
    photo["sha256"] = hashlib.sha256(photo["image_url"].encode("utf-8")).hexdigest()
    photo["sha256_source"] = "declared"

    result = cache_group_photos(
        group,
        cache_root=tmp_path,
        fetch_photo=lambda _photo: (b"not-the-declared-content", ".jpg", "image/jpeg"),
    )

    assert result["status"] == "failed"
    assert "SHA256 mismatch" in photo["delivery_cache_error"]


def test_delivery_cache_rejects_corrupt_named_objects_and_partial_temp_files(tmp_path: Path) -> None:
    from app.services.delivery_cache import cache_group_photos

    content = b"complete-object"
    sha256 = hashlib.sha256(content).hexdigest()
    object_dir = tmp_path / "objects" / sha256[:2]
    object_dir.mkdir(parents=True)
    corrupt = object_dir / f"{sha256}.png"
    corrupt.write_bytes(b"wrong-content")
    partial = object_dir / f"{sha256}.jpg.tmp-interrupted"
    partial.write_bytes(content[:4])
    group = eligible_group("corrupt-cache")
    group["status"] = "approved"
    group["photos"] = [group["photos"][0]]
    group["photos"][0]["sha256"] = sha256
    fetches: list[str] = []

    result = cache_group_photos(
        group,
        cache_root=tmp_path,
        fetch_photo=lambda photo: fetches.append(photo["id"]) or (content, ".jpg", "image/jpeg"),
    )

    cached = tmp_path / group["photos"][0]["delivery_cache_path"]
    assert result["status"] == "ready"
    assert fetches == [group["photos"][0]["id"]]
    assert cached.read_bytes() == content
    assert hashlib.sha256(cached.read_bytes()).hexdigest() == sha256
    assert not corrupt.exists()
    assert not partial.exists()


def test_worker_gates_reconciliation_before_pause_or_load_can_do_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import barcode_maintenance_worker as worker

    install_json_queue(monkeypatch, [])
    monkeypatch.setattr(worker.settings, "state_backend", "json")
    reconciliations: list[int] = []
    monkeypatch.setattr(
        worker,
        "reconcile_delivery_cache_jobs",
        lambda *, limit: reconciliations.append(limit) or {"enqueued": 0},
    )
    monkeypatch.setattr(
        worker,
        "_claim_next_work",
        lambda _worker_id: pytest.fail("gated worker must not claim work"),
    )

    paused = worker.run_worker_batch(
        can_claim=lambda: False,
        load_too_high=lambda: False,
        sleeper=lambda _seconds: None,
    )
    loaded = worker.run_worker_batch(
        can_claim=lambda: True,
        load_too_high=lambda: True,
        sleeper=lambda _seconds: None,
    )

    assert paused["processed"] == 0
    assert loaded["processed"] == 0
    assert reconciliations == []


@pytest.mark.parametrize(
    ("paused", "overloaded", "expected_load_checks"),
    [(True, False, 0), (False, True, 1)],
)
def test_real_json_worker_gate_is_control_only_and_constant_cost(
    monkeypatch: pytest.MonkeyPatch,
    paused: bool,
    overloaded: bool,
    expected_load_checks: int,
) -> None:
    from app.services import barcode_maintenance_worker as worker

    class ScanForbidden(list):
        def __iter__(self):
            pytest.fail("background gate must not enumerate queue state")

    team_id = install_json_queue(monkeypatch, [], paused=paused)
    state = local_simulation._team_states[team_id]
    state["groups"] = ScanForbidden([{"id": f"group-{index}"} for index in range(10_000)])
    state["delivery_cache_jobs"] = ScanForbidden([{"id": f"job-{index}"} for index in range(10_000)])
    load_checks: list[str] = []
    monkeypatch.setattr(worker.settings, "state_backend", "json")
    monkeypatch.setattr(
        worker,
        "maintenance_status",
        lambda: pytest.fail("background gate must not call the aggregate status path"),
    )
    monkeypatch.setattr(
        worker,
        "maintenance_load_too_high",
        lambda: load_checks.append("load") or overloaded,
    )
    monkeypatch.setattr(
        worker,
        "reconcile_delivery_cache_jobs",
        lambda **_kwargs: pytest.fail("gated worker must not reconcile"),
    )
    monkeypatch.setattr(
        worker,
        "_claim_next_work",
        lambda _worker_id: pytest.fail("gated worker must not claim"),
    )
    monkeypatch.setattr(
        local_simulation,
        "download_delivery_photo_content",
        lambda _photo: pytest.fail("gated worker must not access OSS"),
    )

    report = worker.run_worker_batch(sleeper=lambda _seconds: None)

    assert report["processed"] == 0
    assert len(load_checks) == expected_load_checks


def test_real_postgres_worker_gate_reads_only_control_and_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import barcode_maintenance_worker as worker

    statements: list[str] = []
    load_checks: list[str] = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, statement):
            statements.append(str(statement.compile(dialect=postgresql.dialect())))
            return SimpleNamespace(paused=False)

        def execute(self, _statement):
            pytest.fail("background gate must not execute aggregate queue queries")

    monkeypatch.setattr(worker.settings, "state_backend", "postgres")
    monkeypatch.setattr(local_simulation, "current_team_id", lambda: "team-control-only")
    monkeypatch.setattr(worker, "SessionLocal", Session)
    monkeypatch.setattr(
        worker,
        "maintenance_status",
        lambda: pytest.fail("background gate must not call the aggregate status path"),
    )
    monkeypatch.setattr(
        worker,
        "maintenance_load_too_high",
        lambda: load_checks.append("load") or True,
    )
    monkeypatch.setattr(
        worker,
        "reconcile_delivery_cache_jobs",
        lambda **_kwargs: pytest.fail("overloaded worker must not reconcile"),
    )
    monkeypatch.setattr(
        worker,
        "_claim_next_work",
        lambda _worker_id: pytest.fail("overloaded worker must not claim"),
    )

    report = worker.run_worker_batch(sleeper=lambda _seconds: None)

    assert report["processed"] == 0
    assert len(statements) == 1
    assert "FROM barcode_maintenance_controls" in statements[0]
    assert "group_barcode_verifications" not in statements[0]
    assert "delivery_cache_jobs" not in statements[0]
    assert load_checks == ["load"]


def test_postgres_delivery_cache_reconciliation_uses_bounded_group_first_bulk_lock_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    statements: list[str] = []
    control = SimpleNamespace(delivery_cache_reconcile_cursor=None)

    class Rows:
        def all(self):
            return []

        def scalars(self):
            return self

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalars(self, statement):
            statements.append(
                str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
            )
            return Rows()

        def scalar(self, statement):
            sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
            assert "FROM barcode_maintenance_controls" in sql
            return control

        def rollback(self):
            return None

    monkeypatch.setattr(delivery_cache, "SessionLocal", Session)

    report = delivery_cache._reconcile_postgres_delivery_cache_jobs("team-reconcile", limit=20)

    assert report["enqueued"] == 0
    assert len(statements) == 1
    group_sql = statements[0]
    existing_job_sql = str(
        delivery_cache.build_postgres_delivery_job_lock_statement(
            team_id="team-reconcile",
            group_ids=[uuid4()],
        ).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "JOIN delivery_cache_jobs" not in group_sql
    assert "LIMIT 20" in group_sql
    assert "FOR UPDATE OF material_groups SKIP LOCKED" in group_sql
    assert "ORDER BY delivery_cache_jobs.group_id, delivery_cache_jobs.id" in existing_job_sql
    assert "FOR UPDATE OF delivery_cache_jobs SKIP LOCKED" in existing_job_sql


def test_postgres_delivery_cache_reconciliation_uses_bounded_bulk_queries_per_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models import DeliveryCacheJob
    from app.services import delivery_cache

    groups = [
        SimpleNamespace(
            id=uuid4(),
            team_id="team-reconcile",
            status="approved",
            reviewer="reviewer-a",
            raw_data={"delivery_cache_status": "retry_pending"},
        )
        for _index in range(25)
    ]
    batches = [groups[:20], groups[20:]]
    sessions = []
    control = SimpleNamespace(delivery_cache_reconcile_cursor=None)

    class Rows:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

        def scalars(self):
            return self

    class Session:
        def __init__(self, values):
            self.values = values
            self.execute_calls = 0
            self.committed = False

        def __enter__(self):
            sessions.append(self)
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalars(self, statement):
            self.execute_calls += 1
            sql = str(statement.compile(dialect=postgresql.dialect()))
            if "FROM material_groups" in sql:
                return Rows([] if "material_groups.id <=" in sql else self.values)
            if "FROM delivery_cache_jobs" in sql:
                return Rows([])
            if "FROM photos" in sql:
                return Rows([photo for group in self.values for photo in postgres_eligible_photos(group)])
            pytest.fail(f"unexpected reconciliation statement: {sql}")

        def scalar(self, statement):
            sql = str(statement.compile(dialect=postgresql.dialect()))
            assert "FROM barcode_maintenance_controls" in sql
            return control

        def add(self, value):
            if isinstance(value, DeliveryCacheJob) and value.id is None:
                value.id = uuid4()

        def flush(self):
            return None

        def commit(self):
            self.committed = True

        def rollback(self):
            return None

    monkeypatch.setattr(delivery_cache, "SessionLocal", lambda: Session(batches.pop(0)))

    first = delivery_cache._reconcile_postgres_delivery_cache_jobs("team-reconcile", limit=20)
    second = delivery_cache._reconcile_postgres_delivery_cache_jobs("team-reconcile", limit=20)

    assert [first["enqueued"], second["enqueued"]] == [20, 5]
    assert [session.execute_calls for session in sessions] == [3, 4]
    assert all(session.committed for session in sessions)


def test_postgres_reconciliation_cannot_overwrite_interleaved_live_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    group = SimpleNamespace(
        id=uuid4(),
        team_id="team-live-lease",
        status="approved",
        reviewer="reviewer-a",
        raw_data={"delivery_cache_status": "retry_pending"},
    )
    live_lease_expires_at = datetime(2099, 1, 1, tzinfo=UTC)
    live_job = SimpleNamespace(
        id=uuid4(),
        team_id=group.team_id,
        group_id=group.id,
        status="processing",
        attempt_count=1,
        lease_owner="active-worker",
        lease_token="live-token",
        lease_expires_at=live_lease_expires_at,
        requested_by="reviewer-a",
        request_reason="review_completed",
        last_error=None,
        completed_at=None,
    )
    statements: list[str] = []
    control = SimpleNamespace(delivery_cache_reconcile_cursor=None)

    class Rows:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

        def scalars(self):
            return self

    class Session:
        def __init__(self):
            self.execute_calls = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalars(self, statement):
            self.execute_calls += 1
            statements.append(str(statement.compile(dialect=postgresql.dialect())))
            sql = statements[-1]
            if "FROM material_groups" in sql:
                return Rows([group])
            if "FROM delivery_cache_jobs" in sql:
                return Rows([live_job])
            if "FROM photos" in sql:
                return Rows(postgres_eligible_photos(group))
            return Rows([])

        def scalar(self, statement):
            sql = str(statement.compile(dialect=postgresql.dialect()))
            assert "FROM barcode_maintenance_controls" in sql
            return control

        def flush(self):
            return None

        def commit(self):
            return None

        def rollback(self):
            return None

    monkeypatch.setattr(delivery_cache, "SessionLocal", Session)

    report = delivery_cache._reconcile_postgres_delivery_cache_jobs("team-live-lease", limit=20)

    assert report["enqueued"] == 0
    assert report["skipped_live"] == 1
    assert live_job.status == "processing"
    assert live_job.lease_owner == "active-worker"
    assert live_job.lease_token == "live-token"
    assert live_job.lease_expires_at == live_lease_expires_at
    assert group.raw_data["delivery_cache_status"] == "retry_pending"
    assert len(statements) == 3


def test_postgres_expired_delivery_lease_terminalization_locks_group_before_job() -> None:
    from app.services import delivery_cache

    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    group = SimpleNamespace(
        id=uuid4(),
        team_id="team-terminalize-order",
        raw_data={"delivery_cache_status": "processing"},
    )
    expired_job = SimpleNamespace(
        id=uuid4(),
        team_id=group.team_id,
        group_id=group.id,
        status="processing",
        attempt_count=3,
        lease_owner="expired-worker",
        lease_token="expired-token",
        lease_expires_at=now - timedelta(seconds=1),
        last_error=None,
    )
    lock_order: list[str] = []

    class Rows:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

    class Session:
        def scalars(self, statement):
            sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
            if "FOR UPDATE OF material_groups" in sql:
                lock_order.append("material_groups")
                return Rows([group])
            if "FOR UPDATE OF delivery_cache_jobs" in sql or "FOR UPDATE SKIP LOCKED" in sql:
                lock_order.append("delivery_cache_jobs")
                return Rows([expired_job])
            pytest.fail(f"unexpected terminalization statement: {sql}")

        def get(self, model, identity):
            lock_order.append("material_groups")
            assert identity == group.id
            return group

    terminalized = delivery_cache._terminalize_expired_postgres_delivery_leases(
        Session(),
        team_id=group.team_id,
        now=now,
    )

    assert lock_order == ["material_groups", "delivery_cache_jobs"]
    assert terminalized == 1
    assert expired_job.status == "failed"
    assert expired_job.lease_owner is None
    assert expired_job.lease_token is None
    assert group.raw_data["delivery_cache_status"] == "manual_required"


def test_serve_restart_preserves_persisted_admin_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import barcode_maintenance_worker as worker

    install_json_queue(monkeypatch, [], paused=True)
    monkeypatch.setattr(worker.settings, "state_backend", "json")
    monkeypatch.setenv("BARCODE_MAINTENANCE_START_PAUSED", "true")
    observed_pause_states: list[bool] = []

    def stop_after_start(**_kwargs):
        observed_pause_states.append(bool(worker.maintenance_status()["paused"]))
        raise RuntimeError("stop test worker")

    monkeypatch.setattr(worker, "run_worker_batch", stop_after_start)

    with pytest.raises(RuntimeError, match="stop test worker"):
        worker.main(["--serve"])
    worker.set_maintenance_paused(False, "admin-a")
    with pytest.raises(RuntimeError, match="stop test worker"):
        worker.main(["--serve"])

    assert observed_pause_states == [True, False]


def test_runner_executes_with_flock_and_fixed_batch_limits_despite_hostile_env(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    runner = root / "scripts" / "run_photo_barcode_maintenance_slice.sh"
    app_root = tmp_path / "app"
    fake_bin = app_root / "bin"
    python_path = app_root / "venv" / "bin" / "python"
    (app_root / "current" / "v2-api").mkdir(parents=True)
    fake_bin.mkdir(parents=True)
    python_path.parent.mkdir(parents=True)
    args_file = tmp_path / "python-args.txt"
    lock_file = tmp_path / "flock-called.txt"
    paused_file = tmp_path / "start-paused.txt"
    python_path.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$BARCODE_ARGS_FILE"\n'
        'printf "%s\\n" "$BARCODE_MAINTENANCE_START_PAUSED" > "$BARCODE_PAUSED_FILE"\n',
        encoding="utf-8",
    )
    fake_flock = fake_bin / "flock"
    fake_flock.write_text(
        '#!/usr/bin/env bash\nprintf "called\\n" > "$BARCODE_FLOCK_FILE"\n'
        '[ "$1" = "-n" ] || exit 64\n'
        'shift\nshift\n'
        '[ "${1:-}" != "--" ] || { echo "flock: failed to execute --" >&2; exit 69; }\n'
        'exec "$@"\n',
        encoding="utf-8",
    )
    python_path.chmod(0o755)
    fake_flock.chmod(0o755)
    (app_root / ".env").write_text(
        'BARCODE_MAINTENANCE_BATCH_SIZE=999\n'
        'BARCODE_MAINTENANCE_BATCH_PAUSE_SECONDS=0.01\n'
        'BARCODE_MAINTENANCE_START_PAUSED=false\n'
        'PATH="$APP_ROOT/bin:$PATH"\n',
        encoding="utf-8",
    )
    bash = Path(os.environ.get("PROGRAMFILES", "")) / "Git" / "bin" / "bash.exe"
    if not bash.exists():
        bash = Path(shutil.which("bash") or "")
    assert bash.exists(), "bash is required to execute the production runner test"
    env = os.environ.copy()
    env.update(
        {
            "BARCODE_ARGS_FILE": str(args_file),
            "BARCODE_FLOCK_FILE": str(lock_file),
            "BARCODE_PAUSED_FILE": str(paused_file),
        }
    )
    app_root_argument = app_root.as_posix()
    if app_root.drive:
        app_root_argument = f"/{app_root.drive[0].lower()}{app_root_argument[2:]}"

    completed = subprocess.run(
        [str(bash), str(runner), app_root_argument, "--serve"],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert lock_file.read_text(encoding="utf-8").strip() == "called"
    assert paused_file.read_text(encoding="utf-8").strip() == "false"
    assert args[-4:] == ["--batch-size", "20", "--batch-pause-seconds", "5"]


def test_expired_json_verification_lease_stops_at_retry_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import barcode_maintenance_worker as worker

    group = eligible_group("dead-verification-worker")
    team_id = install_json_queue(monkeypatch, [group])
    monkeypatch.setattr(worker.settings, "state_backend", "json")
    now = datetime(2026, 7, 22, 6, 0, tzinfo=UTC)

    for attempt in range(worker.MAX_VERIFICATION_ATTEMPTS):
        claim = worker.claim_next_verification_job(worker_id=f"dead-{attempt}", now=now)
        assert claim is not None
        now += timedelta(seconds=worker.DEFAULT_LEASE_SECONDS + 1)

    assert worker.claim_next_verification_job(worker_id="must-not-claim", now=now) is None
    verification = local_simulation._team_states[team_id]["groups"][0]["barcode_verification"]
    assert verification["status"] == "failed"
    assert verification["attempt_count"] == worker.MAX_VERIFICATION_ATTEMPTS
    assert verification["manual_review_required"] is True
    assert verification["retryable"] is False
    assert verification["lease_owner"] is None


def test_postgres_delivery_claim_locks_control_before_job_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import barcode_maintenance_worker as worker
    from app.services.delivery_cache import DeliveryCacheClaim

    events: list[str] = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def scalar(self, statement):
            sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
            events.append(sql)
            return SimpleNamespace(paused=False)

    monkeypatch.setattr(worker.settings, "state_backend", "postgres")
    monkeypatch.setattr(local_simulation, "current_team_id", lambda: "team-lock")
    monkeypatch.setattr(worker, "SessionLocal", Session)

    def claim(_session, **_kwargs):
        assert "FOR UPDATE" in events[0]
        events.append("job-claim")
        return DeliveryCacheClaim("team-lock", str(uuid4()), "worker", "token", 1)

    monkeypatch.setattr(worker, "claim_postgres_delivery_cache_job", claim)

    result = worker.claim_next_delivery_cache_job(worker_id="worker")

    assert result is not None
    assert events[-1] == "job-claim"


def test_dual_verification_claim_refuses_before_either_backend_mutates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import barcode_maintenance_worker as worker
    from app.services.state_repository import StateBackendNotReady

    group = eligible_group("dual-claim")
    team_id = install_json_queue(monkeypatch, [group])
    before = deepcopy(local_simulation._team_states[team_id])
    monkeypatch.setattr(worker.settings, "state_backend", "dual")
    monkeypatch.setattr(
        worker,
        "_claim_postgres_verification",
        lambda **_kwargs: pytest.fail("PostgreSQL must not be touched in DualWrite"),
    )

    with pytest.raises(StateBackendNotReady, match="Dual"):
        worker.claim_next_verification_job(worker_id="dual-worker")

    assert local_simulation._team_states[team_id] == before


def test_dual_auto_archive_refuses_before_backends_or_cache_queue_mutate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import barcode_maintenance_worker as worker
    from app.services.state_repository import StateBackendNotReady

    group = eligible_group("dual-archive", verification_status="passed")
    team_id = install_json_queue(monkeypatch, [group])
    before = deepcopy(local_simulation._team_states[team_id])
    monkeypatch.setattr(worker.settings, "state_backend", "dual")
    monkeypatch.setattr(
        worker,
        "_auto_archive_postgres",
        lambda *_args, **_kwargs: pytest.fail("PostgreSQL must not be touched in DualWrite"),
    )

    with pytest.raises(StateBackendNotReady, match="Dual"):
        worker.auto_archive_verified_group(group["id"])

    assert local_simulation._team_states[team_id] == before
    assert local_simulation._team_states[team_id]["delivery_cache_jobs"] == []


def test_json_daily_enqueue_preserves_manual_confirmation_and_completed_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import barcode_maintenance_worker as worker

    group = eligible_group("manual-preserved", verification_status="manual_confirmed")
    group["archive_status"] = "archived"
    group["barcode_verification"].update(
        {
            "auto_archive_status": "completed",
            "auto_archive_attempt_count": 1,
            "auto_archive_error": None,
        }
    )
    team_id = install_json_queue(monkeypatch, [group])
    before = deepcopy(local_simulation._team_states[team_id]["groups"][0])

    report = worker._enqueue_json_verifications([], actor="daily-enqueue", team_id=team_id)

    persisted = local_simulation._team_states[team_id]["groups"][0]
    assert report["enqueued"] == 0
    assert persisted == before
    assert persisted["barcode_verification"]["status"] == "manual_confirmed"
    assert persisted["barcode_verification"]["auto_archive_status"] == "completed"
    assert persisted["archive_status"] == "archived"


def test_json_daily_enqueue_invalidates_manual_confirmation_only_after_evidence_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import barcode_maintenance_worker as worker

    group = eligible_group("manual-evidence-changed", verification_status="manual_confirmed")
    group["barcode_verification"]["auto_archive_status"] = "completed"
    group["photos"][0]["sha256"] = "f" * 64
    team_id = install_json_queue(monkeypatch, [group])

    report = worker._enqueue_json_verifications([], actor="daily-enqueue", team_id=team_id)

    verification = local_simulation._team_states[team_id]["groups"][0]["barcode_verification"]
    assert report["enqueued"] == 1
    assert verification["status"] == "pending"
    assert verification["auto_archive_status"] is None


def test_postgres_verification_enqueue_batch_is_bounded_and_bulk_preloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models import GroupBarcodeVerification
    from app.services import barcode_maintenance_worker as worker
    from app.services import state_repository

    groups = [
        SimpleNamespace(
            id=uuid4(),
            legacy_id=f"enqueue-{index:02d}",
            team_id="team-enqueue",
            terminal=f"T-{index:02d}",
            display_meter_no=f"METER-{index:02d}",
            raw_data={
                "construction_collector": f"COLLECTOR-{index:02d}",
                "construction_module_asset_no": f"MODULE-{index:02d}",
            },
        )
        for index in range(25)
    ]
    groups.sort(key=lambda item: item.id)
    photos = [photo for group in groups[:20] for photo in postgres_eligible_photos(group)]
    statements: list[str] = []
    staged: list[GroupBarcodeVerification] = []

    class Rows:
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
            sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
            statements.append(sql)
            if "FROM material_groups" in sql:
                return Rows(groups[:20])
            if "FROM photos" in sql:
                return Rows(photos)
            if "FROM group_barcode_verifications" in sql:
                return Rows([])
            pytest.fail(f"unexpected enqueue statement: {sql}")

        def scalar(self, _statement):
            pytest.fail("verification enqueue must not issue per-group scalar queries")

        def add(self, value):
            staged.append(value)

        def commit(self):
            return None

    class Repository:
        def _session(self):
            return Session()

    monkeypatch.setattr(state_repository, "PostgresStateRepository", Repository)

    report = worker._enqueue_postgres_verifications(
        [],
        actor="daily-enqueue",
        team_id="team-enqueue",
        batch_size=20,
    )

    assert report["scanned"] == 20
    assert report["enqueued"] == 20
    assert report["has_more"] is True
    assert len(staged) == 20
    assert len(statements) == 3
    assert "LIMIT 20" in statements[0]
    assert "FOR UPDATE OF material_groups SKIP LOCKED" in statements[0]
    assert "group_id IN" in statements[1]
    assert "group_id IN" in statements[2]


def test_deployment_runs_one_paused_worker_and_daily_enqueue() -> None:
    root = Path(__file__).resolve().parents[2]
    api_unit = (root / "infra" / "module-manager-v2.service").read_text(encoding="utf-8")
    worker_unit = (root / "infra" / "module-manager-v2-photo-barcode-maintenance.service").read_text(encoding="utf-8")
    enqueue_unit = (root / "infra" / "module-manager-v2-photo-barcode-maintenance-enqueue.service").read_text(encoding="utf-8")
    timer = (root / "infra" / "module-manager-v2-photo-barcode-maintenance.timer").read_text(encoding="utf-8")
    runner = (root / "scripts" / "run_photo_barcode_maintenance_slice.sh").read_text(encoding="utf-8")
    runbook = (root / "docs" / "sop" / "06-production-deploy-runbook.md").read_text(encoding="utf-8")
    rollback = (root / "docs" / "sop" / "07-rollback-and-incident-review.md").read_text(encoding="utf-8")

    for unit in (api_unit, worker_unit, enqueue_unit):
        assert "User=modulemgr" in unit
        assert "Group=modulemgr" in unit
        assert "UMask=0077" in unit
        assert "EnvironmentFile=/opt/module-manager-v2/.env" in unit
    assert "WorkingDirectory=/opt/module-manager-v2/current/v2-api" in api_unit
    assert "ExecStart=/opt/module-manager-v2/venv/bin/uvicorn" in api_unit

    assert "Type=simple" in worker_unit
    assert "BARCODE_MAINTENANCE_BATCH_SIZE=20" in worker_unit
    assert "BARCODE_MAINTENANCE_BATCH_PAUSE_SECONDS=5" in worker_unit
    assert "BARCODE_MAINTENANCE_START_PAUSED" not in worker_unit
    assert "BARCODE_MAINTENANCE_START_PAUSED" not in runner
    assert "Nice=19" in worker_unit
    assert "IOSchedulingClass=idle" in worker_unit
    assert "CPUQuota=20%" in worker_unit
    assert "MemoryMax=512M" in worker_unit
    assert "OnCalendar=*-*-* 00:00:00" in timer
    assert "Unit=module-manager-v2-photo-barcode-maintenance-enqueue.service" in timer
    assert "--enqueue" in enqueue_unit
    assert "--serve" in runner
    assert "recompute_photo_barcode_checks.py" not in runner
    assert "alembic upgrade head" in runbook
    assert "20260824_0016" in runbook
    assert "module-manager-v2-photo-barcode-maintenance-enqueue.service" in runbook
    assert "id -u modulemgr" in runbook
    assert "useradd --system" in runbook
    assert "chown -R modulemgr:modulemgr" in runbook
    deploy_block = runbook.split("## Deploy", 1)[1].split("```bash", 1)[1].split("```", 1)[0]
    assert deploy_block.lstrip().startswith("set -euo pipefail")
    pip_positions = [
        match.start()
        for match in re.finditer(r"(?m)^[^#\n]*(?:(?:-m\s+pip)|pip3?)\s+install\b", deploy_block)
    ]
    assert pip_positions
    venv_mode_index = deploy_block.index('chmod -R g-w,g+rX "$APP/venv"')
    venv_group_index = deploy_block.index('chgrp -R modulemgr "$APP/venv"')
    pip_index = max(pip_positions)
    assert pip_index < venv_mode_index < venv_group_index
    assert 'find "$APP/venv" \\( -type f -o -type d \\) -perm -g+w -print -quit' in deploy_block
    assert 'runuser -u modulemgr -- "$APP/venv/bin/python" -c "from PIL import Image"' in deploy_block
    assert 'install -m 0644 "$REL/infra/module-manager-v2.service"' in runbook
    assert "systemctl daemon-reload" in runbook
    env_index = runbook.index('. "$APP/.env"')
    migration_index = runbook.index("alembic upgrade head")
    assert env_index < migration_index
    health_index = runbook.index("production_health_check.py")
    resume_index = runbook.index('set_maintenance_paused(False, "production-deploy")')
    assert health_index < resume_index
    assert "systemctl is-active module-manager-v2-photo-barcode-maintenance.service" in runbook
    assert "systemctl is-active module-manager-v2-photo-barcode-maintenance.timer" in runbook
    stop_worker_index = runbook.index("systemctl stop module-manager-v2-photo-barcode-maintenance.service")
    stop_timer_index = runbook.index("systemctl stop module-manager-v2-photo-barcode-maintenance.timer")
    switch_index = runbook.index('ln -sfn "$REL" "$APP/current"')
    assert stop_worker_index < switch_index
    assert stop_timer_index < switch_index

    rollback_stop_worker = rollback.index("systemctl stop module-manager-v2-photo-barcode-maintenance.service")
    rollback_stop_timer = rollback.index("systemctl stop module-manager-v2-photo-barcode-maintenance.timer")
    rollback_switch = rollback.index('ln -sfn "$PREVIOUS" "$APP/current"')
    rollback_health = rollback.index("curl -fsS http://127.0.0.1/health")
    assert rollback_stop_worker < rollback_switch
    assert rollback_stop_timer < rollback_switch
    assert rollback_switch < rollback_health
