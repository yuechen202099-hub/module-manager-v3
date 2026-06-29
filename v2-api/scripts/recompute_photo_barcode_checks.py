from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_DATABASE_URL = "postgresql+psycopg://module_manager:module_manager_password@localhost:5432/module_manager_v2"
DEFAULT_DATABASE_URL_MARKERS = {
    "module_manager_password@localhost:5432/module_manager_v2",
    "module_manager_password@postgres:5432/module_manager_v2",
}


@dataclass(frozen=True)
class RecomputePhotoBarcodeResult:
    raw_data: dict[str, Any]
    changed: bool
    status: str
    expected_type: str
    preserved_unreadable_downgrade: bool = False


def load_env_file(path: Path) -> bool:
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value
    return True


def _scanner_available() -> bool:
    try:
        import zxingcpp  # type: ignore  # noqa: F401
    except Exception:
        return False
    return True


def validate_runtime_environment(*, dry_run: bool) -> None:
    database_url = str(os.environ.get("DATABASE_URL") or "").strip()
    app_env = str(os.environ.get("APP_ENV") or "").strip().lower()
    state_backend = str(os.environ.get("STATE_BACKEND") or "").strip().lower()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured; refusing to recompute photo barcode checks.")
    is_explicit_production_postgres = app_env == "production" and state_backend == "postgres"
    if not dry_run and (
        database_url == DEFAULT_DATABASE_URL or any(marker in database_url for marker in DEFAULT_DATABASE_URL_MARKERS)
    ) and not is_explicit_production_postgres:
        raise RuntimeError("Refusing to apply against the default sample DATABASE_URL.")
    if not dry_run and not is_explicit_production_postgres:
        raise RuntimeError("APP_ENV=production and STATE_BACKEND=postgres are required for apply.")
    if not dry_run and not _scanner_available():
        raise RuntimeError("zxingcpp barcode scanner is unavailable; refusing to apply barcode recompute.")


def build_group_window(*, group_limit: int = 0, group_offset: int = 0) -> dict[str, int]:
    return {
        "group_limit": max(0, int(group_limit or 0)),
        "group_offset": max(0, int(group_offset or 0)),
    }


def should_scan_group_photos(photos: list[Any]) -> bool:
    return len(photos) == 4


def _photo_raw(photo: Any) -> dict[str, Any]:
    if isinstance(photo, dict):
        return dict(photo.get("raw_data") or photo)
    return dict(getattr(photo, "raw_data", {}) or {})


def _photo_category(photo: Any) -> str:
    raw = _photo_raw(photo)
    if isinstance(photo, dict):
        category = photo.get("category") or raw.get("category")
    else:
        category = getattr(photo, "category", None) or raw.get("category")
    return str(category or "").strip()


def group_needs_barcode_analysis(photos: list[Any]) -> bool:
    if not should_scan_group_photos(photos):
        return False
    for photo in photos:
        raw = _photo_raw(photo)
        if not str(raw.get("barcode_check_status") or "").strip():
            return True
        if photo_needs_group_evidence_scan(raw):
            return True
    return False


def photo_needs_group_evidence_scan(raw: dict[str, Any]) -> bool:
    status = str(raw.get("barcode_check_status") or "").strip()
    expected_type = str(raw.get("barcode_check_expected_type") or "").strip()
    values = raw.get("barcode_check_normalized_values") or raw.get("barcode_check_values") or []
    if not isinstance(values, list):
        values = [values]
    has_values = any(str(item or "").strip() for item in values)
    return status == "not_required" and expected_type == "none" and not raw.get("barcode_group_evidence_checked") and not has_values


def group_needs_unreadable_analysis(photos: list[Any], *, recheck_batch_id: str = "") -> bool:
    if not should_scan_group_photos(photos):
        return False
    for photo in photos:
        raw = _photo_raw(photo)
        if str(raw.get("barcode_check_status") or "").strip() != "unreadable":
            continue
        if recheck_batch_id and str(raw.get("barcode_unreadable_recheck_id") or "") == recheck_batch_id:
            continue
        return True
    return False


def photo_needs_not_matched_scan(raw: dict[str, Any], *, recheck_batch_id: str = "") -> bool:
    status = str(raw.get("barcode_check_status") or "").strip()
    if status == "matched":
        return False
    if recheck_batch_id and str(raw.get("barcode_not_matched_recheck_id") or "") == recheck_batch_id:
        return False
    return True


