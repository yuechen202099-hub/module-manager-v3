"""Add collector inventory, one-time pool allocation, and transfer workbench.

Revision ID: 20260823_0015
Revises: 20260724_0014
Create Date: 2026-08-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260823_0015"
down_revision = "20260724_0014"
branch_labels = None
depends_on = None


UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "collector_transfer_runs",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("source_snapshot_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by_id", UUID, nullable=True),
        sa.Column("stats", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("diagnostics", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('draft', 'inventory', 'allocated', 'completed', 'cancelled')",
            name="ck_collector_transfer_runs_status",
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_collector_transfer_runs_team_project_created",
        "collector_transfer_runs",
        ["team_id", "project_id", "created_at"],
    )

    op.create_table(
        "collector_transfer_terminals",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("run_id", UUID, nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("terminal_code", sa.String(length=255), nullable=False),
        sa.Column("installation_address", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'ready'"), nullable=False),
        sa.Column("meter_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("collector_requirement_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_item_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("diagnostics", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('blocked', 'ready', 'in_progress', 'completed')",
            name="ck_collector_transfer_terminals_status",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["collector_transfer_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "terminal_code", name="uq_collector_transfer_terminals_run_code"),
    )
    op.create_index(
        "ix_collector_transfer_terminals_run_status", "collector_transfer_terminals", ["run_id", "status"]
    )

    op.create_table(
        "collector_meter_items",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("run_id", UUID, nullable=False),
        sa.Column("terminal_id", UUID, nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("source_group_id", UUID, nullable=False),
        sa.Column("meter_no", sa.String(length=255), nullable=False),
        sa.Column("meter_barcode", sa.String(length=255), nullable=False),
        sa.Column("module_no", sa.String(length=255), server_default="", nullable=False),
        sa.Column("module_barcode", sa.String(length=255), server_default="", nullable=False),
        sa.Column("original_collector_no", sa.String(length=255), server_default="", nullable=False),
        sa.Column("module_meter_photo_id", UUID, nullable=True),
        sa.Column("after_box_photo_id", UUID, nullable=True),
        sa.Column("module_meter_photo_snapshot", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("after_box_photo_snapshot", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("diagnostics", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["run_id"], ["collector_transfer_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["terminal_id"], ["collector_transfer_terminals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_group_id"], ["material_groups.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["module_meter_photo_id"], ["photos.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["after_box_photo_id"], ["photos.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "source_group_id", name="uq_collector_meter_items_run_group"),
    )
    op.create_index("ix_collector_meter_items_terminal_sort", "collector_meter_items", ["terminal_id", "sort_order"])

    op.create_table(
        "collector_requirements",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("run_id", UUID, nullable=False),
        sa.Column("terminal_id", UUID, nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("original_collector_no", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'unmatched'"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("diagnostics", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('unmatched', 'direct_pending_photo', 'direct_ready', 'assigned', 'used', 'blocked')",
            name="ck_collector_requirements_status",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["collector_transfer_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["terminal_id"], ["collector_transfer_terminals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("terminal_id", "original_collector_no", name="uq_collector_requirements_terminal_no"),
    )
    op.create_index("ix_collector_requirements_run_status", "collector_requirements", ["run_id", "status"])

    op.create_table(
        "collector_requirement_meters",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("requirement_id", UUID, nullable=False),
        sa.Column("meter_item_id", UUID, nullable=False),
        sa.ForeignKeyConstraint(["requirement_id"], ["collector_requirements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["meter_item_id"], ["collector_meter_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("requirement_id", "meter_item_id", name="uq_collector_requirement_meters_pair"),
    )

    op.create_table(
        "physical_collectors",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("collector_no", sa.String(length=255), nullable=False),
        sa.Column("pool_status", sa.String(length=32), server_default=sa.text("'awaiting_photo'"), nullable=False),
        sa.Column("first_seen_run_id", UUID, nullable=True),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "pool_status IN ('awaiting_photo', 'direct', 'available', 'reserved', 'used')",
            name="ck_physical_collectors_pool_status",
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["first_seen_run_id"], ["collector_transfer_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "collector_no", name="uq_physical_collectors_team_no"),
    )
    op.create_index("ix_physical_collectors_team_pool_status", "physical_collectors", ["team_id", "pool_status"])

    op.create_table(
        "collector_photos",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("physical_collector_id", UUID, nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("storage_type", sa.String(length=32), server_default="local", nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_by_id", UUID, nullable=True),
        sa.Column("captured_by_username", sa.String(length=64), server_default="", nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["physical_collector_id"], ["physical_collectors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["captured_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "sha256", name="uq_collector_photos_team_sha256"),
    )
    op.create_index("ix_collector_photos_team_active", "collector_photos", ["team_id", "is_active"])

    op.create_table(
        "collector_scan_events",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("run_id", UUID, nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("physical_collector_id", UUID, nullable=False),
        sa.Column("requirement_id", UUID, nullable=True),
        sa.Column("scanned_value", sa.String(length=255), nullable=False),
        sa.Column("decision", sa.String(length=64), nullable=False),
        sa.Column("requires_photo", sa.Boolean(), nullable=False),
        sa.Column("add_to_pool", sa.Boolean(), nullable=False),
        sa.Column("actor_id", UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["collector_transfer_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["physical_collector_id"], ["physical_collectors.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requirement_id"], ["collector_requirements.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_collector_scan_events_run_created", "collector_scan_events", ["run_id", "created_at"])

    op.create_table(
        "collector_assignments",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("run_id", UUID, nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("requirement_id", UUID, nullable=False),
        sa.Column("physical_collector_id", UUID, nullable=False),
        sa.Column("collector_photo_id", UUID, nullable=False),
        sa.Column("assignment_mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'reserved'"), nullable=False),
        sa.Column("assigned_by_id", UUID, nullable=True),
        sa.Column("assigned_by_username", sa.String(length=64), server_default="", nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint("assignment_mode IN ('direct', 'random')", name="ck_collector_assignments_mode"),
        sa.CheckConstraint("status IN ('reserved', 'used', 'rolled_back')", name="ck_collector_assignments_status"),
        sa.ForeignKeyConstraint(["run_id"], ["collector_transfer_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requirement_id"], ["collector_requirements.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["physical_collector_id"], ["physical_collectors.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["collector_photo_id"], ["collector_photos.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assigned_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_collector_assignments_run_status", "collector_assignments", ["run_id", "status"])
    op.create_index(
        "uq_collector_assignments_requirement_active",
        "collector_assignments",
        ["requirement_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('reserved', 'used')"),
    )
    op.create_index(
        "uq_collector_assignments_physical_active",
        "collector_assignments",
        ["physical_collector_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('reserved', 'used')"),
    )

    op.create_table(
        "collector_workbench_items",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("run_id", UUID, nullable=False),
        sa.Column("terminal_id", UUID, nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("item_kind", sa.String(length=32), nullable=False),
        sa.Column("source_key", sa.String(length=64), nullable=False),
        sa.Column("meter_item_id", UUID, nullable=True),
        sa.Column("requirement_id", UUID, nullable=True),
        sa.Column("assignment_id", UUID, nullable=True),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_by_id", UUID, nullable=True),
        sa.Column("completed_by_username", sa.String(length=64), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint("item_kind IN ('meter_install', 'collector_removal')", name="ck_collector_workbench_items_kind"),
        sa.CheckConstraint("status IN ('pending', 'completed')", name="ck_collector_workbench_items_status"),
        sa.ForeignKeyConstraint(["run_id"], ["collector_transfer_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["terminal_id"], ["collector_transfer_terminals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["meter_item_id"], ["collector_meter_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requirement_id"], ["collector_requirements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assignment_id"], ["collector_assignments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["completed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "item_kind", "source_key", name="uq_collector_workbench_items_source"),
    )
    op.create_index("ix_collector_workbench_items_terminal_sort", "collector_workbench_items", ["terminal_id", "sort_order"])

def downgrade() -> None:
    op.drop_index("ix_collector_workbench_items_terminal_sort", table_name="collector_workbench_items")
    op.drop_table("collector_workbench_items")
    op.drop_index("uq_collector_assignments_physical_active", table_name="collector_assignments")
    op.drop_index("uq_collector_assignments_requirement_active", table_name="collector_assignments")
    op.drop_index("ix_collector_assignments_run_status", table_name="collector_assignments")
    op.drop_table("collector_assignments")
    op.drop_index("ix_collector_scan_events_run_created", table_name="collector_scan_events")
    op.drop_table("collector_scan_events")
    op.drop_index("ix_collector_photos_team_active", table_name="collector_photos")
    op.drop_table("collector_photos")
    op.drop_index("ix_physical_collectors_team_pool_status", table_name="physical_collectors")
    op.drop_table("physical_collectors")
    op.drop_table("collector_requirement_meters")
    op.drop_index("ix_collector_requirements_run_status", table_name="collector_requirements")
    op.drop_table("collector_requirements")
    op.drop_index("ix_collector_meter_items_terminal_sort", table_name="collector_meter_items")
    op.drop_table("collector_meter_items")
    op.drop_index("ix_collector_transfer_terminals_run_status", table_name="collector_transfer_terminals")
    op.drop_table("collector_transfer_terminals")
    op.drop_index("ix_collector_transfer_runs_team_project_created", table_name="collector_transfer_runs")
    op.drop_table("collector_transfer_runs")
