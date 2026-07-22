"""add durable group barcode verification state

Revision ID: 20260722_0006
Revises: 20260721_0005
Create Date: 2026-07-22 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260722_0006"
down_revision = "20260721_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "group_barcode_verifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("evidence_fingerprint", sa.String(length=64)),
        sa.Column("evidence_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("meter_matched", sa.Boolean()),
        sa.Column("module_matched", sa.Boolean()),
        sa.Column("collector_matched", sa.Boolean()),
        sa.Column("recognition_source", sa.String(length=64)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(length=128)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("invalidation_reason", sa.String(length=128)),
        sa.Column("invalidated_by", sa.String(length=64)),
        sa.Column("invalidated_at", sa.DateTime(timezone=True)),
        sa.Column("auto_archive_status", sa.String(length=32)),
        sa.Column("auto_archived_at", sa.DateTime(timezone=True)),
        sa.Column("auto_archive_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('not_eligible', 'pending', 'processing', 'passed', 'partial', "
            "'unreadable', 'mismatch', 'manual_confirmed', 'failed')",
            name="ck_group_barcode_verifications_status",
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["material_groups.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("team_id", "group_id", name="uq_group_barcode_verifications_team_group"),
    )
    op.create_index(
        "ix_group_barcode_verifications_pending",
        "group_barcode_verifications",
        ["team_id", "status", "updated_at"],
    )
    op.create_index(
        "ix_group_barcode_verifications_lease",
        "group_barcode_verifications",
        ["team_id", "lease_expires_at"],
    )
    op.create_table(
        "barcode_maintenance_controls",
        sa.Column("team_id", sa.String(length=64), primary_key=True),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_batch_id", sa.String(length=128)),
        sa.Column("last_batch_progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("barcode_maintenance_controls")
    op.drop_index("ix_group_barcode_verifications_lease", table_name="group_barcode_verifications")
    op.drop_index("ix_group_barcode_verifications_pending", table_name="group_barcode_verifications")
    op.drop_table("group_barcode_verifications")