def group_needs_not_matched_analysis(photos: list[Any], *, recheck_batch_id: str = "") -> bool:
    if not should_scan_group_photos(photos):
        return False
    return any(
        photo_needs_not_matched_scan(_photo_raw(photo), recheck_batch_id=recheck_batch_id)
        for photo in photos
    )


def group_ready_for_auto_archive(group: dict[str, Any], photos: list[Any]) -> bool:
    from app.services import photo_barcode_check

    if not group_status_allows_auto_archive(group.get("status")):
        return False
    if not should_scan_group_photos(photos):
        return False
    for photo in photos:
        category = _photo_category(photo)
        if not category or category == "unclassified":
            return False
        raw = _photo_raw(photo)
        method = str(raw.get("barcode_check_method") or "").strip()
        if method in photo_barcode_check.OCR_REVIEW_REQUIRED_METHODS:
            return False
    payload = dict(group)
    payload["photos"] = [_photo_raw(photo) for photo in photos]
    check = photo_barcode_check.build_group_barcode_check(payload)
    return (
        str(check.get("group_barcode_check_status") or "") == "matched"
        and not check.get("group_barcode_unmatched_values")
    )


def group_status_allows_auto_archive(status: Any) -> bool:
    value = str(getattr(status, "value", status) or "").strip()
    return value in {"unreviewed", "in_review", "incomplete", ""}


def get_state_repository() -> Any:
    from app.services.state_repository import get_state_repository as factory

    return factory()


def record_report_error(report: dict[str, Any], exc: Exception, *, context: str) -> None:
    report["errors"] = int(report.get("errors") or 0) + 1
    message = f"{context}: {type(exc).__name__}: {exc}"
    messages = report.setdefault("error_messages", [])
    if isinstance(messages, list) and len(messages) < 20:
        messages.append(message[:500])


def archive_passed_groups(group_ids: list[str], *, actor: str) -> dict[str, int]:
    archive_result = get_state_repository().bulk_archive_groups(
        group_ids,
        actor=actor,
        reason="条码扫描通过自动归档。",
    )
    return {
        "archived_count": int(archive_result.get("archived_count") or 0),
        "skipped_count": len(archive_result.get("skipped") or []),
    }


def recompute_photo_barcode_raw(
    photo: dict[str, Any],
    group: dict[str, Any],
    *,
    raw_data: dict[str, Any] | None = None,
    force: bool = False,
    dry_run: bool = False,
    preserve_existing_on_unreadable: bool = True,
    collect_group_evidence: bool = False,
    use_ocr: bool = False,
    scanner: Callable[[dict[str, Any]], Iterable[str]] | None = None,
) -> RecomputePhotoBarcodeResult:
    from app.services import photo_barcode_check

    raw = dict(raw_data or {})
    current_status = str(raw.get("barcode_check_status") or photo.get("barcode_check_status") or "").strip()
    should_refresh_group_evidence = collect_group_evidence and photo_needs_group_evidence_scan(raw)
    if current_status and not force and not should_refresh_group_evidence:
        return RecomputePhotoBarcodeResult(
            raw_data=raw,
            changed=False,
            status=current_status,
            expected_type=str(raw.get("barcode_check_expected_type") or photo.get("barcode_check_expected_type") or ""),
        )

    payload = dict(photo)
    payload.update(raw)
    check = photo_barcode_check.check_photo_barcode(
        payload,
        group,
        scanner=scanner,
        collect_group_evidence=collect_group_evidence,
        use_ocr=use_ocr,
    )
    next_status = str(check.get("barcode_check_status") or "")
    if (
        preserve_existing_on_unreadable
        and current_status in {"matched", "mismatched"}
        and next_status == "unreadable"
    ):
        return RecomputePhotoBarcodeResult(
            raw_data=raw,
            changed=False,
            status=current_status,
            expected_type=str(raw.get("barcode_check_expected_type") or photo.get("barcode_check_expected_type") or ""),
            preserved_unreadable_downgrade=True,
        )
    next_raw = dict(raw)
    next_raw.update(check)
    if collect_group_evidence and next_status == "not_required":
        next_raw["barcode_group_evidence_checked"] = True
        next_raw["barcode_group_evidence_checked_at"] = datetime.now(UTC).isoformat()
    changed = any(raw.get(key) != check.get(key) for key in photo_barcode_check.BARCODE_CHECK_FIELDS)
    changed = changed or raw.get("barcode_group_evidence_checked") != next_raw.get("barcode_group_evidence_checked")
    if dry_run:
        return RecomputePhotoBarcodeResult(
            raw_data=next_raw,
            changed=changed,
            status=next_status,
            expected_type=str(check.get("barcode_check_expected_type") or ""),
        )
    return RecomputePhotoBarcodeResult(
        raw_data=next_raw,
        changed=changed,
        status=next_status,
        expected_type=str(check.get("barcode_check_expected_type") or ""),
    )


