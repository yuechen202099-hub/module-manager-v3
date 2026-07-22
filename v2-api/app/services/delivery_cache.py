from __future__ import annotations

import hashlib
import mimetypes
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from sqlalchemy import and_, exists, literal, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import SessionLocal
from app.models import DeliveryCacheJob, GroupStatus, MaterialGroup, Photo
from app.services import local_simulation


MAX_DELIVERY_CACHE_ATTEMPTS = 3
DEFAULT_LEASE_SECONDS = 300
MAX_RECONCILIATION_BATCH_SIZE = 20
_EXISTING_JOB_NOT_PROVIDED = object()


@dataclass(frozen=True)
class DeliveryCacheClaim:
    team_id: str
    group_id: str
    lease_owner: str
    lease_token: str
    attempt_count: int


def _now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).isoformat()


def _job_payload(job: DeliveryCacheJob) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "team_id": job.team_id,
        "group_id": str(job.group_id),
        "status": job.status,
        "attempt_count": int(job.attempt_count or 0),
        "lease_owner": job.lease_owner,
        "lease_token": job.lease_token,
        "lease_expires_at": job.lease_expires_at.isoformat() if job.lease_expires_at else None,
        "requested_by": job.requested_by or "",
        "request_reason": job.request_reason or "",
        "last_error": job.last_error or "",
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


def enqueue_json_delivery_cache_job(
    group_id: str,
    *,
    team_id: str | None = None,
    actor: str = "system",
    reason: str = "review_completed",
) -> dict[str, Any]:
    team = local_simulation.normalize_team_id(team_id or local_simulation.current_team_id())
    state = local_simulation.state_for_team(team)
    group = next((item for item in state.get("groups", []) if str(item.get("id") or "") == group_id), None)
    if group is None:
        raise KeyError(group_id)
    jobs = state.setdefault("delivery_cache_jobs", [])
    job = next((item for item in jobs if str(item.get("group_id") or "") == group_id), None)
    now = _now_iso()
    if job is None:
        job = {
            "id": str(uuid4()),
            "team_id": team,
            "group_id": group_id,
            "status": "pending",
            "attempt_count": 0,
            "lease_owner": None,
            "lease_token": None,
            "lease_expires_at": None,
            "requested_by": actor,
            "request_reason": reason,
            "last_error": "",
            "requested_at": now,
            "updated_at": now,
        }
        jobs.append(job)
    else:
        job.update(
            {
                "status": "pending",
                "lease_owner": None,
                "lease_token": None,
                "lease_expires_at": None,
                "requested_by": actor,
                "request_reason": reason,
                "last_error": "",
                "requested_at": now,
                "updated_at": now,
            }
        )
    group["delivery_cache_status"] = "pending"
    group["delivery_cache_error"] = ""
    return dict(job)


def enqueue_postgres_delivery_cache_job(
    session: Session,
    group: MaterialGroup,
    *,
    actor: str = "system",
    reason: str = "review_completed",
    existing_job: DeliveryCacheJob | None | object = _EXISTING_JOB_NOT_PROVIDED,
) -> dict[str, Any]:
    job = existing_job
    if job is _EXISTING_JOB_NOT_PROVIDED:
        job = session.scalar(
            select(DeliveryCacheJob)
            .where(
                DeliveryCacheJob.team_id == group.team_id,
                DeliveryCacheJob.group_id == group.id,
            )
            .with_for_update()
        )
    if job is None:
        job = DeliveryCacheJob(team_id=group.team_id, group_id=group.id)
        session.add(job)
    job.status = "pending"
    job.lease_owner = None
    job.lease_token = None
    job.lease_expires_at = None
    job.requested_by = actor
    job.request_reason = reason
    job.last_error = None
    job.completed_at = None
    raw = dict(group.raw_data or {})
    raw["delivery_cache_status"] = "pending"
    raw["delivery_cache_error"] = ""
    group.raw_data = raw
    session.flush()
    return _job_payload(job)


