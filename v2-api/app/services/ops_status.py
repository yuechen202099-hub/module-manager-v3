from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.local_simulation import list_team_states, persisted_state_path


DISK_WARN_PERCENT = 70.0
BACKUP_WARN_HOURS = 24.0
LOCAL_UPLOAD_WARN_BYTES = 10 * 1024 * 1024 * 1024
LOCAL_UPLOAD_WARN_FILES = 30_000


def app_version() -> str:
    return "2.5.3"


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def install_root() -> Path:
    root = project_root()
    if root.name == "current":
        return root.parent
    return root


def backup_root() -> Path:
    configured = os.getenv("MODULE_MANAGER_BACKUP_DIR", "").strip()
    if configured:
        return Path(configured)
    return install_root() / "backups" / "runtime"


def uploads_root() -> Path:
    configured = os.getenv("MODULE_MANAGER_UPLOAD_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[1] / "static" / "uploads"


def stat_file(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"configured": False, "exists": False}
    exists = path.exists()
    result: dict[str, Any] = {
        "configured": True,
        "path": str(path),
        "exists": exists,
    }
    if exists:
        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, UTC)
        result.update(
            {
                "size_bytes": stat.st_size,
                "modified_at": mtime.isoformat(),
                "age_hours": round((datetime.now(UTC) - mtime).total_seconds() / 3600, 2),
            }
        )
    return result


def directory_usage(path: Path) -> dict[str, Any]:
    total_bytes = 0
    file_count = 0
    if path.exists():
        for item in path.rglob("*"):
            try:
                if item.is_file():
                    file_count += 1
                    total_bytes += item.stat().st_size
            except OSError:
                continue
    return {"path": str(path), "exists": path.exists(), "bytes": total_bytes, "files": file_count}


def latest_backup(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "count": 0, "latest": None, "age_hours": None}
    candidates = []
    for item in path.iterdir():
        try:
            if item.is_dir() or item.is_file():
                candidates.append((item.stat().st_mtime, item))
        except OSError:
            continue
    if not candidates:
        return {"path": str(path), "exists": True, "count": 0, "latest": None, "age_hours": None}
    mtime, item = max(candidates, key=lambda pair: pair[0])
    modified = datetime.fromtimestamp(mtime, UTC)
    age_hours = round((datetime.now(UTC) - modified).total_seconds() / 3600, 2)
    return {
        "path": str(path),
        "exists": True,
        "count": len(candidates),
        "latest": str(item),
        "latest_modified_at": modified.isoformat(),
        "age_hours": age_hours,
    }


def disk_status(path: Path) -> dict[str, Any]:
    target = path if path.exists() else project_root()
    usage = shutil.disk_usage(target)
    used_percent = round((usage.used / usage.total) * 100, 2) if usage.total else 0.0
    return {
        "path": str(target),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "used_percent": used_percent,
        "warn_percent": DISK_WARN_PERCENT,
        "ok": used_percent < DISK_WARN_PERCENT,
    }


def team_totals() -> dict[str, Any]:
    states = list_team_states()
    total_groups = sum(int(item.get("groups") or 0) for item in states)
    total_tasks = sum(int(item.get("tasks") or 0) for item in states)
    total_photos = 0
    for item in states:
        summary = item.get("summary") or {}
        total_photos += int(summary.get("downloaded_photos") or summary.get("scan_rows") or 0)
    return {
        "teams": states,
        "team_count": len(states),
        "groups": total_groups,
        "tasks": total_tasks,
        "photos": total_photos,
    }


def build_system_status() -> dict[str, Any]:
    now = datetime.now(UTC)
    state_path = persisted_state_path()
    users_path = Path(settings.auth_users_path) if settings.auth_users_path else None
    uploads = directory_usage(uploads_root())
    backups = latest_backup(backup_root())
    disk = disk_status(install_root())
    backup_age = backups.get("age_hours")
    warnings = []
    storage_backend = settings.storage_backend.strip().lower() or "local"
    oss_missing = [
        name
        for name, value in {
            "OSS_ENDPOINT": settings.oss_endpoint,
            "OSS_BUCKET": settings.oss_bucket,
            "OSS_ACCESS_KEY_ID": settings.oss_access_key_id,
            "OSS_ACCESS_KEY_SECRET": settings.oss_access_key_secret,
        }.items()
        if not str(value or "").strip()
    ]
    if not disk["ok"]:
        warnings.append({"code": "disk_high", "message": "Disk usage is above warning threshold."})
    if backup_age is None or float(backup_age) > BACKUP_WARN_HOURS:
        warnings.append({"code": "backup_stale", "message": "No recent runtime backup was found."})
    if uploads["bytes"] >= LOCAL_UPLOAD_WARN_BYTES:
        warnings.append({"code": "uploads_large", "message": "Local uploads exceed the OSS planning threshold."})
    if uploads["files"] >= LOCAL_UPLOAD_WARN_FILES:
        warnings.append({"code": "uploads_many_files", "message": "Local upload photo count exceeds the OSS planning threshold."})
    if storage_backend == "oss" and oss_missing:
        warnings.append({"code": "oss_config_incomplete", "message": "OSS storage is enabled but required config is missing."})

    return {
        "version": app_version(),
        "app_env": settings.app_env,
        "generated_at": now.isoformat(),
        "disk": disk,
        "state_file": stat_file(state_path),
        "users_file": stat_file(users_path),
        "uploads": {
            **uploads,
            "warn_bytes": LOCAL_UPLOAD_WARN_BYTES,
            "warn_files": LOCAL_UPLOAD_WARN_FILES,
        },
        "storage": {
            "backend": "oss" if storage_backend == "oss" else "local",
            "oss_enabled": storage_backend == "oss",
            "oss_bucket": settings.oss_bucket,
            "oss_endpoint": settings.oss_endpoint,
            "oss_internal_endpoint": settings.oss_internal_endpoint,
            "oss_prefix": settings.oss_prefix,
            "oss_public_base_url_configured": bool(settings.oss_public_base_url.strip()),
            "oss_missing_config": oss_missing,
        },
        "backups": {
            **backups,
            "warn_age_hours": BACKUP_WARN_HOURS,
        },
        "teams": team_totals(),
        "warnings": warnings,
        "ok": not warnings,
    }
