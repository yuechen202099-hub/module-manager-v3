from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.models import (  # noqa: E402
    AuditLog,
    GroupStatus,
    MaterialGroup,
    MigrationRun,
    Photo,
    PhotoEvent,
    PhotoUploadStatus,
    Project,
    ProjectStatus,
    ReviewRecord,
    ReviewResult,
    Role,
    Task,
    TaskStatus,
    Team,
    TotalCatalogRow,
    UnmatchedRecord,
    User,
    UserRole,
    UserStatus,
)

ROLE_NAMES = ("admin", "reviewer", "constructor")
TASK_STATUS_MAP = {
    "draft": TaskStatus.DRAFT,
    "published": TaskStatus.PUBLISHED,
    "in_review": TaskStatus.CLAIMED,
    "claimed": TaskStatus.CLAIMED,
    "completed": TaskStatus.COMPLETED,
    "released": TaskStatus.RELEASED,
    "cancelled": TaskStatus.CANCELLED,
}
GROUP_STATUS_MAP = {
    "unreviewed": GroupStatus.UNREVIEWED,
    "in_review": GroupStatus.IN_REVIEW,
    "pending": GroupStatus.UNREVIEWED,
    "incomplete": GroupStatus.INCOMPLETE,
    "approved": GroupStatus.APPROVED,
    "exception": GroupStatus.REJECTED,
    "unmatched": GroupStatus.REJECTED,
    "rejected": GroupStatus.REJECTED,
}


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_sha256(*parts: Any) -> str:
    payload = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_source_url(value: Any) -> str:
    url = safe_text(value)
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return url
    volatile_keys = {
        "access_token",
        "expires",
        "expire",
        "signature",
        "sign",
        "token",
        "x-oss-expires",
        "x-oss-signature",
        "x-oss-signature-version",
        "x-oss-security-token",
    }
    clean_query = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in volatile_keys
    ]
    clean_query.sort()
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path,
            "",
            urlencode(clean_query, doseq=True),
            "",
        )
    )


def source_url_hash(value: Any) -> str:
    normalized = normalize_source_url(value)
    return stable_sha256(normalized) if normalized else ""


def source_fingerprint(raw: dict[str, Any], *, team_id: str, group_legacy_id: str, legacy_id: str, index: int) -> str:
    explicit = safe_text(raw.get("source_fingerprint"))
    if explicit:
        return explicit[:128]
    image_file_id = safe_text(raw.get("image_file_id") or raw.get("source_file_id"))
    if image_file_id:
        return f"file:{stable_sha256(image_file_id)}"
    url_hash = source_url_hash(raw.get("source_url") or raw.get("image_url"))
    if url_hash:
        return f"url:{url_hash}"
    return f"row:{stable_sha256(team_id, group_legacy_id, legacy_id, raw.get('source_file'), index)}"


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def normalize_team_id(value: Any) -> str:
    text = "".join(char if char.isalnum() or char in "-_" else "-" for char in str(value or "").strip().lower())
    text = text.strip("-")
    return text or "default-team"


def safe_text(value: Any, default: str = "") -> str:
    return str(value if value is not None else default).strip()


def infer_storage(image_url: str) -> dict[str, str]:
    url = safe_text(image_url)
    if not url:
        return {"storage_type": "", "storage_bucket": "", "storage_key": ""}
    parsed = urlparse(url)
    if url.startswith("/static/uploads/"):
        return {"storage_type": "local_upload", "storage_bucket": "", "storage_key": url.removeprefix("/static/uploads/")}
    if parsed.scheme == "oss":
        return {"storage_type": "oss", "storage_bucket": parsed.netloc, "storage_key": parsed.path.lstrip("/")}
    if parsed.scheme in {"http", "https"}:
        return {"storage_type": "external_url", "storage_bucket": "", "storage_key": url}
    if url.startswith("/"):
        return {"storage_type": "local_upload", "storage_bucket": "", "storage_key": url.lstrip("/")}
    return {"storage_type": "external_url", "storage_bucket": "", "storage_key": url}


