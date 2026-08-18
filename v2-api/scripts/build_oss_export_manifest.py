from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import and_, select, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import GroupBarcodeVerification, MaterialGroup, Photo  # noqa: E402
from app.services.final_delivery_export import (  # noqa: E402
    group_is_formally_archived,
    plan_delivery_photo_members,
)
from app.services.photo_storage import require_oss_client  # noqa: E402


SCHEMA = "module-manager-oss-export/v1"
SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}")


@dataclass(frozen=True)
class ManifestScope:
    team_id: str
    task_id: int | None = None
    terminal: str = ""
    group_ids: tuple[str, ...] = ()
    archived_only: bool = False


class UnsupportedPhotoStorageError(RuntimeError):
    def __init__(self, counts: dict[str, int]) -> None:
        self.counts = counts
        super().__init__("scope contains unsupported active photo storage")


def enum_text(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def minimal_group_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["group_id"] or row["group_pk"]),
        "terminal": str(row["terminal"] or ""),
        "display_meter_no": str(row["display_meter_no"] or ""),
        "installation_address": str(row["installation_address"] or ""),
        "status": enum_text(row["status"]),
        "archive_status": str(row["archive_status"] or ""),
        "archived_at": row["archived_at"],
        "barcode_verification": {
            "auto_archive_status": str(row["auto_archive_status"] or "")
        },
        "photos": [],
    }


def minimal_photo_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["photo_legacy_id"] or row["photo_pk"]),
        "is_active": True,
        "upload_status": enum_text(row["upload_status"]),
        "category": str(row["category"] or ""),
        "archive_status": str(row["photo_archive_status"] or ""),
        "module_asset_no": str(row["asset_no"] or ""),
        "collector": str(row["collector"] or ""),
        "image_url": str(row["image_url"] or ""),
        "original_filename": str(row["original_filename"] or ""),
        "storage_type": str(row["storage_type"] or ""),
        "storage_bucket": str(row["storage_bucket"] or ""),
        "storage_key": str(row["storage_key"] or ""),
        "sha256": str(row["sha256"] or ""),
        "byte_size": int(row["byte_size"] or 0),
        "content_type": str(row["content_type"] or "application/octet-stream"),
    }


def load_scope_payloads(session: Session, scope: ManifestScope) -> list[dict[str, Any]]:
    session.execute(text("SET TRANSACTION READ ONLY"))
    statement = (
        select(
            MaterialGroup.id.label("group_pk"),
            MaterialGroup.legacy_id.label("group_id"),
            MaterialGroup.terminal,
            MaterialGroup.display_meter_no,
            MaterialGroup.installation_address,
            MaterialGroup.status,
            MaterialGroup.raw_data["archive_status"].astext.label("archive_status"),
            MaterialGroup.raw_data["archived_at"].astext.label("archived_at"),
            GroupBarcodeVerification.auto_archive_status,
            Photo.id.label("photo_pk"),
            Photo.legacy_id.label("photo_legacy_id"),
            Photo.upload_status,
            Photo.category,
            Photo.archive_status.label("photo_archive_status"),
            Photo.asset_no,
            Photo.collector,
            Photo.image_url,
            Photo.original_filename,
            Photo.storage_type,
            Photo.storage_bucket,
            Photo.storage_key,
            Photo.sha256,
            Photo.byte_size,
            Photo.content_type,
            Photo.sort_order,
        )
        .join(Photo, Photo.group_id == MaterialGroup.id)
        .outerjoin(
            GroupBarcodeVerification,
            and_(
                GroupBarcodeVerification.team_id == MaterialGroup.team_id,
                GroupBarcodeVerification.group_id == MaterialGroup.id,
            ),
        )
        .where(
            MaterialGroup.team_id == scope.team_id,
            Photo.is_active.is_(True),
        )
    )
    if scope.task_id is not None:
        statement = statement.where(MaterialGroup.legacy_task_id == scope.task_id)
    if scope.terminal:
        statement = statement.where(MaterialGroup.terminal == scope.terminal)
    if scope.group_ids:
        statement = statement.where(MaterialGroup.legacy_id.in_(scope.group_ids))
    rows = session.execute(
        statement.order_by(
            MaterialGroup.legacy_id,
            MaterialGroup.id,
            Photo.sort_order,
            Photo.id,
        )
    ).mappings()
    payloads: dict[str, dict[str, Any]] = {}
    for row in rows:
        group_key = str(row["group_pk"])
        group = payloads.setdefault(group_key, minimal_group_payload(row))
        group["photos"].append(minimal_photo_payload(row))
    return list(payloads.values())


