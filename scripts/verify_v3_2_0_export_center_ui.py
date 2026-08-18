from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RETIRED_FILES = (
    "v2-web/src/views/ExportsView.vue",
    "v2-web/src/composables/useExportCenterQuery.ts",
    "v2-web/src/components/export-center/ExportCatalogTab.vue",
    "v2-web/src/components/export-center/ExportJobsTable.vue",
    "v2-web/src/components/export-center/TerminalDeliveryTab.vue",
)
FORBIDDEN_MARKERS = (
    "ExportsView",
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
    "/exports/",
    "/local-test/unmatched/export",
    "/local-test/photo-barcode/review-groups/export",
    "buildInstallerKpiCsv",
    "导出 KPI CSV",
)


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    for relative in RETIRED_FILES:
        ensure(not (ROOT / relative).exists(), f"retired export UI still exists: {relative}")
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "v2-web/src").rglob("*")
        if path.suffix in {".ts", ".vue"}
    )
    for marker in FORBIDDEN_MARKERS:
        ensure(marker not in source, f"retired frontend marker remains: {marker}")
    ensure(
        "downloadConstructionPriorityTemplate" in read(
            "v2-web/src/components/ConstructionPriorityImportDialog.vue"
        ),
        "import-template download must remain",
    )
    print("verify_v3_2_0_export_center_ui: retired")


if __name__ == "__main__":
    main()
