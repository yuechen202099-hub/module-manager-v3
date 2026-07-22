from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.services import local_simulation
from app.services.group_barcode_verification import evaluate_group_eligibility


REQUIRED_CATEGORIES = ("before_box", "collector_barcode", "module_meter", "after_box")


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
    load_checks = iter([False, True])
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
def test_auto_archive_is_transactional_idempotent_and_enqueues_cache(
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
    assert len(state["delivery_cache_jobs"]) == 1
    assert state["delivery_cache_jobs"][0]["status"] == "pending"


def test_delivery_cache_reuses_sha_across_groups_and_retries_after_failure(tmp_path: Path) -> None:
    from app.services.delivery_cache import cache_group_photos

    shared_sha = "a" * 64
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
        return b"same-original", "image/jpeg"

    first = cache_group_photos(group_a, cache_root=tmp_path, fetch_photo=fetch)
    second = cache_group_photos(group_b, cache_root=tmp_path, fetch_photo=fetch)

    assert first["status"] == "ready"
    assert second["status"] == "ready"
    assert len(fetches) == 1
    assert group_a["photos"][0]["delivery_cache_path"] == group_b["photos"][0]["delivery_cache_path"]

    retry_group = eligible_group("cache-retry")
    retry_group["status"] = "approved"
    retry_group["photos"] = [retry_group["photos"][0]]
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


def test_deployment_runs_one_paused_worker_and_daily_enqueue() -> None:
    root = Path(__file__).resolve().parents[2]
    worker_unit = (root / "infra" / "module-manager-v2-photo-barcode-maintenance.service").read_text(encoding="utf-8")
    enqueue_unit = (root / "infra" / "module-manager-v2-photo-barcode-maintenance-enqueue.service").read_text(encoding="utf-8")
    timer = (root / "infra" / "module-manager-v2-photo-barcode-maintenance.timer").read_text(encoding="utf-8")
    runner = (root / "scripts" / "run_photo_barcode_maintenance_slice.sh").read_text(encoding="utf-8")

    assert "Type=simple" in worker_unit
    assert "BARCODE_MAINTENANCE_BATCH_SIZE=20" in worker_unit
    assert "BARCODE_MAINTENANCE_BATCH_PAUSE_SECONDS=5" in worker_unit
    assert "BARCODE_MAINTENANCE_START_PAUSED=true" in worker_unit
    assert "Nice=19" in worker_unit
    assert "IOSchedulingClass=idle" in worker_unit
    assert "CPUQuota=20%" in worker_unit
    assert "MemoryMax=512M" in worker_unit
    assert "OnCalendar=*-*-* 00:00:00" in timer
    assert "Unit=module-manager-v2-photo-barcode-maintenance-enqueue.service" in timer
    assert "--enqueue" in enqueue_unit
    assert "--serve" in runner
    assert "recompute_photo_barcode_checks.py" not in runner
