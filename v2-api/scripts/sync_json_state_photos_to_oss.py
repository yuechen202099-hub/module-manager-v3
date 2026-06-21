from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.local_simulation import (  # noqa: E402
    list_team_states,
    reset_current_team,
    save_all_team_states,
    set_current_team,
    sync_state_photos_to_oss,
)
from app.services.photo_storage import (  # noqa: E402
    ALLOWED_IMAGE_SUFFIXES,
    active_storage_backend,
    save_image_bytes,
    static_upload_root,
)


def utc_now_text() -> str:
    return datetime.now(UTC).isoformat()


def collect_referenced_upload_keys(team_states: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for team in team_states:
        state = team.get("state") or {}
        for group in state.get("groups", []):
            for photo in group.get("photos", []):
                for field in (
                    "storage_key",
                    "image_url",
                    "object_key",
                    "pre_oss_storage_key",
                    "pre_oss_image_url",
                ):
                    value = str(photo.get(field) or "").strip()
                    if not value:
                        continue
                    if value.startswith("/static/uploads/"):
                        value = value.removeprefix("/static/uploads/")
                    value = value.lstrip("/").removeprefix("static/uploads/").removeprefix("uploads/")
                    if Path(value).suffix.lower() in ALLOWED_IMAGE_SUFFIXES:
                        keys.add(value.replace("\\", "/"))
    return keys


def list_state_payloads() -> list[dict[str, Any]]:
    from app.services.local_simulation import state_for_team

    payloads: list[dict[str, Any]] = []
    for item in list_team_states():
        team_id = item["team_id"]
        payloads.append({"team_id": team_id, "state": state_for_team(team_id)})
    return payloads


def upload_orphan_local_files(team_id: str, referenced_keys: set[str], limit: int = 0) -> dict[str, Any]:
    root = static_upload_root()
    report: dict[str, Any] = {
        "enabled": True,
        "uploads_root": str(root),
        "scanned_files": 0,
        "referenced_files": 0,
        "orphan_files": 0,
        "uploaded_orphans": 0,
        "failed_orphans": 0,
        "items": [],
        "failures": [],
    }
    if active_storage_backend() != "oss":
        report["enabled"] = False
        report["status"] = "skipped"
        report["reason"] = "storage backend is not oss"
        return report
    if not root.exists():
        return report
    count_uploaded = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in ALLOWED_IMAGE_SUFFIXES:
            continue
        report["scanned_files"] += 1
        rel = path.relative_to(root).as_posix()
        if rel in referenced_keys:
            report["referenced_files"] += 1
            continue
        report["orphan_files"] += 1
        if limit > 0 and count_uploaded >= limit:
            continue
        try:
            content = path.read_bytes()
            sha = hashlib.sha256(content).hexdigest()
            stored = save_image_bytes(
                scope="orphan-local-files",
                filename=path.name,
                content=content,
                team_id=team_id,
                key_hint=f"{Path(rel).with_suffix('').as_posix()}-{sha[:12]}",
            )
            report["uploaded_orphans"] += 1
            count_uploaded += 1
            report["items"].append(
                {
                    "local_path": str(path),
                    "relative_path": rel,
                    "sha256": sha,
                    "oss_url": stored["url"],
                    "storage_key": stored["storage_key"],
                }
            )
        except Exception as exc:  # noqa: BLE001 - keep scanning other files
            report["failed_orphans"] += 1
            report["failures"].append({"local_path": str(path), "error": str(exc)})
    return report


def write_report(path: Path | None, report: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync JSON-state photo refs and optional local orphan files to OSS.")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--upload-orphans", action="store_true", help="Upload unreferenced files under /static/uploads to OSS.")
    parser.add_argument("--orphan-limit", type=int, default=0, help="Limit orphan uploads; 0 means no limit.")
    parser.add_argument("--report", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started_at = utc_now_text()
    teams = list_team_states()
    reports = []
    for team in teams:
        team_id = team["team_id"]
        token = set_current_team(team_id)
        try:
            report = sync_state_photos_to_oss(team_id=team_id, max_workers=args.max_workers)
            reports.append({"team_id": team_id, **report})
        finally:
            reset_current_team(token)
    save_all_team_states()

    state_payloads = list_state_payloads()
    referenced_keys = collect_referenced_upload_keys(state_payloads)
    orphan_report = {"enabled": False}
    if args.upload_orphans:
        orphan_team_id = teams[0]["team_id"] if teams else "default-team"
        orphan_report = upload_orphan_local_files(orphan_team_id, referenced_keys, limit=args.orphan_limit)

    final_report = {
        "started_at": started_at,
        "finished_at": utc_now_text(),
        "teams": reports,
        "orphan_local_files": orphan_report,
    }
    write_report(args.report, final_report)
    print(json.dumps(final_report, ensure_ascii=False, indent=2))
    failed = sum(int(report.get("failed", 0)) for report in reports)
    failed += int(orphan_report.get("failed_orphans", 0) or 0)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
