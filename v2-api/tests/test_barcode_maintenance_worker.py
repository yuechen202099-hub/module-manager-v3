from __future__ import annotations

import hashlib
import os
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


@pytest.mark.parametrize("legacy_url_hash", [False, True])
def test_json_repository_delivery_cache_job_builds_readable_manifest_and_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    legacy_url_hash: bool,
) -> None:
    from app.services import barcode_maintenance_worker as worker
    from app.services.delivery_cache import enqueue_json_delivery_cache_job
    from app.services.state_repository import JsonStateRepository

    content = b"json-durable-cache"
    group = eligible_group("json-cache-e2e")
    group.update({"status": "approved", "reviewer": "reviewer-a"})
    group["photos"] = [group["photos"][0]]
    photo = group["photos"][0]
    content_sha = hashlib.sha256(content).hexdigest()
    photo["sha256"] = (
        hashlib.sha256(photo["image_url"].encode("utf-8")).hexdigest()
        if legacy_url_hash
        else content_sha
    )
    original_sha = photo["sha256"]
    team_id = install_json_queue(monkeypatch, [group])
    monkeypatch.setattr(worker.settings, "state_backend", "json")
    monkeypatch.setattr(local_simulation.settings, "delivery_cache_path", str(tmp_path))
    monkeypatch.setattr(
        local_simulation,
        "download_delivery_photo_content",
        lambda _photo: (content, ".jpg", "image/jpeg"),
    )
    enqueue_json_delivery_cache_job(group["id"], team_id=team_id, actor="reviewer-a")

    claim = worker.claim_next_delivery_cache_job(worker_id="cache-worker")
    assert claim is not None
    worker._process_delivery_job(claim)

    repository = JsonStateRepository()
    manifest = repository.build_final_delivery_manifest(terminal=group["terminal"])
    manifest_photo = manifest["groups"][0]["photos"][0]
    cached_path = repository.get_delivery_cached_photo_path(group["id"], group["photos"][0]["id"])
    assert manifest_photo["delivery_cache_url"].startswith("/local-test/delivery-cache/")
    assert manifest_photo["sha256"] == original_sha
    assert manifest_photo["delivery_cache_content_sha256"] == content_sha
    assert cached_path.read_bytes() == content


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


@pytest.mark.parametrize("gap", ["review", "auto_archive"])
def test_json_delivery_cache_reconciliation_recovers_post_commit_enqueue_gap(
    monkeypatch: pytest.MonkeyPatch,
    gap: str,
) -> None:
    from app.services import barcode_maintenance_worker as worker
    from app.services import delivery_cache
    from app.services.state_repository import JsonStateRepository

    group = eligible_group(f"reconcile-{gap}", verification_status="passed")
    team_id = install_json_queue(monkeypatch, [group])
    monkeypatch.setattr(worker.settings, "state_backend", "json")
    original_enqueue = delivery_cache.enqueue_json_delivery_cache_job
    monkeypatch.setattr(
        delivery_cache,
        "enqueue_json_delivery_cache_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("enqueue unavailable")),
    )

    if gap == "review":
        monkeypatch.setattr(local_simulation, "ensure_task_claimed_by", lambda *_args, **_kwargs: None)
        JsonStateRepository().review_group(group["id"], "approved", "reviewer-a")
    else:
        worker.auto_archive_verified_group(group["id"])

    committed = local_simulation._team_states[team_id]
    assert committed["groups"][0]["status"] == "approved"
    assert committed["groups"][0]["delivery_cache_status"] == "retry_pending"
    assert committed["delivery_cache_jobs"] == []

    monkeypatch.setattr(delivery_cache, "enqueue_json_delivery_cache_job", original_enqueue)
    report = delivery_cache.reconcile_delivery_cache_jobs()

    assert report["enqueued"] == 1
    reconciled = local_simulation._team_states[team_id]
    assert reconciled["delivery_cache_jobs"][0]["status"] == "pending"


