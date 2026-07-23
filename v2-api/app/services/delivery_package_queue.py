from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import BarcodeMaintenanceControl, DeliveryPackageJob
from app.services import local_simulation
from app.services.final_delivery_export import (
    PACKAGE_TTL,
    LeasedDeliveryPackage,
    acquire_delivery_cache_file_lock,
    delivery_evidence_fingerprint,
    group_is_formally_archived,
    reserve_delivery_cache_path,
    validate_delivery_groups,
)


MAX_DELIVERY_PACKAGE_ATTEMPTS = 3
DEFAULT_LEASE_SECONDS = 900
MAX_EXPIRED_DELIVERY_PACKAGE_LEASES = 20


class DeliveryPackageNotReady(RuntimeError):
    def __init__(self, *, job_id: str, status: str):
        self.job_id = job_id
        self.status = status
        super().__init__("Formal delivery package is not ready")


@dataclass(frozen=True)
class DeliveryPackageClaim:
    team_id: str
    job_id: str
    lease_owner: str
    lease_token: str
    evidence_fingerprint: str
    attempt_count: int


def delivery_scope(
    team_id: str,
    *,
    task_id: int | None,
    terminal: str,
    review_scope: str,
) -> tuple[str, str, dict[str, Any]]:
    payload = {
        "task_id": task_id,
        "terminal": terminal.strip(),
        "review_scope": review_scope,
    }
    scope = (
        f"{team_id}|task={task_id or ''}|terminal={payload['terminal']}|"
        f"review_scope={review_scope}"
    )
    return scope, hashlib.sha256(scope.encode("utf-8")).hexdigest(), payload


def delivery_package_advisory_lock_key(team_id: str, scope_hash: str, fingerprint: str) -> int:
    digest = hashlib.sha256(
        f"delivery-package\0{team_id}\0{scope_hash}\0{fingerprint}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def delivery_package_lease_expiry(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def prepare_delivery_request(
    groups: Iterable[Mapping[str, Any]],
    *,
    archived_only: bool,
) -> tuple[list[dict[str, Any]], str, list[str]]:
    candidates = [deepcopy(dict(group)) for group in groups]
    if archived_only:
        candidates = [group for group in candidates if group_is_formally_archived(group)]
    candidates = validate_delivery_groups(candidates)
    fingerprint = delivery_evidence_fingerprint(candidates)
    group_ids = sorted({str(group.get("id") or "") for group in candidates if str(group.get("id") or "")})
    return candidates, fingerprint, group_ids


def _ready_package(
    path_value: Any,
    *,
    evidence_fingerprint: Any,
    content_sha256: Any,
    size_bytes: Any,
    now: datetime | None = None,
) -> LeasedDeliveryPackage | None:
    text = str(path_value or "").strip()
    if not text:
        return None
    cache_root = local_simulation.delivery_cache_root().resolve()
    root = (cache_root / "packages").resolve()
    path = Path(text)
    try:
        candidate = path.resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    file_lock = acquire_delivery_cache_file_lock(
        cache_root,
        candidate,
        blocking=True,
        exclusive=False,
    )
    if file_lock is None:  # pragma: no cover - blocking acquisition returns a lock or raises
        return None
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        stat = resolved.stat()
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        expected_name = f"{str(evidence_fingerprint or '').strip()}.zip"
        expected_sha256 = str(content_sha256 or "").strip().lower()
        try:
            expected_size = int(size_bytes)
        except (TypeError, ValueError):
            expected_size = -1
        if (
            not expected_name.removesuffix(".zip")
            or resolved.name != expected_name
            or stat.st_size <= 0
            or stat.st_size != expected_size
            or current.astimezone(UTC) - modified > PACKAGE_TTL
        ):
            file_lock.release()
            return None
        digest = hashlib.sha256()
        with resolved.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != expected_sha256:
            file_lock.release()
            return None
        lease = reserve_delivery_cache_path(resolved)
        return LeasedDeliveryPackage(resolved, lease, file_lock=file_lock)
    except (FileNotFoundError, OSError, ValueError):
        file_lock.release()
        return None


