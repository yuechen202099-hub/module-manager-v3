from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal  # noqa: E402
from app.models import MaterialGroup, Photo, UnmatchedRecord  # noqa: E402
from app.services.matching import build_long_scan_match_key, build_total_catalog_match_key, normalize_meter_text  # noqa: E402
from app.services.state_repository import _unmatched_payload, state_repository  # noqa: E402


PHOTO_SPLIT_RE = re.compile(r"[\r\n,;\uff0c\uff1b]+")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def split_urls(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in PHOTO_SPLIT_RE.split(str(value)) if item.strip()]


def photo_urls_from_payload(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("photo_urls") or payload.get("image_urls") or payload.get("images") or []
    urls = split_urls(raw)
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        result.append(url)
    return result


def candidate_match_keys(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []

    def add(value: Any) -> None:
        text = normalize_meter_text(str(value or ""))
        if text and text not in values:
            values.append(text)

    raw_key = payload.get("meter_match_key")
    if raw_key:
        add(raw_key)

    for field in ("meter_no", "barcode"):
        raw = normalize_meter_text(str(payload.get(field) or ""))
        if not raw:
            continue
        add(raw)
        try:
            add(build_total_catalog_match_key(raw))
        except ValueError:
            pass
        try:
            add(build_long_scan_match_key(raw))
        except ValueError:
            pass

    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
    for field in ("meter_no", "barcode", "scan_content", "扫码内容", "表号"):
        value = raw.get(field)
        if not value:
            continue
        normalized = normalize_meter_text(str(value))
        add(normalized)
        try:
            add(build_total_catalog_match_key(normalized))
        except ValueError:
            pass
        try:
            add(build_long_scan_match_key(normalized))
        except ValueError:
            pass
    return values


def estimate_photo_delta(session, group: MaterialGroup, urls: list[str]) -> dict[str, int]:
    existing_fingerprints: set[str] = set()
    existing_sha: set[str] = set()
    existing_storage: set[tuple[str, str]] = set()
    for photo in session.scalars(select(Photo).where(Photo.team_id == group.team_id, Photo.group_id == group.id)).all():
        if photo.source_fingerprint:
            existing_fingerprints.add(str(photo.source_fingerprint))
        if photo.sha256:
            existing_sha.add(str(photo.sha256))
        if photo.storage_type and photo.storage_key:
            existing_storage.add((str(photo.storage_type), str(photo.storage_key)))

    new_count = 0
    duplicate_count = 0
    for url in urls:
        source_url = str(url)
        sha256 = hashlib.sha256(source_url.encode("utf-8")).hexdigest()
        fingerprint_seed = "|".join([str(group.legacy_id or group.id), "", "", source_url.split("?", 1)[0]])
        source_fingerprint = hashlib.sha256(fingerprint_seed.encode("utf-8")).hexdigest()[:32]
        if source_fingerprint in existing_fingerprints or sha256 in existing_sha:
            duplicate_count += 1
            continue
        existing_fingerprints.add(source_fingerprint)
        existing_sha.add(sha256)
        new_count += 1
    return {"new": new_count, "duplicate": duplicate_count}


def find_unique_target(session, team_id: str, payload: dict[str, Any]) -> tuple[MaterialGroup | None, str, list[str]]:
    keys = candidate_match_keys(payload)
    terminal = str(payload.get("terminal") or "").strip()
    if not keys:
        return None, "no_match_key", []

    statement = select(MaterialGroup).where(MaterialGroup.team_id == team_id)
    if terminal:
        terminal_statement = statement.where(MaterialGroup.terminal == terminal)
        terminal_candidates = list(
            session.scalars(
                terminal_statement.where(
                    or_(MaterialGroup.meter_match_key.in_(keys), MaterialGroup.display_meter_no.in_(keys))
                )
            ).all()
        )
        unique = {str(item.legacy_id): item for item in terminal_candidates}
        if len(unique) == 1:
            return next(iter(unique.values())), "matched_by_terminal", keys
        if len(unique) > 1:
            return None, "ambiguous_terminal", keys

    candidates = list(
        session.scalars(
            statement.where(or_(MaterialGroup.meter_match_key.in_(keys), MaterialGroup.display_meter_no.in_(keys)))
        ).all()
    )
    unique = {str(item.legacy_id): item for item in candidates}
    if len(unique) == 1:
        return next(iter(unique.values())), "matched_by_meter", keys
    if len(unique) > 1:
        return None, "ambiguous_meter", keys
    return None, "not_found", keys


def build_plan(team_id: str, limit: int = 0) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    report: dict[str, Any] = {
        "generated_at": now_iso(),
        "team_id": team_id,
        "dry_run": True,
        "unmatched_total": 0,
        "matched_success": 0,
        "still_unmatched": 0,
        "ambiguous": 0,
        "photos_seen": 0,
        "photos_new": 0,
        "photos_duplicate": 0,
        "photos_failed": 0,
        "sample_matches": [],
        "sample_unmatched": [],
    }
    plan: list[dict[str, Any]] = []
    with SessionLocal() as session:
        statement = (
            select(UnmatchedRecord)
            .where(UnmatchedRecord.team_id == team_id, UnmatchedRecord.status == "open")
            .order_by(UnmatchedRecord.terminal, UnmatchedRecord.barcode, UnmatchedRecord.legacy_id)
        )
        if limit > 0:
            statement = statement.limit(limit)
        records = session.scalars(statement).all()
        report["unmatched_total"] = len(records)
        for record in records:
            payload = _unmatched_payload(record)
            target, reason, keys = find_unique_target(session, team_id, payload)
            urls = photo_urls_from_payload(payload)
            report["photos_seen"] += len(urls)
            item = {
                "unmatched_id": record.legacy_id,
                "terminal": payload.get("terminal") or "",
                "meter_no": payload.get("meter_no") or "",
                "barcode": payload.get("barcode") or "",
                "keys": keys,
                "reason": reason,
                "target_group_id": "",
                "target_meter_no": "",
                "photo_urls": urls,
                "photos_new": 0,
                "photos_duplicate": 0,
            }
            if target is None:
                if reason.startswith("ambiguous"):
                    report["ambiguous"] += 1
                else:
                    report["still_unmatched"] += 1
                if len(report["sample_unmatched"]) < 20:
                    report["sample_unmatched"].append(item)
                continue
            delta = estimate_photo_delta(session, target, urls)
            item.update(
                {
                    "target_group_id": str(target.legacy_id),
                    "target_meter_no": str(target.display_meter_no),
                    "photos_new": delta["new"],
                    "photos_duplicate": delta["duplicate"],
                }
            )
            report["matched_success"] += 1
            report["photos_new"] += delta["new"]
            report["photos_duplicate"] += delta["duplicate"]
            if len(report["sample_matches"]) < 20:
                report["sample_matches"].append(item)
            plan.append(item)
    return report, plan


def apply_plan(plan: list[dict[str, Any]], actor: str) -> dict[str, Any]:
    repo = state_repository()
    report = {
        "dry_run": False,
        "attempted": len(plan),
        "applied": 0,
        "failed": 0,
        "photos_new": 0,
        "photos_duplicate": 0,
        "failures": [],
    }
    for item in plan:
        try:
            result = repo.associate_unmatched_record(
                str(item["unmatched_id"]),
                actor=actor,
                target_group_id=str(item["target_group_id"]),
                updates={},
            )
            import_result = result.get("import_result") or {}
            report["applied"] += 1
            report["photos_new"] += int(import_result.get("photos_new") or import_result.get("applied_records") or 0)
            report["photos_duplicate"] += int(import_result.get("photos_duplicate") or import_result.get("skipped_duplicates") or 0)
        except Exception as exc:  # noqa: BLE001 - report and continue; maintenance should not stop on one bad row.
            report["failed"] += 1
            if len(report["failures"]) < 50:
                report["failures"].append(
                    {
                        "unmatched_id": item.get("unmatched_id"),
                        "target_group_id": item.get("target_group_id"),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    return report


def write_report(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rematch open unmatched records using the latest meter matching rules.")
    parser.add_argument("--team-id", default=os.getenv("MODULE_MANAGER_TEAM_ID", "default-team"))
    parser.add_argument("--actor", default="maintenance-rematch")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--report", default="")
    parser.add_argument("--apply", action="store_true", help="Apply uniquely matched records after the dry-run plan.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dry_report, plan = build_plan(team_id=args.team_id.strip() or "default-team", limit=max(args.limit, 0))
    output: dict[str, Any] = {"dry_run": dry_report, "apply": {}}
    if args.apply:
        output["apply"] = apply_plan(plan, actor=args.actor.strip() or "maintenance-rematch")
    write_report(args.report, output)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
