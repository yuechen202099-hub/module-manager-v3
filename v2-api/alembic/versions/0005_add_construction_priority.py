"""add terminal construction priority fields

Revision ID: 20260721_0005
Revises: 20260622_0004
Create Date: 2026-07-21 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260721_0005"
down_revision = "20260622_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("construction_priority", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("tasks", sa.Column("construction_priority_updated_by", sa.String(length=64)))
    op.add_column(
        "tasks",
        sa.Column("construction_priority_updated_at", sa.DateTime(timezone=True)),
    )
    op.execute("UPDATE tasks SET construction_priority = FALSE")


def downgrade() -> None:
    op.drop_column("tasks", "construction_priority_updated_at")
    op.drop_column("tasks", "construction_priority_updated_by")
    op.drop_column("tasks", "construction_priority")
