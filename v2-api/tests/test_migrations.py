from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path

import pytest
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


@pytest.mark.parametrize(
    "filename",
    [
        "0006_group_barcode_verification.py",
        "0007_group_barcode_verification_lease_token.py",
        "0008_delivery_cache_jobs.py",
        "0009_delivery_cache_fix3.py",
        "0010_auto_archive_queue_state.py",
        "0011_delivery_package_jobs.py",
        "0012_delivery_package_group_ids_gin.py",
    ],
)
def test_v3_1_migrations_reject_downgrade_before_any_ddl(filename: str) -> None:
    class DdlMustNotRun:
        def __getattr__(self, name: str):
            pytest.fail(f"downgrade attempted destructive DDL through op.{name}")

    migration = load_migration_module(filename)
    migration.op = DdlMustNotRun()

    with pytest.raises(RuntimeError, match="irreversible"):
        migration.downgrade()


def test_group_barcode_verification_lease_token_revision_chain() -> None:
    migration = load_migration_module("0007_group_barcode_verification_lease_token.py")

    assert migration.revision == "20260722_0007"
    assert migration.down_revision == "20260722_0006"


def test_delivery_cache_job_migration_is_persistent_and_chained() -> None:
    migration = load_migration_module("0008_delivery_cache_jobs.py")
    upgrade = render_postgresql_ddl("upgrade", "0008_delivery_cache_jobs.py")

    assert migration.revision == "20260722_0008"
    assert migration.down_revision == "20260722_0007"
    assert "CREATE TABLE delivery_cache_jobs" in upgrade
    assert "CONSTRAINT uq_delivery_cache_jobs_team_group UNIQUE (team_id, group_id)" in upgrade
    assert "CREATE INDEX ix_delivery_cache_jobs_pending" in upgrade
    assert "CREATE INDEX ix_delivery_cache_jobs_lease" in upgrade


def test_delivery_cache_fix3_migration_adds_cursor_evidence_and_not_eligible_status() -> None:
    migration = load_migration_module("0009_delivery_cache_fix3.py")
    upgrade = render_postgresql_ddl("upgrade", "0009_delivery_cache_fix3.py")

    assert migration.revision == "20260722_0009"
    assert migration.down_revision == "20260722_0008"
    assert "ADD COLUMN delivery_cache_reconcile_cursor UUID" in upgrade
    assert "ADD COLUMN evidence_fingerprint VARCHAR(64)" in upgrade
    assert "ADD COLUMN evidence_version INTEGER DEFAULT '0' NOT NULL" in upgrade
    assert "not_eligible" in upgrade


def test_delivery_package_job_migration_is_persistent_and_chained() -> None:
    migration = load_migration_module("0011_delivery_package_jobs.py")
    upgrade = render_postgresql_ddl("upgrade", "0011_delivery_package_jobs.py")

    assert migration.revision == "20260723_0011"
    assert migration.down_revision == "20260723_0010"
    assert "CREATE TABLE delivery_package_jobs" in upgrade
    assert "CONSTRAINT uq_delivery_package_jobs_scope_fingerprint UNIQUE" in upgrade
    assert "CREATE INDEX ix_delivery_package_jobs_pending" in upgrade
    assert "CREATE INDEX ix_delivery_package_jobs_lease" in upgrade


def test_delivery_package_group_ids_gin_migration_is_chained() -> None:
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0012_delivery_package_group_ids_gin.py"
    assert path.exists()
    migration = load_migration_module(path.name)
    upgrade = render_postgresql_ddl("upgrade", path.name)

    assert migration.revision == "20260723_0012"
    assert migration.down_revision == "20260723_0011"
    assert "CREATE INDEX ix_delivery_package_jobs_group_ids_gin" in upgrade
    assert "USING gin (group_ids)" in upgrade
