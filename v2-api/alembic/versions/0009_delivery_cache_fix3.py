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
    op.execute("UPDATE delivery_cache_jobs SET status = 'failed' WHERE status = 'not_eligible'")
    op.drop_constraint("ck_delivery_cache_jobs_status", "delivery_cache_jobs", type_="check")
    op.create_check_constraint(
        "ck_delivery_cache_jobs_status",
        "delivery_cache_jobs",
        "status IN ('pending', 'processing', 'ready', 'failed')",
    )
    op.drop_column("delivery_cache_jobs", "evidence_version")
    op.drop_column("delivery_cache_jobs", "evidence_fingerprint")
    op.drop_column("barcode_maintenance_controls", "delivery_cache_reconcile_cursor")
