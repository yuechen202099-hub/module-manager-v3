"""add persistent final delivery package jobs

Revision ID: 20260723_0011
Revises: 20260723_0010
Create Date: 2026-07-23 02:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260723_0011"
down_revision = "20260723_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivery_package_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("scope_hash", sa.String(length=64), nullable=False),
        sa.Column("scope_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("group_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_owner", sa.String(length=128)),
        sa.Column("lease_token", sa.String(length=128)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("package_path", sa.Text()),
        sa.Column("content_sha256", sa.String(length=64)),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("requested_by", sa.String(length=64)),
        sa.Column("request_reason", sa.String(length=128)),
        sa.Column("last_error", sa.Text()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed', 'stale')",
            name="ck_delivery_package_jobs_status",
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "team_id",
            "scope_hash",
            "evidence_fingerprint",
            name="uq_delivery_package_jobs_scope_fingerprint",
        ),
    )
    op.create_index(
        "ix_delivery_package_jobs_pending",
        "delivery_package_jobs",
        ["team_id", "status", "updated_at"],
    )
    op.create_index(
        "ix_delivery_package_jobs_lease",
        "delivery_package_jobs",
        ["team_id", "lease_expires_at"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "V3.1 delivery package jobs are production-irreversible; destructive downgrade is forbidden"
    )
