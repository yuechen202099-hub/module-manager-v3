from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "v2-api"
sys.path.insert(0, str(API_ROOT))

from app.schemas.project import ProjectWorkItemSchemaCreate  # noqa: E402
from app.services.platform.catalog import _normalize_work_item_schema  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def metric_map(metrics: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(metric.get("key") or ""): metric for metric in metrics if isinstance(metric, dict)}


def assert_metric_object_list(metrics: Any, message: str) -> list[dict[str, Any]]:
    require(isinstance(metrics, list) and metrics, f"{message}: metrics must be a non-empty list")
    require(all(isinstance(metric, dict) for metric in metrics), f"{message}: metrics must be objects")
    require(all(str(metric.get("key") or "").strip() for metric in metrics), f"{message}: metric key is required")
    require(all(str(metric.get("label") or "").strip() for metric in metrics), f"{message}: metric label is required")
    return metrics


def main() -> None:
    default_schema = _normalize_work_item_schema(None)
    default_metrics = assert_metric_object_list(default_schema.get("dashboard_metrics"), "default schema")
    require(
        "total_work_orders" in metric_map(default_metrics),
        "default metrics must keep total_work_orders as an object key",
    )

    create_schema_payload = {
        "primary_field": {"key": "terminal_no", "label": "Terminal", "source": "import"},
        "aggregate_field": {"key": "station_area", "label": "Station area", "source": "import"},
        "custom_fields": [
            {
                "key": "communication_module",
                "label": "Communication module",
                "source": "field_collection",
                "capture_method": "scan",
                "parent_key": "terminal_no",
                "relation_role": "accessory_new_device",
            }
        ],
        "dashboard_metrics": [
            {
                "key": "station_completion_rate",
                "label": "Station completion rate",
                "source": "field_schema",
                "scope": "progress",
            },
            {
                "key": "accessory_replacement_gap",
                "label": "Accessory replacement gap",
                "source": "review",
                "scope": "quality",
            },
        ],
    }
    validated_payload = ProjectWorkItemSchemaCreate.model_validate(create_schema_payload).model_dump()
    require(
        "dashboard_metrics" in validated_payload,
        "API schema model must accept dashboard_metrics from project configuration requests",
    )

    create_schema = _normalize_work_item_schema(validated_payload)
    create_metrics = assert_metric_object_list(create_schema.get("dashboard_metrics"), "created schema")
    created_by_key = metric_map(create_metrics)
    require(
        created_by_key.get("station_completion_rate", {}).get("label") == "Station completion rate",
        "created schema must preserve custom metric label",
    )
    require(
        created_by_key.get("accessory_replacement_gap", {}).get("scope") == "quality",
        "created schema must preserve custom metric scope",
    )

    update_payload = dict(create_schema_payload)
    update_payload["dashboard_metrics"] = [
        *create_schema_payload["dashboard_metrics"],
        {
            "key": "photo_review_exception_rate",
            "label": "Photo review exception rate",
            "source": "review",
            "scope": "quality",
        },
    ]
    update_validated_payload = ProjectWorkItemSchemaCreate.model_validate(update_payload).model_dump()
    update_schema = _normalize_work_item_schema(update_validated_payload)
    update_metrics = assert_metric_object_list(update_schema.get("dashboard_metrics"), "updated schema")
    updated_by_key = metric_map(update_metrics)
    require(
        updated_by_key.get("photo_review_exception_rate", {}).get("source") == "review",
        "updated schema must preserve newly added metric source",
    )

    print("OK: platform dashboard metrics schema contract is preserved")


if __name__ == "__main__":
    main()
