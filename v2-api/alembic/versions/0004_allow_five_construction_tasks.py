"""allow up to five active construction tasks per constructor

Revision ID: 20260622_0004
Revises: 20260619_0003
Create Date: 2026-06-22 12:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260622_0004"
down_revision = "20260619_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_tasks_team_construction_claimed_by")


def downgrade() -> None:
    op.create_index(
        "uq_tasks_team_construction_claimed_by",
        "tasks",
        ["team_id", "construction_claimed_by"],
        unique=True,
        postgresql_where=sa.text("construction_claimed_by IS NOT NULL"),
    )
