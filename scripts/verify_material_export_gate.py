from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def main() -> int:
    routes = read("v2-api/app/api/routes/material_exports.py")
    api_router = read("v2-api/app/api/router.py")
    stream = read("v2-api/app/services/material_export_stream.py")
    service = read("v2-api/app/services/material_export.py")
    vue_router = read("v2-web/src/router/index.ts")
    file_system = read("v2-web/src/features/materialExport/fileSystem.ts")
    workbooks = read("v2-web/src/features/materialExport/workbooks.ts")
    composable = read("v2-web/src/features/materialExport/useMaterialExport.ts")
    task_page = read("v2-web/src/views/ClaimTasksView.vue")

    checks = {
        "material export API has an isolated prefix": 'prefix="/material-exports"' in routes,
        "material export API is registered": "material_exports.router" in api_router,
        "every material export route is administrator-gated": (
            routes.count("@router.") == routes.count("Depends(require_admin)")
            and routes.count("@router.") >= 10
        ),
        "stream rate is capped at 250000 bytes per second": "250_000" in stream,
        "stream reads OSS through the internal-only endpoint": "oss_server_endpoint(require_internal=True)" in stream,
        "stream does not use temporary files": all(
            token not in stream for token in ("TemporaryFile", "NamedTemporaryFile", "mkstemp")
        ),
        "material export implementation does not build ZIP files": "zipfile" not in (routes + stream + service),
        "material export does not revive final delivery builders": "build_final_delivery_export" not in (routes + stream + service),
        "no standalone material export route exists": "material-exports" not in vue_router,
        "folder picker is feature-detected": "if (!window.showDirectoryPicker)" in composable,
        "photo streaming never buffers the complete response": all(
            token not in file_system for token in (".blob(", ".arrayBuffer(")
        ),
        "incremental hash dependency stays lazy": "await import('hash-wasm')" in file_system,
        "workbook dependency stays lazy": "await import('exceljs')" in workbooks,
        "controls remain inside the existing task dispatch page": (
            "MaterialExportToolbar" in task_page and "MaterialExportCardControls" in task_page
        ),
        "task dispatch hides controls from non-admin users": task_page.count('v-if="isAdmin"') >= 3,
    }

    failures = [label for label, passed in checks.items() if not passed]
    if failures:
        for label in failures:
            print(f"FAIL: {label}")
        return 1
    print(f"material export gate passed: {len(checks)} checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
