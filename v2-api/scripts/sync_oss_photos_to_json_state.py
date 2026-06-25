from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.models import Photo  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def backup_state(path: Path, backup_dir: Path | None) -> Path:
    target_dir = backup_dir or path.parent / "backups"
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{path.stem}.pre-oss-json-sync-{stamp}{path.suffix}"
    shutil.copy2(path, target)
    return target


def load_oss_photos(database_url: str) -> dict[str, dict[str, Any]]:
    engine = create_engine(database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with SessionLocal() as session:
        photos = session.scalars(select(Photo).where(Photo.storage_type == "oss")).all()
        return {
            str(photo.legacy_id): {
                "image_url": photo.image_url,
                "storage_type": photo.storage_type,
                "storage_bucket": photo.storage_bucket,
                "storage_key": photo.storage_key,
                "sha256": photo.sha256,
                "content_type": photo.content_type,
                "byte_size": photo.byte_size,
            }
            for photo in photos
            if photo.legacy_id
        }


def sync_state(state: dict[str, Any], photos_by_legacy_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    report = {
        "teams": 0,
        "groups": 0,
        "photos_seen": 0,
        "updated_to_oss": 0,
        "already_oss": 0,
        "missing_in_db": 0,
        "without_legacy_id": 0,
    }
    teams = state.get("teams") if isinstance(state, dict) else {}
    if not isinstance(teams, dict):
        return report
    for team_state in teams.values():
        if not isinstance(team_state, dict):
            continue
        report["teams"] += 1
        groups = team_state.get("groups") or []
        for group in groups:
            if not isinstance(group, dict):
                continue
            report["groups"] += 1
            for photo in group.get("photos") or []:
                if not isinstance(photo, dict):
                    continue
                report["photos_seen"] += 1
                legacy_id = str(photo.get("id") or "").strip()
                if not legacy_id:
                    report["without_legacy_id"] += 1
                    continue
                oss_photo = photos_by_legacy_id.get(legacy_id)
                if not oss_photo:
                    report["missing_in_db"] += 1
                    continue
                if photo.get("storage_type") == "oss" and photo.get("storage_key") == oss_photo.get("storage_key"):
                    report["already_oss"] += 1
                    continue
                if photo.get("storage_type") != "oss":
                    photo.setdefault("pre_oss_image_url", photo.get("image_url", ""))
                    photo.setdefault("pre_oss_storage_type", photo.get("storage_type", ""))
                    photo.setdefault("pre_oss_storage_key", photo.get("storage_key", ""))
                for key, value in oss_photo.items():
                    if value is not None:
                        photo[key] = value
                photo["download_status"] = "oss_migrated"
                report["updated_to_oss"] += 1
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write PostgreSQL OSS photo refs back into local_state.json.")
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--database-url", default="")
    parser.add_argument("--backup-dir", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    state = read_json(args.state)
    photos = load_oss_photos(args.database_url or settings.database_url)
    report = sync_state(state, photos)
    report["oss_photos_in_db"] = len(photos)
    report["dry_run"] = bool(args.dry_run)
    report["state_path"] = str(args.state)
    if not args.dry_run:
        report["backup_path"] = str(backup_state(args.state, args.backup_dir))
        write_json(args.state, state)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
