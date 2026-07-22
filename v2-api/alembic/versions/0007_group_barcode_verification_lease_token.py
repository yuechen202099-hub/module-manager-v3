"""add group barcode verification lease token

Revision ID: 20260722_0007
Revises: 20260722_0006
Create Date: 2026-07-22 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260722_0007"
down_revision = "20260722_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("group_barcode_verifications", sa.Column("lease_token", sa.String(length=128)))


def downgrade() -> None:
    raise RuntimeError(
        "V3.1 verification migrations are production-irreversible; "
        "restore a pre-upgrade backup instead of running downgrade DDL"
    )
