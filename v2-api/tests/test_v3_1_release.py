from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import GroupStatus, MaterialGroup, Photo, PhotoUploadStatus


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


def current_source_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        text=True,
        encoding="utf-8",
    ).strip()


def valid_performance_report(source_commit: str | None = None) -> dict:
    source_commit = source_commit or current_source_commit()
    task_path = "/local-test/tasks/snapshot"
    review_path = "/local-test/tasks/1/review-groups?limit=20&offset=0&review_status=all&query="
    return {
        "ok": True,
        "failures": [],
        "source_commit": source_commit,
        "base_url": "http://127.0.0.1:18010",
        "task_id": "1",
        "measurements": {
            "task_snapshot_ms": 25.0,
            "review_groups_ms": 40.0,
            "review_group_count": 1,
            "task_builds_in_60_seconds": 1,
        },
        "thresholds": {
            "task_snapshot_ms": 300,
            "review_groups_ms": 1500,
            "review_group_count": 20,
            "task_builds_in_60_seconds": 1,
        },
        "build_sample_seconds": 60,
        "start_build_count": 4,
        "end_build_count": 5,
        "start_cache_instance_id": "cache-instance-a",
        "end_cache_instance_id": "cache-instance-a",
        "routes": {
            "task_snapshot": {
                "path": task_path,
                "item_count": 1,
                "selected_task_id": "1",
                "serialized_bytes": 256,
            },
            "review_groups": {
                "path": review_path,
                "item_count": 1,
                "total": 1,
                "limit": 20,
                "offset": 0,
                "serialized_bytes": 512,
            },
        },
    }


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
    photos = []
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
        photos.append(photo)

    projected = preview.project_backfill_groups([checked_group], photos)

    assert len(projected) == 1
    assert {photo["category"] for photo in projected[0]["photos"]} == {
        "before_box",
        "collector_barcode",
        "module_meter",
        "after_box",
    }
    assert all(photo.category == "unclassified" for photo in photos)


def _production_group(group_id: str, team_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=group_id,
        legacy_id=group_id,
        team_id=team_id,
        terminal=f"T-{group_id}",
        display_meter_no=f"M-{group_id}",
        installation_address=f"Address {group_id}",
        status=GroupStatus.UNREVIEWED,
        raw_data={
            "module_asset_no": f"MOD-{group_id}",
            "collector": f"COL-{group_id}",
            "client_completed_at": "2026-07-23T09:00:00+08:00",
        },
    )


def _production_photo(
    group: SimpleNamespace,
    index: int,
    slot: str,
    *,
    active: bool = True,
    upload_status: PhotoUploadStatus = PhotoUploadStatus.UPLOADED,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"{group.id}-photo-db-{index}",
        legacy_id=f"{group.id}-photo-{index}",
        group_id=group.id,
        team_id=group.team_id,
        category="unclassified",
        is_active=active,
        classified_by="",
        upload_status=upload_status,
        sha256=f"{index:x}" * 64,
        archive_status="",
        collector="",
        asset_no="",
        original_filename=f"photo-{index}.jpg",
        sort_order=index,
        raw_data={"construction_slot": slot, "delivery_cache_status": "pending"},
    )


class _ScalarRows:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def all(self) -> list[SimpleNamespace]:
        return list(self._rows)


class _ProjectionSession:
    def __init__(self, groups: list[SimpleNamespace], photos: list[SimpleNamespace]) -> None:
        self.groups = groups
        self.photos = photos
        self.statements = []

    def scalars(self, statement):
        self.statements.append(statement)
        entity = statement.column_descriptions[0]["entity"]
        params = statement.compile().params
        if entity is MaterialGroup:
            team_id = next((value for key, value in params.items() if key.startswith("team_id")), "")
            rows = [group for group in self.groups if not team_id or group.team_id == team_id]
            return _ScalarRows(rows)
        assert entity is Photo
        group_ids = next(value for key, value in params.items() if key.startswith("group_id"))
        return _ScalarRows([photo for photo in self.photos if photo.group_id in group_ids])


