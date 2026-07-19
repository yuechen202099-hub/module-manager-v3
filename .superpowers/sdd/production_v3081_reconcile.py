from __future__ import annotations

import argparse
import copy
import hashlib
import json
from contextlib import contextmanager
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import SessionLocal, engine
from app.models import AuditLog, MaterialGroup, Photo, UnmatchedRecord
from app.services import local_simulation, unmatched_review
from app.services.state_repository import (
    FINALIZATION_REPLAY_KEY,
    PostgresStateRepository,
    _stage_transactional_audit,
    _unmatched_payload,
    get_state_repository,
)


ACTOR = "production-maintenance-v3.0.81"
REPAIR_ACTOR = "production-maintenance-v3.0.82"
REPAIR_ACTION = "unmatched_review_photo_evidence_repaired"
EXPECTED_TARGETS = {
    "scan-unmatched-422f7a0a030a6d41ebbf788a": "g-12102",
    "scan-unmatched-af685ed60b9d412231b51382": "g-12164",
    "scan-unmatched-04b5e41fd8391683e1c57419": "g-12122",
}
_MISSING = object()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def activate_team(raw_team_id: str) -> tuple[Any, str]:
    require(bool(str(raw_team_id or "").strip()), "ADMIN_TEAM_ID is empty")
    token = local_simulation.set_current_team(raw_team_id)
    return token, local_simulation.current_team_id()


def collect_migrated_photo_ids(photos: list[Photo] | list[Any]) -> set[str]:
    evidence: set[str] = set()
    for photo in photos:
        direct = str(getattr(photo, "source_fingerprint", "") or "").strip()
        merged = str((getattr(photo, "raw_data", None) or {}).get("source_fingerprint") or "").strip()
        if direct:
            evidence.add(direct)
        if merged:
            evidence.add(merged)
    return evidence


def _identity_hash(*parts: str) -> str:
    value = "\0".join(str(part or "").strip() for part in parts)
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value.strip("\0") else ""


def build_review_photo_evidence(photos: list[dict[str, Any]]) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    for photo in photos:
        photo_id = str(photo.get("id") or "").strip()
        source_url = str(
            photo.get("source_url")
            or photo.get("image_url")
            or photo.get("url")
            or ""
        )
        normalized_source_url = local_simulation.normalized_photo_source_url(source_url)
        storage_type = str(photo.get("storage_type") or "").strip()
        storage_key = str(photo.get("storage_key") or "").strip()
        evidence.append(
            {
                "id": photo_id,
                "sha256": str(photo.get("sha256") or "").strip(),
                "storage_identity_hash": (
                    _identity_hash(storage_type, storage_key)
                    if storage_type and storage_key
                    else ""
                ),
                "source_url_hash": _identity_hash(normalized_source_url),
            }
        )
    return evidence


def unique_review_photo_source_count(evidence: list[dict[str, str]]) -> int:
    identities = {
        next(
            (
                value
                for value in (
                    f"sha256:{item.get('sha256')}" if item.get("sha256") else "",
                    (
                        f"storage:{item.get('storage_identity_hash')}"
                        if item.get("storage_identity_hash")
                        else ""
                    ),
                    f"url:{item.get('source_url_hash')}" if item.get("source_url_hash") else "",
                    f"id:{item.get('id')}" if item.get("id") else "",
                )
                if value
            ),
            "",
        )
        for item in evidence
    }
    identities.discard("")
    return len(identities)


def matched_review_photo_ids(
    photos: list[Photo] | list[Any],
    evidence: list[dict[str, str]],
) -> set[str]:
    migrated_ids = collect_migrated_photo_ids(photos)
    sha256_values = {
        str(getattr(photo, "sha256", "") or "").strip()
        for photo in photos
        if str(getattr(photo, "sha256", "") or "").strip()
    }
    storage_identities = {
        _identity_hash(
            str(getattr(photo, "storage_type", "") or ""),
            str(getattr(photo, "storage_key", "") or ""),
        )
        for photo in photos
        if str(getattr(photo, "storage_type", "") or "").strip()
        and str(getattr(photo, "storage_key", "") or "").strip()
    }
    source_url_hashes = {
        str(getattr(photo, "source_url_hash", "") or "").strip()
        for photo in photos
        if str(getattr(photo, "source_url_hash", "") or "").strip()
    }
    source_url_hashes.update(
        _identity_hash(
            local_simulation.normalized_photo_source_url(
                str(
                    getattr(photo, "source_url", "")
                    or getattr(photo, "image_url", "")
                    or ""
                )
            )
        )
        for photo in photos
        if str(
            getattr(photo, "source_url", "")
            or getattr(photo, "image_url", "")
            or ""
        ).strip()
    )
    matched: set[str] = set()
    for item in evidence:
        photo_id = str(item.get("id") or "")
        if not photo_id:
            continue
        if (
            photo_id in migrated_ids
            or (item.get("sha256") and item["sha256"] in sha256_values)
            or (
                item.get("storage_identity_hash")
                and item["storage_identity_hash"] in storage_identities
            )
            or (
                item.get("source_url_hash")
                and item["source_url_hash"] in source_url_hashes
            )
        ):
            matched.add(photo_id)
    return matched


