import asyncio
import json
import mimetypes
import hashlib
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from io import BytesIO
from threading import Lock
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from uuid import uuid4

from pydantic import BaseModel

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, select

from app.core.config import settings
from app.core.responses import ok
from app.core.security import decode_access_token
from app.api.routes.auth import require_admin
from app.database import SessionLocal
from app.models import (
    GroupStatus,
    MaterialGroup,
    Photo,
    PhotoUploadStatus,
    Project,
    ProjectStatus,
    Task,
    TaskStatus,
    Team,
    TotalCatalogRow,
    UnmatchedRecord,
)
from app.services.ops_status import build_system_status
from app.services.account_store import get_user
from app.services.project_board_cache import project_board_summary_cache
from app.services.photo_storage import (
    normalize_suffix,
    parse_oss_image_url,
    resolve_group_collection_for_response,
    resolve_group_for_response,
    resolve_manifest_for_response,
    resolve_photo_image_url,
    resolve_photo_for_response,
    resolve_photo_preview_url,
    resolve_photo_thumbnail_url,
    resolve_result_for_response,
    save_image_bytes,
    sign_oss_server_url,
    static_upload_root,
    validate_image_content,
)
from app.services.state_repository import StateBackendNotReady, _unmatched_duplicate_keys, get_state_repository
from app.services.local_simulation import (
    add_photo_urls_to_group,
    assign_construction_task,
    bootstrap_local_simulation,
    associate_unmatched_record,
    build_final_delivery_manifest,
    claim_task,
    claim_construction_task,
    classify_photo,
    clear_scan_data,
    close_construction_task,
    create_blank_unmatched_record,
    create_empty_group_for_terminal,
    create_group_from_unmatched_record,
    current_team_id,
    delete_group_photo,
    delete_unmatched_record,
    build_photo_record,
    expand_detail_pages_for_rows,
    get_group,
    get_delivery_cached_photo_path,
    get_task_progress,
    get_state,
    assert_not_placeholder_construction_group,
    is_all_zero_construction_code,
    group_target_summary,
    import_scan_template_xlsx,
    import_total_catalog_xlsx,
    import_url_scan_rows,
    list_audit_events,
    list_catalog_rows,
    list_exception_groups,
    list_construction_exception_orders,
    list_construction_task_groups,
    list_construction_tasks,
    list_groups,
    make_unmatched_duplicate_key,
    list_team_states,
    list_task_groups,
    list_tasks,
    list_unmatched_records,
    open_construction_task,
    read_catalog_xlsx_rows,
    normalize_url_import_row,
    read_scan_template_xlsx_rows,
    scan_record_to_photo_rows,
    release_all_claimed_tasks,
    release_construction_task,
    release_task,
    reset_group_to_unconstructed,
    return_group_to_exception_order,
    reset_current_team,
    review_group,
    save_exception_note,
    save_all_team_states,
    search_group_targets,
    set_current_team,
    submit_construction_exception_order,
    sync_state_photos_to_oss,
    unassign_construction_task,
    update_group_metadata,
    update_group_terminal,
    upload_construction_group_batch,
)


def response_group_target_summary(group: dict[str, Any] | None) -> dict[str, Any]:
    if not group:
        return {}
    return group_target_summary(group)


async def use_team_context(request: Request):
    team_id = request.headers.get("X-Team-Id") or request.query_params.get("team_id") or ""
    payload = getattr(request.state, "auth", None)
    if payload:
        team_id = payload.get("team_id") or team_id
    elif settings.app_env.lower() in {"prod", "production"}:
            authorization = request.headers.get("authorization", "")
            if authorization.lower().startswith("bearer "):
                try:
                    payload = decode_access_token(authorization.split(" ", 1)[1].strip())
                except ValueError:
                    payload = {}
            team_id = (payload or {}).get("team_id") or team_id
    token = set_current_team(team_id)
    try:
        yield
    finally:
        reset_current_team(token)


router = APIRouter(prefix="/local-test", dependencies=[Depends(use_team_context)])
BOARD_EVENT_INTERVAL_SECONDS = 15 * 60


def display_name_for_actor(request: Request, actor: str) -> str:
    actor = str(actor or "").strip()
    authorization = request.headers.get("Authorization") or ""
    if authorization.lower().startswith("bearer "):
        try:
            payload = decode_access_token(authorization.split(" ", 1)[1].strip())
            if str(payload.get("sub") or "") == actor:
                return str(payload.get("name") or actor).strip() or actor
        except ValueError:
            pass
    try:
        user = get_user(actor)
    except ValueError:
        user = None
    return str((user or {}).get("name") or actor).strip() or actor
_scan_import_executor = ThreadPoolExecutor(max_workers=2)
_scan_import_jobs: dict[str, dict] = {}
_scan_import_jobs_lock = Lock()


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def current_request_team(request: Request) -> str:
    return current_team_id()


def state_repository():
    try:
        return get_state_repository()
    except StateBackendNotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def invalidate_project_board_summary_cache() -> None:
    project_board_summary_cache.invalidate(current_team_id())


