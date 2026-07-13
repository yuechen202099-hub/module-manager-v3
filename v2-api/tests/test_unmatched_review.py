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
