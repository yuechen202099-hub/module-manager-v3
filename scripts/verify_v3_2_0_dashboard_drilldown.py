from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    path = ROOT / relative_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def assert_contains(source: str, needle: str, message: str) -> None:
    assert needle in source, message


def assert_not_contains(source: str, needle: str, message: str) -> None:
    assert needle not in source, message


def transpile_and_run_drilldowns() -> dict[str, dict[str, object]]:
    utility = ROOT / "v2-web/src/utils/dataCenterDrilldown.ts"
    assert utility.exists(), "data center drilldown whitelist utility must exist"

    typescript = ROOT / "v2-web/node_modules/typescript/lib/typescript.js"
    assert typescript.exists(), "local TypeScript runtime must exist under v2-web/node_modules"

    cases = {
        "groups": {"context": {}, "expected": {"path": "/global-search", "query": {"data_type": "group", "page": "1", "page_size": "20"}}},
        "scanned_groups": {
            "context": {},
            "expected": {
                "path": "/global-search",
                "query": {"data_type": "group", "has_photos": "1", "page": "1", "page_size": "20"},
            },
        },
        "archived_groups": {
            "context": {},
            "expected": {
                "path": "/global-search",
                "query": {"data_type": "group", "archive_status": "archived", "page": "1", "page_size": "20"},
            },
        },
        "unmatched_records": {
            "context": {},
            "expected": {
                "path": "/global-search",
                "query": {"data_type": "unmatched", "page": "1", "page_size": "20"},
            },
        },
        "exception_missing_photo": {
            "context": {},
            "expected": {
                "path": "/global-search",
                "query": {"data_type": "group", "exception_status": "open", "page": "1", "page_size": "20"},
            },
        },
        "unconstructed_unscanned": {
            "context": {},
            "expected": {
                "path": "/global-search",
                "query": {"data_type": "group", "construction_status": "unconstructed", "page": "1", "page_size": "20"},
            },
        },
        "terminal_completed": {
            "context": {},
            "expected": {
                "path": "/global-search",
                "query": {"data_type": "group", "terminal_status": "completed", "page": "1", "page_size": "20"},
            },
        },
        "terminal_incomplete": {
            "context": {},
            "expected": {
                "path": "/global-search",
                "query": {"data_type": "group", "terminal_status": "incomplete", "page": "1", "page_size": "20"},
            },
        },
        "terminal_pending_archive": {
            "context": {},
            "expected": {
                "path": "/global-search",
                "query": {
                    "data_type": "group",
                    "terminal_status": "pending_archive",
                    "page": "1",
                    "page_size": "20",
                },
            },
        },
        "terminal_archived": {
            "context": {},
            "expected": {
                "path": "/global-search",
                "query": {"data_type": "group", "terminal_status": "archived", "page": "1", "page_size": "20"},
            },
        },
        "installer_completed": {
            "context": {"installer": "installer-a", "dateFrom": "2026-07-01", "dateTo": "2026-07-23"},
            "expected": {
                "path": "/global-search",
                "query": {
                    "data_type": "group",
                    "installer": "installer-a",
                    "installer_source": "photo",
                    "activity_date_from": "2026-07-01",
                    "activity_date_to": "2026-07-23",
                    "page": "1",
                    "page_size": "20",
                },
            },
        },
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_js = Path(temp_dir) / "dataCenterDrilldown.mjs"
        node_script = f"""
const fs = require('fs');
const path = require('path');
const {{ pathToFileURL }} = require('url');
const ts = require({json.dumps(str(typescript))});
const source = fs.readFileSync({json.dumps(str(utility))}, 'utf8');
const output = ts.transpileModule(source, {{
  compilerOptions: {{
    module: ts.ModuleKind.ES2020,
    target: ts.ScriptTarget.ES2020,
  }},
}}).outputText;
fs.writeFileSync({json.dumps(str(temp_js))}, output, 'utf8');
(async () => {{
  const mod = await import(pathToFileURL({json.dumps(str(temp_js))}).href);
  const build = mod.buildDataCenterDrilldown;
  const cases = {json.dumps({key: value["context"] for key, value in cases.items()}, ensure_ascii=False)};
  const results = {{}};
  for (const [key, context] of Object.entries(cases)) {{
    results[key] = build(key, context);
  }}
  process.stdout.write(JSON.stringify(results));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
        completed = subprocess.run(
            ["node", "-e", node_script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        actual = json.loads(completed.stdout)

    for key, config in cases.items():
        assert actual[key] == config["expected"], f"drilldown mapping `{key}` must stay on the whitelist contract"
    return actual


def main() -> int:
    board_source = read_text("v2-web/src/views/ProjectBoardView.vue")
    router_source = read_text("v2-web/src/router/index.ts")
    utility_source = read_text("v2-web/src/utils/dataCenterDrilldown.ts")
    kpi_source = read_text("v2-web/src/components/InstallerKpiDialog.vue")

    actual = transpile_and_run_drilldowns()
    assert actual["installer_completed"]["query"]["page_size"] == "20"

    assert_contains(utility_source, "buildDataCenterDrilldown", "dashboard drilldown utility must export buildDataCenterDrilldown")
    assert_contains(board_source, "buildDataCenterDrilldown", "ProjectBoardView must consume the unified drilldown whitelist")
    assert_contains(board_source, "router.push(buildDataCenterDrilldown(", "dashboard clicks must push drilldowns through the whitelist")
    assert_contains(board_source, "type=\"button\"", "dashboard drilldown affordances must stay keyboard accessible")
    assert_contains(board_source, "openInstallerKpi(item.installer)", "installer chart must open isolated KPI")
    assert_contains(board_source, "openInstallerDataCenter", "KPI must retain a secondary Data Center entry")
    assert_contains(kpi_source, "open-data-center", "KPI component must emit its precise Data Center context")
    assert_contains(board_source, "openDashboardDrilldown(item.drilldown", "summary/progress/risk/terminal cards must share the same drilldown entry")
    assert_contains(utility_source, "has_photos", "dashboard drilldown utility must expose precise has_photos mapping")
    assert_contains(utility_source, "terminal_status", "terminal drilldowns must use terminal_status keys")
    assert_not_contains(utility_source, "barcode_eligibility", "dashboard must not expose retired barcode eligibility drilldowns")
    assert_contains(utility_source, "installer_source", "installer drilldown must use explicit photo-source key")
    assert_contains(utility_source, "activity_date_from", "installer drilldown must use activity-date keys")
    assert_not_contains(utility_source, "classification_status: 'complete'", "dashboard drilldowns cannot approximate with classification_status")
    assert_not_contains(utility_source, "construction_status: 'completed'", "installer completed cannot approximate with construction_status")
    assert_not_contains(utility_source, "barcode_status", "dashboard must not expose retired barcode-status drilldowns")
    assert_not_contains(utility_source, "construction_status: 'in_progress'", "dashboard drilldown cannot approximate scanned/incomplete with in_progress")
    assert_not_contains(utility_source, "next.date_from = dateFrom", "installer drilldown cannot reuse generic updated_at start-date keys")
    assert_not_contains(utility_source, "next.date_to = dateTo", "installer drilldown cannot reuse generic updated_at end-date keys")
    assert_contains(router_source, "data_type: 'unmatched'", "legacy unmatched entrypoint must route into the data center")
    assert_contains(router_source, "page_size: '20'", "legacy router redirects must pin dashboard drilldowns to 20 rows")

    for removed in [
        "workloadDialogVisible",
        "terminalStatusDialogVisible",
        "exceptionDialogVisible",
        "replacementDialogVisible",
        "photoBarcodeDialogVisible",
        "photoBarcodePhotoDialogVisible",
        "photoBarcodeImagePreviewVisible",
        "fetchGroupPhotoObjectUrl",
        "exportPhotoBarcodeReviewGroups",
        "exportUnmatchedRecords",
        "fetchUnmatchedRecords",
        "fetchReplacementRecords",
        "fetchExceptionGroups",
        "exportExceptionRows",
        "exportInstallerWorkloadCsv",
        "exportExceptionGroupCsv",
        "exportReplacementCsv",
        "exportUnmatchedCsv",
    ]:
        assert_not_contains(
            board_source,
            removed,
            f"ProjectBoardView must remove duplicated dashboard detail/export code: {removed}",
        )

    print("[OK] V3.2.0 dashboard drilldown checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
