"""initial PostgreSQL schema

Revision ID: 20260609_0001
Revises:
Create Date: 2026-06-09 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260609_0001"
down_revision = None
branch_labels = None
depends_on = None


user_status = postgresql.ENUM("active", "disabled", name="user_status")
project_status = postgresql.ENUM("draft", "active", "archived", name="project_status")
group_status = postgresql.ENUM("unreviewed", "in_review", "incomplete", "approved", "rejected", name="group_status")
photo_upload_status = postgresql.ENUM("pending", "uploaded", "invalid", name="photo_upload_status")
task_status = postgresql.ENUM("draft", "published", "claimed", "completed", "released", "cancelled", name="task_status")
review_result = postgresql.ENUM("approved", "incomplete", "rejected", name="review_result")
exception_status = postgresql.ENUM("open", "resolved", "cancelled", name="exception_status")
import_job_type = postgresql.ENUM("total_catalog", "stage_catalog", "scan_data", name="import_job_type")
job_status = postgresql.ENUM("pending", "running", "succeeded", "failed", "cancelled", name="job_status")
export_job_type = postgresql.ENUM("task_detail", "final_delivery", name="export_job_type")


def uuid_pk() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    for enum_type in (
        user_status,
        project_status,
        group_status,
        photo_upload_status,
        task_status,
        review_result,
        exception_status,
        import_job_type,
        job_status,
        export_job_type,
    ):
        enum_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        uuid_pk(),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("status", user_status, nullable=False, server_default="active"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )

    op.create_table(
        "roles",
        uuid_pk(),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        *timestamps(),
        sa.UniqueConstraint("name", name="uq_roles_name"),
    )

    op.create_table(
        "user_roles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name="fk_user_roles_role_id_roles", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_roles_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "role_id", name="pk_user_roles"),
    )

    op.create_table(
        "projects",
        uuid_pk(),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", project_status, nullable=False, server_default="draft"),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_projects_owner_id_users", ondelete="SET NULL"),
        sa.UniqueConstraint("code", name="uq_projects_code"),
    )

    op.create_table(
        "import_jobs",
        uuid_pk(),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", import_job_type, nullable=False),
        sa.Column("status", job_status, nullable=False, server_default="pending"),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("object_key", sa.String(length=512), nullable=True),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], name="fk_import_jobs_created_by_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_import_jobs_project_id_projects", ondelete="CASCADE"),
    )
    op.create_index("ix_import_jobs_project_status", "import_jobs", ["project_id", "status"])

    op.create_table(
        "total_catalog_rows",
        uuid_pk(),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("import_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_row_number", sa.Integer(), nullable=True),
        sa.Column("original_meter_no", sa.String(length=128), nullable=False),
        sa.Column("meter_match_key", sa.String(length=128), nullable=False),
        sa.Column("installation_address", sa.Text(), nullable=False),
        sa.Column("customer_name", sa.String(length=128), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *timestamps(),
        sa.ForeignKeyConstraint(["import_job_id"], ["import_jobs.id"], name="fk_total_catalog_rows_import_job_id_import_jobs", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_total_catalog_rows_project_id_projects", ondelete="CASCADE"),
    )
    op.create_index("ix_total_catalog_rows_project_meter_key", "total_catalog_rows", ["project_id", "meter_match_key"])

    op.create_table(
        "stage_catalog_rows",
        uuid_pk(),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("import_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_row_number", sa.Integer(), nullable=True),
        sa.Column("stage_name", sa.String(length=128), nullable=True),
        sa.Column("terminal_no", sa.String(length=128), nullable=True),
        sa.Column("original_barcode", sa.String(length=255), nullable=False),
        sa.Column("meter_match_key", sa.String(length=128), nullable=False),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *timestamps(),
        sa.ForeignKeyConstraint(["import_job_id"], ["import_jobs.id"], name="fk_stage_catalog_rows_import_job_id_import_jobs", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_stage_catalog_rows_project_id_projects", ondelete="CASCADE"),
    )
    op.create_index("ix_stage_catalog_rows_project_meter_key", "stage_catalog_rows", ["project_id", "meter_match_key"])

    op.create_table(
        "tasks",
        uuid_pk(),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", task_status, nullable=False, server_default="draft"),
        sa.Column("claimed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("published_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["claimed_by_id"], ["users.id"], name="fk_tasks_claimed_by_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_tasks_project_id_projects", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["published_by_id"], ["users.id"], name="fk_tasks_published_by_id_users", ondelete="SET NULL"),
    )
    op.create_index("ix_tasks_project_status", "tasks", ["project_id", "status"])

    op.create_table(
        "material_groups",
        uuid_pk(),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("total_catalog_row_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("meter_match_key", sa.String(length=128), nullable=False),
        sa.Column("display_meter_no", sa.String(length=128), nullable=False),
        sa.Column("installation_address", sa.Text(), nullable=False),
        sa.Column("status", group_status, nullable=False, server_default="unreviewed"),
        sa.Column("photo_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reviewed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_photo_imported_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_material_groups_project_id_projects", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], name="fk_material_groups_reviewed_by_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name="fk_material_groups_task_id_tasks", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["total_catalog_row_id"], ["total_catalog_rows.id"], name="fk_material_groups_total_catalog_row_id_total_catalog_rows", ondelete="SET NULL"),
        sa.UniqueConstraint("project_id", "meter_match_key", name="uq_material_groups_project_meter_key"),
    )
    op.create_index("ix_material_groups_project_meter_key", "material_groups", ["project_id", "meter_match_key"])
    op.create_index("ix_material_groups_task_status", "material_groups", ["task_id", "status"])

    op.create_table(
        "photos",
        uuid_pk(),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("import_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("upload_status", photo_upload_status, nullable=False, server_default="uploaded"),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *timestamps(),
        sa.ForeignKeyConstraint(["group_id"], ["material_groups.id"], name="fk_photos_group_id_material_groups", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["import_job_id"], ["import_jobs.id"], name="fk_photos_import_job_id_import_jobs", ondelete="SET NULL"),
        sa.UniqueConstraint("group_id", "sha256", name="uq_photos_group_sha256"),
    )
    op.create_index("ix_photos_group_sha256", "photos", ["group_id", "sha256"])

    op.create_table(
        "task_groups",
        uuid_pk(),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        *timestamps(),
        sa.ForeignKeyConstraint(["group_id"], ["material_groups.id"], name="fk_task_groups_group_id_material_groups", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name="fk_task_groups_task_id_tasks", ondelete="CASCADE"),
        sa.UniqueConstraint("task_id", "group_id", name="uq_task_groups_task_group"),
    )
    op.create_index("ix_task_groups_task_group", "task_groups", ["task_id", "group_id"])

    op.create_table(
        "review_records",
        uuid_pk(),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("result", review_result, nullable=False),
        sa.Column("previous_status", sa.String(length=32), nullable=True),
        sa.Column("next_status", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *timestamps(),
        sa.ForeignKeyConstraint(["group_id"], ["material_groups.id"], name="fk_review_records_group_id_material_groups", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"], name="fk_review_records_reviewer_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name="fk_review_records_task_id_tasks", ondelete="SET NULL"),
    )
    op.create_index("ix_review_records_group_created", "review_records", ["group_id", "created_at"])

    op.create_table(
        "exceptions",
        uuid_pk(),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reporter_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", exception_status, nullable=False, server_default="open"),
        sa.Column("resolved_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["group_id"], ["material_groups.id"], name="fk_exceptions_group_id_material_groups", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_exceptions_project_id_projects", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"], name="fk_exceptions_reporter_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by_id"], ["users.id"], name="fk_exceptions_resolved_by_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name="fk_exceptions_task_id_tasks", ondelete="SET NULL"),
    )
    op.create_index("ix_exceptions_project_status", "exceptions", ["project_id", "status"])

    op.create_table(
        "export_jobs",
        uuid_pk(),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", export_job_type, nullable=False),
        sa.Column("status", job_status, nullable=False, server_default="pending"),
        sa.Column("object_key", sa.String(length=512), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], name="fk_export_jobs_created_by_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_export_jobs_project_id_projects", ondelete="CASCADE"),
    )
    op.create_index("ix_export_jobs_project_status", "export_jobs", ["project_id", "status"])

    op.create_table(
        "audit_logs",
        uuid_pk(),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("before_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], name="fk_audit_logs_actor_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_audit_logs_project_id_projects", ondelete="SET NULL"),
    )
    op.create_index("ix_audit_logs_project_created", "audit_logs", ["project_id", "created_at"])
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"])


def downgrade() -> None:
    for table_name in (
        "audit_logs",
        "export_jobs",
        "exceptions",
        "review_records",
        "task_groups",
        "photos",
        "material_groups",
        "tasks",
        "stage_catalog_rows",
        "total_catalog_rows",
        "import_jobs",
        "projects",
        "user_roles",
        "roles",
        "users",
    ):
        op.drop_table(table_name)

    for enum_type in (
        export_job_type,
        job_status,
        import_job_type,
        exception_status,
        review_result,
        task_status,
        photo_upload_status,
        group_status,
        project_status,
        user_status,
    ):
        enum_type.drop(op.get_bind(), checkfirst=True)
