from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import mimetypes
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.models import Photo  # noqa: E402
from app.services.photo_storage import normalize_suffix, oss_server_endpoint, sanitize_part  # noqa: E402


@dataclass(frozen=True)
class PhotoCandidate:
    id: str
    team_id: str
    group_id: str
    legacy_id: str
    image_url: str
    storage_type: str
    storage_bucket: str
    storage_key: str
    original_filename: str
    object_key: str
    content_type: str
    sha256: str
    metadata_json: dict[str, Any]


@dataclass
class MigrationResult:
    photo_id: str
    status: str
    source_type: str
    source_ref: str
    oss_bucket: str = ""
    oss_key: str = ""
    oss_url: str = ""
    sha256: str = ""
    byte_size: int = 0
    content_type: str = ""
    error: str = ""


def utc_now_text() -> str:
    return datetime.now(UTC).isoformat()


def require_oss_bucket():
    endpoint = oss_server_endpoint()
    missing = [
        name
        for name, value in {
            "OSS_ENDPOINT/OSS_INTERNAL_ENDPOINT": endpoint,
            "OSS_BUCKET": settings.oss_bucket,
            "OSS_ACCESS_KEY_ID": settings.oss_access_key_id,
            "OSS_ACCESS_KEY_SECRET": settings.oss_access_key_secret,
        }.items()
        if not str(value or "").strip()
    ]
    if missing:
        raise RuntimeError(f"OSS config is incomplete: {', '.join(missing)}")
    try:
        import oss2
    except ImportError as exc:
        raise RuntimeError("The oss2 package is required before migrating photos to OSS") from exc
    auth = oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret)
    return oss2.Bucket(auth, endpoint, settings.oss_bucket)


def parse_oss_url(image_url: str) -> tuple[str, str]:
    parsed = urlparse(str(image_url or ""))
    if parsed.scheme != "oss":
        return "", ""
    return parsed.netloc, parsed.path.lstrip("/")


def infer_source_type(candidate: PhotoCandidate) -> str:
    if candidate.storage_type == "oss" or candidate.image_url.startswith("oss://"):
        return "oss"
    if candidate.storage_type == "local_upload" or candidate.image_url.startswith("/static/uploads/"):
        return "local_upload"
    parsed = urlparse(candidate.image_url)
    if parsed.scheme in {"http", "https"}:
        return "external_url"
    if candidate.storage_key:
        return "local_upload"
    if candidate.object_key and Path(candidate.object_key).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        return "local_upload"
    return "missing"


def suffix_from_candidate(candidate: PhotoCandidate, content_type: str = "") -> str:
    for value in (candidate.original_filename, candidate.image_url, candidate.storage_key, candidate.object_key):
        try:
            return normalize_suffix(Path(str(value).split("?", 1)[0]).name)
        except ValueError:
            continue
    guessed = mimetypes.guess_extension(content_type.split(";", 1)[0].strip()) if content_type else ""
    try:
        return normalize_suffix(guessed or ".jpg")
    except ValueError:
        return ".jpg"


def build_oss_key(candidate: PhotoCandidate, content_sha256: str, suffix: str) -> str:
    prefix = settings.oss_prefix.strip().strip("/") or "module-manager-v2"
    team_id = sanitize_part(candidate.team_id, "default-team")
    group_id = sanitize_part(candidate.group_id, "group")
    photo_id = sanitize_part(candidate.legacy_id or candidate.id, "photo")
    return "/".join(
        [
            prefix,
            team_id,
            "migrated-photos",
            group_id,
            f"{photo_id}-{content_sha256[:16]}{suffix}",
        ]
    )


def local_candidates(candidate: PhotoCandidate, uploads_root: Path) -> list[Path]:
    values = []
    if candidate.storage_key:
        values.append(candidate.storage_key)
    if candidate.image_url.startswith("/static/uploads/"):
        values.append(candidate.image_url.removeprefix("/static/uploads/"))
    if candidate.object_key:
        if Path(candidate.object_key).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
            values.append(candidate.object_key)
    paths: list[Path] = []
    for value in values:
        text = str(value or "").strip().lstrip("/")
        if not text:
            continue
        path = uploads_root / text.removeprefix("static/uploads/").removeprefix("uploads/")
        paths.append(path)
    return paths


def read_local_photo(candidate: PhotoCandidate, uploads_root: Path) -> tuple[bytes, str]:
    for path in local_candidates(candidate, uploads_root):
        if path.exists() and path.is_file():
            return path.read_bytes(), mimetypes.guess_type(path.name)[0] or candidate.content_type or "application/octet-stream"
    checked = ", ".join(str(path) for path in local_candidates(candidate, uploads_root)) or "(none)"
    raise FileNotFoundError(f"Local upload file not found for photo {candidate.id}; checked: {checked}")


