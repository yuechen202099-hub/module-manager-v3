"""add data center query indexes

Revision ID: 20260723_0013
Revises: 20260723_0012
Create Date: 2026-07-23 18:30:00
"""

from alembic import op


revision = "20260723_0013"
down_revision = "20260723_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_material_groups_data_center_team_status_updated",
        "material_groups",
        ["team_id", "status", "updated_at", "legacy_id"],
    )
    op.create_index(
        "ix_material_groups_data_center_team_terminal_updated",
        "material_groups",
        ["team_id", "terminal", "updated_at", "legacy_id"],
    )
    op.create_index(
        "ix_unmatched_records_data_center_team_status_updated",
        "unmatched_records",
        ["team_id", "status", "updated_at", "legacy_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_unmatched_records_data_center_team_status_updated",
        table_name="unmatched_records",
    )
    op.drop_index(
        "ix_material_groups_data_center_team_terminal_updated",
        table_name="material_groups",
    )
    op.drop_index(
        "ix_material_groups_data_center_team_status_updated",
        table_name="material_groups",
    )
