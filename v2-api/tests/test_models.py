from __future__ import annotations

import app.models as models
from sqlalchemy import CheckConstraint, UniqueConstraint


def test_group_barcode_verification_models_are_exposed() -> None:
    assert hasattr(models, "GroupBarcodeVerification")
    assert hasattr(models, "BarcodeMaintenanceControl")


def test_group_barcode_verification_schema_uses_string_status_and_queue_indexes() -> None:
    table = models.GroupBarcodeVerification.__table__
    unique_constraints = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    check_constraints = [
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    ]
    indexes = {index.name: tuple(column.name for column in index.columns) for index in table.indexes}

    assert table.name == "group_barcode_verifications"
    assert ("team_id", "group_id") in unique_constraints
    assert table.c.status.type.__class__.__name__ == "String"
    assert any("manual_confirmed" in constraint for constraint in check_constraints)
    assert indexes["ix_group_barcode_verifications_pending"] == ("team_id", "status", "updated_at")
    assert indexes["ix_group_barcode_verifications_lease"] == ("team_id", "lease_expires_at")
    assert table.c.lease_token.type.__class__.__name__ == "String"
    assert table.c.lease_token.type.length == 128
    assert table.c.lease_token.nullable is True
    assert table.c.lease_token.default is None
    assert table.c.lease_token.server_default is None


def test_barcode_maintenance_control_is_scoped_to_one_team() -> None:
    table = models.BarcodeMaintenanceControl.__table__

    assert table.name == "barcode_maintenance_controls"
    assert table.c.team_id.primary_key is True
    assert {"paused", "last_batch_id", "last_batch_progress"} <= set(table.c.keys())
    assert table.c.paused.default.arg is True
    assert str(table.c.paused.server_default.arg) == "true"


def test_delivery_cache_job_is_durable_retryable_and_group_idempotent() -> None:
    table = models.DeliveryCacheJob.__table__
    unique_constraints = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    check_constraints = [
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    ]
    indexes = {index.name: tuple(column.name for column in index.columns) for index in table.indexes}

    assert table.name == "delivery_cache_jobs"
    assert ("team_id", "group_id") in unique_constraints
    assert any("processing" in constraint and "failed" in constraint for constraint in check_constraints)
    assert indexes["ix_delivery_cache_jobs_pending"] == ("team_id", "status", "updated_at")
    assert indexes["ix_delivery_cache_jobs_lease"] == ("team_id", "lease_expires_at")
    assert table.c.attempt_count.server_default.arg.text == "0"
    assert table.c.lease_token.type.length == 128