def require_sha256(value: Any) -> str:
    normalized = str(value or "").strip()
    if SHA256_PATTERN.fullmatch(normalized) is None:
        raise ValueError("Photo SHA256 must contain exactly 64 hexadecimal characters")
    return normalized.lower()


def _increment(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def count_unsupported_storage(
    payloads: Sequence[Mapping[str, Any]],
    *,
    expected_bucket: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    configured_bucket = str(expected_bucket or "").strip()
    for group in payloads:
        for photo_value in group.get("photos", []) or []:
            if not isinstance(photo_value, dict):
                _increment(counts, "unknown")
                continue
            photo = photo_value
            storage_type = str(photo.get("storage_type") or "").strip().lower()
            if storage_type != "oss":
                _increment(counts, storage_type or "unknown")
                continue
            bucket = str(photo.get("storage_bucket") or "").strip()
            key = str(photo.get("storage_key") or "").strip()
            if not bucket:
                _increment(counts, "missing_storage_bucket")
            elif bucket != configured_bucket:
                _increment(counts, "wrong_storage_bucket")
            if not key:
                _increment(counts, "missing_storage_key")
            if int(photo.get("byte_size") or 0) <= 0:
                _increment(counts, "invalid_byte_size")
            try:
                photo["sha256"] = require_sha256(photo.get("sha256"))
            except ValueError:
                _increment(counts, "invalid_sha256")
            photo["storage_type"] = storage_type
            photo["storage_bucket"] = bucket
            photo["storage_key"] = key
    return counts


def iter_manifest_rows(
    session: Session,
    scope: ManifestScope,
    signer: Callable[[str, int], str],
    expires_seconds: int = 300,
) -> Iterator[dict[str, Any]]:
    if not 60 <= expires_seconds <= 600:
        raise ValueError("expires_seconds must be between 60 and 600")
    payloads = load_scope_payloads(session, scope)
    if scope.archived_only:
        payloads = [group for group in payloads if group_is_formally_archived(group)]
    unsupported = count_unsupported_storage(payloads, expected_bucket=settings.oss_bucket)
    if unsupported:
        raise UnsupportedPhotoStorageError(unsupported)
    members = plan_delivery_photo_members(payloads)
    yield {
        "schema": SCHEMA,
        "kind": "manifest",
        "planned_count": len(members),
        "planned_bytes": sum(int(member["photo"].get("byte_size") or 0) for member in members),
    }
    for member in members:
        photo = member["photo"]
        key = str(photo["storage_key"])
        yield {
            "schema": SCHEMA,
            "kind": "item",
            "group_id": member["group_id"],
            "photo_id": str(photo["id"]),
            "category": str(photo["category"]),
            "relative_path": member["path"],
            "storage_bucket": str(photo["storage_bucket"]),
            "storage_key": key,
            "sha256": require_sha256(photo["sha256"]),
            "byte_size": int(photo.get("byte_size") or 0),
            "content_type": str(photo.get("content_type") or "application/octet-stream"),
            "download_url": signer(key, expires_seconds),
        }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stream a read-only OSS export manifest as JSON Lines")
    parser.add_argument("--team-id", required=True)
    parser.add_argument("--task-id", type=int)
    parser.add_argument("--terminal", default="")
    parser.add_argument("--group-id", action="append", default=[])
    parser.add_argument("--archived-only", action="store_true")
    parser.add_argument("--expires-seconds", type=int, default=300)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    scope = ManifestScope(
        team_id=args.team_id,
        task_id=args.task_id,
        terminal=args.terminal,
        group_ids=tuple(args.group_id),
        archived_only=args.archived_only,
    )
    try:
        bucket = require_oss_client()

        def signer(key: str, ttl: int) -> str:
            return bucket.sign_url("GET", key, ttl, slash_safe=True)

        with SessionLocal() as session:
            for row in iter_manifest_rows(
                session,
                scope,
                signer,
                expires_seconds=args.expires_seconds,
            ):
                print(json.dumps(row, ensure_ascii=False, separators=(",", ":")), flush=True)
    except UnsupportedPhotoStorageError as exc:
        print(
            json.dumps(
                {"error": str(exc), "counts": exc.counts},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 2
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr, flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
