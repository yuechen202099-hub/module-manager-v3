import copy
import json
import re

import pytest

from app.services import unmatched_review


def sample_record() -> dict:
    return {
        "unmatched_id": "unmatched-1",
        "meter_no": "120000912473",
        "collector": "C001",
        "module_asset_no": "M001",
        "photo_urls": ["https://photos.example/a.jpg", "https://photos.example/b.jpg"],
    }


def test_build_review_has_stable_photo_ids_and_does_not_create_terminal() -> None:
    first = unmatched_review.build_review(sample_record())
    second = unmatched_review.build_review(sample_record())
    assert [item["id"] for item in first["photos"]] == [item["id"] for item in second["photos"]]
    assert first["version"] == 1
    assert first["state"] == "pending"
    assert "group_id" not in first
    assert "terminal" not in first


def test_migrated_photo_rows_include_backend_independent_formal_ids() -> None:
    review = unmatched_review.build_review(sample_record())

    rows = unmatched_review.migrate_review_to_photo_rows(review)

    assert [row.get("id") for row in rows] == [
        f"p-unmatched-{review['unmatched_id']}-{unmatched_review.hashlib.sha256(photo['id'].encode('utf-8')).hexdigest()[:16]}"
        for photo in review["photos"]
    ]


def test_apply_review_patch_rejects_stale_version() -> None:
    review = unmatched_review.build_review(sample_record())
    review["version"] = 3
    with pytest.raises(unmatched_review.ReviewVersionConflict):
        unmatched_review.apply_review_patch(
            review,
            actor="reviewer-a",
            expected_version=2,
            metadata={"meter_no": "120000912474"},
            photo_updates=[],
            state="pending",
        )


def test_apply_review_patch_rejects_unknown_state_without_mutating_source() -> None:
    review = unmatched_review.build_review(sample_record())
    source_snapshot = copy.deepcopy(review)

    with pytest.raises(ValueError, match="Unsupported review state"):
        unmatched_review.apply_review_patch(
            review,
            actor="reviewer-a",
            expected_version=1,
            metadata={"meter_no": "120000912474"},
            photo_updates=[],
            state="invalid",
        )

    assert review == source_snapshot


def test_apply_review_patch_updates_only_allowed_fields() -> None:
    review = unmatched_review.build_review(sample_record())
    photo_id = review["photos"][0]["id"]
    updated = unmatched_review.apply_review_patch(
        review,
        actor="reviewer-a",
        expected_version=1,
        metadata={"meter_no": "120000912474", "terminal": "00000000"},
        photo_updates=[{"id": photo_id, "category": "collector_barcode", "source_url": "tampered"}],
        state="reviewed",
    )
    assert updated["version"] == 2
    assert updated["meter_no"] == "120000912474"
    assert "terminal" not in updated
    assert updated["photos"][0]["category"] == "collector_barcode"
    assert updated["photos"][0]["source_url"] == "https://photos.example/a.jpg"


@pytest.mark.parametrize(
    ("metadata", "photo_updates"),
    [
        ({"meter_no": "120000912474"}, []),
        ({"collector": "C002"}, []),
        ({"module_asset_no": "M002"}, []),
        ({}, [{"category": "collector_barcode"}]),
    ],
)
def test_apply_review_patch_invalidates_manual_confirmation_when_evidence_changes(
    metadata: dict,
    photo_updates: list[dict],
) -> None:
    review = unmatched_review.build_review(sample_record())
    review["manual_confirmed"] = True
    review["reviewed_at"] = "2026-07-13T09:00:00+00:00"
    if photo_updates:
        photo_updates[0]["id"] = review["photos"][0]["id"]

    updated = unmatched_review.apply_review_patch(
        review,
        actor="reviewer-b",
        expected_version=1,
        metadata=metadata,
        photo_updates=photo_updates,
        state="reviewed",
    )

    assert updated["manual_confirmed"] is False
    assert updated["reviewed_at"] == ""


def test_apply_review_patch_preserves_manual_confirmation_when_evidence_is_unchanged() -> None:
    review = unmatched_review.build_review(sample_record())
    review["manual_confirmed"] = True
    review["reviewer"] = "reviewer-a"
    review["reviewed_at"] = "2026-07-13T09:00:00+00:00"
    photo_id = review["photos"][0]["id"]

    updated = unmatched_review.apply_review_patch(
        review,
        actor="reviewer-b",
        expected_version=1,
        metadata={
            "meter_no": review["meter_no"],
            "collector": review["collector"],
            "module_asset_no": review["module_asset_no"],
        },
        photo_updates=[{"id": photo_id, "category": review["photos"][0]["category"]}],
        state="reviewed",
    )

    assert updated["manual_confirmed"] is True
    assert updated["reviewer"] == "reviewer-a"
    assert updated["reviewed_at"] == "2026-07-13T09:00:00+00:00"


