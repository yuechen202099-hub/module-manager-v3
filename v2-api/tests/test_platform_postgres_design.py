from __future__ import annotations

from app.services.platform.postgres_design import build_platform_postgres_persistence_design


def test_platform_postgres_persistence_design_covers_schema_workflow_slice() -> None:
    design = build_platform_postgres_persistence_design()

    assert design["contract_version"] == 1
    assert design["scope"] == "project_config"
    assert design["creates_migration"] is False
    assert "requires_user_approval_before_migration" in design["safety"]

    tables = {table["name"]: table for table in design["tables"]}
    assert set(tables) == {"platform_project_configs", "platform_project_config_events"}

    config_table = tables["platform_project_configs"]
    config_columns = {column["name"]: column for column in config_table["columns"]}
    assert config_table["primary_key"] == ["id"]
    assert config_columns["team_id"]["type"] == "text"
    assert config_columns["project_key"]["type"] == "text"
    assert config_columns["field_schema"]["type"] == "jsonb"
    assert config_columns["workflow_definition"]["type"] == "jsonb"
    assert config_columns["created_at"]["type"] == "timestamptz"
    assert config_columns["updated_at"]["type"] == "timestamptz"

    config_indexes = {index["name"]: index for index in config_table["indexes"]}
    assert config_indexes["ix_platform_project_configs_team_status"]["columns"] == ["team_id", "status"]
    assert config_indexes["ix_platform_project_configs_updated_at"]["columns"] == ["updated_at"]
    assert config_indexes["uq_platform_project_configs_team_project_key"]["unique"] is True
    assert config_indexes["uq_platform_project_configs_team_project_key"]["columns"] == ["team_id", "project_key"]

    event_table = tables["platform_project_config_events"]
    event_columns = {column["name"]: column for column in event_table["columns"]}
    assert event_table["primary_key"] == ["id"]
    assert event_columns["config_id"]["references"] == "platform_project_configs.id"
    event_indexes = {index["name"]: index for index in event_table["indexes"]}
    assert event_indexes["ix_platform_project_config_events_config_created"]["columns"] == ["config_id", "created_at"]
    assert event_indexes["ix_platform_project_config_events_team_created"]["columns"] == ["team_id", "created_at"]

    migration_plan = " ".join(design["migration_plan"])
    rollback_plan = " ".join(design["rollback_plan"])
    for token in ("backup", "dry-run", "backfill", "verify", "cutover"):
        assert token in migration_plan
    for token in ("disable_postgres_reads", "json_fallback", "backup_before_drop"):
        assert token in rollback_plan