def recompute_postgres(
    *,
    team_id: str = "",
    dry_run: bool = True,
    force: bool = False,
    max_photos: int = 0,
    group_limit: int = 0,
    group_offset: int = 0,
    allow_unreadable_downgrade: bool = False,
    clear_incomplete_groups: bool = False,
    unprocessed_only: bool = False,
    unreadable_only: bool = False,
    unreadable_recheck_id: str = "",
    not_matched_only: bool = False,
    not_matched_recheck_id: str = "",
    group_sleep_seconds: float = 0,
    scan_max_candidates: int = 0,
    use_ocr: bool = False,
    archive_ready_only: bool = False,
    auto_archive_passed: bool = False,
    auto_archive_actor: str = "barcode-maintenance",
) -> dict[str, Any]:
    from sqlalchemy import exists, func, select

    from app.database import SessionLocal
    from app.models import MaterialGroup, Photo
    from app.services import photo_barcode_check
    from app.services.local_simulation import current_team_id
    from app.services.state_repository import _group_barcode_context, _group_barcode_payload, _photo_payload

    team_id = team_id or current_team_id()
    group_window = build_group_window(group_limit=group_limit, group_offset=group_offset)
    report: dict[str, Any] = {
        "backend": "postgres",
        "team_id": team_id,
        "dry_run": dry_run,
        "force": force,
        "unreadable_only": unreadable_only,
        "unreadable_recheck_id": unreadable_recheck_id,
        "not_matched_only": not_matched_only,
        "not_matched_recheck_id": not_matched_recheck_id,
        "group_sleep_seconds": max(0.0, float(group_sleep_seconds or 0)),
        "scan_max_candidates": max(0, int(scan_max_candidates or 0)),
        "use_ocr": bool(use_ocr),
        "max_photos": max_photos,
        **group_window,
        "groups_seen": 0,
        "groups_selected": 0,
        "groups_skipped_already_analyzed": 0,
        "groups_skipped_incomplete_photo_count": 0,
        "groups_cleared_incomplete_photo_count": 0,
        "groups_ready_for_auto_archive": 0,
        "groups_auto_archived": 0,
        "groups_auto_archive_skipped": 0,
        "groups_skipped_not_archive_ready": 0,
        "groups_skipped_status_not_auto_archivable": 0,
        "photos_seen": 0,
        "photos_required": 0,
        "photos_not_required": 0,
        "photos_skipped_existing": 0,
        "photos_preserved_unreadable_downgrade": 0,
        "photos_changed": 0,
        "photos_updated": 0,
        "matched": 0,
        "mismatched": 0,
        "unreadable": 0,
        "not_required": 0,
        "errors": 0,
        "error_messages": [],
    }
    seen = 0
    auto_archive_group_ids: list[str] = []
    with SessionLocal() as session:
        group_statement = (
            select(MaterialGroup)
            .where(
                MaterialGroup.team_id == team_id,
                exists(
                    select(Photo.id).where(
                        Photo.team_id == team_id,
                        Photo.group_id == MaterialGroup.id,
                        Photo.is_active.is_(True),
                    )
                ),
            )
            .order_by(MaterialGroup.terminal, MaterialGroup.display_meter_no, MaterialGroup.legacy_id)
        )
        if unprocessed_only or unreadable_only or not_matched_only:
            complete_photo_group_ids = (
                select(Photo.group_id)
                .where(Photo.team_id == team_id, Photo.is_active.is_(True))
                .group_by(Photo.group_id)
                .having(func.count(Photo.id) == 4)
            )
            missing_status = func.coalesce(Photo.raw_data["barcode_check_status"].as_string(), "") == ""
            missing_group_evidence = (
                (Photo.raw_data["barcode_check_status"].as_string() == "not_required")
                & (Photo.raw_data["barcode_check_expected_type"].as_string() == "none")
                & (func.coalesce(Photo.raw_data["barcode_group_evidence_checked"].as_string(), "") != "true")
            )
            unreadable_status = Photo.raw_data["barcode_check_status"].as_string() == "unreadable"
            recheck_id_is_different = (
                func.coalesce(Photo.raw_data["barcode_unreadable_recheck_id"].as_string(), "")
                != unreadable_recheck_id
            )
            target_status = (missing_status | missing_group_evidence) if unprocessed_only else unreadable_status
            if unreadable_only and unreadable_recheck_id:
                target_status = unreadable_status & recheck_id_is_different
            if not_matched_only:
                not_matched_status = func.coalesce(Photo.raw_data["barcode_check_status"].as_string(), "") != "matched"
                target_status = not_matched_status
                if not_matched_recheck_id:
                    target_status = target_status & (
                        func.coalesce(Photo.raw_data["barcode_not_matched_recheck_id"].as_string(), "")
                        != not_matched_recheck_id
                    )
            group_statement = group_statement.where(
                MaterialGroup.id.in_(complete_photo_group_ids),
                exists(
                    select(Photo.id).where(
                        Photo.team_id == team_id,
                        Photo.group_id == MaterialGroup.id,
                        Photo.is_active.is_(True),
                        target_status,
                    )
                ),
            )
        else:
            group_statement = group_statement.offset(group_window["group_offset"])
        if group_window["group_limit"] > 0:
            group_statement = group_statement.limit(group_window["group_limit"])
        groups = session.scalars(group_statement).all()
        for group in groups:
            if max_photos > 0 and seen >= max_photos:
                break
            photos = session.scalars(
                select(Photo)
                .where(
                    Photo.team_id == team_id,
                    Photo.group_id == group.id,
                    Photo.is_active.is_(True),
                )
                .order_by(Photo.sort_order, Photo.created_at, Photo.legacy_id)
            ).all()
            if not photos:
                continue
            report["groups_seen"] += 1
            if not should_scan_group_photos(list(photos)):
                if clear_incomplete_groups:
                    group_changed = False
                    for photo in photos:
                        raw = dict(photo.raw_data or {})
                        for key in photo_barcode_check.BARCODE_CHECK_FIELDS:
                            raw.pop(key, None)
                        if raw != (photo.raw_data or {}):
                            report["photos_changed"] += 1
                            if not dry_run:
                                photo.raw_data = raw
                                report["photos_updated"] += 1
                            group_changed = True
                    if group_changed:
                        report["groups_cleared_incomplete_photo_count"] += 1
                report["groups_skipped_incomplete_photo_count"] += 1
                continue
            if unprocessed_only and not group_needs_barcode_analysis(list(photos)):
                report["groups_skipped_already_analyzed"] += 1
                if not archive_ready_only:
                    continue
            if unreadable_only and not group_needs_unreadable_analysis(
                list(photos),
                recheck_batch_id=unreadable_recheck_id,
            ):
                report["groups_skipped_already_analyzed"] += 1
                continue
            if not_matched_only and not group_needs_not_matched_analysis(
                list(photos),
                recheck_batch_id=not_matched_recheck_id,
            ):
                report["groups_skipped_already_analyzed"] += 1
                continue
            if archive_ready_only:
                if not group_status_allows_auto_archive(getattr(group, "status", "")):
                    report["groups_skipped_status_not_auto_archivable"] += 1
                    continue
                archive_payload = _group_barcode_payload(group, list(photos))
                archive_photos = list(archive_payload.get("photos") or [])
                if not group_ready_for_auto_archive(archive_payload, archive_photos):
                    report["groups_skipped_not_archive_ready"] += 1
                    continue
                if group_window["group_limit"] > 0 and report["groups_selected"] >= group_window["group_limit"]:
                    break
                report["groups_selected"] += 1
                report["groups_ready_for_auto_archive"] += 1
                auto_archive_group_ids.append(str(group.legacy_id or group.id))
                continue
            if group_window["group_limit"] > 0 and report["groups_selected"] >= group_window["group_limit"]:
                break
            report["groups_selected"] += 1
            group_context = _group_barcode_context(group)
            for photo in photos:
                if max_photos > 0 and seen >= max_photos:
                    break
                seen += 1
                report["photos_seen"] += 1
                raw = dict(photo.raw_data or {})
                category = str(photo.category or raw.get("category") or "unclassified")
                expected_type = photo_barcode_check.expected_type_for_category(category)
                if expected_type == "none":
                    report["photos_not_required"] += 1
                else:
                    report["photos_required"] += 1
                original_status = str(raw.get("barcode_check_status") or "")
                if not_matched_only and not photo_needs_not_matched_scan(
                    raw,
                    recheck_batch_id=not_matched_recheck_id,
                ):
                    report["photos_skipped_existing"] += 1
                    if original_status in {"matched", "mismatched", "unreadable", "not_required"}:
                        report[original_status] += 1
                    continue
                if raw.get("barcode_check_status") and not force and not not_matched_only:
                    if collect_existing_group_evidence := photo_needs_group_evidence_scan(raw):
                        pass
                    if (
                        unreadable_only
                        and original_status == "unreadable"
                        and (not unreadable_recheck_id or raw.get("barcode_unreadable_recheck_id") != unreadable_recheck_id)
                    ):
                        pass
                    elif not collect_existing_group_evidence:
                        report["photos_skipped_existing"] += 1
                        status = original_status
                        if status in {"matched", "mismatched", "unreadable", "not_required"}:
                            report[status] += 1
                        continue
                try:
                    result = recompute_photo_barcode_raw(
                        {
                            **_photo_payload(photo),
                            "category": category,
                            "category_label": raw.get("category_label") or "",
                            "barcode_scan_max_candidates": max(0, int(scan_max_candidates or 0)),
                        },
                        group_context,
                        raw_data=raw,
                        force=force or unreadable_only or not_matched_only,
                        dry_run=dry_run,
                        preserve_existing_on_unreadable=not allow_unreadable_downgrade,
                        collect_group_evidence=True,
                        use_ocr=bool(use_ocr),
                    )
                except Exception as exc:
                    record_report_error(
                        report,
                        exc,
                        context=(
                            f"photo_scan group={getattr(group, 'legacy_id', '') or group.id} "
                            f"photo={getattr(photo, 'legacy_id', '') or photo.id}"
                        ),
                    )
                    continue
                if result.preserved_unreadable_downgrade:
                    report["photos_preserved_unreadable_downgrade"] += 1
                result_raw = result.raw_data
                result_changed = result.changed
                if unreadable_only and original_status == "unreadable" and unreadable_recheck_id:
                    result_raw = dict(result.raw_data)
                    result_raw["barcode_unreadable_recheck_id"] = unreadable_recheck_id
                    result_raw["barcode_unreadable_rechecked_at"] = datetime.now(UTC).isoformat()
                    result_changed = True
                if not_matched_only and not_matched_recheck_id:
                    result_raw = dict(result_raw)
                    result_raw["barcode_not_matched_recheck_id"] = not_matched_recheck_id
                    result_raw["barcode_not_matched_rechecked_at"] = datetime.now(UTC).isoformat()
                    result_changed = True
                if result.status in {"matched", "mismatched", "unreadable", "not_required"}:
                    report[result.status] += 1
                if not result_changed:
                    continue
                report["photos_changed"] += 1
                if not dry_run:
                    photo.raw_data = result_raw
                    report["photos_updated"] += 1
            if auto_archive_passed:
                if not group_status_allows_auto_archive(getattr(group, "status", "")):
                    report["groups_skipped_status_not_auto_archivable"] += 1
                    continue
                archive_payload = _group_barcode_payload(group, list(photos))
                archive_payload["status"] = str(getattr(group, "status", "") or "")
                archive_photos = list(archive_payload.get("photos") or [])
                if group_ready_for_auto_archive(archive_payload, archive_photos):
                    report["groups_ready_for_auto_archive"] += 1
                    group_identifier = str(group.legacy_id or group.id)
                    if group_identifier:
                        auto_archive_group_ids.append(group_identifier)
            sleep_seconds = max(0.0, float(group_sleep_seconds or 0))
            if sleep_seconds > 0:
                if not dry_run:
                    session.commit()
                time.sleep(sleep_seconds)
        if dry_run:
            session.rollback()
        else:
            session.commit()
    if auto_archive_passed and auto_archive_group_ids:
        if dry_run:
            report["groups_auto_archived"] = 0
        else:
            try:
                archive_result = archive_passed_groups(
                    auto_archive_group_ids,
                    actor=auto_archive_actor,
                )
                report["groups_auto_archived"] = archive_result["archived_count"]
                report["groups_auto_archive_skipped"] = archive_result["skipped_count"]
            except Exception as exc:
                record_report_error(report, exc, context="auto_archive")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Recompute backend photo barcode check fields.")
    parser.add_argument("--env-file", default=str(ROOT / ".env"), help="Path to .env loaded before DB connection.")
    parser.add_argument("--team-id", default="", help="Team id. Defaults to CURRENT_TEAM_ID/default team.")
    parser.add_argument("--force", action="store_true", help="Re-scan photos even when barcode_check_status exists.")
    parser.add_argument(
        "--allow-unreadable-downgrade",
        action="store_true",
        help="Allow force recompute to overwrite matched/mismatched photos with unreadable.",
    )
    parser.add_argument("--max-photos", type=int, default=0, help="Limit processed photos. 0 means no limit.")
    parser.add_argument("--group-limit", type=int, default=0, help="Limit material groups per run. Use 50 in production.")
    parser.add_argument("--group-offset", type=int, default=0, help="Material group offset for batched runs.")
    parser.add_argument(
        "--clear-incomplete-groups",
        action="store_true",
        help="Clear barcode check fields for groups that do not have exactly 4 active photos.",
    )
    parser.add_argument(
        "--unprocessed-only",
        action="store_true",
        help="Select only exactly 4-photo groups that still have photos without barcode_check_status.",
    )
    parser.add_argument(
        "--unreadable-only",
        action="store_true",
        help="Select only exactly 4-photo groups that still have photos marked barcode_check_status=unreadable.",
    )
    parser.add_argument(
        "--unreadable-recheck-id",
        default="",
        help="Batch id used to avoid rechecking the same unreadable photos repeatedly in one maintenance run.",
    )
    parser.add_argument(
        "--not-matched-only",
        action="store_true",
        help="Select exactly 4-photo groups and re-scan photos whose barcode_check_status is not matched.",
    )
    parser.add_argument(
        "--not-matched-recheck-id",
        default="",
        help="Batch id used to avoid rechecking the same non-matched photos repeatedly in one maintenance run.",
    )
    parser.add_argument(
        "--group-sleep-seconds",
        type=float,
        default=0,
        help="Sleep after each selected group. Use 5 for slow production maintenance.",
    )
    parser.add_argument(
        "--scan-max-candidates",
        type=int,
        default=0,
        help="Limit barcode scan candidates per photo. 0 keeps the default scanner cap.",
    )
    parser.add_argument(
        "--use-ocr",
        action="store_true",
        help="Use OCR fallback after barcode/QR candidates fail or mismatch.",
    )
    parser.add_argument(
        "--archive-ready-only",
        action="store_true",
        help="Do not scan photos; archive up to --group-limit unreviewed/incomplete groups already classified and barcode matched.",
    )
    parser.add_argument(
        "--auto-archive-passed",
        action="store_true",
        help="After scanning, automatically archive groups whose photos are classified and group barcode check passes.",
    )
    parser.add_argument(
        "--auto-archive-actor",
        default="barcode-maintenance",
        help="Actor name written to audit logs when --auto-archive-passed archives groups.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Report changes without writing them.")
    mode.add_argument("--apply", action="store_true", help="Persist recomputed barcode check fields.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dry_run = not args.apply
    env_loaded = load_env_file(Path(args.env_file)) if args.env_file else False
    validate_runtime_environment(dry_run=dry_run)
    report = recompute_postgres(
        team_id=args.team_id,
        dry_run=dry_run,
        force=bool(args.force),
        max_photos=max(0, int(args.max_photos or 0)),
        group_limit=max(0, int(args.group_limit or 0)),
        group_offset=max(0, int(args.group_offset or 0)),
        allow_unreadable_downgrade=bool(args.allow_unreadable_downgrade),
        clear_incomplete_groups=bool(args.clear_incomplete_groups),
        unprocessed_only=bool(args.unprocessed_only),
        unreadable_only=bool(args.unreadable_only),
        unreadable_recheck_id=str(args.unreadable_recheck_id or ""),
        not_matched_only=bool(args.not_matched_only),
        not_matched_recheck_id=str(args.not_matched_recheck_id or ""),
        group_sleep_seconds=max(0.0, float(args.group_sleep_seconds or 0)),
        scan_max_candidates=max(0, int(args.scan_max_candidates or 0)),
        use_ocr=bool(args.use_ocr),
        archive_ready_only=bool(args.archive_ready_only),
        auto_archive_passed=bool(args.auto_archive_passed),
        auto_archive_actor=str(args.auto_archive_actor or "barcode-maintenance"),
    )
    report["env_file"] = str(args.env_file or "")
    report["env_loaded"] = env_loaded
    report["database_url_host_hint"] = _database_url_host_hint(str(os.environ.get("DATABASE_URL") or ""))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if report.get("errors") else 0


def _database_url_host_hint(database_url: str) -> str:
    if "@" not in database_url:
        return ""
    return database_url.rsplit("@", 1)[-1].split("/", 1)[0]


if __name__ == "__main__":
    raise SystemExit(main())
