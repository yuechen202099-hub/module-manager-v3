from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VUE_SOURCE_ROOT = ROOT / "v2-web/src"
GENERATED_VUE_ROOT = ROOT / "v2-api/app/static/vue"
SERVICES_PATH = "v2-web/src/api/services.ts"
TEMPLATE_DIALOG_PATH = "v2-web/src/components/ConstructionPriorityImportDialog.vue"
RETIRED_FILES = (
    "v2-web/src/views/ExportsView.vue",
    "v2-web/src/composables/useExportCenterQuery.ts",
    "v2-web/src/components/export-center/ExportCatalogTab.vue",
    "v2-web/src/components/export-center/ExportJobsTable.vue",
    "v2-web/src/components/export-center/TerminalDeliveryTab.vue",
)
FORBIDDEN_MARKERS = (
    "ExportsView",
    "useExportCenterQuery",
    "ExportCatalogTab",
    "ExportJobsTable",
    "TerminalDeliveryTab",
    "EXPORT_CENTER_PAGE_SIZES",
    "fetchExportCatalog",
    "fetchExportTaskOptions",
    "fetchTerminalReadinessPage",
    "fetchExportJobs",
    "createExportJob",
    "downloadExportJob",
    "exportTerminalDeliveryPackage",
    "exportTaskDetail",
    "exportExceptionMeters",
    "exportProjectOutsideConstruction",
    "exportPhotoBarcodeReviewGroups",
    "exportUnmatchedRecords",
    "ExportCenterPageSize",
    "ExportCenterTab",
    "ExportCatalogMode",
    "ExportCatalogRequiredFilterKind",
    "ExportCatalogRequiredFilter",
    "ExportCatalogItem",
    "ExportTaskOption",
    "TerminalReadinessItem",
    "TerminalReadinessPage",
    "ExportJob",
    "ExportJobPage",
    "BackendExportCatalogItem",
    "BackendExportTaskOption",
    "BackendTerminalReadinessItem",
    "BackendTerminalReadinessPage",
    "BackendExportJob",
    "BackendExportJobPage",
    "mapExportCatalogItem",
    "mapExportTaskOption",
    "mapTerminalReadinessItem",
    "mapExportJob",
    "TerminalReadinessQuery",
    "ExportJobListQuery",
    "DeliveryExportProgress",
    "downloadExcel",
    "createResponseError",
    "/exports/final-delivery",
    "/exports",
    "/local-test/unmatched/export",
    "/local-test/photo-barcode/review-groups/export",
    "buildInstallerKpiCsv",
    "function downloadCsv(",
    "csvCell(",
    "text/csv;charset=utf-8",
    "daily-workload.csv",
    "导出 KPI CSV",
)
GENERATED_NAME_MARKERS = ("ExportsView", "ExportCenter", "export-center", "useExportCenterQuery")
SOURCE_SUFFIXES = {".ts", ".vue", ".js", ".mjs"}
GENERATED_TEXT_SUFFIXES = {".css", ".html", ".js", ".json", ".map", ".txt"}
RETIRED_EXPORT_ROUTE_RE = re.compile(
    r"\b(?:path|redirect)\b\s*:\s*(['\"`])/?exports(?:[/?#][^'\"`]*)?\1"
)


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def source_files() -> list[Path]:
    return sorted(
        path
        for path in VUE_SOURCE_ROOT.rglob("*")
        if path.is_file() and path.suffix in SOURCE_SUFFIXES
    )


def generated_files() -> list[Path]:
    ensure(GENERATED_VUE_ROOT.is_dir(), "generated Vue asset directory is missing")
    files = sorted(path for path in GENERATED_VUE_ROOT.rglob("*") if path.is_file())
    ensure(bool(files), "generated Vue asset directory is empty")
    return files


def combined_text(paths: list[Path], suffixes: set[str]) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in paths
        if path.suffix in suffixes
    )


def function_body(source: str, signature: str, context: str) -> str:
    start = source.find(signature)
    ensure(start >= 0, f"{context} missing `{signature}`")
    opening = source.find("{", start + len(signature))
    ensure(opening >= 0, f"{context} has no function body")
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening + 1 : index]
    raise AssertionError(f"{context} has an unterminated function body")


