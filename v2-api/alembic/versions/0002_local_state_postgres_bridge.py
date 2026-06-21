"""local JSON state to PostgreSQL bridge tables

Revision ID: 20260618_0002
Revises: 20260609_0001
Create Date: 2026-06-18 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260618_0002"
down_revision = "20260609_0001"
branch_labels = None
depends_on = None


def _add_team_fk(table_name: str, nullable: bool = True) -> None:
    op.add_column(table_name, sa.Column("team_id", sa.String(length=64), nullable=nullable))
    op.create_foreign_key(
        f"fk_{table_name}_team_id_teams",
        table_name,
        "teams",
        ["team_id"],
        ["id"],
        ondelete="CASCADE" if not nullable else "SET NULL",
    )
    op.create_index(f"ix_{table_name}_team_id", table_name, ["team_id"])


def _drop_index(name: str, table: str) -> None:
    op.drop_index(name, table_name=table)


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    _add_team_fk("users")
    op.add_column("users", sa.Column("name", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("home", sa.String(length=255), nullable=True))

    _add_team_fk("projects")

    _add_team_fk("import_jobs")

    _add_team_fk("total_catalog_rows")
    op.add_column("total_catalog_rows", sa.Column("source_file", sa.String(length=255), nullable=True))
    op.add_column("total_catalog_rows", sa.Column("terminal", sa.String(length=128), nullable=True))
    op.add_column("total_catalog_rows", sa.Column("installer", sa.String(length=128), nullable=True))
    op.create_index("ix_total_catalog_rows_team_meter_key", "total_catalog_rows", ["team_id", "meter_match_key"])
    op.create_index(
        "uq_total_catalog_rows_team_meter_key",
        "total_catalog_rows",
        ["team_id", "meter_match_key"],
        unique=True,
        postgresql_where=sa.text("team_id IS NOT NULL AND meter_match_key <> ''"),
    )

    _add_team_fk("stage_catalog_rows")

    _add_team_fk("tasks")
    op.add_column("tasks", sa.Column("legacy_id", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("terminal", sa.String(length=128), nullable=True))
    op.add_column("tasks", sa.Column("review_claimed_by", sa.String(length=64), nullable=True))
    op.add_column("tasks", sa.Column("construction_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("tasks", sa.Column("construction_claimed_by", sa.String(length=64), nullable=True))
    op.add_column("tasks", sa.Column("construction_claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("construction_released_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("construction_opened_by", sa.String(length=64), nullable=True))
    op.add_column("tasks", sa.Column("construction_opened_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("construction_closed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "tasks",
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_unique_constraint("uq_tasks_team_legacy_id", "tasks", ["team_id", "legacy_id"])
    op.create_index("ix_tasks_team_terminal", "tasks", ["team_id", "terminal"])
    op.create_index("ix_tasks_team_review_claimed_by", "tasks", ["team_id", "review_claimed_by"])
    op.create_index(
        "uq_tasks_team_construction_claimed_by",
        "tasks",
        ["team_id", "construction_claimed_by"],
        unique=True,
        postgresql_where=sa.text("construction_claimed_by IS NOT NULL"),
    )

    _add_team_fk("material_groups")
    op.alter_column(
        "material_groups",
        "meter_match_key",
        existing_type=sa.String(length=128),
        nullable=True,
    )
    op.add_column("material_groups", sa.Column("legacy_id", sa.String(length=128), nullable=True))
    op.add_column("material_groups", sa.Column("legacy_task_id", sa.Integer(), nullable=True))
    op.add_column("material_groups", sa.Column("terminal", sa.String(length=128), nullable=True))
    op.add_column("material_groups", sa.Column("reviewer", sa.String(length=64), nullable=True))
    op.add_column("material_groups", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column("material_groups", sa.Column("exception_status", sa.String(length=32), nullable=True))
    op.add_column("material_groups", sa.Column("exception_note", sa.Text(), nullable=True))
    op.add_column(
        "material_groups",
        sa.Column("has_archive_blocker", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "material_groups",
        sa.Column("exception_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "material_groups",
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_unique_constraint("uq_material_groups_team_legacy_id", "material_groups", ["team_id", "legacy_id"])
    op.create_index("ix_material_groups_team_terminal_status", "material_groups", ["team_id", "terminal", "status"])
    op.create_index("ix_material_groups_team_task_status", "material_groups", ["team_id", "legacy_task_id", "status"])
    op.create_index(
        "uq_material_groups_team_meter_key_nonempty",
        "material_groups",
        ["team_id", "meter_match_key"],
        unique=True,
        postgresql_where=sa.text("team_id IS NOT NULL AND meter_match_key <> ''"),
    )

    _add_team_fk("photos")
    op.add_column("photos", sa.Column("legacy_id", sa.String(length=128), nullable=True))
    op.add_column("photos", sa.Column("source", sa.String(length=64), nullable=True))
    op.add_column("photos", sa.Column("barcode", sa.String(length=255), nullable=True))
    op.add_column("photos", sa.Column("collector", sa.String(length=255), nullable=True))
    op.add_column("photos", sa.Column("asset_no", sa.String(length=255), nullable=True))
    op.add_column("photos", sa.Column("creator", sa.String(length=128), nullable=True))
    op.add_column("photos", sa.Column("image_url", sa.Text(), nullable=True))
    op.add_column("photos", sa.Column("image_file_id", sa.Text(), nullable=True))
    op.add_column("photos", sa.Column("storage_type", sa.String(length=32), nullable=True))
    op.add_column("photos", sa.Column("storage_bucket", sa.String(length=255), nullable=True))
    op.add_column("photos", sa.Column("storage_key", sa.Text(), nullable=True))
    op.add_column("photos", sa.Column("category", sa.String(length=64), nullable=True))
    op.add_column("photos", sa.Column("archive_status", sa.String(length=32), nullable=True))
    op.add_column("photos", sa.Column("archive_filename", sa.String(length=255), nullable=True))
    op.add_column("photos", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("photos", sa.Column("classified_by", sa.String(length=64), nullable=True))
    op.add_column("photos", sa.Column("classified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("photos", sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("photos", sa.Column("client_batch_id", sa.String(length=128), nullable=True))
    op.add_column("photos", sa.Column("client_photo_id", sa.String(length=128), nullable=True))
    op.add_column(
        "photos",
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_unique_constraint("uq_photos_team_group_legacy_id", "photos", ["team_id", "group_id", "legacy_id"])
    op.create_index("ix_photos_team_group_category", "photos", ["team_id", "group_id", "category"])
    op.create_index("ix_photos_team_storage", "photos", ["team_id", "storage_type", "storage_key"])

    _add_team_fk("review_records")
    op.add_column("review_records", sa.Column("legacy_id", sa.String(length=128), nullable=True))
    op.create_unique_constraint("uq_review_records_team_legacy_id", "review_records", ["team_id", "legacy_id"])
    op.create_index("ix_review_records_team_created", "review_records", ["team_id", "created_at"])

    _add_team_fk("exceptions")

    _add_team_fk("export_jobs")

    _add_team_fk("audit_logs")
    op.add_column("audit_logs", sa.Column("legacy_id", sa.String(length=128), nullable=True))
    op.add_column("audit_logs", sa.Column("actor_username", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_unique_constraint("uq_audit_logs_team_legacy_id", "audit_logs", ["team_id", "legacy_id"])
    op.create_index("ix_audit_logs_team_created", "audit_logs", ["team_id", "created_at"])

    op.create_table(
        "photo_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("legacy_id", sa.String(length=128), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("photo_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("previous_category", sa.String(length=64), nullable=True),
        sa.Column("next_category", sa.String(length=64), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["group_id"], ["material_groups.id"], name="fk_photo_events_group_id_material_groups", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["photo_id"], ["photos.id"], name="fk_photo_events_photo_id_photos", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], name="fk_photo_events_team_id_teams", ondelete="CASCADE"),
        sa.UniqueConstraint("team_id", "legacy_id", name="uq_photo_events_team_legacy_id"),
    )
    op.create_index("ix_photo_events_team_created", "photo_events", ["team_id", "created_at"])

    op.create_table(
        "unmatched_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("team_id", sa.String(length=64), nullable=False),
        sa.Column("legacy_id", sa.String(length=128), nullable=False),
        sa.Column("record_type", sa.String(length=64), nullable=False, server_default="scan"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("terminal", sa.String(length=128), nullable=True),
        sa.Column("meter_no", sa.String(length=128), nullable=True),
        sa.Column("meter_match_key", sa.String(length=128), nullable=True),
        sa.Column("barcode", sa.String(length=255), nullable=True),
        sa.Column("collector", sa.String(length=255), nullable=True),
        sa.Column("module_asset_no", sa.String(length=255), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], name="fk_unmatched_records_team_id_teams", ondelete="CASCADE"),
        sa.UniqueConstraint("team_id", "legacy_id", name="uq_unmatched_records_team_legacy_id"),
    )
    op.create_index("ix_unmatched_records_team_status", "unmatched_records", ["team_id", "status"])

    op.create_table(
        "migration_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_state_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_users_sha256", sa.String(length=64), nullable=False),
        sa.Column("state_path", sa.Text(), nullable=False),
        sa.Column("users_path", sa.Text(), nullable=False),
        sa.Column("counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("migration_runs")
    op.drop_index("ix_unmatched_records_team_status", table_name="unmatched_records")
    op.drop_table("unmatched_records")
    op.drop_index("ix_photo_events_team_created", table_name="photo_events")
    op.drop_table("photo_events")

    op.drop_index("ix_audit_logs_team_created", table_name="audit_logs")
    op.drop_constraint("uq_audit_logs_team_legacy_id", "audit_logs", type_="unique")
    op.drop_column("audit_logs", "payload")
    op.drop_column("audit_logs", "actor_username")
    op.drop_column("audit_logs", "legacy_id")
    op.drop_index("ix_audit_logs_team_id", table_name="audit_logs")
    op.drop_constraint("fk_audit_logs_team_id_teams", "audit_logs", type_="foreignkey")
    op.drop_column("audit_logs", "team_id")

    for table_name in ("export_jobs", "exceptions"):
        op.drop_index(f"ix_{table_name}_team_id", table_name=table_name)
        op.drop_constraint(f"fk_{table_name}_team_id_teams", table_name, type_="foreignkey")
        op.drop_column(table_name, "team_id")

    op.drop_index("ix_review_records_team_created", table_name="review_records")
    op.drop_constraint("uq_review_records_team_legacy_id", "review_records", type_="unique")
    op.drop_column("review_records", "legacy_id")
    op.drop_index("ix_review_records_team_id", table_name="review_records")
    op.drop_constraint("fk_review_records_team_id_teams", "review_records", type_="foreignkey")
    op.drop_column("review_records", "team_id")

    op.drop_index("ix_photos_team_storage", table_name="photos")
    op.drop_index("ix_photos_team_group_category", table_name="photos")
    op.drop_constraint("uq_photos_team_group_legacy_id", "photos", type_="unique")
    for column in (
        "raw_data",
        "client_photo_id",
        "client_batch_id",
        "sort_order",
        "classified_at",
        "classified_by",
        "archived_at",
        "archive_filename",
        "archive_status",
        "category",
        "storage_key",
        "storage_bucket",
        "storage_type",
        "image_file_id",
        "image_url",
        "creator",
        "asset_no",
        "collector",
        "barcode",
        "source",
        "legacy_id",
    ):
        op.drop_column("photos", column)
    op.drop_index("ix_photos_team_id", table_name="photos")
    op.drop_constraint("fk_photos_team_id_teams", "photos", type_="foreignkey")
    op.drop_column("photos", "team_id")

    op.drop_index("uq_material_groups_team_meter_key_nonempty", table_name="material_groups")
    op.drop_index("ix_material_groups_team_task_status", table_name="material_groups")
    op.drop_index("ix_material_groups_team_terminal_status", table_name="material_groups")
    op.drop_constraint("uq_material_groups_team_legacy_id", "material_groups", type_="unique")
    for column in (
        "raw_data",
        "exception_reasons",
        "has_archive_blocker",
        "exception_note",
        "exception_status",
        "review_note",
        "reviewer",
        "terminal",
        "legacy_task_id",
        "legacy_id",
    ):
        op.drop_column("material_groups", column)
    op.drop_index("ix_material_groups_team_id", table_name="material_groups")
    op.drop_constraint("fk_material_groups_team_id_teams", "material_groups", type_="foreignkey")
    op.drop_column("material_groups", "team_id")
    op.drop_index("uq_tasks_team_construction_claimed_by", table_name="tasks")
    op.drop_index("ix_tasks_team_review_claimed_by", table_name="tasks")
    op.drop_index("ix_tasks_team_terminal", table_name="tasks")
    op.drop_constraint("uq_tasks_team_legacy_id", "tasks", type_="unique")
    for column in (
        "raw_data",
        "construction_closed_at",
        "construction_opened_at",
        "construction_opened_by",
        "construction_released_at",
        "construction_claimed_at",
        "construction_claimed_by",
        "construction_enabled",
        "review_claimed_by",
        "terminal",
        "legacy_id",
    ):
        op.drop_column("tasks", column)
    op.drop_index("ix_tasks_team_id", table_name="tasks")
    op.drop_constraint("fk_tasks_team_id_teams", "tasks", type_="foreignkey")
    op.drop_column("tasks", "team_id")

    op.drop_index("ix_stage_catalog_rows_team_id", table_name="stage_catalog_rows")
    op.drop_constraint("fk_stage_catalog_rows_team_id_teams", "stage_catalog_rows", type_="foreignkey")
    op.drop_column("stage_catalog_rows", "team_id")

    op.drop_index("uq_total_catalog_rows_team_meter_key", table_name="total_catalog_rows")
    op.drop_index("ix_total_catalog_rows_team_meter_key", table_name="total_catalog_rows")
    for column in ("installer", "terminal", "source_file"):
        op.drop_column("total_catalog_rows", column)
    op.drop_index("ix_total_catalog_rows_team_id", table_name="total_catalog_rows")
    op.drop_constraint("fk_total_catalog_rows_team_id_teams", "total_catalog_rows", type_="foreignkey")
    op.drop_column("total_catalog_rows", "team_id")

    op.drop_index("ix_import_jobs_team_id", table_name="import_jobs")
    op.drop_constraint("fk_import_jobs_team_id_teams", "import_jobs", type_="foreignkey")
    op.drop_column("import_jobs", "team_id")

    op.drop_index("ix_projects_team_id", table_name="projects")
    op.drop_constraint("fk_projects_team_id_teams", "projects", type_="foreignkey")
    op.drop_column("projects", "team_id")

    op.drop_column("users", "home")
    op.drop_column("users", "name")
    op.drop_index("ix_users_team_id", table_name="users")
    op.drop_constraint("fk_users_team_id_teams", "users", type_="foreignkey")
    op.drop_column("users", "team_id")

    op.drop_table("teams")
