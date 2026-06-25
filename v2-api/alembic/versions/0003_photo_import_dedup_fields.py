"""photo import dedup and soft delete fields

Revision ID: 20260619_0003
Revises: 20260618_0002
Create Date: 2026-06-19 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260619_0003"
down_revision = "20260618_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("photos", sa.Column("source_url", sa.Text(), nullable=True))
    op.add_column("photos", sa.Column("source_url_hash", sa.String(length=64), nullable=True))
    op.add_column("photos", sa.Column("source_file_id", sa.Text(), nullable=True))
    op.add_column("photos", sa.Column("source_fingerprint", sa.String(length=128), nullable=True))
    op.add_column("photos", sa.Column("import_batch_id", sa.String(length=128), nullable=True))
    op.add_column("photos", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("photos", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("photos", sa.Column("deleted_by", sa.String(length=64), nullable=True))
    op.add_column("photos", sa.Column("delete_reason", sa.Text(), nullable=True))

    op.execute(
        """
        update photos
        set
          source_url = coalesce(image_url, storage_key),
          source_url_hash = encode(digest(coalesce(image_url, storage_key, legacy_id, id::text), 'sha256'), 'hex'),
          source_file_id = image_file_id,
          source_fingerprint = coalesce(
            nullif(image_file_id, ''),
            encode(digest(coalesce(image_url, storage_key, legacy_id, id::text), 'sha256'), 'hex')
          )
        where source_fingerprint is null
        """
    )

    op.create_index("ix_photos_team_active_group", "photos", ["team_id", "group_id", "is_active"])
    op.create_index(
        "ix_photos_team_source_url_hash",
        "photos",
        ["team_id", "source_url_hash"],
        postgresql_where=sa.text("source_url_hash IS NOT NULL AND source_url_hash <> ''"),
    )
    op.create_index(
        "uq_photos_team_group_source_fingerprint_active",
        "photos",
        ["team_id", "group_id", "source_fingerprint"],
        unique=True,
        postgresql_where=sa.text("source_fingerprint IS NOT NULL AND source_fingerprint <> '' AND is_active = true"),
    )


def downgrade() -> None:
    op.drop_index("uq_photos_team_group_source_fingerprint_active", table_name="photos")
    op.drop_index("ix_photos_team_source_url_hash", table_name="photos")
    op.drop_index("ix_photos_team_active_group", table_name="photos")
    for column in (
        "delete_reason",
        "deleted_by",
        "deleted_at",
        "is_active",
        "import_batch_id",
        "source_fingerprint",
        "source_file_id",
        "source_url_hash",
        "source_url",
    ):
        op.drop_column("photos", column)