def physical_source_matched_review_photo_ids(
    photos: list[Photo] | list[Any],
    evidence: list[dict[str, str]],
) -> set[str]:
    source_url_hashes: set[str] = set()
    for photo in photos:
        source_url = str(
            getattr(photo, "source_url", "")
            or getattr(photo, "image_url", "")
            or ""
        ).strip()
        source_url_hash = (
            _identity_hash(local_simulation.normalized_photo_source_url(source_url))
            if source_url
            else str(getattr(photo, "source_url_hash", "") or "").strip()
        )
        if source_url_hash:
            source_url_hashes.add(source_url_hash)
    return {
        str(item.get("id") or "")
        for item in evidence
        if str(item.get("id") or "")
        and str(item.get("source_url_hash") or "") in source_url_hashes
    }


def canonicalize_surviving_photo_identity(
    photo: Photo | Any,
    group: MaterialGroup | Any,
    migrated_row: dict[str, Any],
) -> None:
    legacy_id = str(migrated_row.get("id") or "").strip()
    require(legacy_id, "canonical migrated photo legacy id is empty")
    image_url = str(migrated_row.get("url") or migrated_row.get("image_url") or "").strip()
    source_url = str(migrated_row.get("source_url") or image_url)
    normalized_source_url = local_simulation.normalized_photo_source_url(source_url)
    source_url_hash = _identity_hash(normalized_source_url)
    sha256 = str(migrated_row.get("sha256") or "").strip() or _identity_hash(image_url)
    fingerprint_seed = "|".join(
        [
            str(getattr(group, "legacy_id", "") or getattr(group, "id", "") or ""),
            str(migrated_row.get("client_photo_id") or ""),
            str(migrated_row.get("source_fingerprint") or ""),
            normalized_source_url,
        ]
    )
    source_fingerprint = str(
        migrated_row.get("source_fingerprint")
        or hashlib.sha256(fingerprint_seed.encode("utf-8")).hexdigest()[:32]
    )
    storage_type = str(migrated_row.get("storage_type") or "").strip()
    storage_bucket = str(migrated_row.get("storage_bucket") or "").strip()
    storage_key = str(migrated_row.get("storage_key") or "").strip()
    category = str(
        migrated_row.get("slot")
        or migrated_row.get("category")
        or "unclassified"
    )

    raw_payload = dict(getattr(photo, "raw_data", None) or {})
    unmatched_review.merge_migrated_photo_evidence(raw_payload, migrated_row)
    photo.legacy_id = legacy_id
    photo.source_fingerprint = source_fingerprint
    photo.raw_data = raw_payload
    photo.source_url = source_url
    photo.source_url_hash = source_url_hash
    photo.image_url = image_url
    photo.sha256 = sha256
    photo.category = category
    photo.storage_type = storage_type
    photo.storage_bucket = storage_bucket
    photo.storage_key = storage_key
    photo.object_key = storage_key or image_url or str(getattr(photo, "legacy_id", "") or "")
    photo.source_file_id = str(migrated_row.get("source_file_id") or "")
    photo.original_filename = str(migrated_row.get("filename") or "")
    photo.content_type = str(migrated_row.get("content_type") or "")
    if hasattr(photo, "image_file_id"):
        photo.image_file_id = str(migrated_row.get("image_file_id") or "")


def _restore_instance_attribute(target: Any, name: str, previous: Any) -> None:
    if previous is _MISSING:
        target.__dict__.pop(name, None)
    else:
        setattr(target, name, previous)


@contextmanager
def repository_commit_guard(
    repository: PostgresStateRepository | Any,
    *,
    bind=engine,
):
    connection = bind.connect()
    if connection.dialect.name == "postgresql":
        connection = connection.execution_options(isolation_level="REPEATABLE READ")
    outer_transaction = connection.begin()
    previous_session = repository.__dict__.get("_session", _MISSING)

    def guarded_session() -> Session:
        return Session(
            bind=connection,
            autoflush=False,
            expire_on_commit=False,
            join_transaction_mode="rollback_only",
        )

    repository._session = guarded_session
    try:
        yield connection
        require(
            outer_transaction.is_active and connection.in_transaction(),
            "repository commit escaped the maintenance transaction",
        )
        outer_transaction.commit()
    except Exception:
        if outer_transaction.is_active:
            outer_transaction.rollback()
        raise
    finally:
        _restore_instance_attribute(repository, "_session", previous_session)
        connection.close()


