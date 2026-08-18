from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal  # noqa: E402
from app.models import MaterialGroup, Photo  # noqa: E402
from app.services.external_photo_oss_migration import (  # noqa: E402
    DownloadPolicy,
    ExternalPhotoSource,
    OssObjectConflictError,
    OssObjectReceipt,
    OssVerificationError,
    PhotoTransferError,
    cleanup_download,
    download_external_photo,
    redact_source_url,
    store_downloaded_photo,
)
from app.services.photo_storage import (  # noqa: E402
    oss_bucket_name,
    oss_object_key,
    require_oss_client,
    validate_remote_image_url,
)
from app.services.state_repository import invalidate_verification_for_group  # noqa: E402


MIB = 1024 * 1024
START_MEMORY_BYTES = 400 * MIB
START_TEMP_FREE_BYTES = 512 * MIB
STOP_MEMORY_BYTES = 250 * MIB
OSS_ERROR_LIMIT = 5
KNOWN_STORAGE_TYPES = frozenset({"external_url", "local_upload", "oss"})
MIGRATION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")
HOST_RE = re.compile(
    r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z"
)
URL_IN_TEXT_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


class ResourceGateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    mem_available_bytes: int
    temp_free_bytes: int
    api_healthy: bool
    oom_marker: str


@dataclass(frozen=True, slots=True)
class ExternalPhotoCandidate:
    photo_id: UUID
    team_id: str
    group_id: UUID
    group_legacy_id: str
    url: str
    declared_sha256: str
    filename: str


@dataclass(frozen=True, slots=True)
class PreparedTransfer:
    candidate: ExternalPhotoCandidate
    receipt: OssObjectReceipt


@dataclass(frozen=True, slots=True)
class RollbackCandidate:
    photo_id: UUID
    group_id: UUID


def candidate_statement(team_id: str = "", limit: int = 0):
    statement = (
        select(
            Photo.id.label("photo_id"),
            Photo.team_id,
            Photo.group_id,
            MaterialGroup.legacy_id.label("group_legacy_id"),
            Photo.image_url.label("url"),
            Photo.sha256.label("declared_sha256"),
            Photo.original_filename.label("filename"),
            Photo.sort_order,
        )
        .join(MaterialGroup, MaterialGroup.id == Photo.group_id)
        .where(Photo.is_active.is_(True), Photo.storage_type == "external_url")
        .order_by(
            Photo.team_id.asc(),
            MaterialGroup.legacy_id.asc(),
            Photo.sort_order.asc(),
            Photo.id.asc(),
        )
    )
    if team_id:
        statement = statement.where(Photo.team_id == team_id)
    if limit:
        statement = statement.limit(limit)
    return statement


def start_gate(snapshot: ResourceSnapshot) -> None:
    if snapshot.mem_available_bytes < START_MEMORY_BYTES:
        raise ResourceGateError("migration requires at least 400 MiB available memory")
    if snapshot.temp_free_bytes < START_TEMP_FREE_BYTES:
        raise ResourceGateError("migration requires at least 512 MiB free temporary disk")
    if not snapshot.api_healthy:
        raise ResourceGateError("local API health check failed")


def stop_reason(
    snapshot: ResourceSnapshot,
    initial_oom_marker: str,
    consecutive_oss_errors: int,
) -> str:
    if snapshot.mem_available_bytes < STOP_MEMORY_BYTES:
        return "low_memory"
    if not snapshot.api_healthy:
        return "health_failed"
    if snapshot.oom_marker != initial_oom_marker:
        return "new_oom"
    if consecutive_oss_errors >= OSS_ERROR_LIMIT:
        return "oss_error_limit"
    return ""


def _memory_available_bytes() -> int:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    if hasattr(os, "sysconf"):
        try:
            return int(os.sysconf("SC_AVPHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE"))
        except (OSError, TypeError, ValueError):
            pass
    return 0


