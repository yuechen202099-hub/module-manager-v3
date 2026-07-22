from __future__ import annotations

import argparse
import os
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select

from app.core.config import settings
from app.database import SessionLocal
from app.models import (
    BarcodeMaintenanceControl,
    DeliveryCacheJob,
    GroupBarcodeVerification,
    GroupStatus,
    MaterialGroup,
    Photo,
)
from app.services import local_simulation
from app.services.delivery_cache import (
    MAX_DELIVERY_CACHE_ATTEMPTS,
    cache_group_photos,
    claim_postgres_delivery_cache_job,
)
from app.services.group_barcode_verification import (
    evaluate_group_eligibility,
    invalidate_group_verification,
    scan_group_evidence,
)


MAX_VERIFICATION_ATTEMPTS = 3
DEFAULT_BATCH_SIZE = 20
DEFAULT_BATCH_PAUSE_SECONDS = 5
DEFAULT_LEASE_SECONDS = 300
DEFAULT_MAX_LOAD_RATIO = 0.75
WORKER_ACTOR = "barcode-maintenance"
_batch_lock = threading.Lock()
_claim_kind_lock = threading.Lock()
_next_claim_kind = "verification"


@dataclass(frozen=True)
class MaintenanceJob:
    kind: str
    team_id: str
    group_id: str
    lease_owner: str = ""
    lease_token: str = ""
    evidence_fingerprint: str = ""
    evidence_version: int = 0
    attempt_count: int = 0


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _backend() -> str:
    backend = settings.state_backend.lower().strip()
    if backend not in {"json", "postgres", "dual"}:
        from app.services.state_repository import StateBackendNotReady

        raise StateBackendNotReady(f"Unsupported STATE_BACKEND value: {settings.state_backend}")
    return backend


