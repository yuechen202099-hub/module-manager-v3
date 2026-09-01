"""Add terminal material export settings, reservations, files and lease.

Revision ID: 20260901_0017
Revises: 20260824_0016
Create Date: 2026-09-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260901_0017"
down_revision = "20260824_0016"
branch_labels = None
depends_on = None


UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def upgrade() -> None:
    op.create_table(
        "terminal_export_settings",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("terminal_code", sa.String(length=128), nullable=False),
        sa.Column(
            "requested_collector_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("updated_by_id", UUID, nullable=True),
        sa.Column("updated_by_username", sa.String(length=64), server_default=sa.text("''"), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "requested_collector_count >= 0",
            name="ck_terminal_export_settings_requested_count",
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "team_id",
            "project_id",
            "task_id",
            name="uq_terminal_export_settings_team_project_task",
        ),
    )
    op.create_index(
        "ix_terminal_export_settings_project_terminal",
        "terminal_export_settings",
        ["team_id", "project_id", "terminal_code"],
    )

    op.create_table(
        "material_export_jobs",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", UUID, nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'reserved'"), nullable=False),
        sa.Column("preflight_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by_id", UUID, nullable=True),
        sa.Column("created_by_username", sa.String(length=64), nullable=False),
        sa.Column("stats", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("diagnostics", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('prechecking', 'ready', 'reserved', 'downloading', 'paused', "
            "'needs_recheck', 'failed', 'completed', 'cancelled')",
            name="ck_material_export_jobs_status",
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_material_export_jobs_project_created",
        "material_export_jobs",
        ["team_id", "project_id", "created_at"],
    )
    op.create_index(
        "ix_material_export_jobs_status", "material_export_jobs", ["status", "updated_at"]
    )

    op.create_table(
        "material_export_terminals",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_id", UUID, nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("terminal_code", sa.String(length=128), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default=sa.text("'not_prechecked'"), nullable=False
        ),
        sa.Column("requested_collector_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("source_collector_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("final_collector_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("source_revision", sa.String(length=64), nullable=False),
        sa.Column("manifest_json", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("diagnostics", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('not_prechecked', 'blocked', 'ready', 'reserved', 'downloading', "
            "'paused', 'needs_recheck', 'failed', 'completed', 'cancelled_released')",
            name="ck_material_export_terminals_status",
        ),
        sa.CheckConstraint(
            "requested_collector_count >= 0 AND source_collector_count >= 0 "
            "AND final_collector_count >= source_collector_count "
            "AND final_collector_count >= requested_collector_count",
            name="ck_material_export_terminals_counts",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["material_export_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "task_id", name="uq_material_export_terminals_job_task"),
    )
    op.create_index(
        "ix_material_export_terminals_project_task",
        "material_export_terminals",
        ["team_id", "project_id", "task_id"],
    )
    op.create_index(
        "ix_material_export_terminals_job_status",
        "material_export_terminals",
        ["job_id", "status"],
    )

    op.create_table(
        "material_export_collector_allocations",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_id", UUID, nullable=False),
        sa.Column("terminal_export_id", UUID, nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", UUID, nullable=False),
        sa.Column("requirement_key", sa.String(length=255), nullable=False),
        sa.Column("original_collector_no", sa.String(length=255), nullable=True),
        sa.Column("physical_collector_id", UUID, nullable=False),
        sa.Column("source_assignment_id", UUID, nullable=True),
        sa.Column("collector_photo_id", UUID, nullable=True),
        sa.Column("group_photo_id", UUID, nullable=True),
        sa.Column("allocation_mode", sa.String(length=32), nullable=False),
        sa.Column(
            "photo_source_kind", sa.String(length=32), server_default=sa.text("'none'"), nullable=False
        ),
        sa.Column("prior_pool_status", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'reserved'"), nullable=False),
        sa.Column("created_by_id", UUID, nullable=True),
        sa.Column("created_by_username", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by_id", UUID, nullable=True),
        sa.Column("released_by_username", sa.String(length=64), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "allocation_mode IN ('same_number', 'random_pool', 'extra_pool')",
            name="ck_material_export_allocations_mode",
        ),
        sa.CheckConstraint(
            "photo_source_kind IN ('inventory_same', 'terminal_group', 'pool', 'none')",
            name="ck_material_export_allocations_photo_source",
        ),
        sa.CheckConstraint(
            "status IN ('reserved', 'used', 'released')",
            name="ck_material_export_allocations_status",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["material_export_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["terminal_export_id"], ["material_export_terminals.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["physical_collector_id"], ["physical_collectors.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_assignment_id"], ["collector_assignments.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["collector_photo_id"], ["collector_photos.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["group_photo_id"], ["photos.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["released_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_material_export_allocations_project_status",
        "material_export_collector_allocations",
        ["team_id", "project_id", "status"],
    )
    op.create_index(
        "uq_material_export_allocations_active_requirement",
        "material_export_collector_allocations",
        ["terminal_export_id", "requirement_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('reserved', 'used')"),
    )
    op.create_index(
        "uq_material_export_allocations_active_physical",
        "material_export_collector_allocations",
        ["physical_collector_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('reserved', 'used')"),
    )

    op.create_table(
        "material_export_files",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_id", UUID, nullable=False),
        sa.Column("terminal_export_id", UUID, nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", UUID, nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_photo_id", UUID, nullable=True),
        sa.Column("source_collector_photo_id", UUID, nullable=True),
        sa.Column("storage_type", sa.String(length=32), nullable=True),
        sa.Column("storage_bucket", sa.String(length=255), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("original_extension", sa.String(length=16), server_default=sa.text("''"), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("manifest_position", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "source_kind IN ('photo', 'collector_photo', 'client_workbook')",
            name="ck_material_export_files_source_kind",
        ),
        sa.CheckConstraint(
            "(source_kind = 'photo' AND source_photo_id IS NOT NULL "
            "AND source_collector_photo_id IS NULL) OR "
            "(source_kind = 'collector_photo' AND source_photo_id IS NULL "
            "AND source_collector_photo_id IS NOT NULL) OR "
            "(source_kind = 'client_workbook' AND source_photo_id IS NULL "
            "AND source_collector_photo_id IS NULL)",
            name="ck_material_export_files_source_reference",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'downloading', 'completed', 'failed', 'skipped')",
            name="ck_material_export_files_status",
        ),
        sa.CheckConstraint(
            "(byte_size IS NULL OR byte_size >= 0) AND retry_count >= 0",
            name="ck_material_export_files_sizes",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["material_export_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["terminal_export_id"], ["material_export_terminals.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_photo_id"], ["photos.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_collector_photo_id"], ["collector_photos.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "terminal_export_id", "relative_path", name="uq_material_export_files_terminal_path"
        ),
    )
    op.create_index(
        "ix_material_export_files_job_status", "material_export_files", ["job_id", "status"]
    )
    op.create_index(
        "ix_material_export_files_terminal_order",
        "material_export_files",
        ["terminal_export_id", "manifest_position"],
    )

    op.create_table(
        "material_export_leases",
        sa.Column(
            "scope",
            sa.String(length=32),
            server_default=sa.text("'global-download'"),
            nullable=False,
        ),
        sa.Column("job_id", UUID, nullable=False),
        sa.Column("owner_token", sa.String(length=128), nullable=False),
        sa.Column("owner_id", UUID, nullable=True),
        sa.Column("owner_username", sa.String(length=64), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        *timestamps(),
        sa.CheckConstraint("scope = 'global-download'", name="ck_material_export_leases_scope"),
        sa.ForeignKeyConstraint(["job_id"], ["material_export_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("scope"),
    )
    op.create_index("ix_material_export_leases_expiry", "material_export_leases", ["expires_at"])


def downgrade() -> None:
    raise RuntimeError("material export persistence is forward-only")