@contextmanager
def strict_candidate_resolution(
    repository: PostgresStateRepository | Any,
    *,
    expected_candidate_key: str,
    expected_target_group_id: str,
):
    previous_resolver = repository.__dict__.get("_resolve_unmatched_candidate", _MISSING)

    def resolve(session: Session, record: UnmatchedRecord, review: dict[str, Any], candidate_key: str):
        require(candidate_key == expected_candidate_key, "candidate key changed before finalization")
        candidates = repository._unmatched_match_candidates_for_session(session, record, review)
        require(len(candidates) == 1, f"candidate count is not one inside transaction: {len(candidates)}")
        candidate = dict(candidates[0])
        require(
            str(candidate.get("candidate_key") or "") == expected_candidate_key,
            "candidate key changed inside transaction",
        )
        require(bool(candidate.get("has_existing_group")), "candidate has no existing group inside transaction")
        require(
            str(candidate.get("target_group_id") or "") == expected_target_group_id,
            f"candidate target changed inside transaction: {candidate.get('target_group_id')}",
        )
        return candidate

    repository._resolve_unmatched_candidate = resolve
    try:
        yield
    finally:
        _restore_instance_attribute(repository, "_resolve_unmatched_candidate", previous_resolver)


def _placeholder_group_count(session: Session, team_id: str) -> int:
    terminal = func.btrim(func.coalesce(MaterialGroup.terminal, ""))
    legacy_id = func.lower(func.btrim(func.coalesce(MaterialGroup.legacy_id, "")))
    return int(
        session.scalar(
            select(func.count(MaterialGroup.id)).where(
                MaterialGroup.team_id == team_id,
                or_(
                    terminal == "",
                    terminal == "00000000",
                    legacy_id.like("manual-%"),
                    legacy_id.like("unmatched-%"),
                ),
            )
        )
        or 0
    )


def placeholder_group_count(team_id: str) -> int:
    with SessionLocal() as session:
        return _placeholder_group_count(session, team_id)


def _group_count(session: Session, team_id: str) -> int:
    return int(
        session.scalar(
            select(func.count(MaterialGroup.id)).where(MaterialGroup.team_id == team_id)
        )
        or 0
    )


def group_count(team_id: str) -> int:
    with SessionLocal() as session:
        return _group_count(session, team_id)


def _target_snapshot(session: Session, team_id: str, group_id: str) -> dict[str, Any]:
    group = session.scalar(
        select(MaterialGroup).where(
            MaterialGroup.team_id == team_id,
            MaterialGroup.legacy_id == group_id,
        )
    )
    require(group is not None, f"target group is missing: {group_id}")
    active_photos = int(
        session.scalar(
            select(func.count(Photo.id)).where(
                Photo.team_id == team_id,
                Photo.group_id == group.id,
                Photo.is_active.is_(True),
            )
        )
        or 0
    )
    return {
        "db_id": str(group.id),
        "group_id": str(group.legacy_id or group.id),
        "terminal": str(group.terminal or ""),
        "meter_match_key": str(group.meter_match_key or ""),
        "photo_count": active_photos,
        "project_id": str(group.project_id),
    }


def target_snapshot(team_id: str, group_id: str) -> dict[str, Any]:
    with SessionLocal() as session:
        return _target_snapshot(session, team_id, group_id)


def dry_run_record(
    repository: PostgresStateRepository,
    team_id: str,
    unmatched_id: str,
) -> dict[str, Any]:
    expected_target = EXPECTED_TARGETS[unmatched_id]
    payload = repository.get_unmatched_review(unmatched_id)
    record = dict(payload.get("record") or {})
    review = dict(payload.get("review") or {})
    candidates_payload = repository.list_unmatched_match_candidates(unmatched_id)
    candidates = list(candidates_payload.get("items") or [])

    require(str(record.get("status") or "") == "open", f"record is not open: {unmatched_id}")
    require(bool(review.get("manual_confirmed")), f"record is not manually confirmed: {unmatched_id}")
    require(len(candidates) == 1, f"candidate count is not one: {unmatched_id} -> {len(candidates)}")
    candidate = dict(candidates[0])
    require(bool(candidate.get("has_existing_group")), f"candidate has no existing group: {unmatched_id}")
    require(
        str(candidate.get("target_group_id") or "") == expected_target,
        f"candidate target changed: {unmatched_id} -> {candidate.get('target_group_id')}",
    )
    require(str(candidate.get("candidate_key") or "").startswith("candidate:"), "candidate key is not opaque")
    require(int(review.get("version") or 0) > 0, f"invalid review version: {unmatched_id}")

    target = target_snapshot(team_id, expected_target)
    require(target["terminal"] == str(candidate.get("terminal") or ""), "target terminal conflict")
    require(target["meter_match_key"] == str(candidate.get("meter_match_key") or ""), "target meter key conflict")

    review_photo_ids = sorted(
        {
            str(photo.get("id") or "")
            for photo in review.get("photos") or []
            if str(photo.get("id") or "")
        }
    )
    require(bool(review_photo_ids), f"review has no photo evidence: {unmatched_id}")
    review_photo_evidence = build_review_photo_evidence(
        [dict(photo) for photo in review.get("photos") or [] if str(photo.get("id") or "")]
    )
    require(
        len(review_photo_evidence) == len(review_photo_ids),
        f"review photo evidence is ambiguous: {unmatched_id}",
    )
    return {
        "unmatched_id": unmatched_id,
        "status": "open",
        "manual_confirmed": True,
        "expected_version": int(review.get("version") or 0),
        "candidate_count": 1,
        "candidate_key": str(candidate.get("candidate_key") or ""),
        "target_group_id": expected_target,
        "terminal": str(candidate.get("terminal") or ""),
        "meter_match_key": str(candidate.get("meter_match_key") or ""),
        "has_existing_group": True,
        "review_photo_ids": review_photo_ids,
        "review_photo_count": len(review_photo_ids),
        "review_photo_evidence": review_photo_evidence,
        "unique_review_photo_source_count": unique_review_photo_source_count(review_photo_evidence),
        "target_before": target,
    }


