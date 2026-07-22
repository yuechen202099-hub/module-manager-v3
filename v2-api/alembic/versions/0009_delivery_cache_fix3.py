"""close delivery cache lease and reconciliation gaps

Revision ID: 20260722_0009
Revises: 20260722_0008
Create Date: 2026-07-22 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260722_0009"
down_revision = "20260722_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "barcode_maintenance_controls",
        sa.Column("delivery_cache_reconcile_cursor", postgresql.UUID(as_uuid=True)),
    )
    op.add_column("delivery_cache_jobs", sa.Column("evidence_fingerprint", sa.String(length=64)))
    op.add_column(
        "delivery_cache_jobs",
        sa.Column("evidence_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.drop_constraint("ck_delivery_cache_jobs_status", "delivery_cache_jobs", type_="check")
    op.create_check_constraint(
        "ck_delivery_cache_jobs_status",
        "delivery_cache_jobs",
        "status IN ('pending', 'processing', 'ready', 'failed', 'not_eligible')",
    )


def downgrade() -> None:
    raise RuntimeError(
        "V3.1 delivery cache migrations are production-irreversible; "
        "restore a pre-upgrade backup instead of running downgrade DDL"
    )