def build_postgres_verification_claim_statement(*, team_id: str, now: datetime):
    return (
        select(GroupBarcodeVerification)
        .where(
            GroupBarcodeVerification.team_id == team_id,
            or_(
                GroupBarcodeVerification.status == "pending",
                (GroupBarcodeVerification.status == "failed")
                & (GroupBarcodeVerification.attempt_count < MAX_VERIFICATION_ATTEMPTS)
                & (GroupBarcodeVerification.auto_archive_status == "retry_pending"),
                (GroupBarcodeVerification.status == "processing")
                & (GroupBarcodeVerification.lease_expires_at < now),
            ),
        )
        .order_by(GroupBarcodeVerification.updated_at, GroupBarcodeVerification.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def _claim_json_verification_in_state(
    state: dict[str, Any],
    *,
    worker_id: str,
    now: datetime,
    lease_seconds: int,
) -> MaintenanceJob | None:
    control = state.get("barcode_maintenance_control")
    if not isinstance(control, dict) or bool(control.get("paused", True)):
        return None
    candidates: list[tuple[str, dict[str, Any]]] = []
    for group in state.get("groups", []):
        verification = group.get("barcode_verification")
        if not isinstance(verification, dict):
            continue
        status = str(verification.get("status") or "")
        attempts = int(verification.get("attempt_count") or 0)
        expired = (_parse_datetime(verification.get("lease_expires_at")) or datetime.max.replace(tzinfo=UTC)) < now
        retryable_failed = status == "failed" and bool(verification.get("retryable")) and attempts < MAX_VERIFICATION_ATTEMPTS
        if status == "pending" or retryable_failed or (status == "processing" and expired):
            candidates.append((str(group.get("id") or ""), verification))
    if not candidates:
        return None
    group_id, verification = sorted(candidates, key=lambda item: item[0])[0]
    token = str(uuid4())
    verification.update(
        {
            "status": "processing",
            "attempt_count": int(verification.get("attempt_count") or 0) + 1,
            "lease_owner": worker_id,
            "lease_token": token,
            "lease_expires_at": (now + timedelta(seconds=max(1, int(lease_seconds)))).isoformat(),
            "retryable": False,
            "manual_review_required": False,
        }
    )
    return MaintenanceJob(
        kind="verification",
        team_id=str(state.get("team_id") or local_simulation.current_team_id()),
        group_id=group_id,
        lease_owner=worker_id,
        lease_token=token,
        evidence_fingerprint=str(verification.get("evidence_fingerprint") or ""),
        evidence_version=int(verification.get("evidence_version") or 0),
        attempt_count=int(verification.get("attempt_count") or 0),
    )


def _claim_json_verification(
    *,
    worker_id: str,
    team_id: str,
    now: datetime,
    lease_seconds: int,
) -> MaintenanceJob | None:
    transaction = local_simulation.begin_authoritative_json_write(team_id)
    token = local_simulation.activate_authoritative_json_write(transaction)
    try:
        claim = _claim_json_verification_in_state(
            transaction.working_state,
            worker_id=worker_id,
            now=now,
            lease_seconds=lease_seconds,
        )
        if claim is None:
            local_simulation.abort_authoritative_json_write(transaction, token)
            return None
        local_simulation.finish_authoritative_json_write(transaction, token)
        return claim
    except BaseException:
        if not transaction.closed:
            local_simulation.abort_authoritative_json_write(transaction, token)
        raise


def _claim_postgres_verification(
    *,
    worker_id: str,
    team_id: str,
    now: datetime,
    lease_seconds: int,
) -> MaintenanceJob | None:
    with SessionLocal() as session:
        control = session.scalar(
            select(BarcodeMaintenanceControl)
            .where(BarcodeMaintenanceControl.team_id == team_id)
            .with_for_update()
        )
        if control is None or control.paused:
            session.rollback()
            return None
        verification = session.scalar(build_postgres_verification_claim_statement(team_id=team_id, now=now))
        if verification is None:
            session.rollback()
            return None
        token = str(uuid4())
        verification.status = "processing"
        verification.attempt_count = int(verification.attempt_count or 0) + 1
        verification.lease_owner = worker_id
        verification.lease_token = token
        verification.lease_expires_at = now + timedelta(seconds=max(1, int(lease_seconds)))
        verification.auto_archive_status = None
        session.commit()
        return MaintenanceJob(
            kind="verification",
            team_id=team_id,
            group_id=str(verification.group_id),
            lease_owner=worker_id,
            lease_token=token,
            evidence_fingerprint=str(verification.evidence_fingerprint or ""),
            evidence_version=int(verification.evidence_version or 0),
            attempt_count=int(verification.attempt_count or 0),
        )


def claim_next_verification_job(
    *,
    worker_id: str,
    now: datetime | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> MaintenanceJob | None:
    claimed_at = now or datetime.now(UTC)
    team_id = local_simulation.current_team_id()
    backend = _backend()
    if backend == "json":
        return _claim_json_verification(
            worker_id=worker_id,
            team_id=team_id,
            now=claimed_at,
            lease_seconds=lease_seconds,
        )
    if backend == "postgres":
        return _claim_postgres_verification(
            worker_id=worker_id,
            team_id=team_id,
            now=claimed_at,
            lease_seconds=lease_seconds,
        )
    transaction = local_simulation.begin_authoritative_json_write(team_id)
    token = local_simulation.activate_authoritative_json_write(transaction)
    try:
        json_claim = _claim_json_verification_in_state(
            transaction.working_state,
            worker_id=worker_id,
            now=claimed_at,
            lease_seconds=lease_seconds,
        )
        postgres_claim = _claim_postgres_verification(
            worker_id=worker_id,
            team_id=team_id,
            now=claimed_at,
            lease_seconds=lease_seconds,
        )
        if (json_claim is None) != (postgres_claim is None) or (
            json_claim is not None
            and postgres_claim is not None
            and json_claim.group_id != postgres_claim.group_id
        ):
            from app.services.state_repository import StateBackendNotReady

            raise StateBackendNotReady("Dual barcode worker claim diverged; JSON claim was aborted")
        if json_claim is None:
            local_simulation.abort_authoritative_json_write(transaction, token)
            return None
        local_simulation.finish_authoritative_json_write(transaction, token)
        return json_claim
    except BaseException:
        if not transaction.closed:
            local_simulation.abort_authoritative_json_write(transaction, token)
        raise


def _fail_json_verification(job: MaintenanceJob, error: Exception, now: datetime) -> None:
    transaction = local_simulation.begin_authoritative_json_write(job.team_id)
    token = local_simulation.activate_authoritative_json_write(transaction)
    try:
        group = next(
            (item for item in transaction.working_state.get("groups", []) if str(item.get("id") or "") == job.group_id),
            None,
        )
        if group is None:
            raise KeyError(job.group_id)
        verification = group.get("barcode_verification") or {}
        if verification.get("lease_owner") != job.lease_owner or verification.get("lease_token") != job.lease_token:
            local_simulation.abort_authoritative_json_write(transaction, token)
            return
        retryable = int(verification.get("attempt_count") or 0) < MAX_VERIFICATION_ATTEMPTS
        verification.update(
            {
                "status": "failed",
                "lease_owner": None,
                "lease_token": None,
                "lease_expires_at": None,
                "retryable": retryable,
                "manual_review_required": not retryable,
                "last_error": str(error)[:500],
                "failed_at": now.isoformat(),
            }
        )
        local_simulation.append_audit_event(
            "group_barcode_worker_failed",
            WORKER_ACTOR,
            {
                "group_id": job.group_id,
                "attempt_count": verification.get("attempt_count"),
                "retryable": retryable,
            },
        )
        local_simulation.finish_authoritative_json_write(transaction, token)
    except BaseException:
        if not transaction.closed:
            local_simulation.abort_authoritative_json_write(transaction, token)
        raise


def _fail_postgres_verification(job: MaintenanceJob, error: Exception, now: datetime) -> None:
    from app.services.state_repository import _stage_transactional_audit

    with SessionLocal() as session:
        verification = session.scalar(
            select(GroupBarcodeVerification)
            .where(
                GroupBarcodeVerification.team_id == job.team_id,
                GroupBarcodeVerification.group_id == UUID(job.group_id),
            )
            .with_for_update()
        )
        if verification is None:
            raise KeyError(job.group_id)
        if verification.lease_owner != job.lease_owner or verification.lease_token != job.lease_token:
            session.rollback()
            return
        retryable = int(verification.attempt_count or 0) < MAX_VERIFICATION_ATTEMPTS
        verification.status = "failed"
        verification.lease_owner = None
        verification.lease_token = None
        verification.lease_expires_at = None
        verification.auto_archive_status = "retry_pending" if retryable else "manual_required"
        verification.auto_archive_error = str(error)[:500]
        _stage_transactional_audit(
            session,
            team_id=job.team_id,
            actor=WORKER_ACTOR,
            action="group_barcode_worker_failed",
            entity_type="material_group",
            entity_id=verification.group_id,
            payload={
                "group_id": job.group_id,
                "attempt_count": verification.attempt_count,
                "retryable": retryable,
                "failed_at": now.isoformat(),
            },
        )
        session.commit()


def fail_verification_job(
    job: MaintenanceJob,
    error: Exception,
    *,
    now: datetime | None = None,
) -> None:
    failed_at = now or datetime.now(UTC)
    backend = _backend()
    if backend in {"json", "dual"}:
        _fail_json_verification(job, error, failed_at)
    if backend in {"postgres", "dual"}:
        _fail_postgres_verification(job, error, failed_at)


def _archive_block_reason(group: dict[str, Any], verification: dict[str, Any]) -> tuple[str, str]:
    status = str(verification.get("status") or "")
    source = str(verification.get("recognition_source") or "")
    if status not in {"passed", "manual_confirmed"}:
        return "verification_not_passed", ""
    if status == "manual_confirmed":
        source = "manual_confirmed"
    if source == "manual":
        source = "manual_confirmed"
    if source in {"ocr", "ocr_candidate", "none", ""}:
        return "ocr_only", ""
    if source == "machine":
        result = verification.get("result") or {}
        source = "machine_qr" if result.get("machine_qr_values") and not result.get("machine_barcode_values") else "machine_barcode"
    if source not in {"machine_barcode", "machine_qr", "manual_confirmed"}:
        return "unsupported_recognition_source", ""
    if not all(verification.get(field) is True for field in ("meter_matched", "module_matched", "collector_matched")):
        return "verification_not_three_of_three", ""
    result = verification.get("result") or {}
    if int(result.get("passed_count") or 0) != 3:
        return "verification_not_three_of_three", ""
    active_photos = [photo for photo in group.get("photos", []) if photo.get("is_active") is not False]
    categories = [str(photo.get("category") or "") for photo in active_photos]
    required = {"before_box", "collector_barcode", "module_meter", "after_box"}
    if len(active_photos) != 4 or len(set(categories)) != 4 or set(categories) != required:
        return "incomplete_categories", ""
    if str(group.get("status") or "") not in {"", "pending", "unreviewed", "in_review", "incomplete"}:
        return "final_review_status", ""
    if group.get("has_archive_blocker") or group.get("exception_reasons"):
        return "archive_blocked", ""
    eligibility = evaluate_group_eligibility(group)
    if eligibility.status != "pending" or eligibility.evidence_fingerprint != verification.get("evidence_fingerprint"):
        return "evidence_changed", ""
    return "", source


def _auto_archive_json_in_state(
    state: dict[str, Any],
    group_id: str,
    *,
    actor: str,
) -> dict[str, Any]:
    group = next((item for item in state.get("groups", []) if str(item.get("id") or "") == group_id), None)
    if group is None:
        raise KeyError(group_id)
    verification = group.get("barcode_verification") or {}
    if str(group.get("status") or "") == "approved" and verification.get("auto_archive_status") == "archived":
        return {"archived": False, "group_id": group_id, "reason": "already_archived"}
    reason, source = _archive_block_reason(group, verification)
    if reason:
        return {"archived": False, "group_id": group_id, "reason": reason}
    now = datetime.now(UTC).isoformat()
    for photo in group.get("photos", []):
        photo["archive_status"] = "archived"
        photo["archived_at"] = now
        photo["classified_by"] = photo.get("classified_by") or actor
    group.update(
        {
            "status": "approved",
            "reviewer": actor,
            "review_note": "barcode verification auto archive",
            "exception_note": "",
            "reviewed_at": now,
        }
    )
    verification.update(
        {
            "auto_archive_status": "archived",
            "auto_archived_at": now,
            "auto_archive_error": "",
            "recognition_source": source,
        }
    )
    local_simulation.schedule_delivery_cache_build(
        group_id,
        str(state.get("team_id") or ""),
        reason="auto_archive",
    )
    local_simulation.append_audit_event(
        "group_barcode_auto_archived",
        actor,
        {"group_id": group_id, "source": source, "evidence_version": verification.get("evidence_version")},
    )
    local_simulation.refresh_summary()
    return {"archived": True, "group_id": group_id, "source": source}


def _auto_archive_json(group_id: str, *, actor: str, team_id: str) -> dict[str, Any]:
    transaction = local_simulation.begin_authoritative_json_write(team_id)
    token = local_simulation.activate_authoritative_json_write(transaction)
    try:
        result = _auto_archive_json_in_state(transaction.working_state, group_id, actor=actor)
        local_simulation.finish_authoritative_json_write(transaction, token)
        return result
    except BaseException:
        if not transaction.closed:
            local_simulation.abort_authoritative_json_write(transaction, token)
        raise


def _postgres_group_id(group_id: str) -> UUID | None:
    try:
        return UUID(group_id)
    except ValueError:
        return None


def _auto_archive_postgres(group_id: str, *, actor: str, team_id: str) -> dict[str, Any]:
    from app.services import state_repository

    repository = state_repository.PostgresStateRepository()
    with repository._session() as session:
        group = repository._group_by_legacy_id(session, group_id, lock=True)
        verification = session.scalar(
            select(GroupBarcodeVerification)
            .where(
                GroupBarcodeVerification.team_id == team_id,
                GroupBarcodeVerification.group_id == group.id,
            )
            .with_for_update()
        )
        if verification is None:
            return {"archived": False, "group_id": group_id, "reason": "verification_not_passed"}
        if group.status == GroupStatus.APPROVED and verification.auto_archive_status == "archived":
            return {"archived": False, "group_id": group_id, "reason": "already_archived"}
        photos = list(
            session.scalars(
                select(Photo)
                .where(Photo.team_id == team_id, Photo.group_id == group.id, Photo.is_active.is_(True))
                .order_by(Photo.sort_order, Photo.created_at, Photo.id)
                .with_for_update()
            ).all()
        )
        payload = state_repository._verification_group_payload(session, group)
        persisted = dict((group.raw_data or {}).get("barcode_verification") or {})
        verification_payload = {
            **persisted,
            "status": verification.status,
            "evidence_fingerprint": verification.evidence_fingerprint,
            "evidence_version": verification.evidence_version,
            "meter_matched": verification.meter_matched,
            "module_matched": verification.module_matched,
            "collector_matched": verification.collector_matched,
            "recognition_source": verification.recognition_source,
        }
        reason, source = _archive_block_reason(payload, verification_payload)
        if reason:
            verification.auto_archive_status = "blocked"
            verification.auto_archive_error = reason
            session.commit()
            return {"archived": False, "group_id": group_id, "reason": reason}
        now = datetime.now(UTC)
        before = state_repository._group_payload(session, group, include_photos=True)
        for photo in photos:
            raw = dict(photo.raw_data or {})
            photo.archive_status = "archived"
            photo.archived_at = now
            photo.classified_by = photo.classified_by or actor
            raw.update({"archive_status": "archived", "archived_at": now.isoformat(), "classified_by": photo.classified_by})
            photo.raw_data = raw
        group.status = GroupStatus.APPROVED
        group.reviewer = actor
        group.review_note = "barcode verification auto archive"
        group.exception_note = ""
        group.reviewed_at = now
        raw = dict(group.raw_data or {})
        raw.update({"status": "approved", "reviewer": actor, "review_note": group.review_note, "exception_note": ""})
        verification_payload.update(
            {
                "auto_archive_status": "archived",
                "auto_archived_at": now.isoformat(),
                "auto_archive_error": "",
                "recognition_source": source,
            }
        )
        raw["barcode_verification"] = verification_payload
        group.raw_data = raw
        verification.auto_archive_status = "archived"
        verification.auto_archived_at = now
        verification.auto_archive_error = None
        verification.recognition_source = source
        state_repository._stage_transactional_audit(
            session,
            team_id=team_id,
            actor=actor,
            action="group_barcode_auto_archived",
            entity_type="material_group",
            entity_id=group.id,
            before_data=before,
            after_data={"status": "approved", "source": source},
            payload={"group_id": group.legacy_id or str(group.id), "source": source},
        )
        session.commit()
        result = {"archived": True, "group_id": group_id, "source": source}
    repository._enqueue_delivery_cache_after_commit(
        group_id,
        actor=actor,
        reason="auto_archive",
    )
    return result


def auto_archive_verified_group(group_id: str, *, actor: str = WORKER_ACTOR) -> dict[str, Any]:
    backend = _backend()
    team_id = local_simulation.current_team_id()
    if backend == "json":
        return _auto_archive_json(group_id, actor=actor, team_id=team_id)
    if backend == "postgres":
        return _auto_archive_postgres(group_id, actor=actor, team_id=team_id)
    transaction = local_simulation.begin_authoritative_json_write(team_id)
    token = local_simulation.activate_authoritative_json_write(transaction)
    try:
        json_result = _auto_archive_json_in_state(transaction.working_state, group_id, actor=actor)
        postgres_result = _auto_archive_postgres(group_id, actor=actor, team_id=team_id)
        if json_result != postgres_result:
            from app.services.state_repository import StateBackendNotReady

            raise StateBackendNotReady("Dual auto archive diverged; JSON archive was aborted")
        local_simulation.finish_authoritative_json_write(transaction, token)
        return json_result
    except BaseException:
        if not transaction.closed:
            local_simulation.abort_authoritative_json_write(transaction, token)
        raise


def _claim_json_delivery(*, worker_id: str, team_id: str, now: datetime) -> MaintenanceJob | None:
    transaction = local_simulation.begin_authoritative_json_write(team_id)
    token = local_simulation.activate_authoritative_json_write(transaction)
    try:
        state = transaction.working_state
        control = state.get("barcode_maintenance_control")
        if not isinstance(control, dict) or bool(control.get("paused", True)):
            local_simulation.abort_authoritative_json_write(transaction, token)
            return None
        candidates = []
        for job in state.setdefault("delivery_cache_jobs", []):
            status = str(job.get("status") or "")
            attempts = int(job.get("attempt_count") or 0)
            expired = (_parse_datetime(job.get("lease_expires_at")) or datetime.max.replace(tzinfo=UTC)) < now
            if status == "pending" or (status == "failed" and attempts < MAX_DELIVERY_CACHE_ATTEMPTS) or (status == "processing" and expired):
                candidates.append(job)
        if not candidates:
            local_simulation.abort_authoritative_json_write(transaction, token)
            return None
        job = sorted(candidates, key=lambda item: (str(item.get("updated_at") or ""), str(item.get("id") or "")))[0]
        lease_token = str(uuid4())
        job.update(
            {
                "status": "processing",
                "attempt_count": int(job.get("attempt_count") or 0) + 1,
                "lease_owner": worker_id,
                "lease_token": lease_token,
                "lease_expires_at": (now + timedelta(seconds=DEFAULT_LEASE_SECONDS)).isoformat(),
                "updated_at": now.isoformat(),
            }
        )
        claim = MaintenanceJob(
            kind="delivery_cache",
            team_id=team_id,
            group_id=str(job.get("group_id") or ""),
            lease_owner=worker_id,
            lease_token=lease_token,
            attempt_count=int(job.get("attempt_count") or 0),
        )
        local_simulation.finish_authoritative_json_write(transaction, token)
        return claim
    except BaseException:
        if not transaction.closed:
            local_simulation.abort_authoritative_json_write(transaction, token)
        raise


def claim_next_delivery_cache_job(*, worker_id: str, now: datetime | None = None) -> MaintenanceJob | None:
    claimed_at = now or datetime.now(UTC)
    team_id = local_simulation.current_team_id()
    backend = _backend()
    if backend == "json":
        return _claim_json_delivery(worker_id=worker_id, team_id=team_id, now=claimed_at)
    if backend == "dual":
        from app.services.state_repository import StateBackendNotReady

        raise StateBackendNotReady("Dual delivery-cache claim is disabled until PostgreSQL is authoritative")
    with SessionLocal() as session:
        control = session.scalar(select(BarcodeMaintenanceControl).where(BarcodeMaintenanceControl.team_id == team_id))
        if control is None or control.paused:
            return None
        claim = claim_postgres_delivery_cache_job(
            session,
            team_id=team_id,
            worker_id=worker_id,
            now=claimed_at,
        )
        if claim is None:
            return None
        return MaintenanceJob(
            kind="delivery_cache",
            team_id=claim.team_id,
            group_id=claim.group_id,
            lease_owner=claim.lease_owner,
            lease_token=claim.lease_token,
            attempt_count=claim.attempt_count,
        )


def _claim_next_work(worker_id: str) -> MaintenanceJob | None:
    global _next_claim_kind
    with _claim_kind_lock:
        first = _next_claim_kind
        _next_claim_kind = "delivery_cache" if first == "verification" else "verification"
    claimers = {
        "verification": lambda: claim_next_verification_job(worker_id=worker_id),
        "delivery_cache": lambda: claim_next_delivery_cache_job(worker_id=worker_id),
    }
    return claimers[first]() or claimers[_next_claim_kind]()


def _load_group_for_scan(job: MaintenanceJob) -> dict[str, Any]:
    if _backend() in {"json", "dual"}:
        token = local_simulation.set_current_team(job.team_id)
        try:
            group = local_simulation.get_group(job.group_id)
            if group is None:
                raise KeyError(job.group_id)
            return deepcopy(group)
        finally:
            local_simulation.reset_current_team(token)
    from app.services.state_repository import PostgresStateRepository, _verification_group_payload

    repository = PostgresStateRepository()
    with repository._session() as session:
        group = session.scalar(select(MaterialGroup).where(MaterialGroup.id == UUID(job.group_id)))
        if group is None:
            raise KeyError(job.group_id)
        return _verification_group_payload(session, group)


def _process_verification_job(job: MaintenanceJob) -> None:
    from app.services.state_repository import get_state_repository

    token = local_simulation.set_current_team(job.team_id)
    try:
        group = _load_group_for_scan(job)
        result = scan_group_evidence(group, list(group.get("photos") or []))
        applied = get_state_repository().apply_group_scan_result(
            job.group_id,
            result,
            claimed_evidence_fingerprint=job.evidence_fingerprint,
            claimed_evidence_version=job.evidence_version,
            lease_owner=job.lease_owner,
            lease_token=job.lease_token,
            actor=WORKER_ACTOR,
        )
        if applied.get("applied") and result.status == "passed":
            auto_archive_verified_group(job.group_id, actor=WORKER_ACTOR)
    finally:
        local_simulation.reset_current_team(token)


def _process_json_delivery_job(job: MaintenanceJob) -> None:
    token = local_simulation.set_current_team(job.team_id)
    try:
        group = local_simulation.get_group(job.group_id)
        if group is None:
            raise KeyError(job.group_id)
        snapshot = deepcopy(group)
        report = cache_group_photos(snapshot)
        transaction = local_simulation.begin_authoritative_json_write(job.team_id)
        transaction_token = local_simulation.activate_authoritative_json_write(transaction)
        try:
            state = transaction.working_state
            current = next((item for item in state.get("groups", []) if str(item.get("id") or "") == job.group_id), None)
            durable_job = next((item for item in state.get("delivery_cache_jobs", []) if str(item.get("group_id") or "") == job.group_id), None)
            if current is None or durable_job is None:
                raise KeyError(job.group_id)
            if durable_job.get("lease_owner") != job.lease_owner or durable_job.get("lease_token") != job.lease_token:
                local_simulation.abort_authoritative_json_write(transaction, transaction_token)
                return
            snapshot_by_id = {str(photo.get("id") or ""): photo for photo in snapshot.get("photos", [])}
            for photo in current.get("photos", []):
                cached = snapshot_by_id.get(str(photo.get("id") or ""))
                if cached is None or cached.get("sha256") != photo.get("sha256"):
                    continue
                for key in (
                    "delivery_cache_path",
                    "delivery_cache_version",
                    "delivery_cache_status",
                    "delivery_cache_content_type",
                    "delivery_cache_built_at",
                    "delivery_cache_error",
                ):
                    if key in cached:
                        photo[key] = cached[key]
            current["delivery_cache_status"] = report["status"]
            current["delivery_cache_error"] = snapshot.get("delivery_cache_error", "")
            durable_job.update(
                {
                    "status": "ready" if report["status"] == "ready" else "failed",
                    "lease_owner": None,
                    "lease_token": None,
                    "lease_expires_at": None,
                    "last_error": snapshot.get("delivery_cache_error", ""),
                    "retryable": bool(report.get("retryable")),
                    "completed_at": datetime.now(UTC).isoformat() if report["status"] == "ready" else None,
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
            local_simulation.append_audit_event("delivery_cache_build", WORKER_ACTOR, report)
            local_simulation.finish_authoritative_json_write(transaction, transaction_token)
        except BaseException:
            if not transaction.closed:
                local_simulation.abort_authoritative_json_write(transaction, transaction_token)
            raise
    finally:
        local_simulation.reset_current_team(token)


def _process_delivery_job(job: MaintenanceJob) -> None:
    if _backend() == "json":
        _process_json_delivery_job(job)
        return
    if _backend() == "dual":
        from app.services.state_repository import StateBackendNotReady

        raise StateBackendNotReady("Dual delivery-cache processing is disabled until PostgreSQL is authoritative")
    from app.services import state_repository

    repository = state_repository.PostgresStateRepository()
    with repository._session() as session:
        group = session.scalar(select(MaterialGroup).where(MaterialGroup.id == UUID(job.group_id)))
        if group is None:
            raise KeyError(job.group_id)
        snapshot = state_repository._group_payload(session, group, include_photos=True)
    report = cache_group_photos(snapshot)
    with repository._session() as session:
        group = session.scalar(select(MaterialGroup).where(MaterialGroup.id == UUID(job.group_id)).with_for_update())
        durable_job = session.scalar(
            select(DeliveryCacheJob)
            .where(DeliveryCacheJob.team_id == job.team_id, DeliveryCacheJob.group_id == UUID(job.group_id))
            .with_for_update()
        )
        if group is None or durable_job is None:
            raise KeyError(job.group_id)
        if durable_job.lease_owner != job.lease_owner or durable_job.lease_token != job.lease_token:
            session.rollback()
            return
        photos = list(session.scalars(select(Photo).where(Photo.group_id == group.id, Photo.is_active.is_(True)).with_for_update()).all())
        cached_by_id = {str(photo.get("id") or ""): photo for photo in snapshot.get("photos", [])}
        for photo in photos:
            cached = cached_by_id.get(str(photo.legacy_id or photo.id))
            if cached is None or cached.get("sha256") != photo.sha256:
                continue
            raw = dict(photo.raw_data or {})
            for key in (
                "delivery_cache_path",
                "delivery_cache_version",
                "delivery_cache_status",
                "delivery_cache_content_type",
                "delivery_cache_built_at",
                "delivery_cache_error",
            ):
                if key in cached:
                    raw[key] = cached[key]
            photo.raw_data = raw
        raw = dict(group.raw_data or {})
        raw["delivery_cache_status"] = report["status"]
        raw["delivery_cache_error"] = snapshot.get("delivery_cache_error", "")
        group.raw_data = raw
        durable_job.status = "ready" if report["status"] == "ready" else "failed"
        durable_job.lease_owner = None
        durable_job.lease_token = None
        durable_job.lease_expires_at = None
        durable_job.last_error = snapshot.get("delivery_cache_error", "") or None
        durable_job.completed_at = datetime.now(UTC) if report["status"] == "ready" else None
        state_repository._stage_transactional_audit(
            session,
            team_id=job.team_id,
            actor=WORKER_ACTOR,
            action="delivery_cache_build",
            entity_type="material_group",
            entity_id=group.id,
            payload=report,
        )
        session.commit()


def _process_job(job: MaintenanceJob) -> None:
    if job.kind == "verification":
        _process_verification_job(job)
        return
    if job.kind == "delivery_cache":
        _process_delivery_job(job)
        return
    raise ValueError(f"Unsupported maintenance job kind: {job.kind}")


def _fail_job(job: MaintenanceJob, error: Exception) -> None:
    if job.kind == "verification":
        fail_verification_job(job, error)
        return
    if job.kind == "delivery_cache" and _backend() == "json":
        token = local_simulation.set_current_team(job.team_id)
        try:
            transaction = local_simulation.begin_authoritative_json_write(job.team_id)
            transaction_token = local_simulation.activate_authoritative_json_write(transaction)
            try:
                durable_job = next(
                    (item for item in transaction.working_state.get("delivery_cache_jobs", []) if str(item.get("group_id") or "") == job.group_id),
                    None,
                )
                if durable_job and durable_job.get("lease_owner") == job.lease_owner and durable_job.get("lease_token") == job.lease_token:
                    durable_job.update(
                        {
                            "status": "failed",
                            "lease_owner": None,
                            "lease_token": None,
                            "lease_expires_at": None,
                            "last_error": str(error)[:500],
                            "retryable": int(durable_job.get("attempt_count") or 0) < MAX_DELIVERY_CACHE_ATTEMPTS,
                        }
                    )
                local_simulation.finish_authoritative_json_write(transaction, transaction_token)
            except BaseException:
                if not transaction.closed:
                    local_simulation.abort_authoritative_json_write(transaction, transaction_token)
                raise
        finally:
            local_simulation.reset_current_team(token)
        return
    if job.kind == "delivery_cache" and _backend() == "postgres":
        with SessionLocal() as session:
            durable_job = session.scalar(
                select(DeliveryCacheJob)
                .where(DeliveryCacheJob.team_id == job.team_id, DeliveryCacheJob.group_id == UUID(job.group_id))
                .with_for_update()
            )
            if durable_job and durable_job.lease_owner == job.lease_owner and durable_job.lease_token == job.lease_token:
                durable_job.status = "failed"
                durable_job.lease_owner = None
                durable_job.lease_token = None
                durable_job.lease_expires_at = None
                durable_job.last_error = str(error)[:500]
                session.commit()


def maintenance_load_too_high(max_ratio: float = DEFAULT_MAX_LOAD_RATIO) -> bool:
    try:
        one_minute = os.getloadavg()[0]
    except (AttributeError, OSError):
        return False
    return one_minute / max(1, os.cpu_count() or 1) >= max(0.0, float(max_ratio))


def _maintenance_can_claim() -> bool:
    return not bool(maintenance_status().get("paused", True))


def run_worker_batch(
    batch_size: int = DEFAULT_BATCH_SIZE,
    batch_pause_seconds: float = DEFAULT_BATCH_PAUSE_SECONDS,
    *,
    claim_next: Callable[[], MaintenanceJob | None] | None = None,
    process_job: Callable[[MaintenanceJob], None] | None = None,
    can_claim: Callable[[], bool] | None = None,
    load_too_high: Callable[[], bool] | None = None,
    fail_job: Callable[[MaintenanceJob, Exception], None] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    limit = min(DEFAULT_BATCH_SIZE, max(0, int(batch_size)))
    if not _batch_lock.acquire(blocking=False):
        return {"processed": 0, "failed": 0, "status": "worker_busy"}
    worker_id = f"{os.uname().nodename if hasattr(os, 'uname') else 'worker'}-{os.getpid()}"
    claim = claim_next or (lambda: _claim_next_work(worker_id))
    process = process_job or _process_job
    allowed = can_claim or _maintenance_can_claim
    loaded = load_too_high or maintenance_load_too_high
    on_failure = fail_job or _fail_job
    processed = 0
    failed = 0
    try:
        while processed < limit:
            if not allowed() or loaded():
                break
            job = claim()
            if job is None:
                break
            try:
                process(job)
            except Exception as exc:
                failed += 1
                on_failure(job, exc)
            processed += 1
        if limit > 0 and processed == limit and batch_pause_seconds > 0:
            sleeper(float(batch_pause_seconds))
        return {"processed": processed, "failed": failed, "status": "complete"}
    finally:
        _batch_lock.release()


def maintenance_status() -> dict[str, Any]:
    backend = _backend()
    team_id = local_simulation.current_team_id()
    if backend == "json":
        state = local_simulation.state_for_team(team_id)
        control = state.get("barcode_maintenance_control") or {"paused": True}
        verification_counts: dict[str, int] = {}
        for group in state.get("groups", []):
            status = str((group.get("barcode_verification") or {}).get("status") or "none")
            verification_counts[status] = verification_counts.get(status, 0) + 1
        cache_counts: dict[str, int] = {}
        for job in state.setdefault("delivery_cache_jobs", []):
            status = str(job.get("status") or "pending")
            cache_counts[status] = cache_counts.get(status, 0) + 1
        return {
            "team_id": team_id,
            "backend": backend,
            "paused": bool(control.get("paused", True)),
            "verification": verification_counts,
            "delivery_cache": cache_counts,
            "verification_pending": verification_counts.get("pending", 0),
            "delivery_cache_pending": cache_counts.get("pending", 0),
        }
    if backend == "dual":
        from app.services.state_repository import StateBackendNotReady

        raise StateBackendNotReady("Dual maintenance status is disabled until queue cutover is complete")
    with SessionLocal() as session:
        control = session.scalar(select(BarcodeMaintenanceControl).where(BarcodeMaintenanceControl.team_id == team_id))
        verification_rows = session.execute(
            select(GroupBarcodeVerification.status, func.count(GroupBarcodeVerification.id))
            .where(GroupBarcodeVerification.team_id == team_id)
            .group_by(GroupBarcodeVerification.status)
        ).all()
        cache_rows = session.execute(
            select(DeliveryCacheJob.status, func.count(DeliveryCacheJob.id))
            .where(DeliveryCacheJob.team_id == team_id)
            .group_by(DeliveryCacheJob.status)
        ).all()
        verification_counts = {str(status): int(count) for status, count in verification_rows}
        cache_counts = {str(status): int(count) for status, count in cache_rows}
        return {
            "team_id": team_id,
            "backend": backend,
            "paused": True if control is None else bool(control.paused),
            "verification": verification_counts,
            "delivery_cache": cache_counts,
            "verification_pending": verification_counts.get("pending", 0),
            "delivery_cache_pending": cache_counts.get("pending", 0),
        }


def set_maintenance_paused(paused: bool, actor: str) -> dict[str, Any]:
    backend = _backend()
    team_id = local_simulation.current_team_id()
    if backend == "json":
        transaction = local_simulation.begin_authoritative_json_write(team_id)
        token = local_simulation.activate_authoritative_json_write(transaction)
        try:
            control = transaction.working_state.setdefault(
                "barcode_maintenance_control",
                {"paused": True, "last_batch_id": "", "last_batch_progress": 0},
            )
            control.update({"paused": bool(paused), "updated_by": actor, "updated_at": datetime.now(UTC).isoformat()})
            local_simulation.append_audit_event(
                "barcode_maintenance_paused" if paused else "barcode_maintenance_resumed",
                actor,
                {"paused": bool(paused)},
            )
            local_simulation.finish_authoritative_json_write(transaction, token)
            return {"paused": bool(paused), "team_id": team_id}
        except BaseException:
            if not transaction.closed:
                local_simulation.abort_authoritative_json_write(transaction, token)
            raise
    if backend == "dual":
        from app.services.state_repository import StateBackendNotReady

        raise StateBackendNotReady("Dual maintenance control is disabled until queue cutover is complete")
    with SessionLocal() as session:
        control = session.scalar(
            select(BarcodeMaintenanceControl)
            .where(BarcodeMaintenanceControl.team_id == team_id)
            .with_for_update()
        )
        if control is None:
            control = BarcodeMaintenanceControl(team_id=team_id)
            session.add(control)
        control.paused = bool(paused)
        session.commit()
    return {"paused": bool(paused), "team_id": team_id}


def _enqueue_json_verifications(group_ids: list[str], *, actor: str, team_id: str) -> dict[str, Any]:
    transaction = local_simulation.begin_authoritative_json_write(team_id)
    token = local_simulation.activate_authoritative_json_write(transaction)
    try:
        selected = set(group_ids)
        enqueued = 0
        skipped: list[dict[str, str]] = []
        for group in transaction.working_state.get("groups", []):
            group_id = str(group.get("id") or "")
            if selected and group_id not in selected:
                continue
            eligibility = evaluate_group_eligibility(group)
            if eligibility.status != "pending":
                skipped.append({"group_id": group_id, "reason": eligibility.reason or "not_eligible"})
                continue
            current = dict(group.get("barcode_verification") or {})
            next_verification = invalidate_group_verification(
                current,
                reason="admin_enqueued",
                actor=actor,
                evidence_fingerprint=eligibility.evidence_fingerprint,
                next_status="pending",
            )
            next_verification.update({"attempt_count": 0, "retryable": False, "manual_review_required": False})
            group["barcode_verification"] = next_verification
            enqueued += 1
        missing = sorted(selected - {str(group.get("id") or "") for group in transaction.working_state.get("groups", [])})
        skipped.extend({"group_id": group_id, "reason": "not_found"} for group_id in missing)
        local_simulation.append_audit_event(
            "barcode_maintenance_enqueued",
            actor,
            {"enqueued": enqueued, "skipped": skipped},
        )
        local_simulation.finish_authoritative_json_write(transaction, token)
        return {"team_id": team_id, "enqueued": enqueued, "skipped": skipped}
    except BaseException:
        if not transaction.closed:
            local_simulation.abort_authoritative_json_write(transaction, token)
        raise


def _enqueue_postgres_verifications(group_ids: list[str], *, actor: str, team_id: str) -> dict[str, Any]:
    from app.services import state_repository

    repository = state_repository.PostgresStateRepository()
    with repository._session() as session:
        statement = select(MaterialGroup).where(MaterialGroup.team_id == team_id).order_by(MaterialGroup.id).with_for_update()
        if group_ids:
            parsed_ids = [_postgres_group_id(group_id) for group_id in group_ids]
            statement = statement.where(
                or_(
                    MaterialGroup.legacy_id.in_(group_ids),
                    MaterialGroup.id.in_([value for value in parsed_ids if value is not None]),
                )
            )
        groups = list(session.scalars(statement).all())
        enqueued = 0
        skipped: list[dict[str, str]] = []
        found: set[str] = set()
        for group in groups:
            identifier = str(group.legacy_id or group.id)
            found.update({identifier, str(group.id)})
            payload = state_repository._verification_group_payload(session, group)
            eligibility = evaluate_group_eligibility(payload)
            if eligibility.status != "pending":
                skipped.append({"group_id": identifier, "reason": eligibility.reason or "not_eligible"})
                continue
            verification = session.scalar(
                select(GroupBarcodeVerification)
                .where(GroupBarcodeVerification.team_id == team_id, GroupBarcodeVerification.group_id == group.id)
                .with_for_update()
            )
            if verification is None:
                verification = GroupBarcodeVerification(team_id=team_id, group_id=group.id, evidence_version=0)
                session.add(verification)
            verification.status = "pending"
            verification.evidence_fingerprint = eligibility.evidence_fingerprint
            verification.evidence_version = int(verification.evidence_version or 0) + 1
            verification.attempt_count = 0
            verification.lease_owner = None
            verification.lease_token = None
            verification.lease_expires_at = None
            verification.auto_archive_status = None
            verification.auto_archive_error = None
            enqueued += 1
        skipped.extend({"group_id": value, "reason": "not_found"} for value in group_ids if value not in found)
        session.commit()
        return {"team_id": team_id, "enqueued": enqueued, "skipped": skipped}


def enqueue_verification_jobs(group_ids: list[str] | None = None, actor: str = WORKER_ACTOR) -> dict[str, Any]:
    clean_ids = list(dict.fromkeys(str(value).strip() for value in (group_ids or []) if str(value).strip()))
    backend = _backend()
    team_id = local_simulation.current_team_id()
    if backend == "json":
        return _enqueue_json_verifications(clean_ids, actor=actor, team_id=team_id)
    if backend == "postgres":
        return _enqueue_postgres_verifications(clean_ids, actor=actor, team_id=team_id)
    from app.services.state_repository import StateBackendNotReady

    raise StateBackendNotReady("Dual maintenance enqueue is disabled until queue cutover is complete")


def _load_env(path: str) -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() and key.strip() not in os.environ:
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run durable low-load barcode maintenance work.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--serve", action="store_true")
    mode.add_argument("--enqueue", action="store_true")
    parser.add_argument("--env-file", default="")
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("BARCODE_MAINTENANCE_BATCH_SIZE", "20")))
    parser.add_argument(
        "--batch-pause-seconds",
        type=float,
        default=float(os.getenv("BARCODE_MAINTENANCE_BATCH_PAUSE_SECONDS", "5")),
    )
    args = parser.parse_args(argv)
    if args.env_file:
        _load_env(args.env_file)
    if args.enqueue:
        report = enqueue_verification_jobs(actor=WORKER_ACTOR)
        print(report)
        return 0
    while True:
        report = run_worker_batch(
            batch_size=args.batch_size,
            batch_pause_seconds=args.batch_pause_seconds,
        )
        if int(report.get("processed") or 0) < min(DEFAULT_BATCH_SIZE, max(0, int(args.batch_size))):
            time.sleep(max(1.0, float(args.batch_pause_seconds)))


if __name__ == "__main__":
    raise SystemExit(main())