def associated_snapshot(team_id: str, unmatched_id: str) -> dict[str, Any] | None:
    expected_target = EXPECTED_TARGETS[unmatched_id]
    with SessionLocal() as session:
        record = session.scalar(
            select(UnmatchedRecord).where(
                UnmatchedRecord.team_id == team_id,
                UnmatchedRecord.legacy_id == unmatched_id,
            )
        )
        require(record is not None, f"record disappeared: {unmatched_id}")
        if record.status != "associated":
            return None
        payload = dict(record.payload or {})
        require(payload.get("associated_group_id") == expected_target, "associated group mismatch")
        require(payload.get("associated_by") == ACTOR, "associated actor mismatch")
        replay = dict(payload.get(FINALIZATION_REPLAY_KEY) or {})
        candidate_key = str(replay.get("candidate_key") or "")
        expected_version = int(replay.get("expected_version") or 0)
        replay_result = dict(replay.get("result") or {})
        require(candidate_key.startswith("candidate:"), "associated replay candidate key is missing")
        require(expected_version > 0, "associated replay version is missing")
        require(bool(replay_result.get("attached")), "associated replay did not attach")
        require(
            str((replay_result.get("group") or {}).get("id") or "") == expected_target,
            "associated replay target mismatch",
        )
        review = dict(payload.get("temporary_review") or {})
        require(bool(review.get("manual_confirmed")), "temporary review evidence was not retained")
        review_photo_ids = sorted(
            {
                str(photo.get("id") or "")
                for photo in review.get("photos") or []
                if str(photo.get("id") or "")
            }
        )
        require(bool(review_photo_ids), f"associated review has no photo evidence: {unmatched_id}")
        review_photo_evidence = build_review_photo_evidence(
            [dict(photo) for photo in review.get("photos") or [] if str(photo.get("id") or "")]
        )
        require(
            len(review_photo_evidence) == len(review_photo_ids),
            f"associated review photo evidence is ambiguous: {unmatched_id}",
        )
        target = _target_snapshot(session, team_id, expected_target)
        return {
            "unmatched_id": unmatched_id,
            "status": "associated",
            "manual_confirmed": True,
            "expected_version": expected_version,
            "candidate_count": 1,
            "candidate_key": candidate_key,
            "target_group_id": expected_target,
            "terminal": target["terminal"],
            "meter_match_key": target["meter_match_key"],
            "has_existing_group": True,
            "review_photo_ids": review_photo_ids,
            "review_photo_count": len(review_photo_ids),
            "review_photo_evidence": review_photo_evidence,
            "unique_review_photo_source_count": unique_review_photo_source_count(review_photo_evidence),
            "target_before": target,
        }