def empty_photo_url_index() -> dict[str, Any]:
    return {
        "total": 0,
        "with_image_url": 0,
        "with_storage_key": 0,
        "with_source_fingerprint": 0,
        "without_image_url": 0,
        "by_storage_type": {},
    }


def add_photo_to_url_index(index: dict[str, Any], raw_photo: dict[str, Any]) -> None:
    image_url = safe_text(raw_photo.get("image_url"))
    storage = infer_storage(image_url)
    storage_type = safe_text(raw_photo.get("storage_type")) or storage["storage_type"] or "unknown"
    storage_key = safe_text(raw_photo.get("storage_key")) or storage["storage_key"]
    index["total"] += 1
    if image_url:
        index["with_image_url"] += 1
    else:
        index["without_image_url"] += 1
    if storage_key:
        index["with_storage_key"] += 1
    if raw_photo.get("source_fingerprint") or raw_photo.get("image_file_id") or raw_photo.get("image_url"):
        index["with_source_fingerprint"] += 1
    by_type = index["by_storage_type"]
    by_type[storage_type] = int(by_type.get(storage_type, 0)) + 1


def merge_photo_url_index(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key in ("total", "with_image_url", "with_storage_key", "with_source_fingerprint", "without_image_url"):
        target[key] += int(source.get(key) or 0)
    for storage_type, count in (source.get("by_storage_type") or {}).items():
        target["by_storage_type"][storage_type] = int(target["by_storage_type"].get(storage_type, 0)) + int(count or 0)


def public_group_payload(group: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in group.items() if key != "photos"}


def summarize_payload(state_payload: dict[str, Any], users_payload: dict[str, Any]) -> dict[str, Any]:
    teams = state_payload.get("teams") if isinstance(state_payload, dict) else {}
    if not isinstance(teams, dict):
        teams = {}
    raw_users = users_payload.get("users") if isinstance(users_payload, dict) else []
    if not isinstance(raw_users, list):
        raw_users = []

    report: dict[str, Any] = {
        "teams": len(teams),
        "users": len(raw_users),
        "roles": sorted(ROLE_NAMES),
        "total_catalog_rows": 0,
        "tasks": 0,
        "groups": 0,
        "photos": 0,
        "scan_unmatched": 0,
        "review_events": 0,
        "photo_events": 0,
        "audit_events": 0,
        "photo_url_index": empty_photo_url_index(),
        "by_team": {},
        "warnings": [],
    }
    for raw_team_id, state in sorted(teams.items()):
        if not isinstance(state, dict):
            report["warnings"].append(f"Skipped non-object team state: {raw_team_id}")
            continue
        groups = state.get("groups") or []
        if not isinstance(groups, list):
            groups = []
        photo_url_index = empty_photo_url_index()
        for group in groups:
            if isinstance(group, dict):
                for photo in group.get("photos") or []:
                    if isinstance(photo, dict):
                        add_photo_to_url_index(photo_url_index, photo)
        team_counts = {
            "total_catalog_rows": len(state.get("total_catalog") or []),
            "tasks": len(state.get("tasks") or []),
            "groups": len(groups),
            "photos": sum(len(group.get("photos") or []) for group in groups if isinstance(group, dict)),
            "scan_unmatched": len(state.get("scan_unmatched") or []),
            "review_events": len(state.get("review_events") or []),
            "photo_events": len(state.get("photo_events") or []),
            "audit_events": len(state.get("audit_events") or []),
            "photo_url_index": photo_url_index,
        }
        team_id = normalize_team_id(state.get("team_id") or raw_team_id)
        report["by_team"][team_id] = team_counts
        for key, value in team_counts.items():
            if key == "photo_url_index":
                merge_photo_url_index(report[key], value)
            else:
                report[key] += value
    return report


def write_report(path: Path | None, report: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def backup_sources(state_path: Path, users_path: Path | None, report_path: Path | None) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_root = (report_path.parent if report_path else state_path.parent / "backups") / f"postgres-migration-{stamp}"
    backup_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(state_path, backup_root / state_path.name)
    if users_path and users_path.exists():
        shutil.copy2(users_path, backup_root / users_path.name)
    env_path = ROOT / ".env"
    if env_path.exists():
        shutil.copy2(env_path, backup_root / ".env")
    return backup_root


def get_or_create_team(session: Session, team_id: str) -> Team:
    team = session.get(Team, team_id)
    if team is None:
        team = Team(id=team_id, name=team_id, status="active")
        session.add(team)
    else:
        team.name = team.name or team_id
        team.status = team.status or "active"
    session.flush()
    return team


def ensure_roles(session: Session) -> dict[str, Role]:
    roles = {role.name: role for role in session.scalars(select(Role)).all()}
    for name in ROLE_NAMES:
        if name not in roles:
            role = Role(name=name, description=f"{name} role")
            session.add(role)
            roles[name] = role
    session.flush()
    return roles


def ensure_users(session: Session, users_payload: dict[str, Any], roles_by_name: dict[str, Role]) -> dict[str, User]:
    raw_users = users_payload.get("users") if isinstance(users_payload, dict) else []
    if not isinstance(raw_users, list):
        raw_users = []
    users_by_name = {user.username: user for user in session.scalars(select(User)).all()}
    for raw_user in raw_users:
        if not isinstance(raw_user, dict):
            continue
        username = safe_text(raw_user.get("username")).lower()
        password_hash = safe_text(raw_user.get("password_hash"))
        if not username or not password_hash:
            continue
        team_id = normalize_team_id(raw_user.get("team_id"))
        get_or_create_team(session, team_id)
        display_name = safe_text(raw_user.get("name"), username)
        user = users_by_name.get(username)
        if user is None:
            user = User(
                username=username,
                display_name=display_name,
                name=display_name,
                password_hash=password_hash,
                status=UserStatus.ACTIVE if raw_user.get("status") != "disabled" else UserStatus.DISABLED,
                team_id=team_id,
                home=safe_text(raw_user.get("home"), "/app"),
                last_login_at=parse_dt(raw_user.get("last_login_at")),
            )
            session.add(user)
            users_by_name[username] = user
        else:
            user.display_name = display_name
            user.name = display_name
            user.password_hash = password_hash
            user.status = UserStatus.ACTIVE if raw_user.get("status") != "disabled" else UserStatus.DISABLED
            user.team_id = team_id
            user.home = safe_text(raw_user.get("home"), "/app")
            user.last_login_at = parse_dt(raw_user.get("last_login_at"))
        clean_roles = [role for role in raw_user.get("roles", []) if role in roles_by_name]
        if not clean_roles:
            clean_roles = ["reviewer"]
        user.roles = [roles_by_name[role] for role in sorted(set(clean_roles))]
    session.flush()
    return users_by_name


def get_or_create_project(session: Session, team_id: str, state: dict[str, Any]) -> Project:
    project = session.scalar(select(Project).where(Project.code == team_id))
    name = safe_text((state.get("projects") or [{}])[0].get("name") if state.get("projects") else "", f"Project {team_id}")
    if project is None:
        project = Project(code=team_id, name=name, status=ProjectStatus.ACTIVE, team_id=team_id, settings={})
        session.add(project)
    else:
        project.name = name
        project.team_id = team_id
        project.status = ProjectStatus.ACTIVE
    session.flush()
    return project


def sync_total_catalog(session: Session, team_id: str, project: Project, rows: list[dict[str, Any]]) -> dict[str, TotalCatalogRow]:
    existing = {
        row.meter_match_key: row
        for row in session.scalars(select(TotalCatalogRow).where(TotalCatalogRow.team_id == team_id)).all()
    }
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        meter_key = safe_text(raw.get("meter_match_key"))
        if not meter_key:
            continue
        row = existing.get(meter_key)
        values = {
            "team_id": team_id,
            "project_id": project.id,
            "source_file": safe_text(raw.get("source"), "total"),
            "source_row_number": int(raw.get("row_number") or 0) or None,
            "terminal": safe_text(raw.get("terminal")),
            "installer": safe_text(raw.get("installer")),
            "original_meter_no": safe_text(raw.get("meter_no")),
            "meter_match_key": meter_key,
            "installation_address": safe_text(raw.get("address")),
            "customer_name": safe_text(raw.get("customer_name")) or None,
            "raw_data": raw,
        }
        if row is None:
            row = TotalCatalogRow(**values)
            session.add(row)
            existing[meter_key] = row
        else:
            for key, value in values.items():
                setattr(row, key, value)
    session.flush()
    return existing


def map_task_status(value: Any) -> TaskStatus:
    return TASK_STATUS_MAP.get(safe_text(value).lower(), TaskStatus.PUBLISHED)


def map_group_status(value: Any) -> GroupStatus:
    return GROUP_STATUS_MAP.get(safe_text(value).lower(), GroupStatus.UNREVIEWED)


def map_review_result(value: Any) -> ReviewResult:
    status = safe_text(value).lower()
    if status == "approved":
        return ReviewResult.APPROVED
    if status in {"exception", "rejected"}:
        return ReviewResult.REJECTED
    return ReviewResult.INCOMPLETE


def sync_tasks(session: Session, team_id: str, project: Project, tasks: list[dict[str, Any]]) -> dict[int, Task]:
    existing = {
        int(task.legacy_id): task
        for task in session.scalars(select(Task).where(Task.team_id == team_id, Task.legacy_id.is_not(None))).all()
    }
    for raw in tasks:
        if not isinstance(raw, dict):
            continue
        legacy_id = int(raw.get("id") or 0)
        if legacy_id <= 0:
            continue
        task = existing.get(legacy_id)
        values = {
            "team_id": team_id,
            "legacy_id": legacy_id,
            "project_id": project.id,
            "terminal": safe_text(raw.get("terminal")),
            "title": safe_text(raw.get("name"), f"Terminal {raw.get('terminal') or legacy_id}"),
            "status": map_task_status(raw.get("status")),
            "review_claimed_by": safe_text(raw.get("claimed_by")) or None,
            "claimed_at": parse_dt(raw.get("claimed_at")),
            "released_at": parse_dt(raw.get("released_at")),
            "construction_enabled": bool(raw.get("construction_enabled")),
            "construction_claimed_by": safe_text(raw.get("construction_claimed_by")) or None,
            "construction_claimed_at": parse_dt(raw.get("construction_claimed_at")),
            "construction_released_at": parse_dt(raw.get("construction_released_at")),
            "construction_opened_by": safe_text(raw.get("construction_opened_by")) or None,
            "construction_opened_at": parse_dt(raw.get("construction_opened_at")),
            "construction_closed_at": parse_dt(raw.get("construction_closed_at")),
            "raw_data": raw,
        }
        if task is None:
            task = Task(**values)
            session.add(task)
            existing[legacy_id] = task
        else:
            for key, value in values.items():
                setattr(task, key, value)
    session.flush()
    return existing


def sync_groups(
    session: Session,
    team_id: str,
    project: Project,
    groups: list[dict[str, Any]],
    tasks_by_legacy_id: dict[int, Task],
    catalog_by_key: dict[str, TotalCatalogRow],
) -> dict[str, MaterialGroup]:
    existing = {
        safe_text(group.legacy_id): group
        for group in session.scalars(select(MaterialGroup).where(MaterialGroup.team_id == team_id)).all()
        if group.legacy_id
    }
    seen_meter_keys: dict[str, str] = {}
    for raw in groups:
        if not isinstance(raw, dict):
            continue
        legacy_id = safe_text(raw.get("id"))
        if not legacy_id:
            continue
        legacy_task_id = int(raw.get("task_id") or 0) or None
        task = tasks_by_legacy_id.get(legacy_task_id or 0)
        meter_key = safe_text(raw.get("meter_match_key"))
        duplicate_meter_key = bool(meter_key and seen_meter_keys.get(meter_key) not in {None, legacy_id})
        if meter_key and not duplicate_meter_key:
            seen_meter_keys[meter_key] = legacy_id
        stored_meter_key = None if duplicate_meter_key else meter_key
        catalog = catalog_by_key.get(meter_key)
        group = existing.get(legacy_id)
        raw_data = public_group_payload(raw)
        if duplicate_meter_key:
            raw_data["migration_duplicate_meter_match_key"] = meter_key
            raw_data["migration_duplicate_of_group_id"] = seen_meter_keys[meter_key]
        values = {
            "team_id": team_id,
            "legacy_id": legacy_id,
            "legacy_task_id": legacy_task_id,
            "terminal": safe_text(raw.get("terminal")),
            "project_id": project.id,
            "task_id": task.id if task else None,
            "total_catalog_row_id": catalog.id if catalog else None,
            "meter_match_key": stored_meter_key,
            "display_meter_no": safe_text(raw.get("meter_no")),
            "installation_address": safe_text(raw.get("address")),
            "status": map_group_status(raw.get("status")),
            "photo_count": int(raw.get("photo_count") or len(raw.get("photos") or [])),
            "reviewer": safe_text(raw.get("reviewer")) or None,
            "review_note": safe_text(raw.get("review_note")) or None,
            "exception_status": "open" if raw.get("status") == "exception" else None,
            "exception_note": safe_text(raw.get("exception_note")) or None,
            "has_archive_blocker": bool(raw.get("has_archive_blocker")),
            "exception_reasons": raw.get("exception_reasons") or [],
            "reviewed_at": parse_dt(raw.get("reviewed_at")),
            "raw_data": raw_data,
        }
        if group is None:
            group = MaterialGroup(**values)
            session.add(group)
            existing[legacy_id] = group
        else:
            for key, value in values.items():
                setattr(group, key, value)
    session.flush()
    return existing


def sync_photos(session: Session, team_id: str, groups: list[dict[str, Any]], groups_by_legacy_id: dict[str, MaterialGroup]) -> dict[tuple[str, str], Photo]:
    existing = {
        (safe_text(photo.group_id), safe_text(photo.legacy_id)): photo
        for photo in session.scalars(select(Photo).where(Photo.team_id == team_id)).all()
        if photo.legacy_id
    }
    existing_by_group_sha = {
        (safe_text(photo.group_id), safe_text(photo.sha256)): photo
        for photo in session.scalars(select(Photo).where(Photo.team_id == team_id)).all()
        if photo.sha256
    }
    photos_by_legacy: dict[tuple[str, str], Photo] = {}
    for raw_group in groups:
        if not isinstance(raw_group, dict):
            continue
        group_legacy_id = safe_text(raw_group.get("id"))
        group = groups_by_legacy_id.get(group_legacy_id)
        if group is None:
            continue
        for index, raw in enumerate(raw_group.get("photos") or [], start=1):
            if not isinstance(raw, dict):
                continue
            legacy_id = safe_text(raw.get("id"), f"{group_legacy_id}-photo-{index}")
            storage = infer_storage(safe_text(raw.get("image_url")))
            storage_type = safe_text(raw.get("storage_type")) or storage["storage_type"]
            storage_key = safe_text(raw.get("storage_key")) or storage["storage_key"]
            raw_source_url = safe_text(raw.get("source_url") or raw.get("image_url"))
            raw_source_file_id = safe_text(raw.get("source_file_id") or raw.get("image_file_id"))
            fingerprint = source_fingerprint(
                raw,
                team_id=team_id,
                group_legacy_id=group_legacy_id,
                legacy_id=legacy_id,
                index=index,
            )
            sha256 = safe_text(raw.get("sha256")) or stable_sha256(
                team_id,
                group_legacy_id,
                legacy_id,
                raw.get("image_url"),
                raw.get("image_file_id"),
            )
            object_key = storage_key or safe_text(raw.get("image_url")) or safe_text(raw.get("image_file_id")) or legacy_id
            key = (str(group.id), legacy_id)
            sha_key = (str(group.id), sha256)
            photo = existing.get(key)
            values = {
                "team_id": team_id,
                "legacy_id": legacy_id,
                "group_id": group.id,
                "source": safe_text(raw.get("upload_source")) or safe_text(raw.get("source_file")),
                "barcode": safe_text(raw.get("barcode")) or None,
                "collector": safe_text(raw.get("collector")) or None,
                "asset_no": safe_text(raw.get("asset_no")) or None,
                "creator": safe_text(raw.get("creator")) or None,
                "image_url": safe_text(raw.get("image_url")) or None,
                "image_file_id": safe_text(raw.get("image_file_id")) or None,
                "source_url": raw_source_url or None,
                "source_url_hash": source_url_hash(raw_source_url) or None,
                "source_file_id": raw_source_file_id or None,
                "source_fingerprint": fingerprint,
                "import_batch_id": safe_text(raw.get("import_batch_id") or raw.get("source_file")) or None,
                "storage_type": storage_type or None,
                "storage_bucket": safe_text(raw.get("storage_bucket")) or storage["storage_bucket"] or None,
                "storage_key": storage_key or None,
                "sha256": sha256,
                "original_filename": safe_text(raw.get("original_filename")) or None,
                "object_key": object_key,
                "upload_status": PhotoUploadStatus.UPLOADED,
                "category": safe_text(raw.get("category"), "unclassified"),
                "archive_status": safe_text(raw.get("archive_status"), "pending"),
                "archive_filename": safe_text(raw.get("archive_filename")) or None,
                "archived_at": parse_dt(raw.get("archived_at")),
                "classified_by": safe_text(raw.get("classified_by")) or None,
                "classified_at": parse_dt(raw.get("classified_at")),
                "sort_order": index,
                "client_batch_id": safe_text(raw.get("client_batch_id")) or None,
                "client_photo_id": safe_text(raw.get("client_photo_id")) or None,
                "is_active": raw.get("is_active") is not False and not raw.get("deleted_at"),
                "deleted_at": parse_dt(raw.get("deleted_at")),
                "deleted_by": safe_text(raw.get("deleted_by")) or None,
                "delete_reason": safe_text(raw.get("delete_reason")) or None,
                "metadata_json": {
                    "download_status": raw.get("download_status"),
                    "construction_slot": raw.get("construction_slot"),
                    "category_label": raw.get("category_label"),
                    "normalized_source_url": normalize_source_url(raw_source_url),
                },
                "raw_data": raw,
            }
            if photo is None:
                duplicate_photo = existing_by_group_sha.get(sha_key)
                if duplicate_photo is not None:
                    photo = duplicate_photo
                else:
                    photo = Photo(**values)
                    session.add(photo)
                    existing[key] = photo
                    existing_by_group_sha[sha_key] = photo
            else:
                if photo.storage_type == "oss" and values.get("storage_type") != "oss":
                    values["image_url"] = photo.image_url
                    values["storage_type"] = photo.storage_type
                    values["storage_bucket"] = photo.storage_bucket
                    values["storage_key"] = photo.storage_key
                    values["object_key"] = photo.object_key
                    values["sha256"] = photo.sha256
                    values["byte_size"] = photo.byte_size
                    values["content_type"] = photo.content_type
                    values["metadata_json"] = photo.metadata_json
                for column, value in values.items():
                    setattr(photo, column, value)
                existing_by_group_sha[sha_key] = photo
            photos_by_legacy[(group_legacy_id, legacy_id)] = photo
    session.flush()
    return photos_by_legacy


def sync_unmatched(session: Session, team_id: str, records: list[dict[str, Any]]) -> None:
    existing = {
        record.legacy_id: record
        for record in session.scalars(select(UnmatchedRecord).where(UnmatchedRecord.team_id == team_id)).all()
    }
    for index, raw in enumerate(records, start=1):
        if not isinstance(raw, dict):
            continue
        legacy_id = safe_text(raw.get("unmatched_id"), f"unmatched-{index:06d}")
        record = existing.get(legacy_id)
        values = {
            "team_id": team_id,
            "legacy_id": legacy_id,
            "record_type": safe_text(raw.get("record_type"), "scan"),
            "status": safe_text(raw.get("status"), "open"),
            "terminal": safe_text(raw.get("terminal")) or None,
            "meter_no": safe_text(raw.get("meter_no")) or None,
            "meter_match_key": safe_text(raw.get("meter_match_key")) or None,
            "barcode": safe_text(raw.get("barcode")) or None,
            "collector": safe_text(raw.get("collector")) or None,
            "module_asset_no": safe_text(raw.get("module_asset_no") or raw.get("asset_no")) or None,
            "address": safe_text(raw.get("address")) or None,
            "payload": raw,
        }
        if record is None:
            session.add(UnmatchedRecord(**values))
        else:
            for key, value in values.items():
                setattr(record, key, value)


def sync_review_events(
    session: Session,
    team_id: str,
    events: list[dict[str, Any]],
    groups_by_legacy_id: dict[str, MaterialGroup],
    tasks_by_legacy_id: dict[int, Task],
) -> None:
    existing = {
        record.legacy_id: record
        for record in session.scalars(select(ReviewRecord).where(ReviewRecord.team_id == team_id)).all()
        if record.legacy_id
    }
    for index, raw in enumerate(events, start=1):
        if not isinstance(raw, dict):
            continue
        legacy_id = safe_text(raw.get("id"), f"review-{index:06d}")
        group = groups_by_legacy_id.get(safe_text(raw.get("group_id")))
        if group is None:
            continue
        task = tasks_by_legacy_id.get(int(raw.get("task_id") or 0))
        record = existing.get(legacy_id)
        values = {
            "team_id": team_id,
            "legacy_id": legacy_id,
            "group_id": group.id,
            "task_id": task.id if task else None,
            "result": map_review_result(raw.get("next_status")),
            "previous_status": safe_text(raw.get("previous_status")) or None,
            "next_status": safe_text(raw.get("next_status"), "incomplete"),
            "notes": safe_text(raw.get("note") or raw.get("exception_note")) or None,
            "payload": raw,
            "created_at": parse_dt(raw.get("created_at")) or datetime.now(UTC),
        }
        if record is None:
            session.add(ReviewRecord(**values))
        else:
            for key, value in values.items():
                setattr(record, key, value)


def sync_photo_events(
    session: Session,
    team_id: str,
    events: list[dict[str, Any]],
    groups_by_legacy_id: dict[str, MaterialGroup],
    photos_by_legacy: dict[tuple[str, str], Photo],
) -> None:
    existing = {
        event.legacy_id: event
        for event in session.scalars(select(PhotoEvent).where(PhotoEvent.team_id == team_id)).all()
    }
    for index, raw in enumerate(events, start=1):
        if not isinstance(raw, dict):
            continue
        legacy_id = safe_text(raw.get("id"), f"photo-event-{index:06d}")
        group_legacy_id = safe_text(raw.get("group_id"))
        group = groups_by_legacy_id.get(group_legacy_id)
        photo = photos_by_legacy.get((group_legacy_id, safe_text(raw.get("photo_id"))))
        event = existing.get(legacy_id)
        values = {
            "team_id": team_id,
            "legacy_id": legacy_id,
            "group_id": group.id if group else None,
            "photo_id": photo.id if photo else None,
            "actor": safe_text(raw.get("reviewer") or raw.get("actor")) or None,
            "event_type": "photo_category",
            "previous_category": safe_text(raw.get("previous_category")) or None,
            "next_category": safe_text(raw.get("next_category")) or None,
            "payload": raw,
            "created_at": parse_dt(raw.get("created_at")) or datetime.now(UTC),
        }
        if event is None:
            session.add(PhotoEvent(**values))
        else:
            for key, value in values.items():
                setattr(event, key, value)


def sync_audit_events(session: Session, team_id: str, project: Project, events: list[dict[str, Any]]) -> None:
    existing = {
        audit.legacy_id: audit
        for audit in session.scalars(select(AuditLog).where(AuditLog.team_id == team_id)).all()
        if audit.legacy_id
    }
    for index, raw in enumerate(events, start=1):
        if not isinstance(raw, dict):
            continue
        legacy_id = safe_text(raw.get("id"), f"audit-{index:06d}")
        audit = existing.get(legacy_id)
        values = {
            "team_id": team_id,
            "legacy_id": legacy_id,
            "actor_username": safe_text(raw.get("actor")) or None,
            "project_id": project.id,
            "action": safe_text(raw.get("action"), "legacy_event"),
            "entity_type": "local_state",
            "request_id": "",
            "before_data": None,
            "after_data": raw.get("payload") if isinstance(raw.get("payload"), dict) else None,
            "payload": raw.get("payload") if isinstance(raw.get("payload"), dict) else raw,
            "created_at": parse_dt(raw.get("created_at")) or datetime.now(UTC),
        }
        if audit is None:
            session.add(AuditLog(**values))
        else:
            for key, value in values.items():
                setattr(audit, key, value)


def migrate_payload(
    session: Session,
    state_payload: dict[str, Any],
    users_payload: dict[str, Any],
    state_path: Path,
    users_path: Path | None,
    report: dict[str, Any],
) -> None:
    roles_by_name = ensure_roles(session)
    users_by_name = ensure_users(session, users_payload, roles_by_name)
    del users_by_name

    teams = state_payload.get("teams") if isinstance(state_payload, dict) else {}
    if not isinstance(teams, dict):
        teams = {}

    for raw_team_id, state in sorted(teams.items()):
        if not isinstance(state, dict):
            continue
        team_id = normalize_team_id(state.get("team_id") or raw_team_id)
        get_or_create_team(session, team_id)
        project = get_or_create_project(session, team_id, state)
        catalog_by_key = sync_total_catalog(session, team_id, project, state.get("total_catalog") or [])
        tasks_by_legacy_id = sync_tasks(session, team_id, project, state.get("tasks") or [])
        groups_by_legacy_id = sync_groups(
            session,
            team_id,
            project,
            state.get("groups") or [],
            tasks_by_legacy_id,
            catalog_by_key,
        )
        photos_by_legacy = sync_photos(session, team_id, state.get("groups") or [], groups_by_legacy_id)
        sync_unmatched(session, team_id, state.get("scan_unmatched") or [])
        sync_review_events(session, team_id, state.get("review_events") or [], groups_by_legacy_id, tasks_by_legacy_id)
        sync_photo_events(session, team_id, state.get("photo_events") or [], groups_by_legacy_id, photos_by_legacy)
        sync_audit_events(session, team_id, project, state.get("audit_events") or [])

    session.add(
        MigrationRun(
            source_state_sha256=file_sha256(state_path),
            source_users_sha256=file_sha256(users_path),
            state_path=str(state_path),
            users_path=str(users_path or ""),
            counts={key: value for key, value in report.items() if key != "by_team"},
            report=report,
        )
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate local JSON state into PostgreSQL.")
    parser.add_argument("--state", required=True, type=Path, help="Path to local_state.json.")
    parser.add_argument("--users", type=Path, default=None, help="Path to users.json.")
    parser.add_argument("--report", type=Path, default=None, help="Path to write migration report JSON.")
    parser.add_argument("--database-url", default="", help="Override DATABASE_URL.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report without connecting to PostgreSQL.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    state_payload = read_json(args.state)
    users_payload = read_json(args.users) if args.users else {}
    report = summarize_payload(state_payload, users_payload)
    report["state_sha256"] = file_sha256(args.state)
    report["users_sha256"] = file_sha256(args.users)
    report["dry_run"] = bool(args.dry_run)

    if args.dry_run:
        write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    backup_path = backup_sources(args.state, args.users, args.report)
    report["backup_path"] = str(backup_path)

    database_url = args.database_url or settings.database_url
    engine = create_engine(database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with SessionLocal() as session:
        migrate_payload(session, state_payload, users_payload, args.state, args.users, report)
        session.commit()

    write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
