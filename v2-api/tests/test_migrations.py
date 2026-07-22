from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations


def load_migration_module(filename: str):
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render_postgresql_ddl(direction: str, *filenames: str) -> str:
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    for filename in filenames:
        migration = load_migration_module(filename)
        migration.op = Operations(context)
        getattr(migration, direction)()
    return output.getvalue()


def test_group_barcode_verification_upgrade_renders_postgresql_schema_contract() -> None:
    ddl = render_postgresql_ddl(
        "upgrade",
        "0006_group_barcode_verification.py",
        "0007_group_barcode_verification_lease_token.py",
    )

    assert "CREATE TABLE group_barcode_verifications" in ddl
    assert "CONSTRAINT uq_group_barcode_verifications_team_group UNIQUE (team_id, group_id)" in ddl
    assert "CONSTRAINT ck_group_barcode_verifications_status CHECK" in ddl
    assert "CREATE INDEX ix_group_barcode_verifications_pending" in ddl
    assert "CREATE INDEX ix_group_barcode_verifications_lease" in ddl
    assert "CREATE TABLE barcode_maintenance_controls" in ddl
    assert "paused BOOLEAN DEFAULT true NOT NULL" in ddl
    assert "ALTER TABLE group_barcode_verifications ADD COLUMN lease_token VARCHAR(128)" in ddl


def test_group_barcode_verification_downgrade_renders_reversible_postgresql_ddl() -> None:
    ddl = render_postgresql_ddl(
        "downgrade",
        "0007_group_barcode_verification_lease_token.py",
        "0006_group_barcode_verification.py",
    )

    assert "DROP TABLE barcode_maintenance_controls" in ddl
    assert "DROP INDEX ix_group_barcode_verifications_lease" in ddl
    assert "DROP INDEX ix_group_barcode_verifications_pending" in ddl
    assert "DROP TABLE group_barcode_verifications" in ddl
    assert "ALTER TABLE group_barcode_verifications DROP COLUMN lease_token" in ddl


def test_group_barcode_verification_lease_token_revision_chain() -> None:
    migration = load_migration_module("0007_group_barcode_verification_lease_token.py")

    assert migration.revision == "20260722_0007"
    assert migration.down_revision == "20260722_0006"


def test_delivery_cache_job_migration_is_reversible_and_chained() -> None:
    migration = load_migration_module("0008_delivery_cache_jobs.py")
    upgrade = render_postgresql_ddl("upgrade", "0008_delivery_cache_jobs.py")
    downgrade = render_postgresql_ddl("downgrade", "0008_delivery_cache_jobs.py")

    assert migration.revision == "20260722_0008"
    assert migration.down_revision == "20260722_0007"
    assert "CREATE TABLE delivery_cache_jobs" in upgrade
    assert "CONSTRAINT uq_delivery_cache_jobs_team_group UNIQUE (team_id, group_id)" in upgrade
    assert "CREATE INDEX ix_delivery_cache_jobs_pending" in upgrade
    assert "CREATE INDEX ix_delivery_cache_jobs_lease" in upgrade
    assert "DROP TABLE delivery_cache_jobs" in downgrade
