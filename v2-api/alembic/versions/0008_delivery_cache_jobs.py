"""add durable delivery cache jobs

Revision ID: 20260722_0008
Revises: 20260722_0007
Create Date: 2026-07-22 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260722_0008"
down_revision = "20260722_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivery_cache_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(length=128)),
        sa.Column("lease_token", sa.String(length=128)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("requested_by", sa.String(length=64)),
        sa.Column("request_reason", sa.String(length=128)),
        sa.Column("last_error", sa.Text()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed')",
            name="ck_delivery_cache_jobs_status",
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["material_groups.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("team_id", "group_id", name="uq_delivery_cache_jobs_team_group"),
    )
    op.create_index(
        "ix_delivery_cache_jobs_pending",
        "delivery_cache_jobs",
        ["team_id", "status", "updated_at"],
    )
    op.create_index(
        "ix_delivery_cache_jobs_lease",
        "delivery_cache_jobs",
        ["team_id", "lease_expires_at"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "V3.1 delivery cache migrations are production-irreversible; "
        "restore a pre-upgrade backup instead of running downgrade DDL"
    )
