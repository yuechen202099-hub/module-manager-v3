from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal  # noqa: E402
from app.models import Photo  # noqa: E402
from app.services.account_store import list_users  # noqa: E402


def now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)


def backup_file(path: Path, label: str, backup_dir: Path | None = None) -> Path | None:
    if not path.exists():
        return None
    target_dir = backup_dir or path.parent / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{path.stem}.{label}.{now_stamp()}{path.suffix}"
    shutil.copy2(path, target)
    return target


def public_user_map_from_file(path: Path) -> dict[str, str]:
    payload = read_json(path)
    raw_users = payload.get("users") if isinstance(payload, dict) else []
    mapping: dict[str, str] = {}
    if not isinstance(raw_users, list):
        return mapping
    for raw_user in raw_users:
        if not isinstance(raw_user, dict):
            continue
        username = str(raw_user.get("username") or "").strip()
        name = str(raw_user.get("name") or "").strip()
        if username and name and username != name:
            mapping[username] = name
    return mapping


def public_user_map(users_path: Path | None = None) -> dict[str, str]:
    if users_path is not None:
        return public_user_map_from_file(users_path)
    mapping: dict[str, str] = {}
    for user in list_users():
        username = str(user.get("username") or "").strip()
        name = str(user.get("name") or "").strip()
        if username and name and username != name:
            mapping[username] = name
    return mapping


def is_construction_photo(source: str | None, raw: dict[str, Any] | None) -> bool:
    raw = raw or {}
    source_text = " ".join(
        str(value or "")
        for value in (source, raw.get("upload_source"), raw.get("storage_source"), raw.get("source_file"))
    ).lower()
    return "construction" in source_text


def backfill_postgres(
    *,
    user_names: dict[str, str],
    team_id: str = "",
    dry_run: bool = True,
    limit: int = 0,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "backend": "postgres",
        "dry_run": dry_run,
        "team_id": team_id,
        "candidate_usernames": sorted(user_names),
        "photos_seen": 0,
        "construction_photos_seen": 0,
        "matched_creator_username": 0,
        "updated": 0,
        "skipped_non_construction": 0,
        "skipped_no_mapping": 0,
        "by_username": {},
    }
    usernames = set(user_names)
    if not usernames:
        return report
    with SessionLocal() as session:
        statement = select(Photo).where(Photo.creator.in_(sorted(usernames))).order_by(Photo.created_at.asc(), Photo.id.asc())
        if team_id:
            statement = statement.where(Photo.team_id == team_id)
        if limit > 0:
            statement = statement.limit(limit)
        photos = session.scalars(statement).all()
        report["photos_seen"] = len(photos)
        for photo in photos:
            username = str(photo.creator or "").strip()
            target_name = user_names.get(username)
            if not target_name:
                report["skipped_no_mapping"] += 1
                continue
            raw_data = dict(photo.raw_data or {})
            if not is_construction_photo(photo.source, raw_data):
                report["skipped_non_construction"] += 1
                continue
            report["construction_photos_seen"] += 1
            report["matched_creator_username"] += 1
            by_username = report["by_username"].setdefault(username, {"target_name": target_name, "photos": 0})
            by_username["photos"] += 1
            if dry_run:
                continue
            photo.creator = target_name
            raw_data["creator"] = target_name
            photo.raw_data = raw_data
            report["updated"] += 1
        if not dry_run:
            session.commit()
        else:
            session.rollback()
    return report


def iter_json_groups(state_payload: dict[str, Any], team_id: str = ""):
    teams = state_payload.get("teams") if isinstance(state_payload, dict) else {}
    if not isinstance(teams, dict):
        return
    for current_team_id, team_state in teams.items():
        if team_id and current_team_id != team_id:
            continue
        if not isinstance(team_state, dict):
            continue
        groups = team_state.get("groups") or []
        if not isinstance(groups, list):
            continue
        for group in groups:
            if isinstance(group, dict):
                yield current_team_id, group


def backfill_json_state(
    *,
    state_path: Path,
    user_names: dict[str, str],
    team_id: str = "",
    dry_run: bool = True,
    backup_dir: Path | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "backend": "json",
        "dry_run": dry_run,
        "state_path": str(state_path),
        "team_id": team_id,
        "photos_seen": 0,
        "construction_photos_seen": 0,
        "matched_creator_username": 0,
        "updated": 0,
        "skipped_non_construction": 0,
        "skipped_no_mapping": 0,
        "backup": "",
        "by_username": {},
    }
    if not state_path.exists():
        report["missing_state_file"] = True
        return report
    payload = read_json(state_path)
    for _, group in iter_json_groups(payload, team_id):
        photos = group.get("photos") or []
        if not isinstance(photos, list):
            continue
        for photo in photos:
            if not isinstance(photo, dict):
                continue
            report["photos_seen"] += 1
            username = str(photo.get("creator") or "").strip()
            target_name = user_names.get(username)
            if not target_name:
                report["skipped_no_mapping"] += 1
                continue
            if not is_construction_photo(str(photo.get("source") or ""), photo):
                report["skipped_non_construction"] += 1
                continue
            report["construction_photos_seen"] += 1
            report["matched_creator_username"] += 1
            by_username = report["by_username"].setdefault(username, {"target_name": target_name, "photos": 0})
            by_username["photos"] += 1
            if dry_run:
                continue
            photo["creator"] = target_name
            report["updated"] += 1
    if not dry_run and report["updated"]:
        backup = backup_file(state_path, "pre-creator-name-backfill", backup_dir)
        report["backup"] = str(backup or "")
        write_json(state_path, payload)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill construction photo creator usernames to display names.")
    parser.add_argument("--team-id", default="", help="Only backfill one team id.")
    parser.add_argument("--users", default="", help="Path to users.json. Defaults to AUTH_USERS_PATH.")
    parser.add_argument("--state", default="", help="Optional local_state.json path to backfill JSON compatibility state.")
    parser.add_argument("--backup-dir", default="", help="Directory for JSON state backups.")
    parser.add_argument("--report", default="", help="Write JSON report to this path.")
    parser.add_argument("--limit", type=int, default=0, help="Limit PostgreSQL candidate photos for testing.")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=True, help="Preview changes without writing.")
    parser.add_argument("--apply", dest="dry_run", action="store_false", help="Write the backfill changes.")
    parser.add_argument("--skip-postgres", action="store_true", help="Only update JSON state when --state is provided.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    users_path = Path(args.users) if args.users else None
    state_path = Path(args.state or os.getenv("LOCAL_SIMULATION_STATE_PATH", "")) if (args.state or os.getenv("LOCAL_SIMULATION_STATE_PATH")) else None
    backup_dir = Path(args.backup_dir) if args.backup_dir else None
    user_names = public_user_map(users_path)
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "dry_run": bool(args.dry_run),
        "team_id": args.team_id,
        "user_mapping_count": len(user_names),
        "postgres": {},
        "json_state": {},
    }
    if not args.skip_postgres:
        report["postgres"] = backfill_postgres(
            user_names=user_names,
            team_id=args.team_id.strip(),
            dry_run=bool(args.dry_run),
            limit=max(args.limit, 0),
        )
    if state_path is not None:
        report["json_state"] = backfill_json_state(
            state_path=state_path,
            user_names=user_names,
            team_id=args.team_id.strip(),
            dry_run=bool(args.dry_run),
            backup_dir=backup_dir,
        )
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
