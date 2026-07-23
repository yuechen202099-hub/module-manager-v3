"""index delivery package group ids for set-based invalidation

Revision ID: 20260723_0012
Revises: 20260723_0011
Create Date: 2026-07-23 11:30:00
"""

from alembic import op


revision = "20260723_0012"
down_revision = "20260723_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_delivery_package_jobs_group_ids_gin",
        "delivery_package_jobs",
        ["group_ids"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    raise RuntimeError(
        "V3.1 delivery package group index is production-irreversible; destructive downgrade is forbidden"
    )