def test_worker_and_daily_enqueue_paths_run_delivery_cache_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import barcode_maintenance_worker as worker

    install_json_queue(monkeypatch, [])
    monkeypatch.setattr(worker.settings, "state_backend", "json")
    reconciliations: list[str] = []
    monkeypatch.setattr(
        worker,
        "reconcile_delivery_cache_jobs",
        lambda *, limit=20: reconciliations.append(f"reconcile:{limit}") or {"enqueued": 0},
    )
    monkeypatch.setattr(worker, "_claim_next_work", lambda _worker_id: None)
    monkeypatch.setattr(worker, "_maintenance_can_claim", lambda: True)
    monkeypatch.setattr(worker, "maintenance_load_too_high", lambda: False)

    worker.run_worker_batch(sleeper=lambda _seconds: None)
    worker.enqueue_verification_jobs([])

    assert reconciliations == ["reconcile:20", "reconcile:20"]


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


def test_json_delivery_cache_reconciliation_is_bounded_and_eventually_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    groups = [eligible_group(f"reconcile-bounded-{index}") for index in range(25)]
    for group in groups:
        group.update({"status": "approved", "reviewer": "reviewer-a"})
    team_id = install_json_queue(monkeypatch, groups)
    monkeypatch.setattr(delivery_cache.settings, "state_backend", "json")

    first = delivery_cache.reconcile_delivery_cache_jobs(limit=20)
    assert first["enqueued"] == 20
    assert first["scanned"] <= 20
    assert len(local_simulation._team_states[team_id]["delivery_cache_jobs"]) == 20

    second = delivery_cache.reconcile_delivery_cache_jobs(limit=20)
    assert second["enqueued"] == 5
    assert second["scanned"] <= 20
    assert len(local_simulation._team_states[team_id]["delivery_cache_jobs"]) == 25


