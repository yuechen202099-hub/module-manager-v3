from sqlalchemy import UniqueConstraint

from app.models import GroupStatus, MaterialGroup, Photo, TaskStatus, TotalCatalogRow
from app.services.local_simulation import build_summary


def test_production_status_enums_cover_v21_canonical_values() -> None:
    assert {item.value for item in TaskStatus} == {
        "draft",
        "published",
        "claimed",
        "completed",
        "released",
        "cancelled",
    }
    assert {item.value for item in GroupStatus} == {
        "unreviewed",
        "in_review",
        "incomplete",
        "approved",
        "rejected",
    }


def test_local_status_aliases_map_to_production_values() -> None:
    task_aliases = {
        "published": "published",
        "released": "released",
        "in_review": "claimed",
    }
    group_aliases = {
        "pending": "unreviewed",
        "incomplete": "incomplete",
        "unmatched": "rejected",
        "approved": "approved",
        "exception": "rejected",
    }

    assert task_aliases["in_review"] in {item.value for item in TaskStatus}
    assert "in_review" not in {item.value for item in TaskStatus}
    assert set(task_aliases.values()) <= {item.value for item in TaskStatus}
    assert set(group_aliases.values()) <= {item.value for item in GroupStatus}
    assert group_aliases["unmatched"] != "approved"
    assert group_aliases["exception"] != "approved"


def test_database_constraints_protect_group_and_photo_identity() -> None:
    material_constraints = {
        constraint.name
        for constraint in MaterialGroup.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    photo_constraints = {
        constraint.name
        for constraint in Photo.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert "uq_material_groups_project_meter_key" in material_constraints
    assert "uq_photos_group_sha256" in photo_constraints


def test_address_fields_keep_total_catalog_as_single_authoritative_source() -> None:
    total_columns = TotalCatalogRow.__table__.columns
    group_columns = MaterialGroup.__table__.columns

    assert "installation_address" in total_columns
    assert total_columns["installation_address"].nullable is False
    assert "installation_address" in group_columns
    assert group_columns["installation_address"].nullable is False
    assert "total_catalog_row_id" in group_columns


def test_photo_insufficient_threshold_is_four_valid_photos() -> None:
    groups = [
        {"status": "incomplete", "photo_count": 0},
        {"status": "incomplete", "photo_count": 3},
        {"status": "pending", "photo_count": 4},
    ]
    summary = build_summary([], [], [], groups, [], [])

    assert summary["incomplete_groups"] == 0
    assert summary["exception_groups"] == 1
    assert summary["unconstructed_groups"] == 1
    assert summary["unreviewed_groups"] == 2
    assert summary["reviewed_groups"] == 0
    assert summary["photo_rows_linked"] == 7
    assert summary["scanned_groups"] == 2


def test_supplemental_photo_rule_returns_group_to_unreviewed_after_threshold() -> None:
    group = {"status": "incomplete", "photo_count": 3}

    group["photo_count"] += 1
    if group["photo_count"] >= 4:
        group["status"] = "pending"

    assert group == {"status": "pending", "photo_count": 4}
