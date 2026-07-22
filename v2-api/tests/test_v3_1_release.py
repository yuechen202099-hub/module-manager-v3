from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import GroupStatus, PhotoUploadStatus


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPOSITORY_ROOT / "v2-api"
EXPECTED_VERSION = "3.1.0"


def read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def load_script(module_name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(module_name, REPOSITORY_ROOT / relative_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {relative_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def release_group(group_id: str = "release-group", *, identity_suffix: str = "1") -> dict:
    categories = ("before_box", "collector_barcode", "module_meter", "after_box")
    return {
        "id": group_id,
        "status": "archived",
        "terminal": f"T-{identity_suffix}",
        "meter_no": f"M-{identity_suffix}",
        "module_asset_no": f"MOD-{identity_suffix}",
        "collector": f"COL-{identity_suffix}",
        "address": f"Release address {identity_suffix}",
        "client_completed_at": "2026-07-23T09:00:00+08:00",
        "photos": [
            {
                "id": f"{group_id}-photo-{index}",
                "sha256": f"{index:x}" * 64,
                "category": category,
                "is_active": True,
                "upload_status": "uploaded",
                "archive_status": "archived",
                "delivery_cache_status": "ready",
                "delivery_cache_path": f"objects/{group_id}/{index}.jpg",
            }
            for index, category in enumerate(categories, start=1)
        ],
    }


def mark_unarchived(groups: list[dict]) -> None:
    groups[0]["status"] = "approved"
    for photo in groups[0]["photos"]:
        photo["archive_status"] = ""


def test_v3_1_runtime_version_sources_and_release_notes_are_aligned() -> None:
    assert f'version="{EXPECTED_VERSION}"' in read("v2-api/app/main.py")
    assert f'return "{EXPECTED_VERSION}"' in read("v2-api/app/services/ops_status.py")
    assert f'version = "{EXPECTED_VERSION}"' in read("v2-api/pyproject.toml")
    assert json.loads(read("v2-web/package.json"))["version"] == EXPECTED_VERSION
    assert json.loads(read("v2-web/src/version.json"))["version"] == EXPECTED_VERSION
    assert f"Module Manager V{EXPECTED_VERSION}" in read("v2-web/index.html")

    release_notes = read("v2-web/src/constants/releaseNotes.ts")
    for required_text in (
        "双 Sheet",
        "四类照片",
        "条码/二维码",
        "OCR",
        "人工确认",
        "自动归档",
        "后台自动缓存",
    ):
        assert required_text in release_notes


def test_v3_1_preview_defaults_to_read_only_preview() -> None:
    preview = read("v2-api/scripts/preview_v3_1_backfill.py")
    assert "--preview" in preview
    assert "--apply" in preview
    assert "default=\"preview\"" in preview
    for field in ("backfilled", "conflicts", "skipped", "queueable", "unscannable", "export_errors"):
        assert field in preview


def test_v3_1_preview_uses_projected_group_eligibility_instead_of_affected_group_count() -> None:
    preview = load_script("preview_v3_1_backfill", "v2-api/scripts/preview_v3_1_backfill.py")
    eligible = release_group("eligible", identity_suffix="1")
    ineligible = release_group("ineligible", identity_suffix="2")
    ineligible["collector"] = ""

    summary = preview.summarize_preview(
        {
            "mode": "preview",
            "candidates": 4,
            "affected_groups": 99,
            "projected_groups": [eligible, ineligible],
        }
    )

    assert summary["queueable"] == 1
    assert summary["unscannable"] == 1
    assert summary["queueable_reasons"] == {"eligible": 1}
    assert summary["unscannable_reasons"] == {"missing_identity": 1}
    assert summary["estimated_export_error_reasons"]["missing_collector"] == 1


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (lambda groups: groups[0].update(terminal="0"), "placeholder_identity"),
        (lambda groups: groups[0].update(client_completed_at="not-a-date"), "invalid_completed_at"),
        (lambda groups: groups[0]["photos"][1].update(category="before_box"), "invalid_photo_categories"),
        (
            lambda groups: groups.append({**copy.deepcopy(groups[0]), "id": "duplicate-identity-group"}),
            "device_conflict",
        ),
        (mark_unarchived, "not_archived"),
        (lambda groups: groups[0]["photos"][0].update(delivery_cache_status="pending"), "delivery_cache_pending"),
    ],
)
def test_v3_1_preview_reuses_full_pure_delivery_validation(mutate, expected_code: str) -> None:
    preview = load_script("preview_v3_1_backfill", "v2-api/scripts/preview_v3_1_backfill.py")
    groups = [release_group()]
    mutate(groups)

    summary = preview.summarize_preview({"mode": "preview", "projected_groups": groups})

    assert summary["estimated_export_error_reasons"][expected_code] >= 1


def test_v3_1_backfill_projection_is_in_memory_and_does_not_mutate_models() -> None:
    preview = load_script("preview_v3_1_projection", "v2-api/scripts/preview_v3_1_backfill.py")
    checked_group = SimpleNamespace(
        id="group-db-id",
        legacy_id="group-legacy-id",
        team_id="team-a",
        terminal="T-1",
        display_meter_no="M-1",
        installation_address="Release address",
        status=GroupStatus.UNREVIEWED,
        raw_data={
            "module_asset_no": "MOD-1",
            "collector": "COL-1",
            "client_completed_at": "2026-07-23T09:00:00+08:00",
        },
    )
    rows = []
    for index, slot in enumerate(("before_box", "collector_barcode", "module_meter", "after_box"), start=1):
        photo = SimpleNamespace(
            id=f"photo-db-{index}",
            legacy_id=f"photo-{index}",
            group_id=checked_group.id,
            team_id="team-a",
            category="unclassified",
            is_active=True,
            classified_by="",
            upload_status=PhotoUploadStatus.UPLOADED,
            sha256=f"{index:x}" * 64,
            archive_status="",
            collector="",
            asset_no="",
            original_filename=f"photo-{index}.jpg",
            raw_data={"construction_slot": slot, "delivery_cache_status": "pending"},
        )
        rows.append((photo, checked_group))

    projected = preview.project_backfill_groups(rows)

    assert len(projected) == 1
    assert {photo["category"] for photo in projected[0]["photos"]} == {
        "before_box",
        "collector_barcode",
        "module_meter",
        "after_box",
    }
    assert all(photo.category == "unclassified" for photo, _group in rows)


def test_v3_1_release_verifier_validates_candidate_contract() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/verify_v3_1_release.py", "--repo-root", str(REPOSITORY_ROOT)],
        cwd=API_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for expected in (
        "migration",
        "4-photo eligibility",
        "worker paused",
        "20 groups serial",
        "5 seconds",
        "placeholder zero",
        "export sample",
        "task claim",
        "review performance",
    ):
        assert expected in result.stdout


def test_v3_1_release_verifier_executes_worker_ocr_export_and_performance_behavior() -> None:
    verifier = load_script("verify_v3_1_release", "v2-api/scripts/verify_v3_1_release.py")

    worker = verifier.verify_worker_behavior()
    eligibility = verifier.verify_eligibility_and_ocr_behavior()
    export = verifier.verify_export_behavior()
    performance = verifier.measure_and_verify_performance()

    assert worker == {
        "processed": 20,
        "remaining": 1,
        "maximum_active": 1,
        "sleeps": [5.0],
    }
    assert eligibility["eligible_status"] == "pending"
    assert eligibility["ineligible_status"] == "not_eligible"
    assert eligibility["ocr_only_status"] != "passed"
    assert export["sheetnames"] == ["老设备", "新设备"]
    assert export["old_fixed_values"] == ["南大供电服务中心", "奕福"]
    assert export["all_text_formatted"] is True
    assert performance["ok"] is True
    assert performance["measurements"]["review_group_count"] == 20


def test_v3_1_release_verifier_checks_migration_and_model_paused_defaults() -> None:
    verifier = load_script("verify_v3_1_paused", "v2-api/scripts/verify_v3_1_release.py")

    defaults = verifier.verify_paused_defaults(REPOSITORY_ROOT)

    assert defaults == {"migration_paused": True, "model_paused": True}


def test_v3_1_documents_keep_task8_package_hash_and_online_evidence_pending() -> None:
    signoff = read("docs/CLIENT_SIGNOFF_CHECKLIST.md")
    acceptance = read("docs/CLIENT_ACCEPTANCE_REPORT.md")
    final_audit = read("docs/CLIENT_FINAL_AUDIT.md")
    release_record = read("ops/releases/V3.1.0.md")

    assert "126 个必需文件齐全" not in signoff
    assert "待构建" in signoff and "待验包" in signoff
    assert "待 Task 8" in acceptance
    assert "待 Task 8" in final_audit
    assert "- Package: pending" in release_record
    assert "- Production Deployment: pending" in release_record
    assert "- Production Reconciliation: pending" in release_record


def test_task_review_performance_cli_description_is_not_bound_to_v3084() -> None:
    source = read("v2-api/scripts/verify_task_review_performance.py")

    assert "V3.0.84" not in source
    assert "V3.1.0" in source or "task and review performance thresholds" in source


def test_v3_1_release_package_contains_new_release_guards() -> None:
    build_script = read("scripts/build-client-release.ps1")
    package_verifier = read("scripts/verify-client-release.py")
    for path in (
        "v2-api\\scripts\\preview_v3_1_backfill.py",
        "v2-api\\scripts\\verify_v3_1_release.py",
    ):
        assert path in build_script
    for path in (
        "v2-api/scripts/preview_v3_1_backfill.py",
        "v2-api/scripts/verify_v3_1_release.py",
    ):
        assert path in package_verifier
