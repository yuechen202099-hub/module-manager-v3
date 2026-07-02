from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    templates_source = (ROOT / "v2-api" / "app" / "services" / "platform" / "templates.py").read_text(encoding="utf-8")
    catalog_source = (ROOT / "v2-api" / "app" / "services" / "platform" / "catalog.py").read_text(encoding="utf-8")
    test_source = (ROOT / "v2-api" / "tests" / "test_api.py").read_text(encoding="utf-8")

    checks = [
        (
            "def summarize_platform_work_orders" in templates_source
            and '"total": total' in templates_source
            and "_PLATFORM_WORK_ORDERS" in templates_source,
            "Platform work order service must expose a read-only summary helper.",
        ),
        (
            "summarize_platform_work_orders" in catalog_source
            and 'sections["tasks"]["total"] = total' in catalog_source
            and 'sections["delivery"]["total_items"] = total' in catalog_source
            and 'sections["field"]["unconstructed_groups"]' in catalog_source,
            "Draft project overview must use local platform work order counts.",
        ),
        (
            "return _empty_sections()[section]" not in catalog_source
            and "overview = get_project_overview(project_id)" in catalog_source,
            "Draft project module sections must be derived from project overview, not empty sections.",
        ),
        (
            "test_project_overview_counts_local_platform_work_orders_after_execution" in test_source
            and 'tasks.json()["data"]["total"] == 4' in test_source
            and 'tasks.json()["data"]["uploaded"] == 3' in test_source,
            "API tests must cover project overview and module task counts after local execution.",
        ),
    ]

    failures = [message for ok, message in checks if not ok]
    if failures:
        for message in failures:
            print(message)
        raise SystemExit(1)
    print("[OK] Local platform work orders feed draft project dashboard summaries.")


if __name__ == "__main__":
    main()
