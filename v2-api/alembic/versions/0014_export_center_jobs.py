"""Add export center job facade fields.

Revision ID: 20260724_0014
Revises: 20260723_0013
Create Date: 2026-07-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260724_0014"
down_revision = "20260723_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "export_jobs",
        "job_type",
        type_=sa.String(length=64),
        existing_type=postgresql.ENUM("task_detail", "final_delivery", name="export_job_type"),
        postgresql_using="job_type::text",
        existing_nullable=False,
    )
    op.add_column(
        "export_jobs",
        sa.Column(
            "filter_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("export_jobs", sa.Column("content_path", sa.Text(), nullable=True))
    op.add_column("export_jobs", sa.Column("content_sha256", sa.String(length=64), nullable=True))
    op.add_column("export_jobs", sa.Column("request_key", sa.String(length=128), nullable=True))
    op.create_unique_constraint(
        "uq_export_jobs_team_request_key",
        "export_jobs",
        ["team_id", "request_key"],
    )
    op.create_index(
        "ix_export_jobs_team_type_created",
        "export_jobs",
        ["team_id", "job_type", "created_at"],
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM export_jobs
                WHERE job_type NOT IN ('task_detail', 'final_delivery')
            ) THEN
                RAISE EXCEPTION 'Cannot downgrade export_jobs while V3.2 export center job types exist';
            END IF;
        END $$;
        """
    )
    op.drop_index("ix_export_jobs_team_type_created", table_name="export_jobs")
    op.drop_constraint("uq_export_jobs_team_request_key", "export_jobs", type_="unique")
    op.drop_column("export_jobs", "request_key")
    op.drop_column("export_jobs", "content_sha256")
    op.drop_column("export_jobs", "content_path")
    op.drop_column("export_jobs", "filter_snapshot")
    op.alter_column(
        "export_jobs",
        "job_type",
        type_=postgresql.ENUM("task_detail", "final_delivery", name="export_job_type"),
        existing_type=sa.String(length=64),
        postgresql_using="job_type::export_job_type",
        existing_nullable=False,
    )
