from __future__ import annotations

from sqlalchemy.sql.elements import TextClause

from app.models import (
    MaterialExportCollectorAllocation,
    MaterialExportFile,
    MaterialExportJob,
    MaterialExportLease,
    MaterialExportTerminal,
    TerminalExportSetting,
)


def _sql_text(value: object) -> str:
    return str(value.text if isinstance(value, TextClause) else value)


def test_material_export_models_have_required_uniqueness_and_checks() -> None:
    setting = TerminalExportSetting.__table__
    allocation = MaterialExportCollectorAllocation.__table__
    assert {column.name for column in setting.primary_key.columns} == {"id"}
    assert any(
        constraint.name == "uq_terminal_export_settings_team_project_task"
        for constraint in setting.constraints
    )
    assert any(
        index.name == "uq_material_export_allocations_active_requirement"
        and "status IN ('reserved', 'used')" in _sql_text(index.dialect_options["postgresql"]["where"])
        for index in allocation.indexes
    )
    assert any(
        index.name == "uq_material_export_allocations_active_physical"
        and "status IN ('reserved', 'used')" in _sql_text(index.dialect_options["postgresql"]["where"])
        for index in allocation.indexes
    )


def test_collector_photo_is_optional_for_export_allocation() -> None:
    table = MaterialExportCollectorAllocation.__table__
    assert table.c.collector_photo_id.nullable is True
    assert table.c.group_photo_id.nullable is True


def test_export_model_boundaries_and_non_negative_counts_are_explicit() -> None:
    terminal = MaterialExportTerminal.__table__
    export_file = MaterialExportFile.__table__
    assert any(constraint.name == "uq_material_export_terminals_job_task" for constraint in terminal.constraints)
    assert {"requested_collector_count", "source_collector_count", "final_collector_count"} <= set(terminal.c.keys())
    assert any(
        constraint.name and constraint.name.endswith("material_export_terminals_counts")
        for constraint in terminal.constraints
    )
    assert export_file.c.byte_size.nullable is True
    assert export_file.c.sha256.nullable is True


def test_export_job_and_lease_keep_manifest_and_global_scope() -> None:
    assert {"manifest_sha256", "preflight_fingerprint", "stats", "diagnostics"} <= set(
        MaterialExportJob.__table__.c.keys()
    )
    lease = MaterialExportLease.__table__
    assert lease.c.scope.primary_key is True
    assert str(lease.c.scope.server_default.arg) == "'global-download'"


def test_material_export_model_ddl_remains_compatible_with_sqlite_test_databases() -> None:
    json_columns = (
        MaterialExportJob.__table__.c.stats,
        MaterialExportJob.__table__.c.diagnostics,
        MaterialExportTerminal.__table__.c.manifest_json,
        MaterialExportTerminal.__table__.c.diagnostics,
    )
    assert all(
        column.server_default is None
        or "::jsonb" not in str(column.server_default.arg)
        for column in json_columns
    )
