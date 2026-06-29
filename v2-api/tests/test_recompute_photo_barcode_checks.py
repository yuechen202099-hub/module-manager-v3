from __future__ import annotations

import pytest

from scripts.recompute_photo_barcode_checks import (
    DEFAULT_DATABASE_URL,
    archive_passed_groups,
    build_group_window,
    record_report_error,
    group_ready_for_auto_archive,
    group_needs_barcode_analysis,
    group_needs_not_matched_analysis,
    group_needs_unreadable_analysis,
    group_status_allows_auto_archive,
    should_scan_group_photos,
    load_env_file,
    photo_needs_not_matched_scan,
    photo_needs_group_evidence_scan,
    recompute_photo_barcode_raw,
    validate_runtime_environment,
)


def group_payload() -> dict:
    return {
        "id": "group-1",
        "meter_no": "3130001111800002817421",
        "meter_match_key": "1111800002",
        "module_asset_no": "3130054512250026172609",
        "collector": "3130009381930003253416",
    }


def test_recompute_photo_barcode_raw_overwrites_stale_unreadable_when_forced() -> None:
    raw = {
        "category": "module_meter",
        "barcode_check_status": "unreadable",
        "barcode_check_values": [],
        "barcode_check_normalized_values": [],
        "barcode_check_expected_type": "module",
    }
    photo = {
        "id": "photo-1",
        "category": "module_meter",
        "image_url": "oss://bucket/photo.jpg",
    }

    result = recompute_photo_barcode_raw(
        photo,
        group_payload(),
        raw_data=raw,
        force=True,
        scanner=lambda _photo: ["3130054512250026172609"],
    )

    assert result.changed is True
    assert result.raw_data is not raw
    assert result.raw_data["barcode_check_status"] == "matched"
    assert result.raw_data["barcode_check_matched_value"] == "3130054512250026172609"
    assert result.raw_data["barcode_check_values"] == ["3130054512250026172609"]


def test_recompute_photo_barcode_raw_dry_run_reports_change_without_mutating_raw() -> None:
    raw = {
        "category": "collector_barcode",
        "barcode_check_status": "unreadable",
        "barcode_check_values": [],
        "barcode_check_normalized_values": [],
        "barcode_check_expected_type": "collector",
    }
    photo = {
        "id": "photo-2",
        "category": "collector_barcode",
        "image_url": "oss://bucket/photo.jpg",
    }

    result = recompute_photo_barcode_raw(
        photo,
        group_payload(),
        raw_data=raw,
        force=True,
        dry_run=True,
        scanner=lambda _photo: ["3130009381930003253416"],
    )

    assert result.changed is True
    assert result.raw_data["barcode_check_status"] == "matched"
    assert raw["barcode_check_status"] == "unreadable"


def test_recompute_photo_barcode_raw_can_enable_ocr_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import photo_barcode_check

    raw = {
        "category": "collector_barcode",
        "barcode_check_status": "unreadable",
        "barcode_check_values": [],
        "barcode_check_normalized_values": [],
        "barcode_check_expected_type": "collector",
    }
    photo = {
        "id": "photo-2",
        "category": "collector_barcode",
        "image_url": "oss://bucket/photo.jpg",
    }
    monkeypatch.setattr(
        photo_barcode_check,
        "default_ocr_reader",
        lambda _photo, _expected_values: ["3130009381930003253416"],
    )

    result = recompute_photo_barcode_raw(
        photo,
        group_payload(),
        raw_data=raw,
        force=True,
        scanner=lambda _photo: [],
        use_ocr=True,
    )

    assert result.changed is True
    assert result.raw_data["barcode_check_status"] == "matched"
    assert result.raw_data["barcode_check_method"] == "ocr"


def test_recompute_photo_barcode_raw_preserves_existing_match_when_rescan_is_unreadable() -> None:
    raw = {
        "category": "module_meter",
        "barcode_check_status": "matched",
        "barcode_check_values": ["3130054512250026172609"],
        "barcode_check_normalized_values": ["3130054512250026172609"],
        "barcode_check_expected_type": "module",
        "barcode_check_matched_value": "3130054512250026172609",
    }
    photo = {
        "id": "photo-3",
        "category": "module_meter",
        "image_url": "oss://bucket/photo.jpg",
    }

    result = recompute_photo_barcode_raw(
        photo,
        group_payload(),
        raw_data=raw,
        force=True,
        scanner=lambda _photo: [],
    )

    assert result.changed is False
    assert result.preserved_unreadable_downgrade is True
    assert result.raw_data["barcode_check_status"] == "matched"
    assert result.raw_data["barcode_check_values"] == ["3130054512250026172609"]