def test_v3_1_preview_loads_all_team_groups_then_bulk_preloads_photos() -> None:
    preview = load_script("preview_v3_1_group_first", "v2-api/scripts/preview_v3_1_backfill.py")
    zero = _production_group("zero", "team-a")
    inactive = _production_group("inactive", "team-a")
    invalid = _production_group("invalid", "team-a")
    eligible = _production_group("eligible", "team-a")
    other_team = _production_group("other-team", "team-b")
    photos = [
        _production_photo(inactive, 1, "before_box", active=False),
        _production_photo(invalid, 1, "before_box", upload_status=PhotoUploadStatus.INVALID),
        *[
            _production_photo(eligible, index, slot)
            for index, slot in enumerate(
                ("before_box", "collector_barcode", "module_meter", "after_box"),
                start=1,
            )
        ],
        _production_photo(other_team, 1, "before_box"),
    ]
    session = _ProjectionSession([zero, inactive, invalid, eligible, other_team], photos)

    projected = preview.load_projected_groups(session, team_id="team-a")
    summary = preview.summarize_preview({"mode": "preview", "projected_groups": projected})

    assert [group["id"] for group in projected] == ["zero", "inactive", "invalid", "eligible"]
    assert [len(group["photos"]) for group in projected] == [0, 1, 1, 4]
    assert len(session.statements) == 2
    assert "material_groups.team_id" in str(session.statements[0])
    assert "WHERE photos.team_id" not in str(session.statements[1])
    assert summary["queueable"] == 1
    assert summary["unscannable"] == 3
    assert summary["unscannable_reasons"] == {
        "invalid_photo_count": 2,
        "invalid_photo_evidence": 1,
    }
    assert summary["estimated_export_error_reasons"]["invalid_photo_count"] >= 1
    assert "no_groups" not in summary["estimated_export_error_reasons"]


@pytest.mark.parametrize("argv", [[], ["--preview"]])
def test_v3_1_preview_default_and_explicit_preview_are_read_only(monkeypatch, capsys, argv: list[str]) -> None:
    preview = load_script(f"preview_v3_1_read_only_{len(argv)}", "v2-api/scripts/preview_v3_1_backfill.py")
    session = SimpleNamespace()

    class SessionContext:
        def __enter__(self):
            return session

        def __exit__(self, *_args):
            return False

    observed: list[dict] = []
    monkeypatch.setattr(preview, "SessionLocal", SessionContext)
    monkeypatch.setattr(preview, "load_projected_groups", lambda checked_session, team_id="": [])

    def fake_backfill(checked_session, **kwargs):
        assert checked_session is session
        observed.append(kwargs)
        return {"mode": "preview"}

    monkeypatch.setattr(preview, "backfill_construction_photo_categories", fake_backfill)

    assert preview.main(argv) == 0
    assert observed == [{"apply_changes": False, "actor": "v3-1-category-backfill", "team_id": ""}]
    assert json.loads(capsys.readouterr().out)["mode"] == "preview"


def test_v3_1_release_verifier_validates_candidate_contract(tmp_path: Path) -> None:
    source_commit = current_source_commit()
    report_path = tmp_path / "performance-report.json"
    report_path.write_text(json.dumps(valid_performance_report(source_commit)), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_v3_1_release.py",
            "--repo-root",
            str(REPOSITORY_ROOT),
            "--performance-report",
            str(report_path),
            "--expected-source-commit",
            source_commit,
        ],
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
    performance = verifier.verify_performance_report(
        valid_performance_report(),
        expected_source_commit=current_source_commit(),
    )

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
    assert performance["measurements"]["review_group_count"] == 1


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda report: report["measurements"].update(task_snapshot_ms=301), "task_snapshot_ms"),
        (lambda report: report["measurements"].update(review_groups_ms=1501), "review_groups_ms"),
        (
            lambda report: (
                report["measurements"].update(task_builds_in_60_seconds=2),
                report.update(end_build_count=6),
            ),
            "task_builds_in_60_seconds",
        ),
        (lambda report: report.update(build_sample_seconds=59), "60 seconds"),
        (lambda report: report.update(task_id=""), "task_id"),
        (lambda report: report["routes"]["task_snapshot"].update(item_count=0), "task snapshot data"),
        (lambda report: report["routes"]["review_groups"].update(item_count=0), "review group data"),
        (lambda report: report.update(source_commit="b" * 40), "source commit"),
        (lambda report: report.update(base_url="https://production.example.com"), "localhost"),
        (lambda report: report.update(end_cache_instance_id="cache-instance-b"), "cache instance"),
    ],
)
def test_v3_1_release_rejects_unqualified_performance_reports(mutate, message: str) -> None:
    verifier = load_script("verify_v3_1_performance_negative", "v2-api/scripts/verify_v3_1_release.py")
    expected_commit = current_source_commit()
    report = valid_performance_report(expected_commit)
    mutate(report)

    with pytest.raises(AssertionError, match=message):
        verifier.verify_performance_report(report, expected_source_commit=expected_commit)


def test_v3_1_release_cli_requires_a_performance_report() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/verify_v3_1_release.py", "--repo-root", str(REPOSITORY_ROOT)],
        cwd=API_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode != 0
    assert "--performance-report" in result.stderr


def test_v3_1_release_cli_rejects_a_report_bound_to_a_non_head_commit(tmp_path: Path) -> None:
    wrong_commit = "b" * 40
    report_path = tmp_path / "wrong-commit-performance-report.json"
    report_path.write_text(json.dumps(valid_performance_report(wrong_commit)), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_v3_1_release.py",
            "--repo-root",
            str(REPOSITORY_ROOT),
            "--performance-report",
            str(report_path),
            "--expected-source-commit",
            wrong_commit,
        ],
        cwd=API_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 1
    assert "current HEAD" in result.stderr


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
