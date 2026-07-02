from __future__ import annotations

from typing import Any

from app.services.platform.persistence import build_platform_persistence_status
from app.services.platform.postgres_design import build_platform_postgres_persistence_design


def _gate_item(
    item_id: str,
    label: str,
    description: str,
    evidence: str,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "label": label,
        "description": description,
        "required": True,
        "status": "blocked",
        "evidence": evidence,
    }


def build_platform_migration_readiness() -> dict[str, Any]:
    persistence_status = build_platform_persistence_status()
    postgres_design = build_platform_postgres_persistence_design()
    target_tables = [
        str(table.get("name") or "")
        for table in postgres_design.get("tables", [])
        if str(table.get("name") or "").strip()
    ]
    database = persistence_status.get("database", {})
    return {
        "readiness_version": 1,
        "scope": "project_config",
        "ready_for_migration": False,
        "requires_user_approval": True,
        "creates_migration": False,
        "target_backend": "postgres_after_approved_migration",
        "target_tables": target_tables,
        "database_configured": bool(database.get("configured")),
        "current_state_backend": persistence_status.get("state_backend", ""),
        "gate_items": [
            _gate_item(
                "backup",
                "备份生产数据库和 JSON 草稿",
                "迁移前必须有已复核的数据库备份，以及当前本地 JSON 草稿备份。",
                "本包不创建迁移备份产物。",
            ),
            _gate_item(
                "dry_run",
                "在恢复数据上 dry-run",
                "Alembic 迁移必须先在恢复副本或预发数据库上演练，再考虑生产执行。",
                "当前还没有 dry-run 结果。",
            ),
            _gate_item(
                "verification",
                "核对行数和 JSON 还原",
                "必须核对项目数量、project_key 唯一性、field_schema JSON 和 workflow_definition JSON。",
                "当前包只提供契约预览，不替代迁移验收。",
            ),
            _gate_item(
                "rollback",
                "回滚路径已演练",
                "必须能关闭 PostgreSQL 读取、保留 JSON fallback，并演练 backup_before_drop。",
                "本包不执行回滚演练。",
            ),
            _gate_item(
                "approval",
                "用户明确审批",
                "迁移方案、dry-run 证据、备份和回滚路径必须由用户明确批准。",
                "本包没有获得迁移执行审批。",
            ),
            _gate_item(
                "cutover_flag",
                "通过开关切换读取",
                "PostgreSQL 读取只能在验收后通过明确开关切换，不能默认启用。",
                "当前故意保持切换关闭。",
            ),
        ],
        "migration_plan": list(postgres_design.get("migration_plan", [])),
        "rollback_plan": list(postgres_design.get("rollback_plan", [])),
        "safety": [
            "read_only_no_write",
            "no_database_connection",
            "no_postgres_schema_change",
            "no_production_data_edit",
            "requires_user_approval_before_migration",
            "json_fallback_required",
        ],
    }
