from __future__ import annotations

from typing import Any


def _column(
    name: str,
    column_type: str,
    *,
    nullable: bool = False,
    default: str = "",
    references: str = "",
) -> dict[str, Any]:
    column: dict[str, Any] = {
        "name": name,
        "type": column_type,
        "nullable": nullable,
    }
    if default:
        column["default"] = default
    if references:
        column["references"] = references
    return column


def _index(name: str, columns: list[str], *, unique: bool = False) -> dict[str, Any]:
    return {
        "name": name,
        "columns": columns,
        "unique": unique,
    }


def build_platform_postgres_persistence_design() -> dict[str, Any]:
    return {
        "contract_version": 1,
        "scope": "project_config",
        "creates_migration": False,
        "tables": [
            {
                "name": "platform_project_configs",
                "purpose": "Durable PM platform project definitions, field schemas, and workflow definitions.",
                "primary_key": ["id"],
                "columns": [
                    _column("id", "uuid", default="gen_random_uuid()"),
                    _column("team_id", "text", references="teams.id"),
                    _column("project_key", "text"),
                    _column("name", "text"),
                    _column("status", "text", default="'draft'"),
                    _column("adapter", "text", default="'platform'"),
                    _column("module_ids", "jsonb", default="'[]'::jsonb"),
                    _column("description", "text", default="''"),
                    _column("field_schema", "jsonb", default="'{}'::jsonb"),
                    _column("workflow_definition", "jsonb", default="'{}'::jsonb"),
                    _column("created_at", "timestamptz", default="now()"),
                    _column("updated_at", "timestamptz", default="now()"),
                    _column("created_by", "text", nullable=True),
                    _column("updated_by", "text", nullable=True),
                ],
                "constraints": [
                    {
                        "name": "ck_platform_project_configs_status",
                        "type": "check",
                        "expression": "status in ('draft', 'active', 'archived')",
                    },
                    {
                        "name": "fk_platform_project_configs_team_id_teams",
                        "type": "foreign_key",
                        "columns": ["team_id"],
                        "references": "teams.id",
                        "on_delete": "CASCADE",
                    },
                ],
                "indexes": [
                    _index("uq_platform_project_configs_team_project_key", ["team_id", "project_key"], unique=True),
                    _index("ix_platform_project_configs_team_status", ["team_id", "status"]),
                    _index("ix_platform_project_configs_updated_at", ["updated_at"]),
                ],
            },
            {
                "name": "platform_project_config_events",
                "purpose": "Append-only audit trail for field schema and workflow definition changes.",
                "primary_key": ["id"],
                "columns": [
                    _column("id", "uuid", default="gen_random_uuid()"),
                    _column("team_id", "text", references="teams.id"),
                    _column("config_id", "uuid", references="platform_project_configs.id"),
                    _column("event_type", "text"),
                    _column("actor", "text", nullable=True),
                    _column("before_data", "jsonb", nullable=True),
                    _column("after_data", "jsonb", nullable=True),
                    _column("created_at", "timestamptz", default="now()"),
                ],
                "constraints": [
                    {
                        "name": "fk_platform_project_config_events_team_id_teams",
                        "type": "foreign_key",
                        "columns": ["team_id"],
                        "references": "teams.id",
                        "on_delete": "CASCADE",
                    },
                    {
                        "name": "fk_platform_project_config_events_config_id_configs",
                        "type": "foreign_key",
                        "columns": ["config_id"],
                        "references": "platform_project_configs.id",
                        "on_delete": "CASCADE",
                    },
                ],
                "indexes": [
                    _index("ix_platform_project_config_events_config_created", ["config_id", "created_at"]),
                    _index("ix_platform_project_config_events_team_created", ["team_id", "created_at"]),
                ],
            },
        ],
        "migration_plan": [
            "backup production database and current local JSON stores before migration",
            "dry-run Alembic migration against a restored copy or staging database",
            "create new tables and indexes without changing read paths",
            "backfill platform_project_configs from platform-project-drafts.json",
            "verify project counts, project_key uniqueness, field_schema JSON, and workflow_definition JSON",
            "cutover reads behind an explicit feature flag after user approval",
        ],
        "rollback_plan": [
            "disable_postgres_reads and force json_fallback for platform project config",
            "keep JSON fallback files unchanged until production acceptance completes",
            "export platform_project_configs and platform_project_config_events before rollback",
            "backup_before_drop, then drop new tables only after explicit user approval",
        ],
        "safety": [
            "requires_user_approval_before_migration",
            "no_alembic_file_created_in_this_package",
            "no_database_connection",
            "no_production_data_edit",
            "json_fallback_required",
        ],
    }

