"""Make collector inventory project-scoped and independent from runs.

Revision ID: 20260824_0016
Revises: 20260823_0015
Create Date: 2026-08-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260824_0016"
down_revision = "20260823_0015"
branch_labels = None
depends_on = None


UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column("physical_collectors", sa.Column("project_id", UUID, nullable=True))
    op.add_column("collector_photos", sa.Column("project_id", UUID, nullable=True))
    op.add_column("collector_scan_events", sa.Column("project_id", UUID, nullable=True))

    op.execute(
        sa.text(
            """
DO $$
BEGIN
  IF EXISTS (
    WITH project_refs AS (
      SELECT pc.id AS physical_collector_id, run.project_id
      FROM physical_collectors AS pc
      JOIN collector_transfer_runs AS run ON run.id = pc.first_seen_run_id
      UNION
      SELECT event.physical_collector_id, run.project_id
      FROM collector_scan_events AS event
      JOIN collector_transfer_runs AS run ON run.id = event.run_id
      UNION
      SELECT assignment.physical_collector_id, run.project_id
      FROM collector_assignments AS assignment
      JOIN collector_transfer_runs AS run ON run.id = assignment.run_id
    )
    SELECT 1
    FROM physical_collectors AS pc
    LEFT JOIN project_refs AS ref ON ref.physical_collector_id = pc.id
    GROUP BY pc.id
    HAVING COUNT(DISTINCT ref.project_id) <> 1
  ) THEN
    RAISE EXCEPTION 'ambiguous collector project ownership';
  END IF;
END
$$
"""
        )
    )
    op.execute(
        sa.text(
            """
WITH project_refs AS (
  SELECT pc.id AS physical_collector_id, run.project_id
  FROM physical_collectors AS pc
  JOIN collector_transfer_runs AS run ON run.id = pc.first_seen_run_id
  UNION
  SELECT event.physical_collector_id, run.project_id
  FROM collector_scan_events AS event
  JOIN collector_transfer_runs AS run ON run.id = event.run_id
  UNION
  SELECT assignment.physical_collector_id, run.project_id
  FROM collector_assignments AS assignment
  JOIN collector_transfer_runs AS run ON run.id = assignment.run_id
), resolved AS (
  SELECT physical_collector_id, (array_agg(DISTINCT project_id))[1] AS project_id
  FROM project_refs
  GROUP BY physical_collector_id
)
UPDATE physical_collectors AS pc
SET project_id = resolved.project_id
FROM resolved
WHERE resolved.physical_collector_id = pc.id
"""
        )
    )
    op.execute(
        sa.text(
            """
UPDATE collector_photos AS photo
SET project_id = physical.project_id
FROM physical_collectors AS physical
WHERE physical.id = photo.physical_collector_id
"""
        )
    )
    op.execute(
        sa.text(
            """
UPDATE collector_scan_events AS event
SET project_id = physical.project_id
FROM physical_collectors AS physical
WHERE physical.id = event.physical_collector_id
"""
        )
    )
    op.execute(
        sa.text(
            """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM collector_photos
    WHERE is_active
    GROUP BY physical_collector_id
    HAVING COUNT(*) > 1
  ) THEN
    RAISE EXCEPTION 'multiple active collector photos require manual resolution';
  END IF;
END
$$
"""
        )
    )

    op.alter_column("physical_collectors", "project_id", existing_type=UUID, nullable=False)
    op.alter_column("collector_photos", "project_id", existing_type=UUID, nullable=False)
    op.alter_column("collector_scan_events", "project_id", existing_type=UUID, nullable=False)
    op.alter_column("collector_scan_events", "run_id", existing_type=UUID, nullable=True)

    op.create_foreign_key(
        "fk_physical_collectors_project_id",
        "physical_collectors",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_collector_photos_project_id",
        "collector_photos",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_collector_scan_events_project_id",
        "collector_scan_events",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "fk_collector_scan_events_run_id_collector_transfer_runs",
        "collector_scan_events",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_collector_scan_events_run_id",
        "collector_scan_events",
        "collector_transfer_runs",
        ["run_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_constraint("uq_physical_collectors_team_no", "physical_collectors", type_="unique")
    op.drop_index("ix_physical_collectors_team_pool_status", table_name="physical_collectors")
    op.create_unique_constraint(
        "uq_physical_collectors_team_project_no",
        "physical_collectors",
        ["team_id", "project_id", "collector_no"],
    )
    op.create_index(
        "ix_physical_collectors_team_project_status",
        "physical_collectors",
        ["team_id", "project_id", "pool_status"],
    )

    op.drop_constraint("uq_collector_photos_team_sha256", "collector_photos", type_="unique")
    op.drop_index("ix_collector_photos_team_active", table_name="collector_photos")
    op.create_unique_constraint(
        "uq_collector_photos_team_project_sha256",
        "collector_photos",
        ["team_id", "project_id", "sha256"],
    )
    op.create_index(
        "ix_collector_photos_team_project_active",
        "collector_photos",
        ["team_id", "project_id", "is_active"],
    )
    op.create_index(
        "uq_collector_photos_one_active",
        "collector_photos",
        ["physical_collector_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(
        "ix_collector_scan_events_project_created",
        "collector_scan_events",
        ["team_id", "project_id", "created_at"],
    )


def downgrade() -> None:
    raise RuntimeError("project-scoped collector inventory is forward-only")