def _api_is_healthy() -> bool:
    connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=3)
    try:
        connection.request("GET", "/health", headers={"Host": "127.0.0.1"})
        response = connection.getresponse()
        response.read(4096)
        return response.status == 200
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def _oom_marker() -> str:
    try:
        result = subprocess.run(
            ["journalctl", "-k", "--no-pager", "-n", "200", "-o", "short-unix"],
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "journal-unavailable"
    oom_lines = b"\n".join(
        line
        for line in result.stdout.splitlines()
        if b"out of memory" in line.lower() or b"oom-kill" in line.lower()
    )
    return hashlib.sha256(oom_lines).hexdigest()


def probe_resources(temp_dir: Path) -> ResourceSnapshot:
    return ResourceSnapshot(
        mem_available_bytes=_memory_available_bytes(),
        temp_free_bytes=shutil.disk_usage(temp_dir).free,
        api_healthy=_api_is_healthy(),
        oom_marker=_oom_marker(),
    )


def _sanitize_text(value: str) -> str:
    return URL_IN_TEXT_RE.sub(lambda match: redact_source_url(match.group(0)), str(value or ""))


def _sanitize_report(value: Any, *, key: str = "") -> Any:
    if isinstance(value, dict):
        return {str(item_key): _sanitize_report(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_report(item, key=key) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str):
        if "url" in key.lower():
            return redact_source_url(value)
        return _sanitize_text(value)
    return value


def _ensure_owner_directory(path: Path) -> Path:
    directory = Path(path)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir():
        raise RuntimeError("migration operational directory is unsafe")
    try:
        directory.chmod(0o700)
    except OSError as exc:
        raise RuntimeError("migration operational directory cannot be made owner-only") from exc
    if os.name != "nt" and directory.stat().st_mode & 0o077:
        raise RuntimeError("migration operational directory is not owner-only")
    return directory


def operational_directory() -> Path:
    configured = str(os.environ.get("MODULE_MANAGER_MIGRATION_DIR") or "").strip()
    base = Path(configured) if configured else Path(tempfile.gettempdir()) / "module-manager-v3-operations"
    return _ensure_owner_directory(base / "external-photo-oss")


def write_report(path: Path, report: dict[str, Any]) -> Path:
    target = Path(path)
    _ensure_owner_directory(target.parent)
    if target.exists() and target.is_symlink():
        raise RuntimeError("migration report path is unsafe")
    payload = json.dumps(_sanitize_report(report), ensure_ascii=False, indent=2, sort_keys=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(target, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            descriptor = -1
            output.write(payload)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return target


def _candidate_from_row(row: Any) -> ExternalPhotoCandidate:
    return ExternalPhotoCandidate(
        photo_id=UUID(str(row.photo_id)),
        team_id=str(row.team_id or ""),
        group_id=UUID(str(row.group_id)),
        group_legacy_id=str(row.group_legacy_id or ""),
        url=str(row.url or ""),
        declared_sha256=str(row.declared_sha256 or ""),
        filename=str(row.filename or ""),
    )


def _declared_hash_class(value: str, url: str) -> str:
    declared = str(value or "").strip().lower()
    if not declared:
        return "empty"
    if not re.fullmatch(r"[0-9a-f]{64}", declared):
        return "invalid"
    if declared == hashlib.sha256(url.encode("utf-8")).hexdigest():
        return "url_sha256"
    return "content_sha256_or_mismatch"


def _host(url: str) -> str:
    try:
        return str(urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def run_dry_run(
    session: Session,
    *,
    team_id: str,
    allowlist: frozenset[str] | None,
) -> dict[str, Any]:
    try:
        session.execute(text("SET TRANSACTION READ ONLY"))
        candidates = [_candidate_from_row(row) for row in session.execute(candidate_statement(team_id)).all()]
        storage_statement = (
            select(Photo.storage_type, func.count(Photo.id))
            .where(Photo.is_active.is_(True))
            .group_by(Photo.storage_type)
        )
        if team_id:
            storage_statement = storage_statement.where(Photo.team_id == team_id)
        storage_types = {
            str(storage_type or "unknown"): int(count)
            for storage_type, count in session.execute(storage_statement).all()
        }

        hosts: Counter[str] = Counter()
        hash_classes: Counter[str] = Counter()
        url_syntax_failures = 0
        dns_safety_failures = 0
        allowlist_mismatches = 0
        items: dict[str, Any] = {}
        for candidate in candidates:
            host = _host(candidate.url)
            if host:
                hosts[host] += 1
            hash_classes[_declared_hash_class(candidate.declared_sha256, candidate.url)] += 1
            url_status = "safe"
            if not host:
                url_syntax_failures += 1
                url_status = "invalid_url"
            else:
                try:
                    validate_remote_image_url(
                        candidate.url,
                        allowed_hosts=frozenset({host}),
                        app_env="production",
                    )
                except ValueError as exc:
                    if "Invalid image URL" in str(exc):
                        url_syntax_failures += 1
                        url_status = "invalid_url"
                    else:
                        dns_safety_failures += 1
                        url_status = "dns_unsafe"
            if allowlist is not None and host not in allowlist:
                allowlist_mismatches += 1
                if url_status == "safe":
                    url_status = "allowlist_mismatch"
            items[str(candidate.photo_id)] = {
                "team_id": candidate.team_id,
                "group_id": str(candidate.group_id),
                "source_url": redact_source_url(candidate.url),
                "status": url_status,
            }

        unknown_storage = sum(
            count for storage_type, count in storage_types.items() if storage_type not in KNOWN_STORAGE_TYPES
        )
        return {
            "mode": "dry_run",
            "read_only": True,
            "external_url_candidates": len(candidates),
            "unknown_storage": unknown_storage,
            "storage_types": dict(sorted(storage_types.items())),
            "source_hosts": dict(sorted(hosts.items())),
            "declared_hash_classes": dict(sorted(hash_classes.items())),
            "url_syntax_failures": url_syntax_failures,
            "dns_safety_failures": dns_safety_failures,
            "allowlist_mismatches": allowlist_mismatches,
            "items": items,
        }
    finally:
        session.rollback()


def _new_run_temp_directory(migration_id: str) -> Path:
    root = _ensure_owner_directory(operational_directory() / "tmp")
    prefix = f"{migration_id}-{os.getpid()}-"
    path = Path(tempfile.mkdtemp(prefix=prefix, dir=root))
    path.chmod(0o700)
    if path.is_symlink() or not path.is_dir():
        raise ResourceGateError("migration temporary directory is unsafe")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ResourceGateError("migration temporary directory is not owner-only")
    return path


def _close_run_temp_directory(path: Path) -> None:
    try:
        Path(path).rmdir()
    except OSError:
        # Task 6 performs identity-checked per-file cleanup. Never recursively
        # remove a directory if an unexpected entry remains.
        return


def _fetch_candidates(
    session_factory: sessionmaker,
    *,
    limit: int,
) -> list[ExternalPhotoCandidate]:
    with session_factory() as session:
        try:
            session.execute(text("SET TRANSACTION READ ONLY"))
            rows = session.execute(candidate_statement(limit=limit)).all()
            return [_candidate_from_row(row) for row in rows]
        finally:
            session.rollback()


def _database_counts(session_factory: sessionmaker) -> tuple[int, int]:
    with session_factory() as session:
        try:
            session.execute(text("SET TRANSACTION READ ONLY"))
            remaining = int(
                session.scalar(
                    select(func.count(Photo.id)).where(
                        Photo.is_active.is_(True),
                        Photo.storage_type == "external_url",
                    )
                )
                or 0
            )
            unknown = int(
                session.scalar(
                    select(func.count(Photo.id)).where(
                        Photo.is_active.is_(True),
                        or_(
                            Photo.storage_type.is_(None),
                            Photo.storage_type.not_in(KNOWN_STORAGE_TYPES),
                        ),
                    )
                )
                or 0
            )
            return remaining, unknown
        finally:
            session.rollback()


def _bucket_name(bucket: Any) -> str:
    value = str(getattr(bucket, "bucket_name", "") or oss_bucket_name()).strip()
    if not value:
        raise RuntimeError("OSS bucket name is unavailable")
    return value


def _hash_status(candidate: ExternalPhotoCandidate, content_sha256: str) -> str:
    declared = candidate.declared_sha256.strip().lower()
    if not declared:
        return "accepted"
    if not re.fullmatch(r"[0-9a-f]{64}", declared):
        return "invalid_declared_hash"
    url_sha256 = hashlib.sha256(candidate.url.encode("utf-8")).hexdigest()
    if declared in {url_sha256, content_sha256.lower()}:
        return "accepted"
    return "declared_hash_mismatch"


def _enum_text(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def _final_delivery_ready(group: MaterialGroup) -> bool:
    return _enum_text(getattr(group, "status", "")) == "approved"


def _source_still_matches(photo: Photo, candidate: ExternalPhotoCandidate) -> bool:
    return bool(
        photo.id == candidate.photo_id
        and photo.team_id == candidate.team_id
        and photo.group_id == candidate.group_id
        and photo.is_active is True
        and photo.storage_type == "external_url"
        and str(photo.image_url or "") == candidate.url
        and str(photo.sha256 or "") == candidate.declared_sha256
    )


def _commit_group(
    session_factory: sessionmaker,
    *,
    group_id: UUID,
    transfers: list[PreparedTransfer],
    migration_id: str,
) -> dict[str, Any]:
    statuses: dict[str, str] = {}
    group_status = ""
    final_delivery_ready = False
    with session_factory() as session:
        with session.begin():
            group = session.scalar(
                select(MaterialGroup)
                .where(MaterialGroup.id == group_id)
                .with_for_update()
            )
            if group is None:
                return {
                    "statuses": {str(item.candidate.photo_id): "conflict" for item in transfers},
                    "group_status": "missing",
                    "final_delivery_ready": False,
                }
            group_status = _enum_text(group.status)
            locked_photos = session.scalars(
                select(Photo)
                .where(Photo.group_id == group_id)
                .order_by(Photo.id.asc())
                .with_for_update()
            ).all()
            photos_by_id = {photo.id: photo for photo in locked_photos}
            sha_owners: dict[str, set[UUID]] = defaultdict(set)
            for photo in locked_photos:
                digest = str(photo.sha256 or "").strip().lower()
                if digest:
                    sha_owners[digest].add(photo.id)

            changed = False
            for transfer in transfers:
                candidate = transfer.candidate
                receipt = transfer.receipt
                item_key = str(candidate.photo_id)
                photo = photos_by_id.get(candidate.photo_id)
                if photo is None or not _source_still_matches(photo, candidate):
                    statuses[item_key] = "conflict"
                    continue
                receipt_sha = receipt.sha256.strip().lower()
                if sha_owners.get(receipt_sha, set()) - {photo.id}:
                    statuses[item_key] = "duplicate_content"
                    continue

                original_sha = str(photo.sha256 or "").strip().lower()
                if original_sha:
                    sha_owners[original_sha].discard(photo.id)
                sha_owners[receipt_sha].add(photo.id)
                raw = dict(photo.raw_data or {})
                raw.update(
                    {
                        "pre_oss_image_url": photo.image_url,
                        "pre_oss_storage_type": photo.storage_type,
                        "pre_oss_storage_bucket": photo.storage_bucket,
                        "pre_oss_storage_key": photo.storage_key,
                        "pre_oss_object_key": photo.object_key,
                        "pre_oss_sha256": photo.sha256,
                        "pre_oss_content_type": photo.content_type,
                        "pre_oss_byte_size": photo.byte_size,
                        "pre_oss_source_type": "external_url",
                        "oss_migration_id": migration_id,
                        "oss_synced_at": datetime.now(UTC).isoformat(),
                        "oss_migration_bucket": receipt.bucket,
                        "oss_migration_key": receipt.key,
                        "oss_migration_sha256": receipt.sha256,
                    }
                )
                photo.image_url = f"oss://{receipt.bucket}/{receipt.key}"
                photo.storage_type = "oss"
                photo.storage_bucket = receipt.bucket
                photo.storage_key = receipt.key
                photo.object_key = receipt.key
                photo.sha256 = receipt.sha256
                photo.content_type = receipt.content_type
                photo.byte_size = receipt.byte_size
                photo.raw_data = raw
                statuses[item_key] = "committed"
                changed = True

            if changed:
                session.flush()
                invalidate_verification_for_group(
                    session,
                    group,
                    actor="oss-migration",
                    reason="external_photo_migrated_to_oss",
                )
                final_delivery_ready = _final_delivery_ready(group)
    return {
        "statuses": statuses,
        "group_status": group_status,
        "final_delivery_ready": final_delivery_ready,
    }


def _base_run_report(
    *,
    mode: str,
    migration_id: str,
    candidates: list[ExternalPhotoCandidate],
) -> dict[str, Any]:
    return {
        "mode": mode,
        "migration_id": migration_id,
        "candidate_count": len(candidates),
        "uploaded": 0,
        "reused_objects": 0,
        "committed": 0,
        "failed": 0,
        "conflicts": 0,
        "byte_count": 0,
        "remaining_external_url": 0,
        "unknown_storage": 0,
        "failure_counts": {},
        "stop_reason": "",
        "items": {
            str(candidate.photo_id): {
                "team_id": candidate.team_id,
                "group_id": str(candidate.group_id),
                "group_status": "",
                "final_delivery_ready": False,
                "source_url": redact_source_url(candidate.url),
                "status": "not_started",
            }
            for candidate in candidates
        },
    }


def _finish_run_report(
    report: dict[str, Any],
    session_factory: sessionmaker,
) -> dict[str, Any]:
    remaining, unknown = _database_counts(session_factory)
    report["remaining_external_url"] = remaining
    report["unknown_storage"] = unknown
    status_counts = Counter(item["status"] for item in report["items"].values())
    report["committed"] = status_counts["committed"]
    report["conflicts"] = status_counts["conflict"]
    ignored = {"committed", "not_started", "already_committed"}
    failures = {status: count for status, count in sorted(status_counts.items()) if status not in ignored}
    report["failure_counts"] = failures
    report["failed"] = sum(failures.values())
    return _sanitize_report(report)


def _run_transfer_mode(
    session_factory: sessionmaker,
    bucket: Any,
    *,
    mode: str,
    migration_id: str,
    allowlist: frozenset[str],
    limit: int,
) -> dict[str, Any]:
    if not allowlist:
        raise ValueError("source-host allowlist must not be empty")
    if limit < 0:
        raise ValueError("limit must be zero or positive")
    temp_dir = _new_run_temp_directory(migration_id)
    try:
        initial_snapshot = probe_resources(temp_dir)
        start_gate(initial_snapshot)
        candidates = _fetch_candidates(session_factory, limit=limit)
        report = _base_run_report(mode=mode, migration_id=migration_id, candidates=candidates)
        policy = DownloadPolicy(allowed_hosts=allowlist)
        bucket_name = _bucket_name(bucket)
        groups: dict[UUID, list[ExternalPhotoCandidate]] = {}
        for candidate in candidates:
            groups.setdefault(candidate.group_id, []).append(candidate)

        consecutive_oss_errors = 0
        stopped = False
        for group_id, group_candidates in groups.items():
            transfers: list[PreparedTransfer] = []
            for candidate in group_candidates:
                snapshot = probe_resources(temp_dir)
                reason = stop_reason(snapshot, initial_snapshot.oom_marker, consecutive_oss_errors)
                if reason:
                    report["stop_reason"] = reason
                    stopped = True
                    break
                item = report["items"][str(candidate.photo_id)]
                downloaded = None
                try:
                    source = ExternalPhotoSource(
                        photo_id=str(candidate.photo_id),
                        team_id=candidate.team_id,
                        group_id=str(candidate.group_id),
                        url=candidate.url,
                        filename=candidate.filename,
                    )
                    downloaded = download_external_photo(source, policy, temp_dir=temp_dir)
                    hash_status = _hash_status(candidate, downloaded.sha256)
                    if hash_status != "accepted":
                        item["status"] = hash_status
                        continue
                    key = oss_object_key(
                        "external-migration",
                        candidate.filename,
                        downloaded.sha256,
                        team_id=candidate.team_id,
                        group_id=str(candidate.group_id),
                    )
                    try:
                        receipt = store_downloaded_photo(bucket, bucket_name, key, downloaded)
                    except (OssObjectConflictError, OssVerificationError) as exc:
                        consecutive_oss_errors += 1
                        item["status"] = (
                            "oss_object_conflict"
                            if isinstance(exc, OssObjectConflictError)
                            else "oss_verification_failed"
                        )
                        item["error"] = _sanitize_text(str(exc))
                        if consecutive_oss_errors >= OSS_ERROR_LIMIT:
                            report["stop_reason"] = "oss_error_limit"
                            stopped = True
                        continue
                    except Exception as exc:
                        consecutive_oss_errors += 1
                        item["status"] = "oss_error"
                        item["error"] = _sanitize_text(str(exc))
                        if consecutive_oss_errors >= OSS_ERROR_LIMIT:
                            report["stop_reason"] = "oss_error_limit"
                            stopped = True
                        continue
                    consecutive_oss_errors = 0
                    report["byte_count"] += receipt.byte_size
                    if receipt.reused:
                        report["reused_objects"] += 1
                    else:
                        report["uploaded"] += 1
                    item["status"] = "uploaded"
                    transfers.append(PreparedTransfer(candidate, receipt))
                except PhotoTransferError as exc:
                    item["status"] = "download_failed"
                    item["error"] = _sanitize_text(str(exc))
                except Exception as exc:
                    item["status"] = "transfer_failed"
                    item["error"] = _sanitize_text(str(exc))
                finally:
                    if downloaded is not None:
                        cleanup_download(downloaded)
                if stopped:
                    break

            if stopped:
                for transfer in transfers:
                    report["items"][str(transfer.candidate.photo_id)]["status"] = "uploaded_not_committed"
                break
            if not transfers:
                continue
            try:
                committed = _commit_group(
                    session_factory,
                    group_id=group_id,
                    transfers=transfers,
                    migration_id=migration_id,
                )
            except Exception as exc:
                for transfer in transfers:
                    item = report["items"][str(transfer.candidate.photo_id)]
                    item["status"] = "commit_failed"
                    item["error"] = _sanitize_text(str(exc))
                continue
            for transfer in transfers:
                item = report["items"][str(transfer.candidate.photo_id)]
                item["status"] = committed["statuses"].get(str(transfer.candidate.photo_id), "commit_failed")
                item["group_status"] = committed["group_status"]
                item["final_delivery_ready"] = committed["final_delivery_ready"]
        return _finish_run_report(report, session_factory)
    finally:
        _close_run_temp_directory(temp_dir)


def execute_run(
    session_factory: sessionmaker,
    bucket: Any,
    *,
    migration_id: str,
    allowlist: frozenset[str],
    limit: int = 0,
) -> dict[str, Any]:
    return _run_transfer_mode(
        session_factory,
        bucket,
        mode="execute",
        migration_id=migration_id,
        allowlist=allowlist,
        limit=limit,
    )


def resume_run(
    session_factory: sessionmaker,
    bucket: Any,
    *,
    migration_id: str,
    allowlist: frozenset[str],
    limit: int = 0,
) -> dict[str, Any]:
    return _run_transfer_mode(
        session_factory,
        bucket,
        mode="resume",
        migration_id=migration_id,
        allowlist=allowlist,
        limit=limit,
    )


def _fetch_rollback_candidates(
    session_factory: sessionmaker,
    *,
    migration_id: str,
) -> list[RollbackCandidate]:
    statement = (
        select(Photo.id.label("photo_id"), Photo.group_id)
        .where(
            Photo.storage_type == "oss",
            Photo.raw_data["oss_migration_id"].as_string() == migration_id,
        )
        .order_by(Photo.team_id.asc(), Photo.group_id.asc(), Photo.id.asc())
    )
    with session_factory() as session:
        try:
            session.execute(text("SET TRANSACTION READ ONLY"))
            return [
                RollbackCandidate(UUID(str(row.photo_id)), UUID(str(row.group_id)))
                for row in session.execute(statement).all()
            ]
        finally:
            session.rollback()


def _rollback_group(
    session_factory: sessionmaker,
    *,
    group_id: UUID,
    candidates: list[RollbackCandidate],
    migration_id: str,
) -> dict[str, Any]:
    statuses: dict[str, str] = {}
    source_urls: dict[str, str] = {}
    candidate_ids = {candidate.photo_id for candidate in candidates}
    group_status = ""
    final_delivery_ready = False
    with session_factory() as session:
        with session.begin():
            group = session.scalar(
                select(MaterialGroup)
                .where(MaterialGroup.id == group_id)
                .with_for_update()
            )
            if group is None:
                return {
                    "statuses": {str(photo_id): "conflict" for photo_id in candidate_ids},
                    "source_urls": {},
                    "group_status": "missing",
                    "final_delivery_ready": False,
                }
            group_status = _enum_text(group.status)
            locked_photos = session.scalars(
                select(Photo)
                .where(Photo.id.in_(candidate_ids))
                .order_by(Photo.id.asc())
                .with_for_update()
            ).all()
            photos_by_id = {photo.id: photo for photo in locked_photos if photo.id in candidate_ids}
            changed = False
            for photo_id in sorted(candidate_ids, key=str):
                item_key = str(photo_id)
                photo = photos_by_id.get(photo_id)
                if photo is None:
                    statuses[item_key] = "conflict"
                    continue
                raw = dict(photo.raw_data or {})
                exact_current_object = bool(
                    photo.storage_type == "oss"
                    and raw.get("oss_migration_id") == migration_id
                    and photo.storage_bucket == raw.get("oss_migration_bucket")
                    and photo.storage_key == raw.get("oss_migration_key")
                    and photo.object_key == raw.get("oss_migration_key")
                    and photo.sha256 == raw.get("oss_migration_sha256")
                )
                required_pre_oss = {
                    "pre_oss_image_url",
                    "pre_oss_storage_type",
                    "pre_oss_storage_bucket",
                    "pre_oss_storage_key",
                    "pre_oss_object_key",
                    "pre_oss_sha256",
                    "pre_oss_content_type",
                    "pre_oss_byte_size",
                }
                if not exact_current_object or not required_pre_oss.issubset(raw):
                    statuses[item_key] = "conflict"
                    continue
                photo.image_url = raw["pre_oss_image_url"]
                photo.storage_type = raw["pre_oss_storage_type"]
                photo.storage_bucket = raw["pre_oss_storage_bucket"]
                photo.storage_key = raw["pre_oss_storage_key"]
                photo.object_key = raw["pre_oss_object_key"]
                photo.sha256 = raw["pre_oss_sha256"]
                photo.content_type = raw["pre_oss_content_type"]
                photo.byte_size = raw["pre_oss_byte_size"]
                raw["oss_rollback_at"] = datetime.now(UTC).isoformat()
                photo.raw_data = raw
                statuses[item_key] = "rolled_back"
                source_urls[item_key] = redact_source_url(str(photo.image_url or ""))
                changed = True
            if changed:
                session.flush()
                invalidate_verification_for_group(
                    session,
                    group,
                    actor="oss-migration",
                    reason="external_photo_oss_migration_rolled_back",
                )
                final_delivery_ready = _final_delivery_ready(group)
    return {
        "statuses": statuses,
        "source_urls": source_urls,
        "group_status": group_status,
        "final_delivery_ready": final_delivery_ready,
    }


def rollback_run(
    session_factory: sessionmaker,
    *,
    migration_id: str,
) -> dict[str, Any]:
    candidates = _fetch_rollback_candidates(session_factory, migration_id=migration_id)
    report: dict[str, Any] = {
        "mode": "rollback",
        "migration_id": migration_id,
        "candidate_count": len(candidates),
        "rolled_back": 0,
        "failed": 0,
        "conflicts": 0,
        "remaining_external_url": 0,
        "unknown_storage": 0,
        "failure_counts": {},
        "items": {
            str(candidate.photo_id): {
                "group_id": str(candidate.group_id),
                "group_status": "",
                "final_delivery_ready": False,
                "status": "not_started",
            }
            for candidate in candidates
        },
    }
    groups: dict[UUID, list[RollbackCandidate]] = {}
    for candidate in candidates:
        groups.setdefault(candidate.group_id, []).append(candidate)
    for group_id, group_candidates in groups.items():
        try:
            result = _rollback_group(
                session_factory,
                group_id=group_id,
                candidates=group_candidates,
                migration_id=migration_id,
            )
        except Exception as exc:
            for candidate in group_candidates:
                item = report["items"][str(candidate.photo_id)]
                item["status"] = "rollback_failed"
                item["error"] = _sanitize_text(str(exc))
            continue
        for candidate in group_candidates:
            item_key = str(candidate.photo_id)
            item = report["items"][item_key]
            item["status"] = result["statuses"].get(item_key, "rollback_failed")
            item["group_status"] = result["group_status"]
            item["final_delivery_ready"] = result["final_delivery_ready"]
            if item_key in result["source_urls"]:
                item["source_url"] = result["source_urls"][item_key]
    status_counts = Counter(item["status"] for item in report["items"].values())
    report["rolled_back"] = status_counts["rolled_back"]
    report["conflicts"] = status_counts["conflict"]
    ignored = {"rolled_back", "not_started"}
    report["failure_counts"] = {
        status: count for status, count in sorted(status_counts.items()) if status not in ignored
    }
    report["failed"] = sum(report["failure_counts"].values())
    remaining, unknown = _database_counts(session_factory)
    report["remaining_external_url"] = remaining
    report["unknown_storage"] = unknown
    return _sanitize_report(report)


def load_allowlist(path: Path) -> frozenset[str]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SystemExit(f"--allowlist-file cannot be read: {path}") from exc
    hosts: set[str] = set()
    for line in lines:
        host = line.split("#", 1)[0].strip().lower().rstrip(".")
        if not host:
            continue
        if not HOST_RE.fullmatch(host):
            raise SystemExit(f"--allowlist-file contains an invalid host: {host}")
        hosts.add(host)
    if not hosts:
        raise SystemExit("--allowlist-file must contain at least one source host")
    return frozenset(hosts)


def validate_args(args: argparse.Namespace) -> argparse.Namespace:
    mutating = bool(args.execute or args.resume)
    if mutating and not str(args.migration_id or "").strip():
        raise SystemExit("--execute/--resume require --migration-id")
    migration_id = args.rollback_run or args.migration_id
    if migration_id and not MIGRATION_ID_RE.fullmatch(str(migration_id)):
        raise SystemExit("migration id must contain only letters, digits, dot, underscore, or hyphen")
    if mutating and args.allowlist_file is None:
        raise SystemExit("--execute/--resume require --allowlist-file")
    if args.limit is not None:
        if not mutating:
            raise SystemExit("--limit is valid only for --execute or --resume")
        if args.limit <= 0:
            raise SystemExit("--limit must be a positive integer")
    if mutating and args.team_id:
        raise SystemExit("--team-id is valid only for --dry-run")
    if args.rollback_run and (args.migration_id or args.allowlist_file or args.team_id):
        raise SystemExit("--rollback-run accepts only its run id and optional --report")
    return args


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate external PostgreSQL photos to OSS safely.")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--execute", action="store_true")
    modes.add_argument("--resume", action="store_true")
    modes.add_argument("--rollback-run", metavar="ID")
    parser.add_argument("--migration-id")
    parser.add_argument("--allowlist-file", type=Path)
    parser.add_argument("--team-id", default="")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--report", type=Path)
    return validate_args(parser.parse_args(argv))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.dry_run:
        allowlist = load_allowlist(args.allowlist_file) if args.allowlist_file else None
        with SessionLocal() as session:
            report = run_dry_run(session, team_id=args.team_id, allowlist=allowlist)
        report_name = f"dry-run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    elif args.rollback_run:
        report = rollback_run(SessionLocal, migration_id=args.rollback_run)
        report_name = f"rollback-{args.rollback_run}"
    else:
        allowlist = load_allowlist(args.allowlist_file)
        bucket = require_oss_client()
        runner = resume_run if args.resume else execute_run
        report = runner(
            SessionLocal,
            bucket,
            migration_id=args.migration_id,
            allowlist=allowlist,
            limit=args.limit or 0,
        )
        report_name = f"{'resume' if args.resume else 'execute'}-{args.migration_id}"
    report_path = args.report or operational_directory() / f"{report_name}.json"
    write_report(report_path, report)
    print(json.dumps(_sanitize_report(report), ensure_ascii=False, indent=2))
    return 1 if report.get("failed") or report.get("stop_reason") else 0


if __name__ == "__main__":
    raise SystemExit(main())