def test_recompute_photo_barcode_raw_collects_group_evidence_for_non_barcode_photo() -> None:
    photo = {
        "id": "photo-4",
        "category": "before_box",
        "image_url": "oss://bucket/photo.jpg",
    }

    result = recompute_photo_barcode_raw(
        photo,
        group_payload(),
        collect_group_evidence=True,
        scanner=lambda _photo: ["3130001111800002817421"],
    )

    assert result.changed is True
    assert result.status == "not_required"
    assert result.raw_data["barcode_check_expected_type"] == "none"
    assert result.raw_data["barcode_check_values"] == ["3130001111800002817421"]
    assert result.raw_data["barcode_check_normalized_values"] == ["3130001111800002817421"]


def test_recompute_photo_barcode_raw_refreshes_historical_not_required_group_evidence() -> None:
    raw = {
        "category": "before_box",
        "barcode_check_status": "not_required",
        "barcode_check_expected_type": "none",
        "barcode_check_values": [],
        "barcode_check_normalized_values": [],
    }
    photo = {
        "id": "photo-5",
        "category": "before_box",
        "image_url": "oss://bucket/photo.jpg",
    }

    result = recompute_photo_barcode_raw(
        photo,
        group_payload(),
        raw_data=raw,
        collect_group_evidence=True,
        scanner=lambda _photo: ["3130001111800002817421"],
    )

    assert result.changed is True
    assert result.status == "not_required"
    assert result.raw_data["barcode_check_values"] == ["3130001111800002817421"]
    assert result.raw_data["barcode_check_normalized_values"] == ["3130001111800002817421"]
    assert result.raw_data["barcode_group_evidence_checked"] is True


def test_photo_needs_group_evidence_scan_only_for_unchecked_not_required_photos() -> None:
    assert photo_needs_group_evidence_scan(
        {
            "barcode_check_status": "not_required",
            "barcode_check_expected_type": "none",
            "barcode_check_values": [],
            "barcode_check_normalized_values": [],
        }
    ) is True
    assert photo_needs_group_evidence_scan(
        {
            "barcode_check_status": "not_required",
            "barcode_check_expected_type": "none",
            "barcode_group_evidence_checked": True,
        }
    ) is False
    assert photo_needs_group_evidence_scan({"barcode_check_status": "matched"}) is False