def download_photo(candidate: PhotoCandidate, timeout: int, max_bytes: int, retries: int, retry_delay: float) -> tuple[bytes, str]:
    if not candidate.image_url:
        raise ValueError(f"Photo {candidate.id} has no image_url to download")
    request = Request(
        candidate.image_url,
        headers={
            "User-Agent": "module-manager-v2-photo-migrator/1.0",
            "Accept": "image/*,*/*;q=0.8",
        },
    )
    last_error = ""
    for attempt in range(1, retries + 2):
        try:
            with urlopen(request, timeout=timeout) as response:
                content_type = response.headers.get("Content-Type", "") or candidate.content_type or "application/octet-stream"
                content = response.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise ValueError(f"Photo {candidate.id} exceeds max bytes limit")
            if content:
                return content, content_type
            last_error = "downloaded empty content"
        except (URLError, TimeoutError, ValueError) as exc:
            last_error = str(exc)
        if attempt <= retries:
            time.sleep(retry_delay * attempt)
    raise RuntimeError(f"Failed to download {candidate.image_url}: {last_error}")


def load_photo_bytes(
    candidate: PhotoCandidate,
    uploads_root: Path,
    timeout: int,
    max_bytes: int,
    retries: int,
    retry_delay: float,
) -> tuple[bytes, str, str, str]:
    source_type = infer_source_type(candidate)
    if source_type == "local_upload":
        content, content_type = read_local_photo(candidate, uploads_root)
        return content, content_type, source_type, candidate.storage_key or candidate.image_url or candidate.object_key
    if source_type == "external_url":
        content, content_type = download_photo(candidate, timeout, max_bytes, retries, retry_delay)
        return content, content_type, source_type, candidate.image_url
    if source_type == "oss":
        bucket, key = parse_oss_url(candidate.image_url)
        return b"", candidate.content_type, source_type, key or candidate.storage_key
    raise ValueError(f"Photo {candidate.id} has no supported source")


def migrate_one_photo(
    candidate: PhotoCandidate,
    uploads_root: Path,
    timeout: int,
    max_bytes: int,
    dry_run: bool,
    force: bool,
    retries: int,
    retry_delay: float,
) -> MigrationResult:
    source_type = infer_source_type(candidate)
    if source_type == "missing":
        return MigrationResult(
            photo_id=candidate.id,
            status="skipped_missing_source",
            source_type=source_type,
            source_ref="",
            error="Photo record has no image_url, local storage key, or object key source.",
        )
    existing_bucket, existing_key = parse_oss_url(candidate.image_url)
    if source_type == "oss" and candidate.storage_key and not force:
        return MigrationResult(
            photo_id=candidate.id,
            status="skipped_existing_oss",
            source_type="oss",
            source_ref=existing_key or candidate.storage_key,
            oss_bucket=candidate.storage_bucket or existing_bucket or settings.oss_bucket,
            oss_key=candidate.storage_key or existing_key,
            oss_url=candidate.image_url,
            sha256=candidate.sha256,
        )

    content, content_type, source_type, source_ref = load_photo_bytes(
        candidate,
        uploads_root,
        timeout,
        max_bytes,
        retries,
        retry_delay,
    )
    if source_type == "oss" and not force:
        return MigrationResult(photo_id=candidate.id, status="skipped_existing_oss", source_type=source_type, source_ref=source_ref)

    content_sha256 = hashlib.sha256(content).hexdigest()
    suffix = suffix_from_candidate(candidate, content_type)
    oss_key = build_oss_key(candidate, content_sha256, suffix)
    oss_url = f"oss://{settings.oss_bucket}/{oss_key}"
    if dry_run:
        return MigrationResult(
            photo_id=candidate.id,
            status="dry_run",
            source_type=source_type,
            source_ref=source_ref,
            oss_bucket=settings.oss_bucket,
            oss_key=oss_key,
            oss_url=oss_url,
            sha256=content_sha256,
            byte_size=len(content),
            content_type=content_type,
        )

    bucket = require_oss_bucket()
    bucket.put_object(oss_key, content, headers={"Content-Type": content_type})
    return MigrationResult(
        photo_id=candidate.id,
        status="uploaded",
        source_type=source_type,
        source_ref=source_ref,
        oss_bucket=settings.oss_bucket,
        oss_key=oss_key,
        oss_url=oss_url,
        sha256=content_sha256,
        byte_size=len(content),
        content_type=content_type,
    )


def load_candidates(session: Session, team_id: str = "", limit: int = 0, force: bool = False) -> list[PhotoCandidate]:
    statement = select(Photo).order_by(Photo.created_at.asc(), Photo.id.asc())
    if team_id:
        statement = statement.where(Photo.team_id == team_id)
    if not force:
        statement = statement.where((Photo.storage_type.is_(None)) | (Photo.storage_type != "oss"))
    if limit > 0:
        statement = statement.limit(limit)
    candidates: list[PhotoCandidate] = []
    for photo in session.scalars(statement).all():
        candidates.append(
            PhotoCandidate(
                id=str(photo.id),
                team_id=str(photo.team_id or "default-team"),
                group_id=str(photo.group_id),
                legacy_id=str(photo.legacy_id or ""),
                image_url=str(photo.image_url or ""),
                storage_type=str(photo.storage_type or ""),
                storage_bucket=str(photo.storage_bucket or ""),
                storage_key=str(photo.storage_key or ""),
                original_filename=str(photo.original_filename or ""),
                object_key=str(photo.object_key or ""),
                content_type=str(photo.content_type or ""),
                sha256=str(photo.sha256 or ""),
                metadata_json=photo.metadata_json or {},
            )
        )
    return candidates


