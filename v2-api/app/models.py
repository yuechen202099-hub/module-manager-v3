import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ProjectStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class GroupStatus(str, enum.Enum):
    UNREVIEWED = "unreviewed"
    IN_REVIEW = "in_review"
    INCOMPLETE = "incomplete"
    APPROVED = "approved"
    REJECTED = "rejected"


class PhotoUploadStatus(str, enum.Enum):
    PENDING = "pending"
    UPLOADED = "uploaded"
    INVALID = "invalid"


class TaskStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    RELEASED = "released"
    CANCELLED = "cancelled"


class ReviewResult(str, enum.Enum):
    APPROVED = "approved"
    INCOMPLETE = "incomplete"
    REJECTED = "rejected"


class ExceptionStatus(str, enum.Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class ImportJobType(str, enum.Enum):
    TOTAL_CATALOG = "total_catalog"
    STAGE_CATALOG = "stage_catalog"
    SCAN_DATA = "scan_data"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExportJobType(str, enum.Enum):
    TASK_DETAIL = "task_detail"
    FINAL_DELIVERY = "final_delivery"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def uuid_column() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


def pg_enum(enum_class: type[enum.Enum], name: str) -> SAEnum:
    return SAEnum(enum_class, name=name, values_callable=lambda items: [item.value for item in items])


class Team(Base, TimestampMixin):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_column()
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), index=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    home: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[UserStatus] = mapped_column(
        pg_enum(UserStatus, "user_status"), nullable=False, default=UserStatus.ACTIVE
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    roles: Mapped[list["Role"]] = relationship(secondary="user_roles", back_populates="users")


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = uuid_column()
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(255))

    users: Mapped[list[User]] = relationship(secondary="user_roles", back_populates="roles")


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = uuid_column()
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ProjectStatus] = mapped_column(
        pg_enum(ProjectStatus, "project_status"), nullable=False, default=ProjectStatus.DRAFT
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportJob(Base, TimestampMixin):
    __tablename__ = "import_jobs"

    id: Mapped[uuid.UUID] = uuid_column()
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    job_type: Mapped[ImportJobType] = mapped_column(pg_enum(ImportJobType, "import_job_type"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"), nullable=False, default=JobStatus.PENDING
    )
    file_name: Mapped[str | None] = mapped_column(String(255))
    object_key: Mapped[str | None] = mapped_column(String(512))
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TotalCatalogRow(Base, TimestampMixin):
    __tablename__ = "total_catalog_rows"
    __table_args__ = (
        Index("ix_total_catalog_rows_project_meter_key", "project_id", "meter_match_key"),
        Index("ix_total_catalog_rows_team_meter_key", "team_id", "meter_match_key"),
    )

    id: Mapped[uuid.UUID] = uuid_column()
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    import_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("import_jobs.id", ondelete="SET NULL"))
    source_file: Mapped[str | None] = mapped_column(String(255))
    source_row_number: Mapped[int | None] = mapped_column(Integer)
    terminal: Mapped[str | None] = mapped_column(String(128))
    installer: Mapped[str | None] = mapped_column(String(128))
    original_meter_no: Mapped[str] = mapped_column(String(128), nullable=False)
    meter_match_key: Mapped[str] = mapped_column(String(128), nullable=False)
    installation_address: Mapped[str] = mapped_column(Text, nullable=False)
    customer_name: Mapped[str | None] = mapped_column(String(128))
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class StageCatalogRow(Base, TimestampMixin):
    __tablename__ = "stage_catalog_rows"
    __table_args__ = (Index("ix_stage_catalog_rows_project_meter_key", "project_id", "meter_match_key"),)

    id: Mapped[uuid.UUID] = uuid_column()
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    import_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("import_jobs.id", ondelete="SET NULL"))
    source_row_number: Mapped[int | None] = mapped_column(Integer)
    stage_name: Mapped[str | None] = mapped_column(String(128))
    terminal_no: Mapped[str | None] = mapped_column(String(128))
    original_barcode: Mapped[str] = mapped_column(String(255), nullable=False)
    meter_match_key: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("team_id", "legacy_id", name="uq_tasks_team_legacy_id"),
        Index("ix_tasks_project_status", "project_id", "status"),
        Index("ix_tasks_team_terminal", "team_id", "terminal"),
        Index("ix_tasks_team_review_claimed_by", "team_id", "review_claimed_by"),
    )

    id: Mapped[uuid.UUID] = uuid_column()
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    legacy_id: Mapped[int | None] = mapped_column(Integer)
    terminal: Mapped[str | None] = mapped_column(String(128))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        pg_enum(TaskStatus, "task_status"), nullable=False, default=TaskStatus.DRAFT
    )
    claimed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    review_claimed_by: Mapped[str | None] = mapped_column(String(64))
    published_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    construction_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    construction_claimed_by: Mapped[str | None] = mapped_column(String(64))
    construction_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    construction_released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    construction_opened_by: Mapped[str | None] = mapped_column(String(64))
    construction_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    construction_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class MaterialGroup(Base, TimestampMixin):
    __tablename__ = "material_groups"
    __table_args__ = (
        UniqueConstraint("project_id", "meter_match_key", name="uq_material_groups_project_meter_key"),
        UniqueConstraint("team_id", "legacy_id", name="uq_material_groups_team_legacy_id"),
        Index("ix_material_groups_project_meter_key", "project_id", "meter_match_key"),
        Index("ix_material_groups_team_terminal_status", "team_id", "terminal", "status"),
        Index("ix_material_groups_team_task_status", "team_id", "legacy_task_id", "status"),
        Index("ix_material_groups_task_status", "task_id", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_column()
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    legacy_id: Mapped[str | None] = mapped_column(String(128))
    legacy_task_id: Mapped[int | None] = mapped_column(Integer)
    terminal: Mapped[str | None] = mapped_column(String(128))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    total_catalog_row_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("total_catalog_rows.id", ondelete="SET NULL")
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    meter_match_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    display_meter_no: Mapped[str] = mapped_column(String(128), nullable=False)
    installation_address: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[GroupStatus] = mapped_column(
        pg_enum(GroupStatus, "group_status"), nullable=False, default=GroupStatus.UNREVIEWED
    )
    photo_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewer: Mapped[str | None] = mapped_column(String(64))
    review_note: Mapped[str | None] = mapped_column(Text)
    exception_status: Mapped[str | None] = mapped_column(String(32))
    exception_note: Mapped[str | None] = mapped_column(Text)
    has_archive_blocker: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    exception_reasons: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_photo_imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Photo(Base, TimestampMixin):
    __tablename__ = "photos"
    __table_args__ = (
        UniqueConstraint("team_id", "group_id", "legacy_id", name="uq_photos_team_group_legacy_id"),
        UniqueConstraint("group_id", "sha256", name="uq_photos_group_sha256"),
        Index("ix_photos_team_group_category", "team_id", "group_id", "category"),
        Index("ix_photos_team_active_group", "team_id", "group_id", "is_active"),
        Index(
            "uq_photos_team_group_source_fingerprint_active",
            "team_id",
            "group_id",
            "source_fingerprint",
            unique=True,
            postgresql_where=text("source_fingerprint IS NOT NULL AND source_fingerprint <> '' AND is_active = true"),
        ),
        Index(
            "ix_photos_team_source_url_hash",
            "team_id",
            "source_url_hash",
            postgresql_where=text("source_url_hash IS NOT NULL AND source_url_hash <> ''"),
        ),
        Index("ix_photos_team_storage", "team_id", "storage_type", "storage_key"),
        Index("ix_photos_group_sha256", "group_id", "sha256"),
    )

    id: Mapped[uuid.UUID] = uuid_column()
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    legacy_id: Mapped[str | None] = mapped_column(String(128))
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("material_groups.id", ondelete="CASCADE"), nullable=False)
    import_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("import_jobs.id", ondelete="SET NULL"))
    source: Mapped[str | None] = mapped_column(String(64))
    barcode: Mapped[str | None] = mapped_column(String(255))
    collector: Mapped[str | None] = mapped_column(String(255))
    asset_no: Mapped[str | None] = mapped_column(String(255))
    creator: Mapped[str | None] = mapped_column(String(128))
    image_url: Mapped[str | None] = mapped_column(Text)
    image_file_id: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_url_hash: Mapped[str | None] = mapped_column(String(64))
    source_file_id: Mapped[str | None] = mapped_column(Text)
    source_fingerprint: Mapped[str | None] = mapped_column(String(128))
    import_batch_id: Mapped[str | None] = mapped_column(String(128))
    storage_type: Mapped[str | None] = mapped_column(String(32))
    storage_bucket: Mapped[str | None] = mapped_column(String(255))
    storage_key: Mapped[str | None] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(100))
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    upload_status: Mapped[PhotoUploadStatus] = mapped_column(
        pg_enum(PhotoUploadStatus, "photo_upload_status"),
        nullable=False,
        default=PhotoUploadStatus.UPLOADED,
    )
    category: Mapped[str | None] = mapped_column(String(64))
    archive_status: Mapped[str | None] = mapped_column(String(32))
    archive_filename: Mapped[str | None] = mapped_column(String(255))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    classified_by: Mapped[str | None] = mapped_column(String(64))
    classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    client_batch_id: Mapped[str | None] = mapped_column(String(128))
    client_photo_id: Mapped[str | None] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[str | None] = mapped_column(String(64))
    delete_reason: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class TaskGroup(Base, TimestampMixin):
    __tablename__ = "task_groups"
    __table_args__ = (
        UniqueConstraint("task_id", "group_id", name="uq_task_groups_task_group"),
        Index("ix_task_groups_task_group", "task_id", "group_id"),
    )

    id: Mapped[uuid.UUID] = uuid_column()
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("material_groups.id", ondelete="CASCADE"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ReviewRecord(Base, TimestampMixin):
    __tablename__ = "review_records"
    __table_args__ = (
        UniqueConstraint("team_id", "legacy_id", name="uq_review_records_team_legacy_id"),
        Index("ix_review_records_team_created", "team_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_column()
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    legacy_id: Mapped[str | None] = mapped_column(String(128))
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("material_groups.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    result: Mapped[ReviewResult] = mapped_column(pg_enum(ReviewResult, "review_result"), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(32))
    next_status: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class ExceptionItem(Base, TimestampMixin):
    __tablename__ = "exceptions"

    id: Mapped[uuid.UUID] = uuid_column()
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("material_groups.id", ondelete="SET NULL"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    reporter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ExceptionStatus] = mapped_column(
        pg_enum(ExceptionStatus, "exception_status"), nullable=False, default=ExceptionStatus.OPEN
    )
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExportJob(Base, TimestampMixin):
    __tablename__ = "export_jobs"

    id: Mapped[uuid.UUID] = uuid_column()
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    job_type: Mapped[ExportJobType] = mapped_column(pg_enum(ExportJobType, "export_job_type"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"), nullable=False, default=JobStatus.PENDING
    )
    object_key: Mapped[str | None] = mapped_column(String(512))
    file_name: Mapped[str | None] = mapped_column(String(255))
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        UniqueConstraint("team_id", "legacy_id", name="uq_audit_logs_team_legacy_id"),
        Index("ix_audit_logs_team_created", "team_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_column()
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    legacy_id: Mapped[str | None] = mapped_column(String(128))
    actor_username: Mapped[str | None] = mapped_column(String(64))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    request_id: Mapped[str | None] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    before_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PhotoEvent(Base):
    __tablename__ = "photo_events"
    __table_args__ = (
        UniqueConstraint("team_id", "legacy_id", name="uq_photo_events_team_legacy_id"),
        Index("ix_photo_events_team_created", "team_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_column()
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    legacy_id: Mapped[str] = mapped_column(String(128), nullable=False)
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("material_groups.id", ondelete="SET NULL"))
    photo_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("photos.id", ondelete="SET NULL"))
    actor: Mapped[str | None] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_category: Mapped[str | None] = mapped_column(String(64))
    next_category: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UnmatchedRecord(Base, TimestampMixin):
    __tablename__ = "unmatched_records"
    __table_args__ = (
        UniqueConstraint("team_id", "legacy_id", name="uq_unmatched_records_team_legacy_id"),
        Index("ix_unmatched_records_team_status", "team_id", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_column()
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    legacy_id: Mapped[str] = mapped_column(String(128), nullable=False)
    record_type: Mapped[str] = mapped_column(String(64), nullable=False, default="scan")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    terminal: Mapped[str | None] = mapped_column(String(128))
    meter_no: Mapped[str | None] = mapped_column(String(128))
    meter_match_key: Mapped[str | None] = mapped_column(String(128))
    barcode: Mapped[str | None] = mapped_column(String(255))
    collector: Mapped[str | None] = mapped_column(String(255))
    module_asset_no: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class MigrationRun(Base):
    __tablename__ = "migration_runs"

    id: Mapped[uuid.UUID] = uuid_column()
    source_state_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_users_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state_path: Mapped[str] = mapped_column(Text, nullable=False)
    users_path: Mapped[str] = mapped_column(Text, nullable=False)
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
