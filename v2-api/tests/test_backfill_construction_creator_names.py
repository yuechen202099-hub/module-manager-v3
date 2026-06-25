from __future__ import annotations

import json

from scripts.backfill_construction_creator_names import backfill_json_state


def test_backfill_json_state_only_updates_construction_creator_usernames(tmp_path):
    state_path = tmp_path / "local_state.json"
    payload = {
        "version": 1,
        "teams": {
            "default-team": {
                "groups": [
                    {
                        "id": "g1",
                        "photos": [
                            {"id": "p1", "creator": "constructor_a", "upload_source": "construction-mobile"},
                            {"id": "p2", "creator": "constructor_a", "source_file": "scan.xlsx"},
                            {"id": "p3", "creator": "unknown", "source": "construction"},
                        ],
                    }
                ]
            }
        },
    }
    state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    dry_report = backfill_json_state(
        state_path=state_path,
        user_names={"constructor_a": "Installer A"},
        dry_run=True,
    )
    assert dry_report["updated"] == 0
    assert dry_report["matched_creator_username"] == 1
    assert json.loads(state_path.read_text(encoding="utf-8"))["teams"]["default-team"]["groups"][0]["photos"][0]["creator"] == "constructor_a"

    report = backfill_json_state(
        state_path=state_path,
        user_names={"constructor_a": "Installer A"},
        dry_run=False,
        backup_dir=tmp_path,
    )
    photos = json.loads(state_path.read_text(encoding="utf-8"))["teams"]["default-team"]["groups"][0]["photos"]

    assert report["updated"] == 1
    assert photos[0]["creator"] == "Installer A"
    assert photos[1]["creator"] == "constructor_a"
    assert photos[2]["creator"] == "unknown"
