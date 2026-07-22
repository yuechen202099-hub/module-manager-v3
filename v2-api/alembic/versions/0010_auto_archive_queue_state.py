"""add durable automatic archive queue state

Revision ID: 20260723_0010
Revises: 20260722_0009
Create Date: 2026-07-23 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260723_0010"
down_revision = "20260722_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "group_barcode_verifications",
        sa.Column("auto_archive_attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "group_barcode_verifications",
        sa.Column("auto_archive_lease_owner", sa.String(length=128)),
    )
    op.add_column(
        "group_barcode_verifications",
        sa.Column("auto_archive_lease_token", sa.String(length=128)),
    )
    op.add_column(
        "group_barcode_verifications",
        sa.Column("auto_archive_lease_expires_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_group_barcode_verifications_archive_pending",
        "group_barcode_verifications",
        ["team_id", "auto_archive_status", "auto_archive_lease_expires_at", "updated_at"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "V3.1 verification and archive queue migrations are irreversible; "
        "restore a pre-upgrade backup instead of running downgrade DDL"
    )