def request_json_delivery_package(
    *,
    groups: Iterable[Mapping[str, Any]],
    task_id: int | None,
    terminal: str,
    review_scope: str,
    requested_by: str,
) -> LeasedDeliveryPackage:
    team_id = local_simulation.current_team_id()
    _candidates, fingerprint, group_ids = prepare_delivery_request(
        groups,
        archived_only=review_scope == "reviewed",
    )
    scope, scope_hash, scope_payload = delivery_scope(
        team_id,
        task_id=task_id,
        terminal=terminal,
        review_scope=review_scope,
    )
    transaction = local_simulation.begin_authoritative_json_write(team_id)
    token = local_simulation.activate_authoritative_json_write(transaction)
    try:
        jobs = transaction.working_state.setdefault("delivery_package_jobs", [])
        job = next(
            (
                item
                for item in jobs
                if str(item.get("scope_hash") or "") == scope_hash
                and str(item.get("evidence_fingerprint") or "") == fingerprint
            ),
            None,
        )
        if job is not None and str(job.get("status") or "") == "ready":
            package = _ready_package(
                job.get("package_path"),
                evidence_fingerprint=job.get("evidence_fingerprint"),
                content_sha256=job.get("content_sha256"),
                size_bytes=job.get("size_bytes"),
            )
            if package is not None:
                local_simulation.abort_authoritative_json_write(transaction, token)
                return package
        if job is not None and str(job.get("status") or "") not in {"ready", "stale"}:
            status = str(job.get("status") or "pending")
            job_id = str(job.get("id") or "")
            local_simulation.abort_authoritative_json_write(transaction, token)
            raise DeliveryPackageNotReady(job_id=job_id, status=status)
        now = datetime.now(UTC).isoformat()
        if job is None:
            job = {
                "id": str(uuid4()),
                "team_id": team_id,
                "scope": scope,
                "scope_hash": scope_hash,
                "scope_payload": scope_payload,
                "group_ids": group_ids,
                "evidence_fingerprint": fingerprint,
                "attempt_count": 0,
                "created_at": now,
            }
            jobs.append(job)
        if str(job.get("status") or "") not in {"pending", "processing"}:
            job["attempt_count"] = 0
        job.update(
            {
                "status": "pending",
                "scope": scope,
                "scope_payload": scope_payload,
                "group_ids": group_ids,
                "lease_owner": None,
                "lease_token": None,
                "lease_expires_at": None,
                "package_path": None,
                "content_sha256": None,
                "size_bytes": None,
                "requested_by": requested_by,
                "request_reason": "formal_delivery_requested",
                "last_error": "",
                "completed_at": None,
                "updated_at": now,
            }
        )
        local_simulation.finish_authoritative_json_write(transaction, token)
    except BaseException:
        if not transaction.closed:
            local_simulation.abort_authoritative_json_write(transaction, token)
        raise
    raise DeliveryPackageNotReady(job_id=str(job["id"]), status=str(job["status"]))


def request_postgres_delivery_package(
    session: Session,
    *,
    groups: Iterable[Mapping[str, Any]],
    team_id: str,
    task_id: int | None,
    terminal: str,
    review_scope: str,
    requested_by: str,
    auto_commit: bool = True,
) -> LeasedDeliveryPackage:
    _candidates, fingerprint, group_ids = prepare_delivery_request(
        groups,
        archived_only=review_scope == "reviewed",
    )
    _scope, scope_hash, scope_payload = delivery_scope(
        team_id,
        task_id=task_id,
        terminal=terminal,
        review_scope=review_scope,
    )
    lock_key = delivery_package_advisory_lock_key(team_id, scope_hash, fingerprint)
    session.scalar(select(func.pg_advisory_xact_lock(lock_key)))
    job = session.scalar(
        select(DeliveryPackageJob)
        .where(
            DeliveryPackageJob.team_id == team_id,
            DeliveryPackageJob.scope_hash == scope_hash,
            DeliveryPackageJob.evidence_fingerprint == fingerprint,
        )
        .with_for_update()
    )
    if job is not None and job.status == "ready":
        package = _ready_package(
            job.package_path,
            evidence_fingerprint=job.evidence_fingerprint,
            content_sha256=job.content_sha256,
            size_bytes=job.size_bytes,
        )
        if package is not None:
            if auto_commit:
                session.rollback()
            return package
    if job is not None and str(job.status or "") not in {"ready", "stale"}:
        status = str(job.status or "pending")
        job_id = str(job.id)
        if auto_commit:
            session.rollback()
        raise DeliveryPackageNotReady(job_id=job_id, status=status)
    if job is None:
        job = DeliveryPackageJob(
            team_id=team_id,
            scope_hash=scope_hash,
            evidence_fingerprint=fingerprint,
        )
        session.add(job)
    if str(job.status or "") not in {"pending", "processing"}:
        job.attempt_count = 0
    job.scope_payload = scope_payload
    job.group_ids = group_ids
    job.status = "pending"
    job.lease_owner = None
    job.lease_token = None
    job.lease_expires_at = None
    job.package_path = None
    job.content_sha256 = None
    job.size_bytes = None
    job.requested_by = requested_by
    job.request_reason = "formal_delivery_requested"
    job.last_error = None
    job.completed_at = None
    if hasattr(session, "flush"):
        session.flush()
    if auto_commit:
        session.commit()
    raise DeliveryPackageNotReady(job_id=str(job.id), status=job.status)


