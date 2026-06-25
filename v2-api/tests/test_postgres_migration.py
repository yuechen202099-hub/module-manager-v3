from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def load_migration_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "migrate_json_to_postgres.py"
    spec = importlib.util.spec_from_file_location("migrate_json_to_postgres", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample_state_payload() -> dict:
    return {
        "version": 1,
        "teams": {
            "alpha-team": {
                "team_id": "alpha-team",
                "total_catalog": [
                    {
                        "source": "total",
                        "row_number": 2,
                        "terminal": "T-001",
                        "meter_no": "110001",
                        "address": "A road",
                        "meter_match_key": "0001",
                    }
                ],
                "tasks": [
                    {
                        "id": 1,
                        "terminal": "T-001",
                        "name": "Terminal T-001",
                        "status": "published",
                        "claimed_by": None,
                    }
                ],
                "groups": [
                    {
                        "id": "g-00001",
                        "task_id": 1,
                        "meter_match_key": "0001",
                        "meter_no": "110001",
                        "terminal": "T-001",
                        "address": "A road",
                        "status": "pending",
                        "photo_count": 2,
                        "photos": [
                            {
                                "id": "p-1",
                                "barcode": "barcode-1",
                                "image_url": "https://example.test/a.jpg",
                                "category": "unclassified",
                            },
                            {
                                "id": "p-2",
                                "barcode": "barcode-1",
                                "image_url": "https://example.test/b.jpg",
                                "category": "before_box",
                            },
                            {
                                "id": "p-3",
                                "barcode": "barcode-1",
                                "image_url": "/static/uploads/construction/c.jpg",
                                "category": "after_box",
                            },
                            {
                                "id": "p-4",
                                "barcode": "barcode-1",
                                "image_url": "oss://bucket-name/team/group/d.jpg",
                                "category": "collector",
                            },
                        ],
                    }
                ],
                "scan_unmatched": [{"unmatched_id": "u-1", "barcode": "no-match"}],
                "review_events": [{"group_id": "g-00001", "task_id": 1, "next_status": "approved"}],
                "photo_events": [{"group_id": "g-00001", "photo_id": "p-1", "next_category": "before_box"}],
                "audit_events": [{"id": "audit-000001", "action": "sample", "actor": "admin", "payload": {}}],
            }
        },
    }


def sample_users_payload() -> dict:
    return {
        "version": 1,
        "users": [
            {
                "username": "admin",
                "name": "Admin",
                "roles": ["admin"],
                "team_id": "alpha-team",
                "status": "active",
                "home": "/app",
                "password_hash": "hashed",
            }
        ],
    }


def test_migration_dry_run_reports_local_state_counts(tmp_path: Path) -> None:
    module = load_migration_module()
    state_path = tmp_path / "local_state.json"
    users_path = tmp_path / "users.json"
    report_path = tmp_path / "report.json"
    state_path.write_text(json.dumps(sample_state_payload()), encoding="utf-8")
    users_path.write_text(json.dumps(sample_users_payload()), encoding="utf-8")

    exit_code = module.main(
        [
            "--state",
            str(state_path),
            "--users",
            str(users_path),
            "--report",
            str(report_path),
            "--dry-run",
        ]
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert report["dry_run"] is True
    assert report["teams"] == 1
    assert report["users"] == 1
    assert report["total_catalog_rows"] == 1
    assert report["tasks"] == 1
    assert report["groups"] == 1
    assert report["photos"] == 4
    assert report["scan_unmatched"] == 1
    assert report["review_events"] == 1
    assert report["photo_events"] == 1
    assert report["audit_events"] == 1
    assert report["by_team"]["alpha-team"]["photos"] == 4
    assert report["photo_url_index"]["with_image_url"] == 4
    assert report["photo_url_index"]["with_storage_key"] == 4
    assert report["photo_url_index"]["with_source_fingerprint"] == 4
    assert report["photo_url_index"]["by_storage_type"] == {
        "external_url": 2,
        "local_upload": 1,
        "oss": 1,
    }


def test_source_fingerprint_ignores_temporary_url_tokens() -> None:
    module = load_migration_module()
    first = module.source_fingerprint(
        {
            "image_url": "https://example.test/image.jpg?token=abc&downloadImg=cloud://stable&expires=1",
        },
        team_id="alpha-team",
        group_legacy_id="g-1",
        legacy_id="p-1",
        index=1,
    )
    second = module.source_fingerprint(
        {
            "image_url": "https://example.test/image.jpg?expires=2&downloadImg=cloud://stable&token=def",
        },
        team_id="alpha-team",
        group_legacy_id="g-1",
        legacy_id="p-1",
        index=1,
    )

    assert first == second
    assert first.startswith("url:")
