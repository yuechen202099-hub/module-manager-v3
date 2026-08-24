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
    assert {"paused", "last_batch_id", "last_batch_progress", "delivery_cache_reconcile_cursor"} <= set(table.c.keys())
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
    assert {"evidence_fingerprint", "evidence_version"} <= set(table.c.keys())
    assert any("not_eligible" in constraint for constraint in check_constraints)


def test_collector_transfer_models_keep_source_data_in_sidecar_tables() -> None:
    """Catches collapsing collector pool state into the legacy photo/group tables."""
    expected = {
        "CollectorTransferRun": "collector_transfer_runs",
        "CollectorTransferTerminal": "collector_transfer_terminals",
        "CollectorMeterItem": "collector_meter_items",
        "CollectorRequirement": "collector_requirements",
        "CollectorRequirementMeter": "collector_requirement_meters",
        "PhysicalCollector": "physical_collectors",
        "CollectorPhoto": "collector_photos",
        "CollectorScanEvent": "collector_scan_events",
        "CollectorAssignment": "collector_assignments",
        "CollectorWorkbenchItem": "collector_workbench_items",
    }

    assert {name: getattr(models, name).__table__.name for name in expected} == expected


def test_cancelled_collector_batch_import_has_no_persistence_model() -> None:
    """Catches the retired batch-import ledger returning to the production schema."""
    assert not hasattr(models, "CollectorImportRow")


def test_collector_assignment_schema_prevents_double_consumption() -> None:
    """Catches an active assignment losing exclusivity or a rollback retaining it forever."""
    table = models.CollectorAssignment.__table__
    unique_constraints = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    indexes = {index.name: index for index in table.indexes}

    assert ("requirement_id",) not in unique_constraints
    assert ("physical_collector_id",) not in unique_constraints
    assert tuple(column.name for column in indexes["uq_collector_assignments_requirement_active"].columns) == ("requirement_id",)
    assert tuple(column.name for column in indexes["uq_collector_assignments_physical_active"].columns) == ("physical_collector_id",)
    assert str(indexes["uq_collector_assignments_requirement_active"].dialect_options["postgresql"]["where"]) == "status IN ('reserved', 'used')"
    assert str(indexes["uq_collector_assignments_physical_active"].dialect_options["postgresql"]["where"]) == "status IN ('reserved', 'used')"
    assert table.c.assignment_mode.type.__class__.__name__ == "String"
    assert table.c.status.type.__class__.__name__ == "String"


def test_physical_collector_is_unique_per_project_and_has_explicit_pool_state() -> None:
    """Catches one project's collector number blocking or leaking into another project."""
    table = models.PhysicalCollector.__table__
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

    assert ("team_id", "project_id", "collector_no") in unique_constraints
    assert ("team_id", "collector_no") not in unique_constraints
    assert indexes["ix_physical_collectors_team_project_status"] == (
        "team_id",
        "project_id",
        "pool_status",
    )
    assert any("awaiting_photo" in constraint and "available" in constraint and "used" in constraint for constraint in check_constraints)


def test_collector_photo_sha_is_unique_per_project_and_has_one_active_photo() -> None:
    """Catches cross-project photo blocking or two active photos for one physical collector."""
    table = models.CollectorPhoto.__table__
    unique_constraints = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("sha256",) not in unique_constraints
    indexes = {index.name: index for index in table.indexes}

    assert ("team_id", "project_id", "sha256") in unique_constraints
    assert ("team_id", "sha256") not in unique_constraints
    assert ("physical_collector_id", "sha256") not in unique_constraints
    active_index = indexes["uq_collector_photos_one_active"]
    assert tuple(column.name for column in active_index.columns) == ("physical_collector_id",)
    assert active_index.unique is True
    assert str(active_index.dialect_options["postgresql"]["where"]) == "is_active"


def test_collector_scan_event_belongs_to_project_without_requiring_a_run() -> None:
    """Catches project inventory scans retaining a hidden batch dependency."""
    table = models.CollectorScanEvent.__table__
    indexes = {index.name: tuple(column.name for column in index.columns) for index in table.indexes}

    assert table.c.project_id.nullable is False
    assert table.c.run_id.nullable is True
    assert indexes["ix_collector_scan_events_project_created"] == (
        "team_id",
        "project_id",
        "created_at",
    )


def test_collector_transfer_models_persist_snapshot_and_operator_provenance() -> None:
    """Catches run evidence or per-mapping operator provenance reverting to mutable lookups."""
    meter_columns = models.CollectorMeterItem.__table__.c
    photo_columns = models.CollectorPhoto.__table__.c
    assignment_columns = models.CollectorAssignment.__table__.c
    workbench_columns = models.CollectorWorkbenchItem.__table__.c

    assert {"module_meter_photo_snapshot", "after_box_photo_snapshot"} <= set(meter_columns.keys())
    assert {"captured_by_id", "captured_by_username"} <= set(photo_columns.keys())
    assert {"assigned_by_id", "assigned_by_username"} <= set(assignment_columns.keys())
    assert {"completed_by_id", "completed_by_username"} <= set(workbench_columns.keys())