def verify_template_download_chain(source_paths: list[Path]) -> None:
    services = read(SERVICES_PATH)
    dialog = read(TEMPLATE_DIALOG_PATH)
    service_body = function_body(
        services,
        "export async function downloadConstructionPriorityTemplate()",
        "construction-priority template service",
    )
    for marker in (
        "await fetchWithAuth('/local-test/construction/priority-template'",
        "authHeaders()",
        "response.ok",
        "await response.blob()",
        "triggerBrowserDownload(",
        "filenameFromDisposition(",
    ):
        ensure(marker in service_body, f"construction-priority template service missing `{marker}`")

    filename_body = function_body(
        services,
        "function filenameFromDisposition(disposition: string, fallbackName: string)",
        "template filename helper",
    )
    ensure(
        "parseContentDispositionFilename(disposition, fallbackName)" in filename_body,
        "template filename helper must delegate to parseContentDispositionFilename",
    )

    browser_body = function_body(
        services,
        "function triggerBrowserDownload(blob: Blob, filename: string)",
        "template browser-download helper",
    )
    browser_lifecycle = (
        "URL.createObjectURL(blob)",
        "document.createElement('a')",
        "link.href = url",
        "link.download = filename",
        "document.body.appendChild(link)",
        "link.click()",
        "link.remove()",
        "URL.revokeObjectURL(url)",
    )
    for marker in browser_lifecycle:
        ensure(marker in browser_body, f"template browser-download helper missing `{marker}`")
    lifecycle_positions = [browser_body.index(marker) for marker in browser_lifecycle]
    ensure(
        lifecycle_positions == sorted(lifecycle_positions),
        "template browser-download helper lifecycle must assign, append, click, remove, and revoke in order",
    )

    ensure(
        re.search(
            r"import\s*\{[^}]*\bdownloadConstructionPriorityTemplate\b[^}]*\}\s*"
            r"from\s*['\"]@/api/services['\"]",
            dialog,
        )
        is not None,
        "priority import dialog must import the template service",
    )
    caller_body = function_body(dialog, "async function downloadTemplate()", "priority import template action")
    ensure(
        "await downloadConstructionPriorityTemplate()" in caller_body,
        "priority import template action must await the template service",
    )
    ensure('@click="downloadTemplate"' in dialog, "priority import template button must invoke downloadTemplate")

    ensure(
        services.count("triggerBrowserDownload(") == 2,
        "browser-download helper must be used only by the retained import-template service",
    )
    ensure(
        services.count("downloadConstructionPriorityTemplate") == 1,
        "template service must have exactly one definition",
    )
    ensure(
        dialog.count("downloadConstructionPriorityTemplate") == 2,
        "priority import dialog must import and call the template service exactly once",
    )
    for path in source_paths:
        relative = path.relative_to(ROOT).as_posix()
        if relative in {SERVICES_PATH, TEMPLATE_DIALOG_PATH}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        ensure(
            "downloadConstructionPriorityTemplate" not in text,
            f"template service has an unexpected caller: {relative}",
        )
        ensure(
            "triggerBrowserDownload" not in text,
            f"browser-download helper escaped the retained template service: {relative}",
        )


def main() -> None:
    for relative in RETIRED_FILES:
        ensure(not (ROOT / relative).exists(), f"retired export UI still exists: {relative}")

    router_source = read("v2-web/src/router/index.ts")
    ensure(
        RETIRED_EXPORT_ROUTE_RE.search(router_source) is None,
        "retired /exports Vue route or redirect remains",
    )

    sources = source_files()
    generated = generated_files()
    source = combined_text(sources, SOURCE_SUFFIXES)
    generated_source = combined_text(generated, GENERATED_TEXT_SUFFIXES)
    generated_names = "\n".join(path.relative_to(GENERATED_VUE_ROOT).as_posix() for path in generated)
    for marker in sorted(FORBIDDEN_MARKERS, key=len, reverse=True):
        ensure(marker not in source, f"retired frontend marker remains: {marker}")
        ensure(marker not in generated_source, f"retired generated Vue marker remains: {marker}")
    for marker in GENERATED_NAME_MARKERS:
        ensure(marker not in generated_names, f"retired generated Vue asset remains: {marker}")

    verify_template_download_chain(sources)
    print("verify_v3_2_0_export_center_ui: retired")


if __name__ == "__main__":
    main()
