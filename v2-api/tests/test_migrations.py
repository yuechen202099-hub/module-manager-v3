from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations


def load_migration_module():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0006_group_barcode_verification.py"
    spec = importlib.util.spec_from_file_location("group_barcode_verification_migration", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render_postgresql_ddl(direction: str) -> str:
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    migration = load_migration_module()
    migration.op = Operations(context)
    getattr(migration, direction)()
    return output.getvalue()


def test_group_barcode_verification_upgrade_renders_postgresql_schema_contract() -> None:
    ddl = render_postgresql_ddl("upgrade")

    assert "CREATE TABLE group_barcode_verifications" in ddl
    assert "CONSTRAINT uq_group_barcode_verifications_team_group UNIQUE (team_id, group_id)" in ddl
    assert "CONSTRAINT ck_group_barcode_verifications_status CHECK" in ddl
    assert "CREATE INDEX ix_group_barcode_verifications_pending" in ddl
    assert "CREATE INDEX ix_group_barcode_verifications_lease" in ddl
    assert "CREATE TABLE barcode_maintenance_controls" in ddl
    assert "paused BOOLEAN DEFAULT true NOT NULL" in ddl


def test_group_barcode_verification_downgrade_renders_reversible_postgresql_ddl() -> None:
    ddl = render_postgresql_ddl("downgrade")

    assert "DROP TABLE barcode_maintenance_controls" in ddl
    assert "DROP INDEX ix_group_barcode_verifications_lease" in ddl
    assert "DROP INDEX ix_group_barcode_verifications_pending" in ddl
    assert "DROP TABLE group_barcode_verifications" in ddl