def test_postgres_delivery_cache_reconciliation_uses_bounded_group_first_bulk_lock_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    statements: list[str] = []

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

        def execute(self, statement):
            statements.append(
                str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
            )
            return Rows()

        def scalar(self, _statement):
            pytest.fail("reconciliation must not issue per-group queries")

        def rollback(self):
            return None

    monkeypatch.setattr(delivery_cache, "SessionLocal", Session)

    report = delivery_cache._reconcile_postgres_delivery_cache_jobs("team-reconcile", limit=20)

    assert report["enqueued"] == 0
    assert len(statements) == 2
    existing_group_sql, missing_sql = statements
    existing_job_sql = str(
        delivery_cache.build_postgres_delivery_job_lock_statement(
            team_id="team-reconcile",
            group_ids=[uuid4()],
        ).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "LEFT OUTER JOIN" not in existing_group_sql
    assert "JOIN delivery_cache_jobs" in existing_group_sql
    assert "LIMIT 20" in existing_group_sql
    assert "FOR UPDATE OF material_groups SKIP LOCKED" in existing_group_sql
    assert "delivery_cache_jobs.lease_expires_at <" in existing_group_sql
    assert "delivery_cache_jobs.attempt_count < 3" in existing_group_sql
    assert "ORDER BY delivery_cache_jobs.group_id, delivery_cache_jobs.id" in existing_job_sql
    assert "FOR UPDATE OF delivery_cache_jobs SKIP LOCKED" in existing_job_sql
    assert "NOT (EXISTS" in missing_sql
    assert "LIMIT 20" in missing_sql
    assert "FOR UPDATE OF material_groups SKIP LOCKED" in missing_sql


def test_postgres_delivery_cache_reconciliation_uses_two_queries_per_bounded_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models import DeliveryCacheJob
    from app.services import delivery_cache

    groups = [
        SimpleNamespace(
            id=uuid4(),
            team_id="team-reconcile",
            reviewer="reviewer-a",
            raw_data={"delivery_cache_status": "retry_pending"},
        )
        for _index in range(25)
    ]
    batches = [groups[:20], groups[20:]]
    sessions = []

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

        def execute(self, _statement):
            self.execute_calls += 1
            if self.execute_calls == 1:
                return Rows([])
            return Rows([(group, None) for group in self.values])

        def scalar(self, _statement):
            pytest.fail("reconciliation must not issue an N+1 job query")

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
    assert [session.execute_calls for session in sessions] == [2, 2]
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

        def execute(self, statement):
            self.execute_calls += 1
            statements.append(str(statement.compile(dialect=postgresql.dialect())))
            if self.execute_calls == 1:
                return Rows([group])
            if self.execute_calls == 2:
                return Rows([live_job])
            return Rows([])

        def scalar(self, _statement):
            pytest.fail("reconciliation must not issue per-group queries")

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


def test_postgres_reconciliation_recovers_expired_processing_lease_below_retry_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import delivery_cache

    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    group = SimpleNamespace(
        id=uuid4(),
        team_id="team-expired-lease",
        status="approved",
        reviewer="reviewer-a",
        raw_data={"delivery_cache_status": "retry_pending"},
    )
    expired_job = SimpleNamespace(
        id=uuid4(),
        team_id=group.team_id,
        group_id=group.id,
        status="processing",
        attempt_count=1,
        lease_owner="dead-worker",
        lease_token="expired-token",
        lease_expires_at=now - timedelta(seconds=1),
        requested_by="reviewer-a",
        request_reason="review_completed",
        last_error="",
        completed_at=None,
    )

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

        def execute(self, _statement):
            self.execute_calls += 1
            if self.execute_calls == 1:
                return Rows([group])
            if self.execute_calls == 2:
                return Rows([expired_job])
            return Rows([])

        def scalar(self, _statement):
            pytest.fail("reconciliation must not issue per-group queries")

        def flush(self):
            return None

        def commit(self):
            return None

        def rollback(self):
            return None

    monkeypatch.setattr(delivery_cache, "SessionLocal", Session)

    report = delivery_cache._reconcile_postgres_delivery_cache_jobs(
        "team-expired-lease",
        limit=20,
        now=now,
    )

    assert report["enqueued"] == 1
    assert report["skipped_live"] == 0
    assert expired_job.status == "pending"
    assert expired_job.lease_owner is None
    assert expired_job.lease_token is None
    assert expired_job.lease_expires_at is None
    assert expired_job.attempt_count == 1
    assert group.raw_data["delivery_cache_status"] == "pending"


def test_postgres_reconciliation_and_expired_worker_completion_lock_group_before_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models import GroupStatus
    from app.services import barcode_maintenance_worker as worker
    from app.services import delivery_cache, state_repository

    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    group = SimpleNamespace(
        id=uuid4(),
        team_id="team-lock-order",
        status=GroupStatus.APPROVED,
        reviewer="reviewer-a",
        raw_data={"delivery_cache_status": "retry_pending"},
    )
    expired_job = SimpleNamespace(
        id=uuid4(),
        team_id=group.team_id,
        group_id=group.id,
        status="processing",
        attempt_count=1,
        lease_owner="expired-worker",
        lease_token="expired-token",
        lease_expires_at=now - timedelta(seconds=1),
        requested_by="reviewer-a",
        request_reason="review_completed",
        last_error="",
        completed_at=None,
    )
    reconciliation_locks: list[str] = []
    completion_locks: list[str] = []

    class Rows:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

        def scalars(self):
            return self

    class ReconciliationSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, statement):
            sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
            if "FOR UPDATE OF material_groups" in sql:
                reconciliation_locks.append("material_groups")
                return Rows([] if "NOT (EXISTS" in sql else [group])
            if "FOR UPDATE OF delivery_cache_jobs" in sql:
                reconciliation_locks.append("delivery_cache_jobs")
                return Rows([(group, expired_job)] if "JOIN material_groups" in sql else [expired_job])
            pytest.fail(f"unexpected reconciliation statement: {sql}")

        def scalar(self, _statement):
            pytest.fail("reconciliation must not issue per-group queries")

        def flush(self):
            return None

        def commit(self):
            return None

        def rollback(self):
            return None

    class SnapshotSession:
        def scalar(self, _statement):
            return group

    class CompletionSession:
        def scalar(self, statement):
            sql = str(statement.compile(dialect=postgresql.dialect()))
            if "FROM material_groups" in sql:
                completion_locks.append("material_groups")
                return group
            if "FROM delivery_cache_jobs" in sql:
                completion_locks.append("delivery_cache_jobs")
                return expired_job
            pytest.fail(f"unexpected completion statement: {sql}")

        def rollback(self):
            return None

    class SessionContext:
        def __init__(self, session):
            self.session = session

        def __enter__(self):
            return self.session

        def __exit__(self, exc_type, exc, tb):
            return False

    class Repository:
        def __init__(self):
            self.sessions = deque([SnapshotSession(), CompletionSession()])

        def _session(self):
            return SessionContext(self.sessions.popleft())

    monkeypatch.setattr(delivery_cache, "SessionLocal", ReconciliationSession)
    monkeypatch.setattr(worker.settings, "state_backend", "postgres")
    monkeypatch.setattr(state_repository, "PostgresStateRepository", Repository)
    monkeypatch.setattr(
        state_repository,
        "_group_payload",
        lambda _session, _group, *, include_photos: {"id": str(group.id), "photos": []},
    )
    monkeypatch.setattr(
        worker,
        "cache_group_photos",
        lambda _snapshot: {"status": "ready", "retryable": False},
    )

    report = delivery_cache._reconcile_postgres_delivery_cache_jobs(
        group.team_id,
        limit=20,
        now=now,
    )
    worker._process_delivery_job(
        worker.MaintenanceJob(
            kind="delivery_cache",
            team_id=group.team_id,
            group_id=str(group.id),
            lease_owner="expired-worker",
            lease_token="expired-token",
        )
    )

    assert reconciliation_locks[:2] == ["material_groups", "delivery_cache_jobs"]
    assert completion_locks == ["material_groups", "delivery_cache_jobs"]
    assert report["enqueued"] == 1
    assert expired_job.status == "pending"
    assert expired_job.lease_owner is None
    assert expired_job.lease_token is None
    assert group.raw_data["delivery_cache_status"] == "pending"


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
        'while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do shift; done\n'
        'shift\nexec "$@"\n',
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