def verify_associated_in_session(
    session: Session,
    team_id: str,
    snapshot: dict[str, Any],
    *,
    groups_before: int | None,
    placeholders_before: int | None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    unmatched_id = str(snapshot["unmatched_id"])
    target_group_id = str(snapshot["target_group_id"])
    review_photo_ids = list(snapshot["review_photo_ids"])
    review_photo_evidence = list(snapshot["review_photo_evidence"])
    require(bool(review_photo_ids), f"review has no photo evidence: {unmatched_id}")

    record = session.scalar(
        select(UnmatchedRecord).where(
            UnmatchedRecord.team_id == team_id,
            UnmatchedRecord.legacy_id == unmatched_id,
        )
    )
    require(record is not None, f"record disappeared: {unmatched_id}")
    require(record.status == "associated", f"record was not associated: {unmatched_id}")
    payload = dict(record.payload or {})
    require(payload.get("associated_group_id") == target_group_id, "associated group mismatch")
    require(payload.get("associated_by") == ACTOR, "associated actor mismatch")
    temporary_review = dict(payload.get("temporary_review") or {})
    require(bool(temporary_review.get("manual_confirmed")), "temporary review evidence was not retained")

    replay = dict(payload.get(FINALIZATION_REPLAY_KEY) or {})
    require(replay.get("candidate_key") == snapshot["candidate_key"], "finalization replay candidate mismatch")
    require(replay.get("expected_version") == snapshot["expected_version"], "finalization replay version mismatch")

    group = session.scalar(
        select(MaterialGroup).where(
            MaterialGroup.team_id == team_id,
            MaterialGroup.legacy_id == target_group_id,
        )
    )
    require(group is not None, f"associated target is missing: {target_group_id}")
    require(str(group.id) == str(snapshot["target_before"]["db_id"]), "associated target row changed")
    require((group.raw_data or {}).get("source_unmatched_id") == unmatched_id, "group source evidence mismatch")
    require(str(group.terminal or "") == str(snapshot["terminal"]), "group terminal changed")
    require(str(group.meter_match_key or "") == str(snapshot["meter_match_key"]), "group meter key changed")

    active_photos = list(
        session.scalars(
            select(Photo).where(
                Photo.team_id == team_id,
                Photo.group_id == group.id,
                Photo.is_active.is_(True),
            )
        ).all()
    )
    migrated_fingerprints = matched_review_photo_ids(active_photos, review_photo_evidence)
    require(
        set(review_photo_ids).issubset(migrated_fingerprints),
        "not all review photo evidence migrated",
    )

    audit_rows = list(
        session.scalars(
            select(AuditLog).where(
                AuditLog.team_id == team_id,
                AuditLog.entity_id == record.id,
                AuditLog.actor_username == ACTOR,
                AuditLog.action == "unmatched_review_finalized",
            )
        ).all()
    )
    matching_audits = [
        audit
        for audit in audit_rows
        if int((audit.before_data or {}).get("review_version") or 0) == int(snapshot["expected_version"])
        and str((audit.after_data or {}).get("group_id") or "") == target_group_id
        and str((audit.after_data or {}).get("terminal") or "") == str(snapshot["terminal"])
        and str((audit.payload or {}).get("candidate_key") or "") == str(snapshot["candidate_key"])
        and bool((audit.payload or {}).get("attached"))
    ]
    require(len(matching_audits) == 1, f"exact finalization audit count is not one: {len(matching_audits)}")
    audit = matching_audits[0]

    duplicate_count = int(
        session.scalar(
            select(func.count(MaterialGroup.id)).where(
                MaterialGroup.project_id == group.project_id,
                MaterialGroup.meter_match_key == group.meter_match_key,
            )
        )
        or 0
    )
    require(duplicate_count == 1, "duplicate formal group identity detected")

    if result is not None:
        require(bool(result.get("attached")), "finalization did not attach to the existing group")
        require(
            str((result.get("group") or {}).get("id") or "") == target_group_id,
            "finalization returned an unexpected group",
        )

    groups_after = _group_count(session, team_id)
    placeholders_after = _placeholder_group_count(session, team_id)
    if groups_before is not None:
        require(groups_after == groups_before, "formal group count changed while attaching existing group")
    if placeholders_before is not None:
        require(placeholders_before == 0, "placeholder formal groups exist before finalization")
    require(placeholders_after == 0, "placeholder formal group count is not zero")
    target_after = _target_snapshot(session, team_id, target_group_id)
    return {
        "unmatched_id": unmatched_id,
        "status": "associated",
        "target_group_id": target_group_id,
        "attached": True,
        "manual_confirmed": True,
        "candidate_key": str(snapshot["candidate_key"]),
        "expected_version": int(snapshot["expected_version"]),
        "review_photo_ids": review_photo_ids,
        "migrated_review_photo_count": len(review_photo_ids),
        "migrated_photo_evidence_ids": sorted(migrated_fingerprints),
        "unique_review_photo_source_count": int(snapshot["unique_review_photo_source_count"]),
        "target_photo_count_before": int(snapshot["target_before"]["photo_count"]),
        "target_photo_count_after": int(target_after["photo_count"]),
        "audit_id": str(audit.id),
        "audit_legacy_id": str(audit.legacy_id or ""),
        "audit_created_at": audit.created_at.isoformat() if audit.created_at else "",
        "duplicate_group_count": duplicate_count,
        "group_count_before": groups_before,
        "group_count_after": groups_after,
        "placeholder_count_before": placeholders_before,
        "placeholder_count_after": placeholders_after,
    }


def matching_repair_audits(
    session: Session,
    *,
    team_id: str,
    record_id: Any,
    unmatched_id: str,
    target_group_id: str,
) -> list[AuditLog]:
    rows = list(
        session.scalars(
            select(AuditLog).where(
                AuditLog.team_id == team_id,
                AuditLog.entity_id == record_id,
                AuditLog.actor_username == REPAIR_ACTOR,
                AuditLog.action == REPAIR_ACTION,
            )
        ).all()
    )
    return [
        row
        for row in rows
        if str((row.before_data or {}).get("unmatched_id") or "") == unmatched_id
        and str((row.after_data or {}).get("group_id") or "") == target_group_id
        and int((row.after_data or {}).get("active_photo_count") or 0) == 4
        and int((row.payload or {}).get("review_photo_count") or 0) == 4
    ]


def repair_dry_run_record(team_id: str, unmatched_id: str) -> dict[str, Any]:
    snapshot = associated_snapshot(team_id, unmatched_id)
    require(snapshot is not None, f"record is not associated: {unmatched_id}")
    require(
        int(snapshot["unique_review_photo_source_count"]) == len(snapshot["review_photo_ids"]),
        f"review does not contain distinct physical photo evidence: {unmatched_id}",
    )
    with SessionLocal() as session:
        record = session.scalar(
            select(UnmatchedRecord).where(
                UnmatchedRecord.team_id == team_id,
                UnmatchedRecord.legacy_id == unmatched_id,
            )
        )
        require(record is not None, f"record disappeared: {unmatched_id}")
        group = session.scalar(
            select(MaterialGroup).where(
                MaterialGroup.team_id == team_id,
                MaterialGroup.legacy_id == snapshot["target_group_id"],
            )
        )
        require(group is not None, f"associated target is missing: {snapshot['target_group_id']}")
        active_photos = list(
            session.scalars(
                select(Photo).where(
                    Photo.team_id == team_id,
                    Photo.group_id == group.id,
                    Photo.is_active.is_(True),
                )
            ).all()
        )
        matched = matched_review_photo_ids(active_photos, list(snapshot["review_photo_evidence"]))
        physical_source_matched = physical_source_matched_review_photo_ids(
            active_photos,
            list(snapshot["review_photo_evidence"]),
        )
        legacy_alias_missing = sorted(set(snapshot["review_photo_ids"]) - matched)
        physical_source_missing = sorted(
            set(snapshot["review_photo_ids"]) - physical_source_matched
        )
        audits = matching_repair_audits(
            session,
            team_id=team_id,
            record_id=record.id,
            unmatched_id=unmatched_id,
            target_group_id=str(snapshot["target_group_id"]),
        )
        return {
            "unmatched_id": unmatched_id,
            "target_group_id": str(snapshot["target_group_id"]),
            "review_photo_count": len(snapshot["review_photo_ids"]),
            "unique_review_photo_source_count": int(snapshot["unique_review_photo_source_count"]),
            "active_photo_count": len(active_photos),
            "historical_alias_matched_review_photo_count": len(matched),
            "historical_alias_missing_review_photo_count": len(legacy_alias_missing),
            "historical_alias_missing_review_photo_ids": legacy_alias_missing,
            "physical_source_matched_review_photo_count": len(physical_source_matched),
            "physical_source_missing_review_photo_count": len(physical_source_missing),
            "physical_source_missing_review_photo_ids": physical_source_missing,
            "repair_audit_count": len(audits),
        }


def repair_associated_photo_evidence(
    repository: PostgresStateRepository,
    team_id: str,
    unmatched_id: str,
) -> dict[str, Any]:
    snapshot = associated_snapshot(team_id, unmatched_id)
    require(snapshot is not None, f"record is not associated: {unmatched_id}")
    review_photo_ids = set(snapshot["review_photo_ids"])
    require(len(review_photo_ids) == 4, f"review photo count is not four: {unmatched_id}")
    require(
        int(snapshot["unique_review_photo_source_count"]) == len(review_photo_ids),
        f"review does not contain four distinct physical photos: {unmatched_id}",
    )
    groups_before = group_count(team_id)
    placeholders_before = placeholder_group_count(team_id)
    require(placeholders_before == 0, "placeholder formal groups exist before photo repair")

    with repository_commit_guard(repository) as connection:
        session = Session(
            bind=connection,
            autoflush=False,
            expire_on_commit=False,
            join_transaction_mode="rollback_only",
        )
        try:
            record = session.scalar(
                select(UnmatchedRecord)
                .where(
                    UnmatchedRecord.team_id == team_id,
                    UnmatchedRecord.legacy_id == unmatched_id,
                )
                .with_for_update()
            )
            require(record is not None, f"record disappeared: {unmatched_id}")
            require(record.status == "associated", f"record is not associated: {unmatched_id}")
            payload = dict(record.payload or {})
            target_group_id = str(snapshot["target_group_id"])
            require(payload.get("associated_group_id") == target_group_id, "associated group mismatch")
            require(payload.get("associated_by") == ACTOR, "associated actor mismatch")
            group = session.scalar(
                select(MaterialGroup)
                .where(
                    MaterialGroup.team_id == team_id,
                    MaterialGroup.legacy_id == target_group_id,
                )
                .with_for_update()
            )
            require(group is not None, f"associated target is missing: {target_group_id}")
            require(str(group.id) == str(snapshot["target_before"]["db_id"]), "associated target row changed")
            active_before = list(
                session.scalars(
                    select(Photo)
                    .where(
                        Photo.team_id == team_id,
                        Photo.group_id == group.id,
                        Photo.is_active.is_(True),
                    )
                    .with_for_update()
                ).all()
            )
            broad_matched_before = matched_review_photo_ids(
                active_before,
                list(snapshot["review_photo_evidence"]),
            )
            physical_source_matched_before = physical_source_matched_review_photo_ids(
                active_before,
                list(snapshot["review_photo_evidence"]),
            )
            physical_source_missing_before = review_photo_ids - physical_source_matched_before
            repair_audits = matching_repair_audits(
                session,
                team_id=team_id,
                record_id=record.id,
                unmatched_id=unmatched_id,
                target_group_id=target_group_id,
            )
            replayed = physical_source_matched_before == review_photo_ids
            add_result: dict[str, Any] = {
                "added": 0,
                "skipped_duplicates": 0,
                "merged_duplicates": 0,
            }
            repair_audit: AuditLog
            if replayed:
                require(len(active_before) == 4, "replayed photo repair count is not four")
                require(len(repair_audits) == 1, f"exact photo repair audit count is not one: {len(repair_audits)}")
                repair_audit = repair_audits[0]
            else:
                require(
                    len(physical_source_matched_before) == 1,
                    "physical-source matched review photo count is not one: "
                    f"{len(physical_source_matched_before)}",
                )
                require(len(active_before) == 1, f"unexpected pre-repair photo count: {len(active_before)}")
                require(
                    len(physical_source_missing_before) == 3,
                    f"unexpected missing physical-source evidence count: {len(physical_source_missing_before)}",
                )
                require(not repair_audits, "photo repair audit exists before repair")
                review = unmatched_review.build_review(_unmatched_payload(record))
                migrated_photo_rows = unmatched_review.migrate_review_to_photo_rows(review)
                require(len(migrated_photo_rows) == 4, "photo repair migration did not produce exactly four rows")
                canonical_review_photo_id = next(iter(physical_source_matched_before))
                canonical_rows = [
                    row
                    for row in migrated_photo_rows
                    if str(row.get("source_fingerprint") or "") == canonical_review_photo_id
                ]
                require(
                    len(canonical_rows) == 1,
                    "physical-source canonical migration row count is not one: "
                    f"{len(canonical_rows)}",
                )
                canonicalize_surviving_photo_identity(
                    active_before[0],
                    group,
                    copy.deepcopy(canonical_rows[0]),
                )
                session.flush()
                add_result = repository._add_photo_records_to_group(
                    session,
                    group,
                    actor=REPAIR_ACTOR,
                    photos=migrated_photo_rows,
                    collector=str(review.get("collector") or ""),
                    module_asset_no=str(review.get("module_asset_no") or ""),
                    creator=str(review.get("reviewer") or REPAIR_ACTOR),
                    source="unmatched-review-finalize",
                )
                require(int(add_result.get("added") or 0) == 3, "photo repair did not add exactly three photos")
                repair_audit = _stage_transactional_audit(
                    session,
                    team_id=team_id,
                    actor=REPAIR_ACTOR,
                    action=REPAIR_ACTION,
                    entity_type="unmatched_record",
                    entity_id=record.id,
                    before_data={
                        "unmatched_id": unmatched_id,
                        "group_id": target_group_id,
                        "active_photo_count": len(active_before),
                    },
                    after_data={
                        "unmatched_id": unmatched_id,
                        "group_id": target_group_id,
                        "active_photo_count": 4,
                    },
                    payload={
                        "review_photo_count": len(review_photo_ids),
                        "added_photo_count": int(add_result.get("added") or 0),
                        "merged_duplicate_count": int(add_result.get("merged_duplicates") or 0),
                    },
                )
                session.flush()

            transaction_evidence = verify_associated_in_session(
                session,
                team_id,
                snapshot,
                groups_before=groups_before,
                placeholders_before=placeholders_before,
            )
            require(transaction_evidence["target_photo_count_after"] == 4, "photo repair count is not four")
            active_after = list(
                session.scalars(
                    select(Photo).where(
                        Photo.team_id == team_id,
                        Photo.group_id == group.id,
                        Photo.is_active.is_(True),
                    )
                ).all()
            )
            require(len(active_after) == 4, "photo repair active photo count is not four")
            require(
                physical_source_matched_review_photo_ids(
                    active_after,
                    list(snapshot["review_photo_evidence"]),
                )
                == review_photo_ids,
                "not all review physical source identities migrated",
            )
            require(
                len(
                    matching_repair_audits(
                        session,
                        team_id=team_id,
                        record_id=record.id,
                        unmatched_id=unmatched_id,
                        target_group_id=target_group_id,
                    )
                )
                == 1,
                "photo repair audit was not persisted exactly once",
            )
            repair_evidence = {
                **transaction_evidence,
                "repair_actor": REPAIR_ACTOR,
                "repair_audit_id": str(repair_audit.id),
                "repair_audit_legacy_id": str(repair_audit.legacy_id or ""),
                "repair_replayed": replayed,
                "repair_added_photo_count": int(add_result.get("added") or 0),
                "repair_merged_duplicate_count": int(add_result.get("merged_duplicates") or 0),
                "repair_broad_matched_review_photo_count_before": len(broad_matched_before),
                "repair_physical_source_matched_review_photo_count_before": len(
                    physical_source_matched_before
                ),
            }
        finally:
            session.close()

    post_commit_repair_verified = False
    try:
        with SessionLocal() as session:
            post_commit_evidence = verify_associated_in_session(
                session,
                team_id,
                snapshot,
                groups_before=None,
                placeholders_before=None,
            )
            post_commit_repair_verified = post_commit_evidence["target_photo_count_after"] == 4
    except Exception:
        # The guarded transaction already enforced every release invariant.
        post_commit_repair_verified = False
    return {**repair_evidence, "post_commit_repair_verified": post_commit_repair_verified}


def apply_record(
    repository: PostgresStateRepository,
    team_id: str,
    unmatched_id: str,
) -> dict[str, Any]:
    replay_snapshot = associated_snapshot(team_id, unmatched_id)
    if replay_snapshot is not None:
        with SessionLocal() as session:
            replay_evidence = verify_associated_in_session(
                session,
                team_id,
                replay_snapshot,
                groups_before=None,
                placeholders_before=None,
            )
        return {**replay_evidence, "replayed": True, "post_commit_verified": True}

    snapshot = dry_run_record(repository, team_id, unmatched_id)
    groups_before = group_count(team_id)
    placeholders_before = placeholder_group_count(team_id)
    require(placeholders_before == 0, "placeholder formal groups exist before finalization")
    with repository_commit_guard(repository) as connection:
        with strict_candidate_resolution(
            repository,
            expected_candidate_key=str(snapshot["candidate_key"]),
            expected_target_group_id=str(snapshot["target_group_id"]),
        ):
            result = repository.finalize_unmatched_match(
                unmatched_id,
                actor=ACTOR,
                candidate_key=str(snapshot["candidate_key"]),
                expected_version=int(snapshot["expected_version"]),
            )
        verification_session = Session(
            bind=connection,
            autoflush=False,
            expire_on_commit=False,
            join_transaction_mode="rollback_only",
        )
        try:
            transaction_evidence = verify_associated_in_session(
                verification_session,
                team_id,
                snapshot,
                groups_before=groups_before,
                placeholders_before=placeholders_before,
                result=result,
            )
        finally:
            verification_session.close()

    with SessionLocal() as session:
        verify_associated_in_session(
            session,
            team_id,
            snapshot,
            groups_before=None,
            placeholders_before=None,
            result=result,
        )
    return {**transaction_evidence, "replayed": False, "post_commit_verified": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--apply", choices=sorted(EXPECTED_TARGETS))
    actions.add_argument("--repair-photos", choices=sorted(EXPECTED_TARGETS))
    actions.add_argument("--repair-dry-run", action="store_true")
    args = parser.parse_args()

    repository = get_state_repository()
    require(isinstance(repository, PostgresStateRepository), "production repository is not PostgreSQL")
    token, team_id = activate_team(str(settings.admin_team_id or ""))
    try:
        if args.repair_photos:
            output = {
                "mode": "repair-photos-one",
                "actor": REPAIR_ACTOR,
                "team_id": team_id,
                "result": repair_associated_photo_evidence(
                    repository,
                    team_id,
                    args.repair_photos,
                ),
            }
        elif args.repair_dry_run:
            placeholders = placeholder_group_count(team_id)
            require(placeholders == 0, "placeholder formal groups exist before repair dry-run")
            output = {
                "mode": "repair-dry-run",
                "team_id": team_id,
                "group_count": group_count(team_id),
                "placeholder_group_count": placeholders,
                "records": [
                    repair_dry_run_record(team_id, unmatched_id)
                    for unmatched_id in EXPECTED_TARGETS
                ],
            }
        elif args.apply:
            output = {
                "mode": "apply-one",
                "actor": ACTOR,
                "team_id": team_id,
                "result": apply_record(repository, team_id, args.apply),
            }
        else:
            placeholders = placeholder_group_count(team_id)
            require(placeholders == 0, "placeholder formal groups exist before dry-run")
            output = {
                "mode": "dry-run",
                "team_id": team_id,
                "group_count": group_count(team_id),
                "placeholder_group_count": placeholders,
                "records": [
                    dry_run_record(repository, team_id, unmatched_id)
                    for unmatched_id in EXPECTED_TARGETS
                ],
            }
    finally:
        local_simulation.reset_current_team(token)
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
