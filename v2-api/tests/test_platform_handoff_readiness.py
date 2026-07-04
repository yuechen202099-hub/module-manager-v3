from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_platform_handoff_readiness_summarizes_review_package_and_safety() -> None:
    client = TestClient(app)

    response = client.get("/projects/handoff/readiness")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["handoff_version"] == 1
    assert payload["feature_branch"] == "pm-platform/production-3.0.77-sync"
    assert payload["production_baseline"] == {
        "branch": "production/V3/3.0.77",
        "version": "V3.0.77",
    }
    assert payload["ready_for_review_package"] is True
    assert payload["ready_for_production_migration"] is False
    assert payload["ready_for_production_release"] is False

    config_preflight = payload["config_preflight"]
    assert config_preflight["preflight_version"] == 1
    assert "ready_for_config_load" in config_preflight
    assert set(config_preflight["safety"]) >= {
        "read_only_no_write",
        "no_project_draft_load",
        "no_database_connection",
        "no_production_data_edit",
    }

    readiness = payload["project_readiness_summary"]
    assert readiness["readiness_version"] == 1
    assert "total" in readiness
    assert "items" in readiness

    persistence = payload["persistence"]
    assert persistence["status_version"] == 1
    assert persistence["database"]["used_for_platform_project_config"] is False

    migration = payload["migration"]
    assert migration["readiness_version"] == 1
    assert migration["ready_for_migration"] is False
    assert migration["requires_user_approval"] is True
    assert "backup" in {item["id"] for item in migration["gate_items"]}

    assert set(payload["production_safety"]) >= {
        "no_tag",
        "no_deploy",
        "no_official_version_bump",
        "no_production_data_edit",
        "no_oss_mutation",
        "no_postgres_write",
        "requires_pr_or_patch_review",
    }
    assert set(payload["next_actions"]) >= {
        "prepare_pr_or_patch_handoff",
        "review_against_production_baseline",
        "keep_migration_blocked_until_user_approval",
    }