def test_apply_review_patch_emits_persistable_audit_event_without_mutating_source() -> None:
    review = unmatched_review.build_review(sample_record())
    source_snapshot = copy.deepcopy(review)

    updated = unmatched_review.apply_review_patch(
        review,
        actor="reviewer-a",
        expected_version=1,
        metadata={"meter_no": "120000912474"},
        photo_updates=[],
        state="reviewed",
    )

    assert review == source_snapshot
    event = updated["audit_event"]
    assert event["actor"] == "reviewer-a"
    assert event["action"] == "update_unmatched_review"
    assert event["timestamp"] == updated["updated_at"]
    assert event["unmatched_id"] == "unmatched-1"
    assert event["before_version"] == 1
    assert event["after_version"] == 2
    assert event["before"] == source_snapshot
    assert event["after"]["version"] == 2
    assert event["after"]["meter_no"] == "120000912474"


def test_apply_review_patch_enforces_photo_update_fields_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    review = unmatched_review.build_review(sample_record())
    photo_id = review["photos"][0]["id"]
    monkeypatch.setattr(unmatched_review, "PHOTO_UPDATE_FIELDS", set())

    updated = unmatched_review.apply_review_patch(
        review,
        actor="reviewer-a",
        expected_version=1,
        metadata={},
        photo_updates=[{"id": photo_id, "category": "collector_barcode"}],
        state="pending",
    )

    assert updated["photos"][0]["category"] == "unclassified"


def test_barcode_context_uses_only_temporary_review_fields() -> None:
    review = unmatched_review.build_review(sample_record())

    context = unmatched_review.barcode_context(review)

    assert context == {
        "meter_no": "120000912473",
        "meter_match_key": "0000912473",
        "collector": "C001",
        "module_asset_no": "M001",
        "photos": review["photos"],
    }


def test_long_scanned_meter_barcode_matches_total_catalog_candidate() -> None:
    record = sample_record()
    review = unmatched_review.build_review(record)
    review["meter_no"] = "3130001112100041536116"

    candidates = unmatched_review.build_match_candidates(
        record,
        review,
        [{
            "id": "catalog-long-scan",
            "catalog_row_db_id": "catalog-long-scan-db",
            "terminal": "350000135073",
            "meter_no": "110004153611",
            "meter_match_key": "0004153611",
            "address": "long scan road",
        }],
        [{
            "id": "g-12102",
            "terminal": "350000135073",
            "total_catalog_row_id": "catalog-long-scan-db",
            "meter_match_key": "0004153611",
        }],
    )

    assert unmatched_review.review_meter_match_key(record, review) == "0004153611"
    assert unmatched_review.barcode_context(review)["meter_match_key"] == "0004153611"
    assert len(candidates) == 1
    assert candidates[0]["target_group_id"] == "g-12102"
    assert candidates[0]["has_existing_group"] is True


def test_match_candidates_use_opaque_keys_without_internal_ids() -> None:
    review = unmatched_review.build_review(sample_record())
    catalog_id = "catalog-public-id"
    catalog_db_id = "8a56330f-e241-43fe-a847-a0166559263e"
    target_group_id = "90f9d31b-982e-46a3-bc79-4b982a7c6997"

    candidates = unmatched_review.build_match_candidates(
        sample_record(),
        review,
        [
            {
                "id": catalog_id,
                "catalog_row_db_id": catalog_db_id,
                "terminal": "T-OPAQUE",
                "meter_no": "120000912473",
                "address": "opaque road",
            }
        ],
        [
            {
                "id": target_group_id,
                "terminal": "T-OPAQUE",
                "total_catalog_row_id": catalog_db_id,
            }
        ],
    )

    assert len(candidates) == 1
    assert re.fullmatch(r"candidate:[0-9a-f]{64}", candidates[0]["candidate_key"])
    assert candidates[0]["has_existing_group"] is True
    serialized = json.dumps(candidates[0])
    assert catalog_id not in candidates[0]["candidate_key"]
    assert catalog_db_id not in candidates[0]["candidate_key"]
    assert target_group_id not in candidates[0]["candidate_key"]
    assert target_group_id in serialized


def test_audit_redaction_hides_private_fields_urls_and_legacy_candidate_keys() -> None:
    payload = {
        "unmatched_id": "unmatched-public-id",
        "candidate_key": "catalog:8a56330f-e241-43fe-a847-a0166559263e:T-1",
        "catalog_row_db_id": "8a56330f-e241-43fe-a847-a0166559263e",
        "target_group_id": "90f9d31b-982e-46a3-bc79-4b982a7c6997",
        "raw": {"private": "must-not-leak"},
        "nested": {"note": "https://photos.example/object.jpg?token=secret"},
    }

    redacted = unmatched_review.redact_audit_photo_secrets(payload)
    serialized = json.dumps(redacted)

    assert redacted["unmatched_id"] == "unmatched-public-id"
    assert redacted["candidate_key"] == unmatched_review.AUDIT_REDACTED_VALUE
    assert redacted["catalog_row_db_id"] == unmatched_review.AUDIT_REDACTED_VALUE
    assert redacted["target_group_id"] == unmatched_review.AUDIT_REDACTED_VALUE
    assert redacted["raw"] == unmatched_review.AUDIT_REDACTED_VALUE
    assert redacted["nested"]["note"] == unmatched_review.AUDIT_REDACTED_VALUE
    for secret in ("must-not-leak", "8a56330f", "90f9d31b", "token=secret"):
        assert secret not in serialized
