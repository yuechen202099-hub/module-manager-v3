from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import DeliveryCacheJob, MaterialGroup
from app.services import local_simulation


MAX_DELIVERY_CACHE_ATTEMPTS = 3
DEFAULT_LEASE_SECONDS = 300


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
) -> dict[str, Any]:
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
                & (DeliveryCacheJob.lease_expires_at < now),
            ),
        )
        .order_by(DeliveryCacheJob.updated_at, DeliveryCacheJob.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def claim_postgres_delivery_cache_job(
    session: Session,
    *,
    team_id: str,
    worker_id: str,
    now: datetime | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> DeliveryCacheClaim | None:
    claimed_at = now or datetime.now(UTC)
    job = session.scalar(build_postgres_delivery_claim_statement(team_id=team_id, now=claimed_at))
    if job is None:
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


def cache_group_photos(
    group: dict[str, Any],
    *,
    cache_root: Path | None = None,
    fetch_photo: Callable[[dict[str, Any]], tuple[bytes, str]] | None = None,
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
        sha256 = str(photo.get("sha256") or "").strip().lower()
        if len(sha256) != 64:
            failures.append({"photo_id": str(photo.get("id") or ""), "error": "missing sha256"})
            continue
        existing_candidates = list((root / "objects" / sha256[:2]).glob(f"{sha256}.*"))
        target = existing_candidates[0] if existing_candidates else None
        content_type = str(photo.get("content_type") or "image/jpeg")
        try:
            if target is None or not target.is_file():
                content, content_type = fetcher(photo)
                suffix = _cache_suffix(photo, content_type)
                target = root / "objects" / sha256[:2] / f"{sha256}{suffix}"
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(f"{target.suffix}.tmp-{uuid4().hex}")
                temporary.write_bytes(content)
                temporary.replace(target)
                built += 1
            else:
                reused += 1
            relative = target.relative_to(root)
            photo["delivery_cache_path"] = str(relative).replace("\\", "/")
            photo["delivery_cache_version"] = sha256
            photo["delivery_cache_status"] = "ready"
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