def test_expired_json_delivery_cache_lease_stops_at_retry_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import barcode_maintenance_worker as worker
    from app.services.delivery_cache import enqueue_json_delivery_cache_job

    group = eligible_group("dead-cache-worker")
    group["status"] = "approved"
    team_id = install_json_queue(monkeypatch, [group])
    monkeypatch.setattr(worker.settings, "state_backend", "json")
    enqueue_json_delivery_cache_job(group["id"], team_id=team_id)
    now = datetime(2026, 7, 22, 7, 0, tzinfo=UTC)

    for attempt in range(worker.MAX_DELIVERY_CACHE_ATTEMPTS):
        claim = worker.claim_next_delivery_cache_job(worker_id=f"dead-{attempt}", now=now)
        assert claim is not None
        now += timedelta(seconds=worker.DEFAULT_LEASE_SECONDS + 1)

    assert worker.claim_next_delivery_cache_job(worker_id="must-not-claim", now=now) is None
    state = local_simulation._team_states[team_id]
    durable_job = state["delivery_cache_jobs"][0]
    assert durable_job["status"] == "failed"
    assert durable_job["attempt_count"] == worker.MAX_DELIVERY_CACHE_ATTEMPTS
    assert durable_job["retryable"] is False
    assert durable_job["manual_review_required"] is True
    assert durable_job["lease_owner"] is None
    assert state["groups"][0]["delivery_cache_status"] == "manual_required"


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


def test_deployment_runs_one_paused_worker_and_daily_enqueue() -> None:
    root = Path(__file__).resolve().parents[2]
    worker_unit = (root / "infra" / "module-manager-v2-photo-barcode-maintenance.service").read_text(encoding="utf-8")
    enqueue_unit = (root / "infra" / "module-manager-v2-photo-barcode-maintenance-enqueue.service").read_text(encoding="utf-8")
    timer = (root / "infra" / "module-manager-v2-photo-barcode-maintenance.timer").read_text(encoding="utf-8")
    runner = (root / "scripts" / "run_photo_barcode_maintenance_slice.sh").read_text(encoding="utf-8")

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