def test_load_env_file_sets_database_url_before_database_import(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        'DATABASE_URL="postgresql+psycopg://user:pass@db.example:5432/prod"\nAPP_ENV=production\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

    loaded = load_env_file(env_path)

    assert loaded is True
    assert "db.example" in str(__import__("os").environ["DATABASE_URL"])
    assert __import__("os").environ["APP_ENV"] == "production"


def test_validate_runtime_environment_rejects_default_database_for_apply(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DEFAULT_DATABASE_URL)

    with pytest.raises(RuntimeError, match="default sample DATABASE_URL"):
        validate_runtime_environment(dry_run=False)


def test_validate_runtime_environment_rejects_env_example_database_for_apply(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://module_manager:module_manager_password@postgres:5432/module_manager_v2",
    )
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("STATE_BACKEND", "postgres")

    with pytest.raises(RuntimeError, match="default sample DATABASE_URL"):
        validate_runtime_environment(dry_run=False)


def test_validate_runtime_environment_allows_localhost_production_postgres(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("STATE_BACKEND", "postgres")
    monkeypatch.setattr("scripts.recompute_photo_barcode_checks._scanner_available", lambda: True)

    validate_runtime_environment(dry_run=False)


def test_build_group_window_normalizes_limit_and_offset() -> None:
    assert build_group_window(group_limit=50, group_offset=100) == {"group_limit": 50, "group_offset": 100}
    assert build_group_window(group_limit=-1, group_offset=-20) == {"group_limit": 0, "group_offset": 0}


def test_should_scan_group_photos_requires_exactly_four_active_photos() -> None:
    assert should_scan_group_photos([object(), object(), object(), object()]) is True
    assert should_scan_group_photos([object(), object(), object()]) is False
    assert should_scan_group_photos([object(), object(), object(), object(), object()]) is False


def test_group_needs_barcode_analysis_requires_exactly_four_and_missing_status() -> None:
    complete_unchecked = [{"raw_data": {"barcode_check_status": "matched"}} for _ in range(3)]
    complete_unchecked.append({"raw_data": {}})

    assert group_needs_barcode_analysis(complete_unchecked) is True
    assert group_needs_barcode_analysis(complete_unchecked[:3]) is False
    assert group_needs_barcode_analysis(
        [{"raw_data": {"barcode_check_status": "matched"}} for _ in range(4)]
    ) is False


def test_group_needs_barcode_analysis_includes_historical_not_required_without_group_evidence() -> None:
    photos = [{"raw_data": {"barcode_check_status": "matched"}} for _ in range(3)]
    photos.append(
        {
            "raw_data": {
                "barcode_check_status": "not_required",
                "barcode_check_expected_type": "none",
                "barcode_check_values": [],
                "barcode_check_normalized_values": [],
            }
        }
    )

    assert group_needs_barcode_analysis(photos) is True

    photos[3]["raw_data"]["barcode_group_evidence_checked"] = True
    assert group_needs_barcode_analysis(photos) is False


def test_group_needs_unreadable_analysis_requires_exactly_four_and_unreadable_status() -> None:
    complete_with_unreadable = [{"raw_data": {"barcode_check_status": "matched"}} for _ in range(3)]
    complete_with_unreadable.append({"raw_data": {"barcode_check_status": "unreadable"}})

    assert group_needs_unreadable_analysis(complete_with_unreadable) is True
    assert group_needs_unreadable_analysis(complete_with_unreadable[:3]) is False
    assert group_needs_unreadable_analysis(
        [{"raw_data": {"barcode_check_status": "matched"}} for _ in range(4)]
    ) is False


def test_group_needs_unreadable_analysis_skips_current_recheck_batch() -> None:
    photos = [{"raw_data": {"barcode_check_status": "matched"}} for _ in range(3)]
    photos.append(
        {
            "raw_data": {
                "barcode_check_status": "unreadable",
                "barcode_unreadable_recheck_id": "batch-1",
            }
        }
    )

    assert group_needs_unreadable_analysis(photos, recheck_batch_id="batch-1") is False
    assert group_needs_unreadable_analysis(photos, recheck_batch_id="batch-2") is True


def test_photo_needs_not_matched_scan_skips_matched_and_current_batch() -> None:
    assert photo_needs_not_matched_scan({"barcode_check_status": "matched"}, recheck_batch_id="batch-1") is False
    assert (
        photo_needs_not_matched_scan(
            {"barcode_check_status": "unreadable", "barcode_not_matched_recheck_id": "batch-1"},
            recheck_batch_id="batch-1",
        )
        is False
    )
    assert photo_needs_not_matched_scan({"barcode_check_status": "mismatched"}, recheck_batch_id="batch-1") is True
    assert photo_needs_not_matched_scan({}, recheck_batch_id="batch-1") is True


def test_group_needs_not_matched_analysis_requires_four_and_skips_passed_groups() -> None:
    complete_matched = [{"raw_data": {"barcode_check_status": "matched"}} for _ in range(4)]
    complete_with_unreadable = [{"raw_data": {"barcode_check_status": "matched"}} for _ in range(3)]
    complete_with_unreadable.append({"raw_data": {"barcode_check_status": "unreadable"}})

    assert group_needs_not_matched_analysis(complete_matched) is False
    assert group_needs_not_matched_analysis(complete_with_unreadable) is True
    assert group_needs_not_matched_analysis(complete_with_unreadable[:3]) is False


def test_group_needs_not_matched_analysis_skips_current_recheck_batch() -> None:
    photos = [{"raw_data": {"barcode_check_status": "matched"}} for _ in range(3)]
    photos.append(
        {
            "raw_data": {
                "barcode_check_status": "unreadable",
                "barcode_not_matched_recheck_id": "batch-1",
            }
        }
    )

    assert group_needs_not_matched_analysis(photos, recheck_batch_id="batch-1") is False
    assert group_needs_not_matched_analysis(photos, recheck_batch_id="batch-2") is True


def test_group_ready_for_auto_archive_requires_classified_photos_and_group_barcode_match() -> None:
    photos = [
        {"category": "meter_barcode", "barcode_check_normalized_values": ["110000288056"]},
        {"category": "module_meter", "barcode_check_normalized_values": ["MOD001"]},
        {"category": "collector_barcode", "barcode_check_normalized_values": ["COLLECTOR001"]},
        {"category": "before_box", "barcode_check_status": "not_required", "barcode_check_normalized_values": []},
    ]
    group = {
        "meter_no": "110000288056",
        "module_asset_no": "MOD-001",
        "collector": "COLLECTOR-001",
        "photos": photos,
    }

    assert group_ready_for_auto_archive(group, photos) is True

    photos[3]["category"] = "unclassified"
    assert group_ready_for_auto_archive(group, photos) is False


def test_group_ready_for_auto_archive_rejects_ocr_matches() -> None:
    photos = [
        {"category": "meter_barcode", "barcode_check_normalized_values": ["110000288056"], "barcode_check_method": "barcode"},
        {"category": "module_meter", "barcode_check_normalized_values": ["MOD001"], "barcode_check_method": "ocr"},
        {"category": "collector_barcode", "barcode_check_normalized_values": ["COLLECTOR001"], "barcode_check_method": "barcode"},
        {"category": "before_box", "barcode_check_status": "not_required", "barcode_check_normalized_values": []},
    ]
    group = {
        "meter_no": "110000288056",
        "module_asset_no": "MOD-001",
        "collector": "COLLECTOR-001",
        "photos": photos,
    }

    assert group_ready_for_auto_archive(group, photos) is False


def test_group_ready_for_auto_archive_rejects_unreadable_group_barcode() -> None:
    photos = [
        {"category": "meter_barcode", "barcode_check_normalized_values": ["110000288056"]},
        {"category": "module_meter", "barcode_check_status": "unreadable", "barcode_check_normalized_values": []},
        {"category": "collector_barcode", "barcode_check_normalized_values": ["COLLECTOR001"]},
        {"category": "before_box", "barcode_check_status": "not_required", "barcode_check_normalized_values": []},
    ]
    group = {
        "meter_no": "110000288056",
        "module_asset_no": "MOD-001",
        "collector": "COLLECTOR-001",
        "photos": photos,
    }

    assert group_ready_for_auto_archive(group, photos) is False


def test_group_ready_for_auto_archive_rejects_extra_unmatched_qr_noise() -> None:
    photos = [
        {"category": "meter_barcode", "barcode_check_normalized_values": ["110000288056"]},
        {"category": "module_meter", "barcode_check_normalized_values": ["MOD001"]},
        {"category": "collector_barcode", "barcode_check_normalized_values": ["COLLECTOR001", "EXTRA999"]},
        {"category": "before_box", "barcode_check_status": "not_required", "barcode_check_normalized_values": []},
    ]
    group = {
        "meter_no": "110000288056",
        "module_asset_no": "MOD-001",
        "collector": "COLLECTOR-001",
        "photos": photos,
    }

    assert group_ready_for_auto_archive(group, photos) is False


def test_group_ready_for_auto_archive_rejects_final_review_status() -> None:
    photos = [
        {"category": "meter_barcode", "barcode_check_normalized_values": ["110000288056"]},
        {"category": "module_meter", "barcode_check_normalized_values": ["MOD001"]},
        {"category": "collector_barcode", "barcode_check_normalized_values": ["COLLECTOR001"]},
        {"category": "before_box", "barcode_check_status": "not_required", "barcode_check_normalized_values": []},
    ]
    group = {
        "meter_no": "110000288056",
        "module_asset_no": "MOD-001",
        "collector": "COLLECTOR-001",
        "status": "approved",
        "photos": photos,
    }

    assert group_ready_for_auto_archive(group, photos) is False


def test_group_status_allows_auto_archive_only_before_final_review() -> None:
    assert group_status_allows_auto_archive("unreviewed") is True
    assert group_status_allows_auto_archive("in_review") is True
    assert group_status_allows_auto_archive("incomplete") is True
    assert group_status_allows_auto_archive("approved") is False
    assert group_status_allows_auto_archive("rejected") is False


def test_record_report_error_keeps_short_diagnostic_messages() -> None:
    report = {"errors": 0}

    record_report_error(report, RuntimeError("archive failed"), context="auto_archive")

    assert report["errors"] == 1
    assert report["error_messages"] == ["auto_archive: RuntimeError: archive failed"]


def test_archive_passed_groups_uses_state_repository_factory(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeRepository:
        def bulk_archive_groups(self, group_ids: list[str], *, actor: str, reason: str = "") -> dict:
            calls.append({"group_ids": group_ids, "actor": actor, "reason": reason})
            return {"archived_count": 2, "skipped": [{"group_id": "group-3", "reason": "already_archived"}]}

    monkeypatch.setattr(
        "scripts.recompute_photo_barcode_checks.get_state_repository",
        lambda: FakeRepository(),
    )

    result = archive_passed_groups(["group-1", "group-2", "group-3"], actor="barcode-maintenance")

    assert result == {"archived_count": 2, "skipped_count": 1}
    assert calls == [
        {
            "group_ids": ["group-1", "group-2", "group-3"],
            "actor": "barcode-maintenance",
            "reason": "条码扫描通过自动归档。",
        }
    ]