def apply_results(session: Session, results: list[MigrationResult]) -> None:
    uploaded = [result for result in results if result.status == "uploaded"]
    if not uploaded:
        return
    photos_by_id = {
        str(photo.id): photo
        for photo in session.scalars(select(Photo).where(Photo.id.in_([result.photo_id for result in uploaded]))).all()
    }
    migrated_at = utc_now_text()
    for result in uploaded:
        photo = photos_by_id.get(result.photo_id)
        if photo is None:
            continue
        metadata = dict(photo.metadata_json or {})
        metadata.setdefault("pre_oss_image_url", photo.image_url)
        metadata.setdefault("pre_oss_storage_type", photo.storage_type)
        metadata.setdefault("pre_oss_storage_bucket", photo.storage_bucket)
        metadata.setdefault("pre_oss_storage_key", photo.storage_key)
        metadata["oss_migrated_at"] = migrated_at
        metadata["oss_migration_source_type"] = result.source_type
        metadata["oss_migration_source_ref"] = result.source_ref
        photo.image_url = result.oss_url
        photo.storage_type = "oss"
        photo.storage_bucket = result.oss_bucket
        photo.storage_key = result.oss_key
        photo.object_key = result.oss_key
        photo.sha256 = result.sha256
        photo.byte_size = result.byte_size
        photo.content_type = result.content_type
        photo.metadata_json = metadata
    session.commit()


def summarize_results(candidates: list[PhotoCandidate], results: list[MigrationResult], elapsed_seconds: float) -> dict[str, Any]:
    report: dict[str, Any] = {
        "started_at": utc_now_text(),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "selected_photos": len(candidates),
        "uploaded": 0,
        "dry_run": 0,
        "skipped_existing_oss": 0,
        "skipped_missing_source": 0,
        "failed": 0,
        "bytes": 0,
        "by_source_type": {},
        "failures": [],
    }
    for result in results:
        report[result.status] = int(report.get(result.status, 0)) + 1
        report["bytes"] += int(result.byte_size or 0)
        report["by_source_type"][result.source_type] = int(report["by_source_type"].get(result.source_type, 0)) + 1
        if result.status == "failed":
            report["failures"].append(asdict(result))
    return report


def write_report(path: Path | None, report: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Move all PostgreSQL photo records to OSS storage.")
    parser.add_argument("--database-url", default="", help="Override DATABASE_URL.")
    parser.add_argument("--uploads-root", type=Path, default=ROOT / "app" / "static" / "uploads")
    parser.add_argument("--team-id", default="", help="Limit migration to one team id.")
    parser.add_argument("--limit", type=int, default=0, help="Limit selected photos for rehearsal.")
    parser.add_argument("--max-workers", type=int, default=6, help="Concurrent download/upload workers.")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP download timeout seconds.")
    parser.add_argument("--retries", type=int, default=3, help="Retries for transient empty/failed HTTP downloads.")
    parser.add_argument("--retry-delay", type=float, default=1.5, help="Base seconds between HTTP retries.")
    parser.add_argument("--max-mb", type=int, default=30, help="Maximum single photo size in MB.")
    parser.add_argument("--dry-run", action="store_true", help="Download/read photos and compute OSS keys without uploading/updating DB.")
    parser.add_argument("--force", action="store_true", help="Re-upload photos already marked as OSS.")
    parser.add_argument("--report", type=Path, default=None, help="Write JSON report.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.max_workers < 1:
        raise SystemExit("--max-workers must be >= 1")
    database_url = args.database_url or settings.database_url
    engine = create_engine(database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with SessionLocal() as session:
        candidates = load_candidates(session, team_id=args.team_id, limit=args.limit, force=args.force)

    start = time.monotonic()
    results: list[MigrationResult] = []
    max_bytes = args.max_mb * 1024 * 1024
    if candidates and not args.dry_run:
        require_oss_bucket()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {
            executor.submit(
                migrate_one_photo,
                candidate,
                args.uploads_root,
                args.timeout,
                max_bytes,
                args.dry_run,
                args.force,
                args.retries,
                args.retry_delay,
            ): candidate
            for candidate in candidates
        }
        for future in concurrent.futures.as_completed(futures):
            candidate = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001
                results.append(
                    MigrationResult(
                        photo_id=candidate.id,
                        status="failed",
                        source_type=infer_source_type(candidate),
                        source_ref=candidate.image_url or candidate.storage_key or candidate.object_key,
                        error=str(exc),
                    )
                )

    if not args.dry_run:
        with SessionLocal() as session:
            apply_results(session, results)

    report = summarize_results(candidates, results, time.monotonic() - start)
    report["dry_run_mode"] = bool(args.dry_run)
    report["uploads_root"] = str(args.uploads_root)
    report["oss_bucket"] = settings.oss_bucket
    report["oss_endpoint"] = settings.oss_endpoint
    write_report(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