def build_postgres_delivery_claim_statement(*, team_id: str, now: datetime):
    return (
        select(DeliveryCacheJob)
        .where(
            DeliveryCacheJob.team_id == team_id,
            or_(
                DeliveryCacheJob.status == "pending",
                (DeliveryCacheJob.status == "failed")
                & (DeliveryCacheJob.attempt_count < MAX_DELIVERY_CACHE_ATTEMPTS),
                (DeliveryCacheJob.status == "processing")
                & (DeliveryCacheJob.attempt_count < MAX_DELIVERY_CACHE_ATTEMPTS)
                & (DeliveryCacheJob.lease_expires_at < now),
            ),
        )
        .order_by(DeliveryCacheJob.updated_at, DeliveryCacheJob.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def build_postgres_delivery_job_lock_statement(*, team_id: str, group_ids: list[Any]):
    return (
        select(DeliveryCacheJob)
        .where(
            DeliveryCacheJob.team_id == team_id,
            DeliveryCacheJob.group_id.in_(group_ids),
        )
        .order_by(DeliveryCacheJob.group_id, DeliveryCacheJob.id)
        .with_for_update(of=DeliveryCacheJob, skip_locked=True)
    )


def build_postgres_expired_delivery_group_statement(*, team_id: str, now: datetime):
    return (
        select(MaterialGroup)
        .join(
            DeliveryCacheJob,
            and_(
                DeliveryCacheJob.team_id == MaterialGroup.team_id,
                DeliveryCacheJob.group_id == MaterialGroup.id,
            ),
        )
        .where(
            MaterialGroup.team_id == team_id,
            DeliveryCacheJob.status == "processing",
            DeliveryCacheJob.attempt_count >= MAX_DELIVERY_CACHE_ATTEMPTS,
            DeliveryCacheJob.lease_expires_at < now,
        )
        .order_by(MaterialGroup.id)
        .with_for_update(of=MaterialGroup, skip_locked=True)
    )


def _terminalize_expired_postgres_delivery_leases(
    session: Session,
    *,
    team_id: str,
    now: datetime,
) -> int:
    groups = list(
        session.scalars(build_postgres_expired_delivery_group_statement(team_id=team_id, now=now)).all()
    )
    if not groups:
        return 0
    groups_by_id = {group.id: group for group in groups}
    jobs = list(
        session.scalars(
            build_postgres_delivery_job_lock_statement(
                team_id=team_id,
                group_ids=list(groups_by_id),
            )
        ).all()
    )
    terminalized = 0
    for job in jobs:
        group = groups_by_id.get(job.group_id)
        if group is None or not _delivery_job_is_terminalizable(job, now=now):
            continue
        job.status = "failed"
        job.lease_owner = None
        job.lease_token = None
        job.lease_expires_at = None
        job.last_error = "worker lease expired after maximum attempts; manual review required"
        raw = dict(group.raw_data or {})
        raw.update(
            {
                "delivery_cache_status": "manual_required",
                "delivery_cache_error": job.last_error,
                "delivery_cache_retryable": False,
            }
        )
        group.raw_data = raw
        terminalized += 1
    return terminalized


def claim_postgres_delivery_cache_job(
    session: Session,
    *,
    team_id: str,
    worker_id: str,
    now: datetime | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> DeliveryCacheClaim | None:
    claimed_at = now or datetime.now(UTC)
    terminalized = _terminalize_expired_postgres_delivery_leases(
        session,
        team_id=team_id,
        now=claimed_at,
    )
    job = session.scalar(build_postgres_delivery_claim_statement(team_id=team_id, now=claimed_at))
    if job is None:
        if terminalized:
            session.commit()
        return None
    token = str(uuid4())
    job.status = "processing"
    job.attempt_count = int(job.attempt_count or 0) + 1
    job.lease_owner = worker_id
    job.lease_token = token
    job.lease_expires_at = claimed_at + timedelta(seconds=max(1, int(lease_seconds)))
    session.commit()
    return DeliveryCacheClaim(
        team_id=team_id,
        group_id=str(job.group_id),
        lease_owner=worker_id,
        lease_token=token,
        attempt_count=job.attempt_count,
    )


def _cache_suffix(photo: Mapping[str, Any], content_type: str) -> str:
    original = Path(str(photo.get("original_filename") or photo.get("image_url") or "").split("?", 1)[0]).suffix.lower()
    if original in {".jpg", ".jpeg", ".png", ".webp"}:
        return ".jpg" if original == ".jpeg" else original
    guessed = mimetypes.guess_extension(content_type.split(";", 1)[0].strip()) or ".jpg"
    return ".jpg" if guessed == ".jpe" else guessed


def _normalized_fetch_result(
    photo: Mapping[str, Any],
    result: tuple[bytes, str] | tuple[bytes, str, str],
) -> tuple[bytes, str, str]:
    if len(result) == 2:
        content, content_type = result
        return content, _cache_suffix(photo, content_type), content_type
    if len(result) == 3:
        content, suffix, content_type = result
        normalized_suffix = str(suffix or "").strip().lower()
        if normalized_suffix and not normalized_suffix.startswith("."):
            normalized_suffix = f".{normalized_suffix}"
        if normalized_suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            normalized_suffix = _cache_suffix(photo, content_type)
        if normalized_suffix == ".jpeg":
            normalized_suffix = ".jpg"
        return content, normalized_suffix, content_type
    raise ValueError("Unsupported delivery photo fetch result")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_existing_object(root: Path, sha256: str) -> Path | None:
    object_dir = root / "objects" / sha256[:2]
    if not object_dir.exists():
        return None
    verified = None
    for candidate in sorted(object_dir.glob(f"{sha256}.*")):
        if ".tmp" in candidate.name:
            candidate.unlink(missing_ok=True)
            continue
        if not candidate.is_file() or _file_sha256(candidate) != sha256:
            candidate.unlink(missing_ok=True)
            continue
        if verified is None:
            verified = candidate
    return verified


def _is_url_fingerprint_sha(photo: Mapping[str, Any], sha256: str) -> bool:
    sha256_source = str(photo.get("sha256_source") or "").strip().lower()
    if sha256_source == "declared":
        return False
    if sha256_source == "image_url":
        return True
    for key in ("image_url", "url", "source_url"):
        value = str(photo.get(key) or "").strip()
        if value and hashlib.sha256(value.encode("utf-8")).hexdigest() == sha256:
            return True
    return False


def _cache_group_photos_impl(
    group: dict[str, Any],
    *,
    cache_root: Path | None = None,
    fetch_photo: Callable[
        [dict[str, Any]],
        tuple[bytes, str] | tuple[bytes, str, str],
    ]
    | None = None,
) -> dict[str, Any]:
    root = (cache_root or local_simulation.delivery_cache_root()).resolve()
    fetcher = fetch_photo or local_simulation.download_delivery_photo_content
    photos = [
        photo
        for photo in group.get("photos", [])
        if isinstance(photo, dict) and photo.get("is_active") is not False
    ]
    failures: list[dict[str, str]] = []
    built = 0
    reused = 0
    group["delivery_cache_status"] = "building"
    group["delivery_cache_error"] = ""
    for photo in photos:
        declared_sha256 = str(photo.get("sha256") or "").strip().lower()
        if len(declared_sha256) != 64:
            failures.append({"photo_id": str(photo.get("id") or ""), "error": "missing sha256"})
            continue
        synthetic_sha256 = _is_url_fingerprint_sha(photo, declared_sha256)
        cached_content_sha256 = str(photo.get("delivery_cache_content_sha256") or "").strip().lower()
        object_sha256 = cached_content_sha256 if synthetic_sha256 and len(cached_content_sha256) == 64 else declared_sha256
        target = _verified_existing_object(root, object_sha256)
        content_type = str(photo.get("content_type") or "image/jpeg")
        try:
            if target is None or not target.is_file():
                content, suffix, content_type = _normalized_fetch_result(photo, fetcher(photo))
                content_sha256 = hashlib.sha256(content).hexdigest()
                if not synthetic_sha256 and content_sha256 != declared_sha256:
                    raise ValueError("Downloaded delivery cache content SHA256 mismatch")
                object_sha256 = content_sha256
                target = _verified_existing_object(root, object_sha256)
                if target is None:
                    target = root / "objects" / object_sha256[:2] / f"{object_sha256}{suffix}"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_suffix(f"{target.suffix}.tmp-{uuid4().hex}")
                    try:
                        with temporary.open("xb") as output:
                            output.write(content)
                            output.flush()
                            os.fsync(output.fileno())
                        temporary.replace(target)
                    finally:
                        temporary.unlink(missing_ok=True)
                    built += 1
                else:
                    reused += 1
            else:
                content_type = mimetypes.guess_type(target.name)[0] or content_type
                reused += 1
            relative = target.relative_to(root)
            photo["delivery_cache_path"] = str(relative).replace("\\", "/")
            photo["delivery_cache_version"] = local_simulation.delivery_photo_cache_version(photo)
            photo["delivery_cache_status"] = "ready"
            photo["delivery_cache_content_sha256"] = object_sha256
            photo["delivery_cache_content_type"] = content_type
            photo["delivery_cache_built_at"] = _now_iso()
            photo["delivery_cache_error"] = ""
        except Exception as exc:
            photo["delivery_cache_status"] = "failed"
            photo["delivery_cache_error"] = str(exc)[:500]
            failures.append({"photo_id": str(photo.get("id") or ""), "error": str(exc)[:500]})
    if failures:
        group["delivery_cache_status"] = "failed"
        group["delivery_cache_error"] = "; ".join(item["error"] for item in failures[:3])
        return {
            "status": "failed",
            "retryable": True,
            "group_id": str(group.get("id") or ""),
            "built": built,
            "reused": reused,
            "failed": failures,
        }
    group["delivery_cache_status"] = "ready"
    group["delivery_cache_built_at"] = _now_iso()
    return {
        "status": "ready",
        "retryable": False,
        "group_id": str(group.get("id") or ""),
        "built": built,
        "reused": reused,
        "failed": [],
    }


def cache_group_photos(
    group: dict[str, Any],
    *,
    cache_root: Path | None = None,
    fetch_photo: Callable[
        [dict[str, Any]],
        tuple[bytes, str] | tuple[bytes, str, str],
    ]
    | None = None,
) -> dict[str, Any]:
    from app.services.final_delivery_export import release_delivery_cache_path, reserve_delivery_cache_path

    root = (cache_root or local_simulation.delivery_cache_root()).resolve()
    lease = reserve_delivery_cache_path(root / "objects")
    try:
        return _cache_group_photos_impl(group, cache_root=root, fetch_photo=fetch_photo)
    finally:
        release_delivery_cache_path(lease)


def _reconciliation_limit(limit: int) -> int:
    return min(MAX_RECONCILIATION_BATCH_SIZE, max(0, int(limit)))


def _reconcile_json_delivery_cache_jobs(team_id: str, *, limit: int) -> dict[str, Any]:
    bounded = _reconciliation_limit(limit)
    transaction = local_simulation.begin_authoritative_json_write(team_id)
    token = local_simulation.activate_authoritative_json_write(transaction)
    try:
        state = transaction.working_state
        jobs_by_group = {
            str(job.get("group_id") or ""): job
            for job in state.setdefault("delivery_cache_jobs", [])
            if isinstance(job, dict)
        }
        enqueued = 0
        scanned = 0
        if bounded == 0:
            local_simulation.abort_authoritative_json_write(transaction, token)
            return {"backend": "json", "scanned": 0, "enqueued": 0}
        groups = state.get("groups", [])
        if not groups:
            local_simulation.abort_authoritative_json_write(transaction, token)
            return {"backend": "json", "scanned": 0, "enqueued": 0}
        previous_cursor = int(state.get("delivery_cache_reconcile_cursor") or 0) % len(groups)
        next_cursor = previous_cursor
        for offset in range(min(bounded, len(groups))):
            group = groups[(previous_cursor + offset) % len(groups)]
            scanned += 1
            next_cursor = (previous_cursor + offset + 1) % len(groups)
            if not isinstance(group, dict) or not local_simulation.is_reviewed_group(group):
                continue
            group_id = str(group.get("id") or "")
            if not group_id:
                continue
            retry_pending = str(group.get("delivery_cache_status") or "") == "retry_pending"
            if group_id in jobs_by_group and not retry_pending:
                continue
            if retry_pending and not local_simulation.delivery_cache_group_is_eligible(group):
                continue
            job = enqueue_json_delivery_cache_job(
                group_id,
                team_id=team_id,
                actor=str(group.get("reviewer") or "system"),
                reason="reconciliation",
            )
            jobs_by_group[group_id] = job
            enqueued += 1
            if enqueued >= bounded:
                break
        cursor_changed = next_cursor != previous_cursor or "delivery_cache_reconcile_cursor" not in state
        state["delivery_cache_reconcile_cursor"] = next_cursor
        if enqueued or cursor_changed:
            local_simulation.finish_authoritative_json_write(transaction, token)
        else:
            local_simulation.abort_authoritative_json_write(transaction, token)
        return {"backend": "json", "scanned": scanned, "enqueued": enqueued}
    except BaseException:
        if not transaction.closed:
            local_simulation.abort_authoritative_json_write(transaction, token)
        raise


def build_postgres_existing_reconciliation_statement(
    *,
    team_id: str,
    limit: int,
    now: datetime,
):
    bounded = _reconciliation_limit(limit)
    return (
        select(MaterialGroup)
        .join(
            DeliveryCacheJob,
            and_(
                DeliveryCacheJob.team_id == MaterialGroup.team_id,
                DeliveryCacheJob.group_id == MaterialGroup.id,
            ),
        )
        .where(
            MaterialGroup.team_id == team_id,
            MaterialGroup.status == GroupStatus.APPROVED,
            MaterialGroup.raw_data["delivery_cache_status"].as_string() == "retry_pending",
            or_(
                DeliveryCacheJob.status == "pending",
                DeliveryCacheJob.status == "ready",
                and_(
                    DeliveryCacheJob.status == "failed",
                    DeliveryCacheJob.attempt_count < MAX_DELIVERY_CACHE_ATTEMPTS,
                ),
                and_(
                    DeliveryCacheJob.status == "processing",
                    DeliveryCacheJob.attempt_count < MAX_DELIVERY_CACHE_ATTEMPTS,
                    DeliveryCacheJob.lease_expires_at.is_not(None),
                    DeliveryCacheJob.lease_expires_at < now,
                ),
            ),
        )
        .order_by(MaterialGroup.id)
        .limit(bounded)
        .with_for_update(of=MaterialGroup, skip_locked=True)
    )


def build_postgres_missing_reconciliation_statement(*, team_id: str, limit: int):
    bounded = _reconciliation_limit(limit)
    job_exists = exists(
        select(DeliveryCacheJob.id).where(
            DeliveryCacheJob.team_id == MaterialGroup.team_id,
            DeliveryCacheJob.group_id == MaterialGroup.id,
        )
    )
    return (
        select(MaterialGroup, literal(None).label("delivery_cache_job"))
        .where(
            MaterialGroup.team_id == team_id,
            MaterialGroup.status == GroupStatus.APPROVED,
            ~job_exists,
        )
        .order_by(MaterialGroup.id)
        .limit(bounded)
        .with_for_update(of=MaterialGroup, skip_locked=True)
    )


def build_postgres_reconciliation_photo_statement(*, team_id: str, group_ids: list[Any]):
    return (
        select(Photo)
        .where(
            Photo.team_id == team_id,
            Photo.group_id.in_(group_ids),
            Photo.is_active.is_(True),
        )
        .order_by(Photo.group_id, Photo.sort_order, Photo.created_at, Photo.id)
    )


def _delivery_job_has_live_lease(job: DeliveryCacheJob, *, now: datetime) -> bool:
    if str(job.status or "") != "processing":
        return False
    lease_expires_at = job.lease_expires_at
    if lease_expires_at is None:
        return True
    if lease_expires_at.tzinfo is None:
        lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
    return lease_expires_at >= now


def _delivery_job_is_terminalizable(job: DeliveryCacheJob, *, now: datetime) -> bool:
    return (
        str(job.status or "") == "processing"
        and int(job.attempt_count or 0) >= MAX_DELIVERY_CACHE_ATTEMPTS
        and not _delivery_job_has_live_lease(job, now=now)
    )


def _delivery_job_is_reconciliation_eligible(job: DeliveryCacheJob, *, now: datetime) -> bool:
    status = str(job.status or "")
    attempts = int(job.attempt_count or 0)
    if status in {"pending", "ready"}:
        return True
    if status == "failed":
        return attempts < MAX_DELIVERY_CACHE_ATTEMPTS
    return status == "processing" and attempts < MAX_DELIVERY_CACHE_ATTEMPTS and not _delivery_job_has_live_lease(job, now=now)


def _postgres_reconciliation_photo_payload(photo: Photo) -> dict[str, Any]:
    raw = dict(getattr(photo, "raw_data", {}) or {})
    image_url = str(getattr(photo, "image_url", None) or getattr(photo, "source_url", None) or "")
    storage_type = str(getattr(photo, "storage_type", None) or "")
    storage_bucket = str(getattr(photo, "storage_bucket", None) or "")
    storage_key = str(getattr(photo, "storage_key", None) or "")
    if not image_url and storage_type == "oss" and storage_key:
        image_url = f"oss://{storage_bucket}/{storage_key}"
    upload_status = getattr(photo, "upload_status", "uploaded")
    return {
        "id": str(getattr(photo, "legacy_id", None) or getattr(photo, "id", "")),
        "is_active": bool(getattr(photo, "is_active", True)),
        "upload_status": str(getattr(upload_status, "value", upload_status) or ""),
        "category": str(getattr(photo, "category", None) or raw.get("category") or "unclassified"),
        "construction_slot": str(raw.get("construction_slot") or ""),
        "image_url": image_url,
        "source_url": str(getattr(photo, "source_url", None) or image_url),
        "storage_type": storage_type,
        "storage_bucket": storage_bucket,
        "storage_key": storage_key,
        "sha256": str(getattr(photo, "sha256", None) or ""),
    }


def _group_is_reconciliation_eligible(group: MaterialGroup, photos: list[Photo]) -> bool:
    status = str(getattr(group.status, "value", group.status) or "")
    return (
        status == GroupStatus.APPROVED.value
        and local_simulation.delivery_cache_group_is_eligible(
            {
                "id": str(group.id),
                "status": "approved",
                "photos": [_postgres_reconciliation_photo_payload(photo) for photo in photos],
            }
        )
    )


def _reconcile_postgres_delivery_cache_jobs(
    team_id: str,
    *,
    limit: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    reconciled_at = now or datetime.now(UTC)
    bounded = _reconciliation_limit(limit)
    with SessionLocal() as session:
        existing_groups = list(
            session.execute(
                build_postgres_existing_reconciliation_statement(
                    team_id=team_id,
                    limit=bounded,
                    now=reconciled_at,
                )
            ).scalars().all()
        )
        groups_by_id = {group.id: group for group in existing_groups}
        existing_jobs = []
        if groups_by_id:
            existing_jobs = list(
                session.execute(
                    build_postgres_delivery_job_lock_statement(
                        team_id=team_id,
                        group_ids=list(groups_by_id),
                    )
                ).scalars().all()
            )
        enqueued = 0
        skipped_live = 0
        retry_state_changed = False
        remaining = max(0, bounded - len(existing_groups))
        missing_rows = []
        if remaining:
            missing_rows = list(
                session.execute(
                    build_postgres_missing_reconciliation_statement(
                        team_id=team_id,
                        limit=remaining,
                    )
                ).all()
            )
        candidate_groups = [*existing_groups, *(group for group, _missing_job in missing_rows)]
        photos_by_group: dict[Any, list[Photo]] = {group.id: [] for group in candidate_groups}
        if photos_by_group:
            photos = session.execute(
                build_postgres_reconciliation_photo_statement(
                    team_id=team_id,
                    group_ids=list(photos_by_group),
                )
            ).scalars().all()
            for photo in photos:
                if photo.group_id in photos_by_group:
                    photos_by_group[photo.group_id].append(photo)
        for job in existing_jobs:
            group = groups_by_id.get(job.group_id)
            if group is None or not _group_is_reconciliation_eligible(
                group,
                photos_by_group.get(group.id, []),
            ):
                continue
            if _delivery_job_has_live_lease(job, now=reconciled_at):
                skipped_live += 1
                continue
            if not _delivery_job_is_reconciliation_eligible(job, now=reconciled_at):
                continue
            enqueue_postgres_delivery_cache_job(
                session,
                group,
                actor=str(group.reviewer or "system"),
                reason="reconciliation",
                existing_job=job,
            )
            enqueued += 1
        for group, _missing_job in missing_rows:
            if not _group_is_reconciliation_eligible(group, photos_by_group.get(group.id, [])):
                raw = dict(group.raw_data or {})
                if str(raw.get("delivery_cache_status") or "") != "retry_pending":
                    raw.update(
                        {
                            "delivery_cache_status": "retry_pending",
                            "delivery_cache_error": "delivery cache evidence is temporarily ineligible",
                            "delivery_cache_retryable": True,
                            "delivery_cache_retry_requested_at": reconciled_at.isoformat(),
                        }
                    )
                    group.raw_data = raw
                    retry_state_changed = True
                continue
            enqueue_postgres_delivery_cache_job(
                session,
                group,
                actor=str(group.reviewer or "system"),
                reason="reconciliation",
                existing_job=None,
            )
            enqueued += 1
        if enqueued or retry_state_changed:
            session.commit()
        else:
            session.rollback()
        return {
            "backend": "postgres",
            "scanned": len(existing_groups) + len(missing_rows),
            "enqueued": enqueued,
            "skipped_live": skipped_live,
        }


def reconcile_delivery_cache_jobs(*, limit: int = MAX_RECONCILIATION_BATCH_SIZE) -> dict[str, Any]:
    bounded = _reconciliation_limit(limit)
    backend = settings.state_backend.lower().strip()
    team_id = local_simulation.current_team_id()
    if backend == "json":
        return _reconcile_json_delivery_cache_jobs(team_id, limit=bounded)
    if backend == "postgres":
        return _reconcile_postgres_delivery_cache_jobs(team_id, limit=bounded)
    from app.services.state_repository import StateBackendNotReady

    raise StateBackendNotReady("Dual delivery-cache reconciliation is disabled until one backend is authoritative")