def validate_construction_upload_group_before_file_save(group_id: str) -> None:
    group = state_repository().get_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    try:
        assert_not_placeholder_construction_group(
            group_id=group.get("id") or group_id,
            meter_no=group.get("meter_no"),
            meter_match_key=group.get("meter_match_key"),
            address=group.get("address"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def request_auth_payload(request: Request) -> dict:
    payload = getattr(request.state, "auth", None) or {}
    if not payload:
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            try:
                payload = decode_access_token(authorization.split(" ", 1)[1].strip())
            except ValueError:
                payload = {}
    return payload


def request_is_admin(request: Request) -> bool:
    payload = request_auth_payload(request)
    return "admin" in set(payload.get("roles") or [])


def require_production_admin_payload(request: Request) -> dict:
    if settings.app_env.lower() not in {"prod", "production"}:
        return request_auth_payload(request)
    return require_admin(request.headers.get("authorization"))


def request_actor(request: Request, fallback: str = "admin") -> str:
    payload = request_auth_payload(request)
    return str(payload.get("username") or payload.get("sub") or fallback).strip() or fallback


def bound_review_actor(request: Request, reviewer: str, fallback: str = "local-reviewer") -> str:
    clean_reviewer = str(reviewer or "").strip()
    if request_is_admin(request):
        return clean_reviewer or request_actor(request, fallback)
    payload = request_auth_payload(request)
    subject = str(payload.get("sub") or payload.get("username") or "").strip()
    if not subject:
        if settings.app_env.lower() in {"prod", "production"}:
            raise HTTPException(status_code=401, detail="Authentication required")
        return clean_reviewer or fallback
    if clean_reviewer and clean_reviewer != subject:
        raise HTTPException(status_code=403, detail="Reviewer must match the signed-in user")
    return subject


def request_is_constructor(request: Request) -> bool:
    payload = request_auth_payload(request)
    return "constructor" in set(payload.get("roles") or [])


def bound_construction_actor(request: Request, actor: str) -> str:
    clean_actor = str(actor or "").strip()
    if request_is_admin(request):
        return clean_actor
    payload = request_auth_payload(request)
    subject = str(payload.get("sub") or "").strip()
    if not subject:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not clean_actor:
        return subject
    if clean_actor != subject:
        raise HTTPException(status_code=403, detail="Construction actor must match the signed-in user")
    return clean_actor


def forbid_constructor_project_board(request: Request) -> None:
    if request_is_constructor(request):
        raise HTTPException(status_code=403, detail="Constructors are not allowed to access project board data")


def store_scan_import_job(job_id: str, update: dict) -> dict:
    with _scan_import_jobs_lock:
        job = _scan_import_jobs.setdefault(job_id, {})
        job.update(update)
        job["updated_at"] = now_iso()
        return deepcopy(job)


@router.get("/system/status")
def system_status(request: Request):
    if not request_is_admin(request):
        raise HTTPException(status_code=403, detail="Only administrators can view system status")
    return ok(request, build_system_status())


def response_payload(payload: dict) -> dict:
    return resolve_result_for_response(payload)


def _postgres_project_for_team(session, team_id: str) -> Project:
    team = session.get(Team, team_id)
    if team is None:
        team = Team(id=team_id, name=team_id, status="active")
        session.add(team)
        session.flush()
    project = session.scalar(select(Project).where(Project.team_id == team_id).order_by(Project.created_at))
    if project is None:
        project = Project(code=team_id, name=f"Project {team_id}", status=ProjectStatus.ACTIVE, team_id=team_id, settings={})
        session.add(project)
        session.flush()
    return project


def _next_task_legacy_id(session, team_id: str) -> int:
    current = session.scalar(select(func.max(Task.legacy_id)).where(Task.team_id == team_id)) or 0
    return int(current) + 1


def _next_group_legacy_id(session, team_id: str) -> int:
    legacy_ids = session.scalars(select(MaterialGroup.legacy_id).where(MaterialGroup.team_id == team_id)).all()
    numeric_ids = [int(item) for item in legacy_ids if str(item or "").isdigit()]
    return (max(numeric_ids) + 1) if numeric_ids else 1


def import_total_catalog_xlsx_for_active_backend(content: bytes) -> dict:
    if settings.state_backend.lower() != "postgres":
        return import_total_catalog_xlsx(content)

    team_id = current_team_id()
    incoming_rows = read_catalog_xlsx_rows(content, source="total")
    now = datetime.now(UTC)
    imported_rows = 0
    skipped_duplicate_meters = 0
    created_tasks = 0
    created_groups = 0
    seen_keys: set[str] = set()

    with SessionLocal() as session:
        project = _postgres_project_for_team(session, team_id)
        existing_catalog = {
            str(row.meter_match_key or ""): row
            for row in session.scalars(select(TotalCatalogRow).where(TotalCatalogRow.team_id == team_id)).all()
        }
        tasks_by_terminal = {
            str(task.terminal or ""): task
            for task in session.scalars(select(Task).where(Task.team_id == team_id)).all()
            if task.terminal
        }
        groups_by_key = {
            str(group.meter_match_key or ""): group
            for group in session.scalars(select(MaterialGroup).where(MaterialGroup.team_id == team_id)).all()
            if group.meter_match_key
        }
        next_task_id = _next_task_legacy_id(session, team_id)
        next_group_id = _next_group_legacy_id(session, team_id)

        for row in incoming_rows:
            key = str(row.get("meter_match_key") or "").strip()
            if not key or key in seen_keys or key in existing_catalog:
                skipped_duplicate_meters += 1
                continue
            seen_keys.add(key)
            terminal = str(row.get("terminal") or "").strip()
            meter_no = str(row.get("meter_no") or "").strip()
            address = str(row.get("address") or "").strip()
            catalog = TotalCatalogRow(
                team_id=team_id,
                project_id=project.id,
                source_file=str(row.get("source") or "total"),
                source_row_number=int(row.get("row_number") or 0) or None,
                terminal=terminal or None,
                installer=str(row.get("installer") or "").strip() or None,
                original_meter_no=meter_no,
                meter_match_key=key,
                installation_address=address,
                customer_name=str(row.get("customer_name") or "").strip() or None,
                raw_data=row,
            )
            session.add(catalog)
            session.flush()
            existing_catalog[key] = catalog
            imported_rows += 1

            task = tasks_by_terminal.get(terminal)
            if task is None:
                task = Task(
                    team_id=team_id,
                    legacy_id=next_task_id,
                    terminal=terminal or None,
                    project_id=project.id,
                    title=f"终端 {terminal or next_task_id}",
                    status=TaskStatus.PUBLISHED,
                    raw_data={"terminal": terminal, "source": "total_catalog_import"},
                )
                session.add(task)
                session.flush()
                tasks_by_terminal[terminal] = task
                next_task_id += 1
                created_tasks += 1

            if key not in groups_by_key:
                group = MaterialGroup(
                    team_id=team_id,
                    legacy_id=str(next_group_id),
                    legacy_task_id=task.legacy_id,
                    terminal=terminal or None,
                    project_id=project.id,
                    total_catalog_row_id=catalog.id,
                    task_id=task.id,
                    meter_match_key=key,
                    display_meter_no=meter_no,
                    installation_address=address,
                    status=GroupStatus.UNREVIEWED,
                    photo_count=0,
                    raw_data={
                        **row,
                        "id": str(next_group_id),
                        "task_id": task.legacy_id,
                        "status": "pending",
                        "photo_count": 0,
                    },
                )
                session.add(group)
                groups_by_key[key] = group
                next_group_id += 1
                created_groups += 1

        project.updated_at = now
        session.commit()

    return {
        "catalog_rows": len(incoming_rows),
        "imported_rows": imported_rows,
        "skipped_duplicate_meters": skipped_duplicate_meters,
        "created_tasks": created_tasks,
        "created_groups": created_groups,
        "summary": state_repository().summary().get("summary", {}),
    }


def _stable_photo_sha(photo: dict) -> str:
    source = "|".join(
        [
            str(photo.get("source_fingerprint") or ""),
            str(photo.get("source_url") or photo.get("image_url") or ""),
            str(photo.get("image_file_id") or ""),
            str(photo.get("id") or ""),
        ]
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _postgres_import_scan_records(records: list[dict], progress_callback=None) -> dict:
    team_id = current_team_id()
    processed_photos = 0
    applied = 0
    skipped_duplicates = 0
    groups_matched: set[str] = set()
    groups_existing: set[str] = set()
    groups_unmatched = 0
    unmatched_records = 0
    now = datetime.now(UTC)

    with SessionLocal() as session:
        project = _postgres_project_for_team(session, team_id)
        groups_by_key = {
            str(group.meter_match_key or ""): group
            for group in session.scalars(select(MaterialGroup).where(MaterialGroup.team_id == team_id)).all()
            if group.meter_match_key
        }
        existing_photo_keys = {
            (str(photo.group_id), str(photo.source_fingerprint or ""))
            for photo in session.scalars(
                select(Photo).where(
                    Photo.team_id == team_id,
                    Photo.is_active.is_(True),
                    Photo.source_fingerprint.is_not(None),
                    Photo.source_fingerprint != "",
                )
            ).all()
        }
        existing_photo_shas = {
            (str(photo.group_id), str(photo.sha256 or ""))
            for photo in session.scalars(select(Photo).where(Photo.team_id == team_id, Photo.sha256.is_not(None), Photo.sha256 != "")).all()
        }
        existing_unmatched_records = list(
            session.scalars(select(UnmatchedRecord).where(UnmatchedRecord.team_id == team_id)).all()
        )
        existing_unmatched = {
            str(record.legacy_id or "")
            for record in existing_unmatched_records
        }
        existing_unmatched_keys = _unmatched_duplicate_keys(existing_unmatched_records)

        for index, record in enumerate(records, start=1):
            match_key = str(record.get("meter_match_key") or "")
            group = groups_by_key.get(match_key)
            if group is None:
                groups_unmatched += 1
                legacy_id = f"scan-unmatched-{hashlib.sha256((team_id + '|' + str(record.get('barcode') or '') + '|' + str(index)).encode('utf-8')).hexdigest()[:24]}"
                duplicate_key = make_unmatched_duplicate_key({**record, "unmatched_id": legacy_id})
                if legacy_id not in existing_unmatched and (
                    duplicate_key.startswith("id:") or duplicate_key not in existing_unmatched_keys
                ):
                    session.add(
                        UnmatchedRecord(
                            team_id=team_id,
                            legacy_id=legacy_id,
                            record_type="scan",
                            status="open",
                            terminal=str(record.get("terminal") or "") or None,
                            meter_no=str(record.get("meter_no") or record.get("barcode") or "") or None,
                            meter_match_key=match_key or None,
                            barcode=str(record.get("barcode") or "") or None,
                            collector=str(record.get("collector") or "") or None,
                            module_asset_no=str(record.get("module_asset_no") or "") or None,
                            address=str(record.get("address") or "") or None,
                            payload=record,
                        )
                    )
                    existing_unmatched.add(legacy_id)
                    if not duplicate_key.startswith("id:"):
                        existing_unmatched_keys.add(duplicate_key)
                    unmatched_records += 1
                continue

            groups_matched.add(str(group.legacy_id or group.id))
            if group.photo_count > 0:
                groups_existing.add(str(group.legacy_id or group.id))

            group_changed = False
            rows = scan_record_to_photo_rows(record, index)
            active_count = int(group.photo_count or 0)
            for row in rows:
                processed_photos += 1
                if not row.get("has_image"):
                    continue
                photo = build_photo_record(active_count + 1, row)
                fingerprint = str(photo.get("source_fingerprint") or "").strip()
                sha256 = str(photo.get("sha256") or "") or _stable_photo_sha(photo)
                if (
                    (fingerprint and (str(group.id), fingerprint) in existing_photo_keys)
                    or (str(group.id), sha256) in existing_photo_shas
                ):
                    skipped_duplicates += 1
                    continue
                legacy_id = str(photo.get("id") or f"p-{group.legacy_id}-{active_count + 1}")
                storage_key = str(photo.get("storage_key") or "")
                image_url = str(photo.get("image_url") or "")
                source_url = str(photo.get("source_url") or image_url or "")
                session.add(
                    Photo(
                        team_id=team_id,
                        legacy_id=legacy_id,
                        group_id=group.id,
                        source=str(photo.get("source_file") or "") or None,
                        barcode=str(photo.get("barcode") or "") or None,
                        collector=str(photo.get("collector") or "") or None,
                        asset_no=str(photo.get("asset_no") or "") or None,
                        creator=str(photo.get("creator") or "") or None,
                        image_url=image_url or None,
                        image_file_id=str(photo.get("image_file_id") or "") or None,
                        source_url=source_url or None,
                        source_url_hash=str(photo.get("source_url_hash") or "") or None,
                        source_file_id=str(photo.get("source_file_id") or "") or None,
                        source_fingerprint=fingerprint or None,
                        import_batch_id=str(photo.get("import_batch_id") or photo.get("source_file") or "") or None,
                        storage_type=str(photo.get("storage_type") or "") or None,
                        storage_bucket=str(photo.get("storage_bucket") or "") or None,
                        storage_key=storage_key or None,
                        sha256=sha256,
                        original_filename=None,
                        object_key=storage_key or image_url or source_url or legacy_id,
                        upload_status=PhotoUploadStatus.UPLOADED,
                        category="unclassified",
                        archive_status="pending",
                        archive_filename=None,
                        sort_order=active_count + 1,
                        is_active=True,
                        metadata_json={
                            "download_status": photo.get("download_status"),
                            "category_label": photo.get("category_label"),
                        },
                        raw_data=photo,
                    )
                )
                if fingerprint:
                    existing_photo_keys.add((str(group.id), fingerprint))
                existing_photo_shas.add((str(group.id), sha256))
                applied += 1
                active_count += 1
                group_changed = True

                if progress_callback and processed_photos % 5 == 0:
                    progress_callback(
                        {
                            "phase": "indexing_photos",
                            "processed_records": index,
                            "total_records": len(records),
                            "processed_photos": processed_photos,
                            "applied_records": applied,
                            "skipped_duplicates": skipped_duplicates,
                            "photos_seen": processed_photos,
                            "photos_new": applied,
                            "photos_duplicate": skipped_duplicates,
                        }
                    )

            if group_changed:
                group.photo_count = active_count
                group.status = GroupStatus.INCOMPLETE if active_count < 4 else GroupStatus.UNREVIEWED
                group.reviewer = None
                group.review_note = ""
                group.exception_note = ""
                group.reviewed_at = None
                group.last_photo_imported_at = now
                group.updated_at = now
                if active_count < 4:
                    group.has_archive_blocker = True
                    group.exception_status = "open"
                    reasons = list(group.exception_reasons or [])
                    reason = "资料组照片不足 4 张"
                    if reason not in reasons:
                        reasons.append(reason)
                    group.exception_reasons = reasons
                raw_data = dict(group.raw_data or {})
                raw_data.update(
                    {
                        "photo_count": active_count,
                        "status": "incomplete" if active_count < 4 else "pending",
                        "reviewer": "",
                        "review_note": "",
                        "exception_note": group.exception_note or "",
                        "reviewed_at": None,
                    }
                )
                group.raw_data = raw_data

        session.commit()

    if progress_callback:
        progress_callback(
            {
                "phase": "complete",
                "processed_records": len(records),
                "total_records": len(records),
                "processed_photos": processed_photos,
                "applied_records": applied,
                "skipped_duplicates": skipped_duplicates,
                "photos_seen": processed_photos,
                "photos_new": applied,
                "photos_duplicate": skipped_duplicates,
            }
        )
    return {
        "rows_total": len(records),
        "received_records": len(records),
        "groups_matched": len(groups_matched),
        "groups_unmatched": groups_unmatched,
        "groups_existing": len(groups_existing),
        "photos_seen": processed_photos,
        "photos_new": applied,
        "photos_duplicate": skipped_duplicates,
        "photos_reused_oss": 0,
        "photos_uploaded_oss": 0,
        "photos_failed": 0,
        "applied_records": applied,
        "skipped_duplicates": skipped_duplicates,
        "skipped_duplicate_meters": 0,
        "unmatched_records": unmatched_records,
    }


def import_scan_template_xlsx_for_active_backend(content: bytes, progress_callback=None) -> dict:
    if settings.state_backend.lower() != "postgres":
        return import_scan_template_xlsx(content, progress_callback=progress_callback)
    rows = read_scan_template_xlsx_rows(content)
    if progress_callback:
        progress_callback({"phase": "parsed", "template_rows": len(rows), "processed_records": 0, "total_records": len(rows)})
    detail_stats = expand_detail_pages_for_rows(rows, progress_callback=progress_callback)
    records = [normalize_url_import_row(row, index) for index, row in enumerate(rows, start=1)]
    result = _postgres_import_scan_records(records, progress_callback=progress_callback)
    result["template_rows"] = len(rows)
    result.update(detail_stats)
    result["summary"] = state_repository().summary().get("summary", {})
    return result


def import_url_scan_rows_for_active_backend(rows: list[dict], progress_callback=None) -> dict:
    if settings.state_backend.lower() != "postgres":
        return import_url_scan_rows(rows, progress_callback=progress_callback)
    records = [normalize_url_import_row(row, index) for index, row in enumerate(rows, start=1)]
    result = _postgres_import_scan_records(records, progress_callback=progress_callback)
    result["summary"] = state_repository().summary().get("summary", {})
    return result


def read_scan_import_job(job_id: str, team_id: str) -> dict:
    with _scan_import_jobs_lock:
        job = deepcopy(_scan_import_jobs.get(job_id) or {})
    if not job or job.get("team_id") != team_id:
        raise KeyError(job_id)
    return job


def run_scan_import_job(job_id: str, team_id: str, content: bytes, filename: str | None) -> None:
    token = set_current_team(team_id)
    try:
        store_scan_import_job(job_id, {"status": "running", "started_at": now_iso(), "progress": {"phase": "starting"}})

        def update_progress(progress: dict) -> None:
            store_scan_import_job(job_id, {"progress": progress})

        result = import_scan_template_xlsx_for_active_backend(content, progress_callback=update_progress)
        result["filename"] = filename
        oss_report = state_repository().sync_photos_to_oss(team_id=team_id, progress_callback=update_progress)
        result["oss_sync"] = oss_report
        if settings.state_backend.lower() in {"json", "dual"}:
            state_repository().persist_state()
        store_scan_import_job(
            job_id,
            {
                "status": "complete",
                "finished_at": now_iso(),
                "result": result,
                "progress": {
                    "phase": "complete",
                    "processed_records": result.get("received_records", result.get("template_rows", 0)),
                    "total_records": result.get("received_records", result.get("template_rows", 0)),
                    "processed_photos": (
                        result.get("photos_seen", 0)
                        + int((oss_report or {}).get("uploaded", 0))
                    ),
                    "applied_records": result.get("applied_records", 0),
                    "skipped_duplicates": result.get("skipped_duplicates", 0),
                    "skipped_duplicate_meters": result.get("skipped_duplicate_meters", 0),
                    "photos_seen": result.get("photos_seen", 0),
                    "photos_new": result.get("photos_new", 0),
                    "photos_duplicate": result.get("photos_duplicate", 0),
                    "photos_reused_oss": result.get("photos_reused_oss", 0) + int((oss_report or {}).get("reused_existing_oss", 0)),
                    "photos_uploaded_oss": result.get("photos_uploaded_oss", 0) + int((oss_report or {}).get("uploaded", 0)),
                    "photos_failed": result.get("photos_failed", 0) + int((oss_report or {}).get("failed", 0)),
                    "oss_uploaded": int((oss_report or {}).get("uploaded", 0)),
                    "oss_failed": int((oss_report or {}).get("failed", 0)),
                },
            },
        )
    except Exception as exc:  # noqa: BLE001 - background job must surface failures through status polling
        store_scan_import_job(
            job_id,
            {
                "status": "failed",
                "finished_at": now_iso(),
                "error": str(exc),
                "progress": {"phase": "failed"},
            },
        )
    finally:
        reset_current_team(token)


class ClaimRequest(BaseModel):
    reviewer: str = "local-reviewer"


class ConstructionActorRequest(BaseModel):
    actor: str = "constructor"


class ConstructionHeartbeatRequest(BaseModel):
    actor: str = "constructor"
    task_id: str | int | None = None
    occurred_at: str = ""


class ConstructionNonIdleEventRequest(BaseModel):
    event_type: str
    actor: str = "constructor"
    task_id: str | int | None = None
    group_id: str = ""
    client_batch_id: str = ""
    occurred_at: str = ""


class ConstructionAssignRequest(BaseModel):
    actor: str = "admin"
    constructor: str
    note: str = ""
    due_date: str = ""


class ReviewRequest(BaseModel):
    status: str
    reviewer: str = "local-reviewer"
    note: str = ""
    exception_note: str = ""


class ExceptionNoteRequest(BaseModel):
    reviewer: str = "local-reviewer"
    note: str


class GroupResetRequest(BaseModel):
    actor: str = "local-reviewer"
    reason: str = ""


class GroupExceptionOrderRequest(BaseModel):
    actor: str = "local-reviewer"
    category: str = "other"
    note: str


class ConstructionExceptionSubmitRequest(BaseModel):
    actor: str = "constructor"
    updates: dict = {}
    note: str = ""


class ConstructionExceptionAssignRequest(BaseModel):
    actor: str = "module_admin"
    constructor: str
    note: str = ""
    due_date: str = ""


class ConstructionExceptionUnassignRequest(BaseModel):
    actor: str = "module_admin"
    reason: str = ""


class PhotoClassifyRequest(BaseModel):
    category: str
    reviewer: str = "local-reviewer"


class PhotoBarcodeRescanRequest(BaseModel):
    reviewer: str = "local-reviewer"
    category: str = ""


class GroupBarcodeManualConfirmRequest(BaseModel):
    actor: str = "local-reviewer"


class UrlImportRequest(BaseModel):
    rows: list[dict]


class UnmatchedAssociateRequest(BaseModel):
    actor: str = "local-reviewer"
    target_group_id: str = ""
    target_meter_no: str = ""
    updates: dict = {}


class UnmatchedCreateGroupRequest(BaseModel):
    actor: str = "local-reviewer"
    terminal: str
    updates: dict = {}


class UnmatchedDeleteRequest(BaseModel):
    actor: str = "local-reviewer"
    reason: str = ""


class UnmatchedDedupeRequest(BaseModel):
    actor: str = "module_admin"


class BlankUnmatchedRequest(BaseModel):
    actor: str = "local-reviewer"


class UnmatchedUpdateRequest(BaseModel):
    actor: str = "local-reviewer"
    updates: dict = {}


class UnmatchedAssignRequest(BaseModel):
    actor: str = "module_admin"
    constructor: str
    note: str = ""
    due_date: str = ""


class UnmatchedUnassignRequest(BaseModel):
    actor: str = "module_admin"
    reason: str = ""


class UnmatchedOutsideProjectRequest(BaseModel):
    actor: str = "local-reviewer"
    note: str = ""


class UnmatchedRematchRequest(BaseModel):
    actor: str = "local-reviewer"
    meter_no: str = ""
    old_meter_no: str = ""
    terminal: str = ""
    updates: dict = {}


class EmptyGroupRequest(BaseModel):
    actor: str = "local-reviewer"
    terminal: str = ""
    meter_no: str = ""
    address: str = ""
    meter_match_key: str = ""


class GroupTerminalRequest(BaseModel):
    actor: str = "local-reviewer"
    terminal: str


class GroupMetadataRequest(BaseModel):
    actor: str = "local-reviewer"
    updates: dict = {}


class AddGroupPhotosRequest(BaseModel):
    actor: str = "local-reviewer"
    photo_urls: list[str]
    collector: str = ""
    module_asset_no: str = ""
    creator: str = ""


class PhotoDeleteRequest(BaseModel):
    reviewer: str = "local-reviewer"


@router.post("/bootstrap")
def bootstrap(request: Request):
    return ok(request, state_repository().bootstrap())


@router.post("/scan/clear")
def clear_scan(request: Request):
    return ok(request, state_repository().clear_scan_data())


@router.post("/scan/import-url-rows")
def import_url_rows(payload: UrlImportRequest, request: Request):
    result = import_url_scan_rows_for_active_backend(payload.rows)
    result["oss_sync"] = state_repository().sync_photos_to_oss(team_id=current_request_team(request))
    return ok(request, result)


@router.post("/scan/import-template-xlsx")
async def import_template_xlsx(request: Request, file: UploadFile = File(...)):
    content = await file.read()
    result = import_scan_template_xlsx_for_active_backend(content)
    result["filename"] = file.filename
    result["oss_sync"] = state_repository().sync_photos_to_oss(team_id=current_request_team(request))
    return ok(request, result)


@router.post("/scan/import-template-xlsx/jobs")
async def create_import_template_xlsx_job(request: Request, file: UploadFile = File(...)):
    content = await file.read()
    team_id = current_request_team(request)
    job_id = uuid4().hex
    job = store_scan_import_job(
        job_id,
        {
            "job_id": job_id,
            "team_id": team_id,
            "filename": file.filename,
            "status": "queued",
            "created_at": now_iso(),
            "progress": {"phase": "queued", "processed_photos": 0},
        },
    )
    _scan_import_executor.submit(run_scan_import_job, job_id, team_id, content, file.filename)
    return ok(request, job)


@router.get("/scan/import-template-xlsx/jobs/{job_id}")
def get_import_template_xlsx_job(job_id: str, request: Request):
    try:
        return ok(request, read_scan_import_job(job_id, current_request_team(request)))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Import job not found") from exc


@router.post("/catalog/total/import-xlsx")
async def import_total_catalog(request: Request, file: UploadFile = File(...)):
    content = await file.read()
    result = import_total_catalog_xlsx_for_active_backend(content)
    result["filename"] = file.filename
    return ok(request, result)


@router.get("/summary")
def summary(request: Request, refresh: bool = Query(default=False)):
    forbid_constructor_project_board(request)
    team_id = current_team_id()
    return ok(
        request,
        project_board_summary_cache.get(
            team_id,
            lambda: state_repository().summary(),
            force_refresh=refresh,
        ),
    )


def build_photo_barcode_review_workbook(items: list[dict[str, Any]]) -> bytes:
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise RuntimeError("openpyxl is required to export Excel files") from exc
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "条码复核清单"
    headers = [
        "状态",
        "资料组状态",
        "是否已归档",
        "缺失项",
        "表号",
        "模块号",
        "采集器号",
        "终端",
        "地址",
        "安装人员",
        "资料组ID",
        "已识别表号",
        "已识别模块",
        "已识别采集器",
        "异常值",
        "照片数量",
        "照片链接",
    ]
    sheet.append(headers)
    status_labels = {"matched": "通过", "unreadable": "无法识别", "mismatched": "异常不匹配"}
    group_status_labels = {"approved": "已归档", "pending": "未审阅", "incomplete": "资料不完整", "exception": "异常"}
    for item in items:
        detected = item.get("detected_values") or {}
        photos = item.get("photos") or []
        photo_urls = [
            str(photo.get("image_url") or photo.get("thumbnail_url") or "").strip()
            for photo in photos
            if str(photo.get("image_url") or photo.get("thumbnail_url") or "").strip()
        ]
        sheet.append(
            [
                status_labels.get(str(item.get("status") or ""), str(item.get("status") or "")),
                group_status_labels.get(str(item.get("group_status") or ""), str(item.get("group_status") or "")),
                "是" if item.get("archived") else "否",
                "、".join(str(value) for value in item.get("missing_fields") or []),
                item.get("meter_no") or "",
                item.get("module_asset_no") or "",
                item.get("collector") or "",
                item.get("terminal") or "",
                item.get("address") or "",
                item.get("installer") or "",
                item.get("group_id") or "",
                "、".join(str(value) for value in detected.get("meter") or []),
                "、".join(str(value) for value in detected.get("module") or []),
                "、".join(str(value) for value in detected.get("collector") or []),
                "、".join(str(value) for value in item.get("unmatched_values") or []),
                item.get("photo_count") or len(photos),
                "\n".join(photo_urls),
            ]
        )
    for column_cells in sheet.columns:
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        sheet.column_dimensions[column_cells[0].column_letter].width = min(max(max_length + 2, 10), 56)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def excel_response(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/photo-barcode/review-groups/export")
def export_photo_barcode_review_groups(
    request: Request,
    status: str = Query(default="unreadable"),
    query: str = Query(default=""),
    _admin: dict = Depends(require_admin),
):
    payload = state_repository().list_photo_barcode_review_groups(status=status, query=query, limit=100000, offset=0)
    content = build_photo_barcode_review_workbook(payload.get("items") or [])
    filename = f"photo-barcode-review-{status}-{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
    return excel_response(content, filename)


@router.get("/photo-barcode/review-groups")
def photo_barcode_review_groups(
    request: Request,
    status: str = Query(default="unreadable"),
    query: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _admin: dict = Depends(require_admin),
):
    return ok(
        request,
        state_repository().list_photo_barcode_review_groups(status=status, query=query, limit=limit, offset=offset),
    )


@router.get("/events")
async def local_events(request: Request, scope: str = Query(default="project-board")):
    if scope == "project-board":
        forbid_constructor_project_board(request)

    async def stream():
        sequence = 0
        ready_payload = {
            "type": "board-events-ready",
            "scope": scope,
            "interval_seconds": BOARD_EVENT_INTERVAL_SECONDS,
            "generated_at": datetime.now(UTC).isoformat(),
        }
        yield f"event: board-ready\ndata: {json.dumps(ready_payload, ensure_ascii=False)}\n\n"
        while True:
            await asyncio.sleep(BOARD_EVENT_INTERVAL_SECONDS)
            sequence += 1
            payload = {
                "type": "board-refresh",
                "scope": scope,
                "sequence": sequence,
                "interval_seconds": BOARD_EVENT_INTERVAL_SECONDS,
                "generated_at": datetime.now(UTC).isoformat(),
            }
            yield f"event: board-refresh\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/installers/{installer}/daily-workload")
def installer_daily_workload(installer: str, request: Request):
    forbid_constructor_project_board(request)
    return ok(request, state_repository().installer_daily_workload(installer))


@router.get("/teams")
def teams(request: Request):
    return ok(request, {"items": state_repository().list_team_states()})


@router.get("/export-manifest/final-delivery")
def final_delivery_manifest(
    request: Request,
    task_id: int | None = Query(default=None),
    terminal: str = "",
    review_scope: str = Query(default="reviewed"),
):
    try:
        manifest = state_repository().build_final_delivery_manifest(
            task_id=task_id,
            terminal=terminal,
            review_scope=review_scope,
        )
        return ok(request, resolve_manifest_for_response(manifest))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/delivery-cache/{group_id}/{photo_id}")
def delivery_cache_photo(group_id: str, photo_id: str):
    try:
        path = state_repository().get_delivery_cached_photo_path(group_id, photo_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Cached photo not found") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Cached photo not ready") from exc
    media_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=86400"})


def _read_remote_image(url: str, *, max_bytes: int = 30 * 1024 * 1024) -> tuple[bytes, str]:
    try:
        upstream_request = UrlRequest(
            url,
            headers={
                "User-Agent": "module-manager-v2-photo-view/1.0",
                "Accept": "image/*,*/*;q=0.8",
            },
        )
        with urlopen(upstream_request, timeout=30) as upstream:
            content_type = upstream.headers.get("Content-Type") or "application/octet-stream"
            expected_length = upstream.headers.get("Content-Length", "")
            content = upstream.read(max_bytes + 1)
    except OSError as exc:
        raise HTTPException(status_code=502, detail=f"Image download failed: {exc}") from exc
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail="Image is too large")
    if expected_length and expected_length.isdigit() and len(content) != int(expected_length):
        raise HTTPException(status_code=502, detail="Image download is incomplete")
    try:
        validate_image_content(content, content_type, url)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return content, content_type


def _source_url_for_photo(photo: dict) -> str:
    raw_data = photo.get("raw_data") if isinstance(photo.get("raw_data"), dict) else {}
    for key in ("source_url", "pre_oss_image_url", "url", "image_url"):
        value = str(photo.get(key) or raw_data.get(key) or "").strip()
        if value.startswith(("http://", "https://")):
            return value
    return ""


def _persist_repaired_photo_storage(group_id: str, photo: dict) -> None:
    if settings.state_backend.lower() not in {"postgres", "dual"}:
        return
    photo_id = str(photo.get("id") or "").strip()
    if not photo_id:
        return
    try:
        with SessionLocal() as session:
            group = session.scalar(
                select(MaterialGroup).where(
                    MaterialGroup.team_id == current_team_id(),
                    MaterialGroup.legacy_id == group_id,
                )
            )
            if group is None:
                return
            record = session.scalar(
                select(Photo).where(
                    Photo.team_id == current_team_id(),
                    Photo.group_id == group.id,
                    Photo.legacy_id == photo_id,
                    Photo.is_active.is_(True),
                )
            )
            if record is None:
                return
            record.image_url = str(photo.get("image_url") or "")
            record.storage_type = str(photo.get("storage_type") or "")
            record.storage_bucket = str(photo.get("storage_bucket") or "")
            record.storage_key = str(photo.get("storage_key") or "")
            record.sha256 = str(photo.get("sha256") or record.sha256)
            record.object_key = str(photo.get("storage_key") or record.object_key or photo.get("image_url") or "")
            record.byte_size = int(photo.get("byte_size") or 0) or record.byte_size
            record.content_type = str(photo.get("content_type") or record.content_type or "image/jpeg")
            raw_data = dict(record.raw_data or {})
            if isinstance(photo.get("raw_data"), dict):
                raw_data.update(photo["raw_data"])
            raw_data.update(
                {
                    "image_url": record.image_url,
                    "storage_type": record.storage_type,
                    "storage_bucket": record.storage_bucket,
                    "storage_key": record.storage_key,
                    "sha256": record.sha256,
                    "byte_size": record.byte_size,
                    "content_type": record.content_type,
                    "delivery_cache_status": "stale",
                    "delivery_cache_path": "",
                    "delivery_cache_version": record.sha256,
                    "repaired_at": photo.get("repaired_at", now_iso()),
                }
            )
            record.raw_data = raw_data
            session.commit()
    except Exception:
        # Preview repair must not take down the review page. The current request
        # still returns the recovered image; persistence can be retried later.
        return


def _replace_photo_storage_from_source(group_id: str, photo: dict, source_url: str) -> tuple[bytes, str]:
    content, media_type = _read_remote_image(source_url)
    filename = str(photo.get("archive_filename") or photo.get("original_filename") or f"{photo.get('id') or 'photo'}.jpg")
    saved = save_image_bytes(
        scope="repaired-photos",
        filename=filename,
        content=content,
        content_type=media_type,
        team_id=current_team_id(),
        group_id=group_id,
        key_hint=str(photo.get("id") or ""),
    )
    now = datetime.now(UTC).isoformat()
    raw_data = photo.setdefault("raw_data", {})
    if isinstance(raw_data, dict):
        raw_data.update(
            {
                "repair_source_url": source_url,
                "repair_previous_image_url": photo.get("image_url", ""),
                "repair_previous_storage_key": photo.get("storage_key", ""),
                "repaired_at": now,
            }
        )
    photo.update(
        {
            "image_url": saved["url"],
            "storage_type": saved.get("storage_type", ""),
            "storage_key": saved.get("storage_key", ""),
            "storage_bucket": saved.get("storage_bucket", ""),
            "sha256": saved.get("sha256") or hashlib.sha256(content).hexdigest(),
            "byte_size": len(content),
            "content_type": media_type,
            "download_status": "downloaded",
            "delivery_cache_status": "stale",
            "delivery_cache_path": "",
            "delivery_cache_version": saved.get("sha256") or hashlib.sha256(content).hexdigest(),
            "repaired_at": now,
        }
    )
    _persist_repaired_photo_storage(group_id, photo)
    return content, media_type


def _looks_like_gray_placeholder(content: bytes) -> bool:
    try:
        from PIL import Image, ImageStat

        image = Image.open(BytesIO(content)).convert("RGB")
        image.load()
        width, height = image.size
        if width < 20 or height < 20:
            return False
        crop = image.crop((int(width * 0.15), int(height * 0.15), int(width * 0.85), int(height * 0.85)))
        sample = crop.resize((80, 80))
        raw_pixels = sample.tobytes()
        gray_pixels = 0
        for index in range(0, len(raw_pixels), 3):
            red, green, blue = raw_pixels[index], raw_pixels[index + 1], raw_pixels[index + 2]
            if abs(red - green) < 3 and abs(green - blue) < 3 and 105 <= red <= 175:
                gray_pixels += 1
        gray_ratio = gray_pixels / 6400
        average_stddev = sum(ImageStat.Stat(crop).stddev) / 3
        return gray_ratio > 0.75 and average_stddev < 25
    except Exception:
        return False


def _looks_like_vertical_artifact(content: bytes) -> bool:
    try:
        from PIL import Image, ImageStat

        image = Image.open(BytesIO(content)).convert("RGB")
        image.load()
        width, height = image.size
        if width < 80 or height < 80:
            return False
        crop = image.crop((int(width * 0.12), int(height * 0.08), int(width * 0.88), int(height * 0.92))).resize((160, 90))
        columns: list[tuple[float, float, float]] = []
        flat_columns = 0
        for x in range(crop.width):
            column = crop.crop((x, 0, x + 1, crop.height))
            stat = ImageStat.Stat(column)
            average_stddev = sum(stat.stddev) / 3
            if average_stddev < 7:
                flat_columns += 1
            columns.append(tuple(stat.mean))
        if flat_columns / crop.width < 0.45:
            return False
        transitions = []
        for index in range(1, len(columns)):
            left = columns[index - 1]
            right = columns[index]
            transitions.append(sum(abs(left[channel] - right[channel]) for channel in range(3)) / 3)
        strong_transitions = sum(1 for value in transitions if value > 22)
        average_transition = sum(transitions) / len(transitions)
        return strong_transitions >= 18 and average_transition > 10
    except Exception:
        return False


def _looks_like_broken_processed_image(content: bytes) -> bool:
    return _looks_like_gray_placeholder(content) or _looks_like_vertical_artifact(content)


def _read_oss_photo_or_repair(
    group_id: str,
    photo: dict,
    storage_key: str,
    parsed_key: str,
    process: str,
    *,
    kind: str = "preview",
) -> tuple[bytes, str]:
    key = storage_key or parsed_key
    try:
        content, media_type = _read_remote_image(sign_oss_server_url(key, process))
    except HTTPException as exc:
        source_url = _source_url_for_photo(photo)
        if not source_url:
            raise
        try:
            repaired_content, repaired_media_type = _replace_photo_storage_from_source(group_id, photo, source_url)
        except HTTPException:
            raise exc
        if process:
            return repaired_content, repaired_media_type
        return repaired_content, repaired_media_type
    source_url = _source_url_for_photo(photo)
    stored_size = int(photo.get("byte_size") or 0)
    broken_processed_image = process and _looks_like_broken_processed_image(content)
    suspicious_processed_image = bool(source_url) and (
        len(content) < 80_000
        or (stored_size and stored_size < 100_000)
        or broken_processed_image
    )
    if broken_processed_image:
        try:
            return _read_remote_image(sign_oss_server_url(key, ""))
        except HTTPException:
            if source_url.startswith(("http://", "https://")):
                return _replace_photo_storage_from_source(group_id, photo, source_url)
            raise
    if suspicious_processed_image:
        try:
            _read_remote_image(sign_oss_server_url(key, ""))
        except HTTPException:
            return _replace_photo_storage_from_source(group_id, photo, source_url)
        if source_url.startswith(("http://", "https://")) and _looks_like_broken_processed_image(content):
            return _replace_photo_storage_from_source(group_id, photo, source_url)
    return content, media_type


def _local_upload_file_response(url: str) -> FileResponse | None:
    if not url.startswith("/static/uploads/"):
        return None
    root = static_upload_root().resolve()
    target = (root / url.removeprefix("/static/uploads/")).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    if not target.exists() or not target.is_file():
        return None
    media_type = mimetypes.guess_type(target.name)[0] or "image/jpeg"
    return FileResponse(target, media_type=media_type, headers={"Cache-Control": "private, max-age=86400"})


@router.get("/groups/{group_id}/photos/{photo_id}/content")
def group_photo_content(group_id: str, photo_id: str, kind: str = Query(default="preview")):
    group = state_repository().get_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    photo = next((item for item in group.get("photos", []) if str(item.get("id") or "") == str(photo_id)), None)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    normalized_kind = kind if kind in {"thumbnail", "preview", "original"} else "preview"
    if normalized_kind in {"preview", "original"} and settings.state_backend.lower() != "postgres":
        try:
            path = state_repository().get_delivery_cached_photo_path(group_id, photo_id)
            media_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
            if path.stat().st_size < 80_000 and _source_url_for_photo(photo):
                content, repaired_media_type = _replace_photo_storage_from_source(group_id, photo, _source_url_for_photo(photo))
                return Response(
                    content=content,
                    media_type=repaired_media_type or media_type,
                    headers={"Cache-Control": "private, no-store"},
                )
            return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=86400"})
        except (KeyError, FileNotFoundError):
            pass

    image_url = str(photo.get("image_url") or "").strip()
    storage_type = str(photo.get("storage_type") or "").strip()
    storage_key = str(photo.get("storage_key") or "").strip()

    if storage_type == "oss" or image_url.startswith("oss://"):
        _, parsed_key = parse_oss_image_url(image_url)
        process = (
            settings.oss_thumbnail_process
            if normalized_kind == "thumbnail"
            else settings.oss_preview_process
            if normalized_kind == "preview"
            else ""
        )
        content, media_type = _read_oss_photo_or_repair(group_id, photo, storage_key, parsed_key, process, kind=normalized_kind)
        return Response(content=content, media_type=media_type, headers={"Cache-Control": "private, max-age=600"})

    resolved_url = (
        resolve_photo_thumbnail_url(photo)
        if normalized_kind == "thumbnail"
        else resolve_photo_preview_url(photo)
        if normalized_kind == "preview"
        else resolve_photo_image_url(photo)
    )
    if not resolved_url:
        resolved_url = _source_url_for_photo(photo)
    local_response = _local_upload_file_response(str(resolved_url or ""))
    if local_response is not None:
        return local_response
    parsed = urlparse(str(resolved_url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=404, detail="Photo has no readable image source")
    content, media_type = _read_remote_image(str(resolved_url))
    return Response(content=content, media_type=media_type, headers={"Cache-Control": "private, max-age=600"})


@router.get("/photo-proxy")
def photo_proxy(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid image URL")
    try:
        content, media_type = _read_remote_image(url, max_bytes=20_000_000)
    except HTTPException:
        raise
    return Response(content=content, media_type=media_type)


@router.get("/groups")
def groups(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    status: str | None = None,
):
    return ok(
        request,
        resolve_group_collection_for_response(
            state_repository().list_groups(limit=limit, offset=offset, status=status)
        ),
    )


@router.get("/group-targets")
def group_targets(
    request: Request,
    query: str = "",
    terminal: str = "",
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    if settings.app_env.lower() in {"prod", "production"} and not request_is_admin(request):
        raise HTTPException(status_code=403, detail="Only administrators can search group targets")
    return ok(
        request,
        state_repository().search_group_targets(query=query, terminal=terminal, limit=limit, offset=offset),
    )


@router.get("/catalog/{catalog_type}")
def catalog_rows(
    catalog_type: str,
    request: Request,
    query: str = "",
    terminal: str = "",
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    try:
        result = state_repository().list_catalog_rows(
            catalog_type,
            query=query,
            terminal=terminal,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, result)


@router.get("/unmatched")
def unmatched_records(
    request: Request,
    query: str = "",
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    return ok(request, state_repository().list_unmatched_records(query=query, limit=limit, offset=offset))


@router.get("/replacements")
def replacement_records(
    request: Request,
    query: str = "",
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    return ok(request, state_repository().list_replacement_records(query=query, limit=limit, offset=offset))


@router.post("/unmatched/dedupe")
def dedupe_unmatched(payload: UnmatchedDedupeRequest, request: Request):
    return ok(request, state_repository().dedupe_unmatched_records(actor=payload.actor))


@router.post("/unmatched/blank")
def create_blank_unmatched(payload: BlankUnmatchedRequest, request: Request):
    return ok(request, state_repository().create_blank_unmatched_record(actor=payload.actor))


@router.patch("/unmatched/{unmatched_id}")
def update_unmatched(unmatched_id: str, payload: UnmatchedUpdateRequest, request: Request):
    try:
        record = state_repository().update_unmatched_record(
            unmatched_id,
            actor=payload.actor,
            updates=payload.updates,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unmatched record not found") from exc
    return ok(request, record)


@router.patch("/unmatched/{unmatched_id}/assign")
def assign_unmatched(unmatched_id: str, payload: UnmatchedAssignRequest, request: Request):
    try:
        record = state_repository().assign_unmatched_record(
            unmatched_id,
            actor=payload.actor,
            constructor=payload.constructor,
            note=payload.note,
            due_date=payload.due_date,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unmatched record not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, record)


@router.patch("/unmatched/{unmatched_id}/unassign")
def unassign_unmatched(unmatched_id: str, payload: UnmatchedUnassignRequest, request: Request):
    try:
        record = state_repository().unassign_unmatched_record(
            unmatched_id,
            actor=payload.actor,
            reason=payload.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unmatched record not found") from exc
    return ok(request, record)


@router.post("/unmatched/{unmatched_id}/outside-project")
def mark_unmatched_outside_project(unmatched_id: str, payload: UnmatchedOutsideProjectRequest, request: Request):
    try:
        record = state_repository().mark_unmatched_outside_project(
            unmatched_id,
            actor=payload.actor,
            note=payload.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unmatched record not found") from exc
    return ok(request, record)


@router.post("/unmatched/{unmatched_id}/rematch")
def rematch_unmatched(unmatched_id: str, payload: UnmatchedRematchRequest, request: Request):
    try:
        result = state_repository().rematch_unmatched_record(
            unmatched_id,
            actor=payload.actor,
            meter_no=payload.meter_no,
            old_meter_no=payload.old_meter_no,
            terminal=payload.terminal,
            updates=payload.updates,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unmatched record not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, response_payload(result))


@router.get("/exception-groups")
def exception_groups(
    request: Request,
    reviewer: str = "",
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    return ok(
        request,
        resolve_group_collection_for_response(
            state_repository().list_exception_groups(reviewer=reviewer, limit=limit, offset=offset)
        ),
    )


@router.post("/unmatched/{unmatched_id}/associate")
def associate_unmatched(unmatched_id: str, payload: UnmatchedAssociateRequest, request: Request):
    try:
        result = state_repository().associate_unmatched_record(
            unmatched_id,
            actor=payload.actor,
            target_group_id=payload.target_group_id,
            target_meter_no=payload.target_meter_no,
            updates=payload.updates,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unmatched record not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, response_payload(result))


@router.post("/unmatched/{unmatched_id}/create-group")
def create_group_from_unmatched(unmatched_id: str, payload: UnmatchedCreateGroupRequest, request: Request):
    try:
        result = state_repository().create_group_from_unmatched_record(
            unmatched_id,
            actor=payload.actor,
            terminal=payload.terminal,
            updates=payload.updates,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unmatched record not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, response_payload(result))


@router.post("/unmatched/{unmatched_id}/delete")
def delete_unmatched(unmatched_id: str, payload: UnmatchedDeleteRequest, request: Request):
    try:
        record = state_repository().delete_unmatched_record(unmatched_id, actor=payload.actor, reason=payload.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unmatched record not found") from exc
    return ok(request, record)


@router.get("/audit-log")
def audit_log(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    return ok(request, state_repository().list_audit_events(limit=limit, offset=offset))


@router.get("/tasks")
def tasks(request: Request, summary: bool = Query(default=False)):
    return ok(request, {"items": state_repository().list_tasks(summary_only=summary)})


@router.get("/tasks/status")
def task_status(request: Request):
    forbid_constructor_project_board(request)
    return ok(request, state_repository().task_status())


@router.get("/tasks/{task_id}/groups")
def task_groups(
    task_id: int,
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    status: str | None = None,
    scan_only: bool = Query(default=False),
    summary: bool = Query(default=False),
):
    try:
        result = state_repository().list_task_groups(
            task_id,
            limit=limit,
            offset=offset,
            status=status,
            scan_only=scan_only,
            summary_only=summary,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    return ok(request, resolve_group_collection_for_response(result))


@router.get("/tasks/{task_id}/progress")
def task_progress(task_id: int, request: Request):
    try:
        progress = state_repository().get_task_progress(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    return ok(request, progress)


@router.post("/tasks/{task_id}/claim")
def claim(task_id: int, payload: ClaimRequest, request: Request):
    try:
        task = state_repository().claim_task(task_id, payload.reviewer)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, task)


@router.post("/tasks/{task_id}/release")
def release(task_id: int, payload: ClaimRequest, request: Request):
    try:
        task = state_repository().release_task(task_id, payload.reviewer, force=request_is_admin(request))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, task)


@router.post("/tasks/release-all")
def release_all(payload: ClaimRequest, request: Request):
    if not request_is_admin(request):
        raise HTTPException(status_code=403, detail="Only administrators can release all tasks")
    return ok(request, state_repository().release_all_claimed_tasks(payload.reviewer))


@router.get("/construction/tasks")
def construction_tasks(
    request: Request,
    actor: str = "",
    include_closed: bool = Query(default=False),
):
    return ok(request, {"items": state_repository().list_construction_tasks(actor=actor, include_closed=include_closed)})


@router.patch("/construction/tasks/{task_id}/open")
def construction_task_open(task_id: int, payload: ConstructionActorRequest, request: Request):
    if not request_is_admin(request):
        raise HTTPException(status_code=403, detail="Only administrators can open construction tasks")
    try:
        task = state_repository().open_construction_task(task_id, payload.actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    return ok(request, task)


@router.patch("/construction/tasks/{task_id}/close")
def construction_task_close(task_id: int, payload: ConstructionActorRequest, request: Request):
    if not request_is_admin(request):
        raise HTTPException(status_code=403, detail="Only administrators can close construction tasks")
    try:
        task = state_repository().close_construction_task(task_id, payload.actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    return ok(request, task)


@router.patch("/construction/tasks/{task_id}/assign")
def construction_task_assign(task_id: int, payload: ConstructionAssignRequest, request: Request):
    if not request_is_admin(request):
        raise HTTPException(status_code=403, detail="Only administrators can assign construction tasks")
    try:
        task = state_repository().assign_construction_task(
            task_id,
            actor=payload.actor,
            constructor=payload.constructor,
            note=payload.note,
            due_date=payload.due_date,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, task)


@router.patch("/construction/tasks/{task_id}/unassign")
def construction_task_unassign(task_id: int, payload: ConstructionActorRequest, request: Request):
    if not request_is_admin(request):
        raise HTTPException(status_code=403, detail="Only administrators can unassign construction tasks")
    try:
        task = state_repository().unassign_construction_task(task_id, actor=payload.actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    return ok(request, task)


@router.get("/construction/my-tasks")
def construction_my_tasks(request: Request, actor: str = "constructor"):
    return ok(request, {"items": state_repository().list_construction_tasks(actor=actor, include_closed=False)})


@router.post("/construction/tasks/{task_id}/claim")
def construction_task_claim(task_id: int, payload: ConstructionActorRequest, request: Request):
    try:
        task = state_repository().claim_construction_task(task_id, payload.actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, task)


@router.get("/construction/exception-orders")
def construction_exception_order_list(
    request: Request,
    actor: str = "",
    task_id: int | None = None,
):
    return ok(request, {"items": state_repository().list_construction_exception_orders(actor=actor, task_id=task_id)})


@router.patch("/construction/exception-orders/{order_id}/assign")
def construction_exception_order_assign(order_id: str, payload: ConstructionExceptionAssignRequest, request: Request):
    try:
        result = state_repository().assign_construction_exception_order(
            order_id,
            actor=payload.actor,
            constructor=payload.constructor,
            note=payload.note,
            due_date=payload.due_date,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Exception order not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, response_payload(result))


@router.patch("/construction/exception-orders/{order_id}/unassign")
def construction_exception_order_unassign(order_id: str, payload: ConstructionExceptionUnassignRequest, request: Request):
    try:
        result = state_repository().unassign_construction_exception_order(
            order_id,
            actor=payload.actor,
            reason=payload.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Exception order not found") from exc
    return ok(request, response_payload(result))


@router.patch("/construction/exception-orders/{order_id}/submit")
def construction_exception_order_submit(order_id: str, payload: ConstructionExceptionSubmitRequest, request: Request):
    try:
        result = state_repository().submit_construction_exception_order(
            order_id,
            actor=payload.actor,
            updates=payload.updates,
            note=payload.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Exception order not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, response_payload(result))


@router.post("/construction/tasks/{task_id}/release")
def construction_task_release(task_id: int, payload: ConstructionActorRequest, request: Request):
    try:
        task = state_repository().release_construction_task(task_id, payload.actor, force=request_is_admin(request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, task)


@router.post("/construction/heartbeat")
def construction_heartbeat(payload: ConstructionHeartbeatRequest, request: Request):
    actor = bound_construction_actor(request, payload.actor)
    try:
        event = state_repository().record_construction_activity_event(
            event_type="construction_heartbeat",
            actor=actor,
            task_id=payload.task_id,
            occurred_at=payload.occurred_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, event)


@router.post("/construction/non-idle-events")
def construction_non_idle_event(payload: ConstructionNonIdleEventRequest, request: Request):
    if payload.event_type not in {"group_draft_completed", "group_draft_deleted", "group_uploaded"}:
        raise HTTPException(status_code=400, detail="Unsupported construction non-idle event")
    actor = bound_construction_actor(request, payload.actor)
    try:
        event = state_repository().record_construction_activity_event(
            event_type=payload.event_type,
            actor=actor,
            task_id=payload.task_id,
            group_id=payload.group_id,
            client_batch_id=payload.client_batch_id,
            occurred_at=payload.occurred_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, event)


@router.get("/construction/tasks/{task_id}/groups")
def construction_task_groups(
    task_id: int,
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    status: str | None = None,
    summary: bool = Query(default=False),
):
    try:
        result = state_repository().list_construction_task_groups(
            task_id,
            limit=limit,
            offset=offset,
            status=status,
            summary_only=summary,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    return ok(request, resolve_group_collection_for_response(result))


@router.post("/construction/groups/{group_id}/upload-batch")
async def construction_group_upload_batch(
    group_id: str,
    request: Request,
    actor: str = Form(default="constructor"),
    client_batch_id: str = Form(default=""),
    client_completed_at: str = Form(default=""),
    collector: str = Form(default=""),
    module_asset_no: str = Form(default=""),
    photo_slots: list[str] = Form(default=[]),
    client_photo_ids: list[str] = Form(default=[]),
    files: list[UploadFile] = File(default=[]),
):
    if is_all_zero_construction_code(group_id):
        raise HTTPException(status_code=400, detail="No work order: 00000000 placeholder group cannot upload")
    actor = bound_construction_actor(request, actor)
    validate_construction_upload_group_before_file_save(group_id)
    if not files:
        raise HTTPException(status_code=400, detail="At least one image file is required")
    records: list[dict] = []
    for index, file in enumerate(files):
        filename = file.filename or f"photo-{index + 1}.jpg"
        try:
            normalize_suffix(filename)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        content = await file.read()
        if not content:
            continue
        client_photo_id = client_photo_ids[index] if index < len(client_photo_ids) else f"photo-{index + 1}"
        slot = photo_slots[index] if index < len(photo_slots) else "other"
        try:
            stored = save_image_bytes(
                scope="construction",
                filename=filename,
                content=content,
                content_type=file.content_type or "",
                team_id=current_request_team(request),
                group_id=group_id,
                key_hint=f"{group_id}-{client_batch_id[:16] or 'batch'}-{client_photo_id[:16]}",
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        records.append(
            {
                "url": stored["url"],
                "sha256": stored["sha256"],
                "client_photo_id": client_photo_id,
                "client_completed_at": client_completed_at,
                "slot": slot,
                "filename": filename,
                "storage_type": stored["storage_type"],
                "storage_key": stored["storage_key"],
                "storage_bucket": stored.get("storage_bucket", ""),
                "storage_source": stored["storage_source"],
            }
        )
    if not records:
        raise HTTPException(status_code=400, detail="Uploaded images are empty")
    try:
        result = state_repository().upload_construction_group_batch(
            group_id,
            actor=actor,
            client_batch_id=client_batch_id,
            collector=collector,
            module_asset_no=module_asset_no,
            photos=records,
            creator=display_name_for_actor(request, actor),
            client_completed_at=client_completed_at,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, {**response_payload(result), "uploaded_urls": [item["url"] for item in records]})


@router.get("/groups/{group_id}")
def group_detail(group_id: str, request: Request):
    group = state_repository().get_group(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return ok(request, resolve_group_for_response(group))


@router.post("/groups")
def create_empty_group(payload: EmptyGroupRequest, request: Request):
    try:
        result = state_repository().create_empty_group_for_terminal(
            terminal=payload.terminal,
            actor=payload.actor,
            meter_no=payload.meter_no,
            address=payload.address,
            meter_match_key=payload.meter_match_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, response_payload(result))


@router.patch("/groups/{group_id}/terminal")
def change_group_terminal(group_id: str, payload: GroupTerminalRequest, request: Request):
    admin_payload = require_production_admin_payload(request)
    actor = str(admin_payload.get("username") or admin_payload.get("sub") or payload.actor or "admin").strip() or "admin"
    try:
        result = state_repository().update_group_terminal(group_id, terminal=payload.terminal, actor=actor)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, response_payload(result))


@router.patch("/groups/{group_id}/metadata")
def change_group_metadata(group_id: str, payload: GroupMetadataRequest, request: Request):
    admin_payload = request_auth_payload(request)
    if settings.app_env.lower() in {"prod", "production"}:
        privileged_fields = {
            "terminal",
            "status",
            "reviewer",
            "review_note",
            "exception_note",
            "construction_collector",
            "construction_module_asset_no",
        }
        if privileged_fields.intersection(payload.updates or {}):
            admin_payload = require_production_admin_payload(request)
    actor = str(admin_payload.get("username") or admin_payload.get("sub") or payload.actor or "admin").strip() or "admin"
    try:
        result = state_repository().update_group_metadata(group_id, actor=actor, updates=payload.updates)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc
    return ok(request, response_payload(result))


@router.post("/groups/{group_id}/photos/import-urls")
def import_group_photo_urls(group_id: str, payload: AddGroupPhotosRequest, request: Request):
    try:
        result = state_repository().add_photo_urls_to_group(
            group_id,
            actor=payload.actor,
            photo_urls=payload.photo_urls,
            collector=payload.collector,
            module_asset_no=payload.module_asset_no,
            creator=payload.creator,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc
    return ok(request, response_payload(result))


@router.post("/groups/{group_id}/photos/upload-images")
async def upload_group_photo_images(
    group_id: str,
    request: Request,
    actor: str = Form(default="admin"),
    collector: str = Form(default=""),
    module_asset_no: str = Form(default=""),
    creator: str = Form(default="人工补图"),
    files: list[UploadFile] = File(default=[]),
):
    if not files:
        raise HTTPException(status_code=400, detail="At least one image file is required")
    saved_urls: list[str] = []
    photo_metadata: dict[str, dict] = {}
    for file in files:
        filename = file.filename or "manual-photo.jpg"
        try:
            normalize_suffix(filename)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        content = await file.read()
        if not content:
            continue
        try:
            stored = save_image_bytes(
                scope="manual",
                filename=filename,
                content=content,
                content_type=file.content_type or "",
                team_id=current_request_team(request),
                group_id=group_id,
                key_hint=f"{group_id}-{uuid4().hex[:16]}",
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        url = stored["url"]
        saved_urls.append(url)
        photo_metadata[url] = {
            "sha256": stored["sha256"],
            "storage_type": stored["storage_type"],
            "storage_key": stored["storage_key"],
            "storage_bucket": stored.get("storage_bucket", ""),
            "storage_source": stored["storage_source"],
        }
    if not saved_urls:
        raise HTTPException(status_code=400, detail="Uploaded images are empty")
    try:
        result = state_repository().add_photo_urls_to_group(
            group_id,
            actor=actor,
            photo_urls=saved_urls,
            collector=collector,
            module_asset_no=module_asset_no,
            creator=creator,
            photo_metadata=photo_metadata,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc
    return ok(request, {**response_payload(result), "uploaded_urls": saved_urls})


@router.patch("/groups/{group_id}/review")
def save_review(group_id: str, payload: ReviewRequest, request: Request):
    try:
        group = state_repository().review_group(
            group_id,
            payload.status,
            payload.reviewer,
            payload.note,
            payload.exception_note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, resolve_group_for_response(group))


@router.post("/groups/{group_id}/exception")
def mark_exception(group_id: str, payload: ExceptionNoteRequest, request: Request):
    try:
        group = state_repository().save_exception_note(group_id, reviewer=payload.reviewer, note=payload.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, resolve_group_for_response(group))


@router.patch("/groups/{group_id}/reset-unconstructed")
def reset_group_unconstructed(group_id: str, payload: GroupResetRequest, request: Request):
    try:
        result = state_repository().reset_group_to_unconstructed(
            group_id,
            actor=payload.actor,
            reason=payload.reason,
            force=request_is_admin(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, response_payload(result))


@router.patch("/groups/{group_id}/return-exception")
def return_group_exception_order(group_id: str, payload: GroupExceptionOrderRequest, request: Request):
    try:
        result = state_repository().return_group_to_exception_order(
            group_id,
            actor=payload.actor,
            category=payload.category,
            note=payload.note,
            force=request_is_admin(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, response_payload(result))


@router.patch("/groups/{group_id}/photos/{photo_id}/category")
def save_photo_category(
    group_id: str,
    photo_id: str,
    payload: PhotoClassifyRequest,
    request: Request,
    include_group: bool = Query(default=False),
):
    try:
        repo = state_repository()
        photo = repo.classify_photo(group_id, photo_id, payload.category, payload.reviewer)
        invalidate_project_board_summary_cache()
        if include_group:
            group = repo.get_group(group_id)
            return ok(
                request,
                {"photo": resolve_photo_for_response(photo), "group": response_group_target_summary(group)},
            )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Photo or group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, resolve_photo_for_response(photo))


@router.post("/groups/{group_id}/photos/{photo_id}/barcode-rescan")
def rescan_photo_barcode(
    group_id: str,
    photo_id: str,
    payload: PhotoBarcodeRescanRequest,
    request: Request,
    include_group: bool = Query(default=False),
):
    try:
        repo = state_repository()
        reviewer = bound_review_actor(request, payload.reviewer)
        photo = repo.rescan_photo_barcode(group_id, photo_id, reviewer, payload.category)
        invalidate_project_board_summary_cache()
        if include_group:
            group = repo.get_group(group_id)
            return ok(
                request,
                {"photo": resolve_photo_for_response(photo), "group": response_group_target_summary(group)},
            )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Photo or group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, resolve_photo_for_response(photo))


@router.post("/groups/{group_id}/barcode-manual-confirm")
def confirm_group_barcode_manually(
    group_id: str,
    payload: GroupBarcodeManualConfirmRequest,
    request: Request,
):
    try:
        actor = bound_review_actor(request, payload.actor)
        result = state_repository().confirm_group_barcode_manually(group_id, actor=actor)
        invalidate_project_board_summary_cache()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, response_payload(result))


@router.delete("/groups/{group_id}/photos/{photo_id}")
def delete_photo(group_id: str, photo_id: str, payload: PhotoDeleteRequest, request: Request):
    try:
        result = state_repository().delete_photo(group_id, photo_id, payload.reviewer)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Photo or group not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, response_payload(result))
