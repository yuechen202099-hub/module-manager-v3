from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def contains_all(text: str, values: list[str], context: str) -> None:
    missing = [value for value in values if value not in text]
    ensure(not missing, f"{context} missing: {', '.join(missing)}")


def main() -> None:
    exports_view = read("v2-web/src/views/ExportsView.vue")
    static_pages = read("v2-web/src/router/staticPages.ts")
    router_index = read("v2-web/src/router/index.ts")
    services = read("v2-web/src/api/services.ts")
    types = read("v2-web/src/api/types.ts")

    query_composable_path = ROOT / "v2-web/src/composables/useExportCenterQuery.ts"
    terminal_tab_path = ROOT / "v2-web/src/components/export-center/TerminalDeliveryTab.vue"
    catalog_tab_path = ROOT / "v2-web/src/components/export-center/ExportCatalogTab.vue"
    jobs_table_path = ROOT / "v2-web/src/components/export-center/ExportJobsTable.vue"

    ensure(query_composable_path.exists(), "missing useExportCenterQuery.ts")
    ensure(terminal_tab_path.exists(), "missing TerminalDeliveryTab.vue")
    ensure(catalog_tab_path.exists(), "missing ExportCatalogTab.vue")
    ensure(jobs_table_path.exists(), "missing ExportJobsTable.vue")

    query_composable = query_composable_path.read_text(encoding="utf-8")
    terminal_tab = terminal_tab_path.read_text(encoding="utf-8")
    catalog_tab = catalog_tab_path.read_text(encoding="utf-8")
    jobs_table = jobs_table_path.read_text(encoding="utf-8")

    contains_all(
        exports_view,
        ["终端交付", "设备清单", "业务清单", "统计报表"],
        "ExportsView tabs",
    )
    ensure("page-sizes" in exports_view or "EXPORT_CENTER_PAGE_SIZES" in exports_view, "ExportsView missing page-size control")
    ensure("el-tabs" in exports_view, "ExportsView must render tabs")

    contains_all(
        static_pages,
        ["'exports'", "routePath: '/exports'", "roles: ['admin']"],
        "staticPages exports route",
    )
    contains_all(
        router_index,
        ["'exports': () => import('@/views/ExportsView.vue')", "name: page.key"],
        "router exports view mapping",
    )

    contains_all(
        query_composable,
        ["EXPORT_CENTER_PAGE_SIZES", "tab", "page_size", "router.replace", "AbortController", "requestSerial"],
        "useExportCenterQuery",
    )
    contains_all(
        query_composable,
        ["terminal_page", "terminal_page_size", "job_page", "job_page_size"],
        "useExportCenterQuery dual pagination URL keys",
    )
    ensure("50" in query_composable and "100" in query_composable, "useExportCenterQuery missing supported page sizes")
    ensure("Number.isFinite" in query_composable, "useExportCenterQuery must strictly parse page numbers")
    ensure("MAX_EXPORT_CENTER_PAGE" in query_composable, "useExportCenterQuery missing page upper bound")
    ensure("pageSize: 100" not in query_composable, "useExportCenterQuery must not hard-code history fetch to page 1 size 100")
    ensure(
        "fetchExportJobs({" in query_composable and "category:" in query_composable,
        "useExportCenterQuery must request server-side job filters",
    )
    ensure(
        "terminalRequestSerial" in query_composable and "jobsRequestSerial" in query_composable,
        "useExportCenterQuery must track stale terminal/job requests independently",
    )
    ensure(
        "terminalController" in query_composable and "jobsController" in query_composable,
        "useExportCenterQuery must abort terminal/job requests independently",
    )

    contains_all(terminal_tab, ["阻断", "最近生成", "操作", "blockers", "latestGeneratedAt"], "TerminalDeliveryTab")
    ensure(
        "final_delivery" in exports_view or "final_delivery" in services,
        "final_delivery launch flow missing",
    )
    contains_all(
        f"{exports_view}\n{catalog_tab}\n{services}",
        ["device_terminal", "device_meter", "device_module", "device_collector"],
        "device export jobs",
    )
    contains_all(
        jobs_table,
        ["jobType", "rowCount", "createdBy", "createdAt", "status", "errorMessage"],
        "ExportJobsTable fields",
    )
    ensure(
        "el-tooltip" in terminal_tab and "el-tooltip" in jobs_table and ("下载" in jobs_table or "download" in jobs_table),
        "tooltip commands missing",
    )

    contains_all(
        services,
        [
            "fetchExportCatalog",
            "fetchExportTaskOptions",
            "fetchTerminalReadinessPage",
            "fetchExportJobs",
            "createExportJob",
            "downloadExportJob",
        ],
        "export-center services",
    )
    ensure("required_filters" in services or "requiredFilters" in types, "export center task filters metadata missing")
    ensure("task_id" in exports_view and "fetchExportTaskOptions" in exports_view, "task_detail task selector missing")
    ensure("remote-method" in catalog_tab or "remoteMethod" in exports_view, "task_detail selector must remote search")
    ensure("createExportJob(item.key, {})" not in exports_view, "task_detail launch must not submit empty filters")
    ensure(
        "terminals: [terminal]" in exports_view or "terminals: [payload.terminal]" in exports_view,
        "terminal download action must request final_delivery by terminal list",
    )
    contains_all(
        types,
        [
            "export type ExportCatalogItem",
            "requiredFilters",
            "export type TerminalReadinessItem",
            "export type ExportJob",
            "export type ExportJobPage",
            "export type ExportCenterPageSize = 20 | 50 | 100",
        ],
        "export-center types",
    )

    print("verify_v3_2_0_export_center_ui: OK")


if __name__ == "__main__":
    main()