def build_postgres_delivery_package_claim_statement(*, team_id: str, now: datetime):
    return (
        select(DeliveryPackageJob)
        .where(
            DeliveryPackageJob.team_id == team_id,
            or_(
                DeliveryPackageJob.status == "pending",
                (DeliveryPackageJob.status == "failed")
                & (DeliveryPackageJob.attempt_count < MAX_DELIVERY_PACKAGE_ATTEMPTS),
                (DeliveryPackageJob.status == "processing")
                & (DeliveryPackageJob.attempt_count < MAX_DELIVERY_PACKAGE_ATTEMPTS)
                & (DeliveryPackageJob.lease_expires_at < now),
            ),
        )
        .order_by(DeliveryPackageJob.updated_at, DeliveryPackageJob.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def build_postgres_expired_delivery_package_statement(*, team_id: str, now: datetime):
    return (
        select(DeliveryPackageJob)
        .where(
            DeliveryPackageJob.team_id == team_id,
            DeliveryPackageJob.status == "processing",
            DeliveryPackageJob.attempt_count >= MAX_DELIVERY_PACKAGE_ATTEMPTS,
            DeliveryPackageJob.lease_expires_at < now,
        )
        .order_by(DeliveryPackageJob.lease_expires_at, DeliveryPackageJob.id)
        .limit(MAX_EXPIRED_DELIVERY_PACKAGE_LEASES)
        .with_for_update(skip_locked=True)
    )


def terminalize_expired_postgres_delivery_package_leases(
    session: Session,
    *,
    team_id: str,
    now: datetime,
) -> int:
    jobs = list(
        session.scalars(
            build_postgres_expired_delivery_package_statement(team_id=team_id, now=now)
        ).all()
    )
    for job in jobs:
        job.status = "failed"
        job.lease_owner = None
        job.lease_token = None
        job.lease_expires_at = None
        job.last_error = "delivery package lease expired after maximum attempts"
        job.updated_at = now
    return len(jobs)


def claim_json_delivery_package_job(
    *,
    worker_id: str,
    team_id: str,
    now: datetime,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> DeliveryPackageClaim | None:
    transaction = local_simulation.begin_authoritative_json_write(team_id)
    token = local_simulation.activate_authoritative_json_write(transaction)
    try:
        candidates = []
        terminalized = 0
        for job in transaction.working_state.setdefault("delivery_package_jobs", []):
            status = str(job.get("status") or "")
            attempts = int(job.get("attempt_count") or 0)
            expires_at = delivery_package_lease_expiry(job.get("lease_expires_at"))
            expired = expires_at is not None and expires_at < now.astimezone(UTC)
            if status == "processing" and expired and attempts >= MAX_DELIVERY_PACKAGE_ATTEMPTS:
                job.update(
                    {
                        "status": "failed",
                        "lease_owner": None,
                        "lease_token": None,
                        "lease_expires_at": None,
                        "last_error": "delivery package lease expired after maximum attempts",
                        "updated_at": now.isoformat(),
                    }
                )
                terminalized += 1
                continue
            if (
                status == "pending"
                or (status == "failed" and attempts < MAX_DELIVERY_PACKAGE_ATTEMPTS)
                or (status == "processing" and expired and attempts < MAX_DELIVERY_PACKAGE_ATTEMPTS)
            ):
                candidates.append(job)
        if not candidates:
            if terminalized:
                local_simulation.finish_authoritative_json_write(transaction, token)
            else:
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
                "lease_expires_at": (now + timedelta(seconds=max(1, int(lease_seconds)))).isoformat(),
                "last_error": "",
                "updated_at": now.isoformat(),
            }
        )
        claim = DeliveryPackageClaim(
            team_id=team_id,
            job_id=str(job.get("id") or ""),
            lease_owner=worker_id,
            lease_token=lease_token,
            evidence_fingerprint=str(job.get("evidence_fingerprint") or ""),
            attempt_count=int(job.get("attempt_count") or 0),
        )
        local_simulation.finish_authoritative_json_write(transaction, token)
        return claim
    except BaseException:
        if not transaction.closed:
            local_simulation.abort_authoritative_json_write(transaction, token)
        raise


def claim_postgres_delivery_package_job(
    *,
    worker_id: str,
    team_id: str,
    now: datetime,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> DeliveryPackageClaim | None:
    with SessionLocal() as session:
        control = session.scalar(
            select(BarcodeMaintenanceControl)
            .where(BarcodeMaintenanceControl.team_id == team_id)
            .with_for_update()
        )
        if control is None or control.paused:
            session.rollback()
            return None
        terminalized = terminalize_expired_postgres_delivery_package_leases(
            session,
            team_id=team_id,
            now=now,
        )
        job = session.scalar(build_postgres_delivery_package_claim_statement(team_id=team_id, now=now))
        if job is None:
            if terminalized:
                session.commit()
            else:
                session.rollback()
            return None
        lease_token = str(uuid4())
        job.status = "processing"
        job.attempt_count = int(job.attempt_count or 0) + 1
        job.lease_owner = worker_id
        job.lease_token = lease_token
        job.lease_expires_at = now + timedelta(seconds=max(1, int(lease_seconds)))
        job.last_error = None
        session.commit()
        return DeliveryPackageClaim(
            team_id=team_id,
            job_id=str(job.id),
            lease_owner=worker_id,
            lease_token=lease_token,
            evidence_fingerprint=job.evidence_fingerprint,
            attempt_count=int(job.attempt_count or 0),
        )


def parse_job_uuid(job_id: str) -> UUID:
    try:
        return UUID(job_id)
    except ValueError as exc:
        raise KeyError(job_id) from exc


def _json_job_for_claim(state: dict[str, Any], claim: DeliveryPackageClaim) -> dict[str, Any]:
    job = next(
        (
            item
            for item in state.setdefault("delivery_package_jobs", [])
            if str(item.get("id") or "") == claim.job_id
        ),
        None,
    )
    if job is None:
        raise KeyError(claim.job_id)
    if job.get("lease_owner") != claim.lease_owner or job.get("lease_token") != claim.lease_token:
        raise RuntimeError("Delivery package lease was lost")
    return job


def load_json_delivery_package_scope(claim: DeliveryPackageClaim) -> dict[str, Any]:
    transaction = local_simulation.begin_authoritative_json_write(claim.team_id)
    token = local_simulation.activate_authoritative_json_write(transaction)
    try:
        job = _json_job_for_claim(transaction.working_state, claim)
        scope = deepcopy(dict(job.get("scope_payload") or {}))
        local_simulation.abort_authoritative_json_write(transaction, token)
        return scope
    except BaseException:
        if not transaction.closed:
            local_simulation.abort_authoritative_json_write(transaction, token)
        raise


def load_postgres_delivery_package_scope(claim: DeliveryPackageClaim) -> dict[str, Any]:
    with SessionLocal() as session:
        job = session.scalar(
            select(DeliveryPackageJob).where(
                DeliveryPackageJob.team_id == claim.team_id,
                DeliveryPackageJob.id == parse_job_uuid(claim.job_id),
            )
        )
        if job is None:
            raise KeyError(claim.job_id)
        if job.lease_owner != claim.lease_owner or job.lease_token != claim.lease_token:
            raise RuntimeError("Delivery package lease was lost")
        return deepcopy(dict(job.scope_payload or {}))


def _package_metadata(path: Path, expected_fingerprint: str) -> tuple[str, int]:
    resolved = Path(path).resolve(strict=True)
    if resolved.name.lower() != f"{expected_fingerprint.lower()}.zip":
        raise RuntimeError("Delivery package evidence fingerprint changed while building")
    digest = hashlib.sha256()
    size = 0
    with resolved.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    if size <= 0:
        raise RuntimeError("Delivery package build produced an empty ZIP")
    return digest.hexdigest(), size


def complete_json_delivery_package_job(
    claim: DeliveryPackageClaim,
    package_path: Path,
    *,
    now: datetime | None = None,
) -> None:
    content_sha256, size_bytes = _package_metadata(package_path, claim.evidence_fingerprint)
    completed_at = now or datetime.now(UTC)
    transaction = local_simulation.begin_authoritative_json_write(claim.team_id)
    token = local_simulation.activate_authoritative_json_write(transaction)
    try:
        job = _json_job_for_claim(transaction.working_state, claim)
        job.update(
            {
                "status": "ready",
                "lease_owner": None,
                "lease_token": None,
                "lease_expires_at": None,
                "package_path": str(Path(package_path).resolve()),
                "content_sha256": content_sha256,
                "size_bytes": size_bytes,
                "last_error": "",
                "completed_at": completed_at.isoformat(),
                "updated_at": completed_at.isoformat(),
            }
        )
        local_simulation.finish_authoritative_json_write(transaction, token)
    except BaseException:
        if not transaction.closed:
            local_simulation.abort_authoritative_json_write(transaction, token)
        raise


def complete_postgres_delivery_package_job(
    claim: DeliveryPackageClaim,
    package_path: Path,
    *,
    now: datetime | None = None,
) -> None:
    content_sha256, size_bytes = _package_metadata(package_path, claim.evidence_fingerprint)
    completed_at = now or datetime.now(UTC)
    with SessionLocal() as session:
        job = session.scalar(
            select(DeliveryPackageJob)
            .where(
                DeliveryPackageJob.team_id == claim.team_id,
                DeliveryPackageJob.id == parse_job_uuid(claim.job_id),
            )
            .with_for_update()
        )
        if job is None:
            raise KeyError(claim.job_id)
        if job.lease_owner != claim.lease_owner or job.lease_token != claim.lease_token:
            session.rollback()
            return
        job.status = "ready"
        job.lease_owner = None
        job.lease_token = None
        job.lease_expires_at = None
        job.package_path = str(Path(package_path).resolve())
        job.content_sha256 = content_sha256
        job.size_bytes = size_bytes
        job.last_error = None
        job.completed_at = completed_at
        session.commit()


def fail_json_delivery_package_job(
    claim: DeliveryPackageClaim,
    error: Exception,
    *,
    now: datetime | None = None,
) -> None:
    failed_at = now or datetime.now(UTC)
    transaction = local_simulation.begin_authoritative_json_write(claim.team_id)
    token = local_simulation.activate_authoritative_json_write(transaction)
    try:
        job = _json_job_for_claim(transaction.working_state, claim)
        job.update(
            {
                "status": "failed",
                "lease_owner": None,
                "lease_token": None,
                "lease_expires_at": None,
                "last_error": str(error)[:500],
                "updated_at": failed_at.isoformat(),
            }
        )
        local_simulation.finish_authoritative_json_write(transaction, token)
    except BaseException:
        if not transaction.closed:
            local_simulation.abort_authoritative_json_write(transaction, token)
        raise


def fail_postgres_delivery_package_job(
    claim: DeliveryPackageClaim,
    error: Exception,
    *,
    now: datetime | None = None,
) -> None:
    failed_at = now or datetime.now(UTC)
    with SessionLocal() as session:
        job = session.scalar(
            select(DeliveryPackageJob)
            .where(
                DeliveryPackageJob.team_id == claim.team_id,
                DeliveryPackageJob.id == parse_job_uuid(claim.job_id),
            )
            .with_for_update()
        )
        if job is None:
            raise KeyError(claim.job_id)
        if job.lease_owner != claim.lease_owner or job.lease_token != claim.lease_token:
            session.rollback()
            return
        job.status = "failed"
        job.lease_owner = None
        job.lease_token = None
        job.lease_expires_at = None
        job.last_error = str(error)[:500]
        job.updated_at = failed_at
        session.commit()
