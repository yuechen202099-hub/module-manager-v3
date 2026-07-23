from __future__ import annotations

import html
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VUE_SRC = ROOT / "v2-web" / "src"
ALLOWED_EXPORT_VUE_PATHS = {
    "v2-web/src/views/ExportsView.vue",
}
ALLOWED_TEMPLATE_USAGE = {
    "downloadConstructionPriorityTemplate": {
        "v2-web/src/components/ConstructionPriorityImportDialog.vue",
    },
}
BUSINESS_EXPORT_APIS = {
    "createExportJob",
    "downloadExportJob",
    "exportTerminalDeliveryPackage",
    "exportTaskDetail",
    "exportExceptionMeters",
    "exportProjectOutsideConstruction",
}
BUSINESS_EXPORT_LABELS = {
    "导出项目外施工",
    "导出异常表计",
    "导出明细",
    "导出终端包",
    "导出范围",
    "导出任务",
}
RETAINED_STATIC_HTML_PATHS = (
    "v2-api/app/static/app_shell.html",
    "v2-api/app/static/claim_tasks.html",
    "v2-api/app/static/construction.html",
    "v2-api/app/static/login.html",
    "v2-api/app/static/project_board.html",
    "v2-api/app/static/sync_config.html",
    "v2-api/app/static/v201.html",
)
DATA_CENTER_STATIC_HTML_PATHS = set(RETAINED_STATIC_HTML_PATHS) - {
    "v2-api/app/static/login.html",
}
RETIRED_REVIEW_WORKBENCH_MARKERS = ("审阅工作台", "/task-hall", "task-hall")
UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")


def read(relative_path: str) -> str:
    path = ROOT / relative_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def ensure(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def contains(text: str, needle: str, context: str) -> None:
    ensure(needle in text, f"{context} missing `{needle}`")


def not_contains(text: str, needle: str, context: str) -> None:
    ensure(needle not in text, f"{context} must remove `{needle}`")


def decoded_static_html(text: str) -> str:
    return UNICODE_ESCAPE_RE.sub(lambda match: chr(int(match.group(1), 16)), html.unescape(text))


def scan_vue_source() -> None:
    for path in sorted(VUE_SRC.rglob("*.vue")):
        relative_path = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for api_name in BUSINESS_EXPORT_APIS:
            if api_name in text and relative_path not in ALLOWED_EXPORT_VUE_PATHS:
                raise AssertionError(f"{relative_path} must not reference business export API `{api_name}`")
        for label in BUSINESS_EXPORT_LABELS:
            if label in text and relative_path not in ALLOWED_EXPORT_VUE_PATHS:
                raise AssertionError(f"{relative_path} must not render business export action `{label}`")
        for api_name, allowed_paths in ALLOWED_TEMPLATE_USAGE.items():
            if api_name in text and relative_path not in allowed_paths:
                raise AssertionError(f"{relative_path} must not reference `{api_name}`")


def main() -> None:
    claim_tasks = read("v2-web/src/views/ClaimTasksView.vue")
    global_search = read("v2-web/src/views/GlobalSearchView.vue")
    project_board = read("v2-web/src/views/ProjectBoardView.vue")
    app_layout = read("v2-web/src/layouts/AppLayout.vue")
    static_pages = read("v2-web/src/router/staticPages.ts")
    router_source = read("v2-web/src/router/index.ts")
    exports_view = read("v2-web/src/views/ExportsView.vue")
    priority_import_dialog = read("v2-web/src/components/ConstructionPriorityImportDialog.vue")
    static_page_verifier = read("scripts/verify-static-pages.py")

    scan_vue_source()

    ensure(
        not (ROOT / "v2-web/src/views/TaskHallView.vue").exists(),
        "obsolete TaskHallView.vue must be deleted",
    )
    ensure(
        not (ROOT / "v2-api/app/static/task_hall.html").exists(),
        "obsolete task_hall.html must be deleted",
    )
    for relative_path in RETAINED_STATIC_HTML_PATHS:
        source = read(relative_path)
        ensure(bool(source), f"retained static page missing: {relative_path}")
        rendered = decoded_static_html(source)
        for marker in RETIRED_REVIEW_WORKBENCH_MARKERS:
            not_contains(rendered, marker, relative_path)
        if relative_path in DATA_CENTER_STATIC_HTML_PATHS:
            contains(rendered, "数据中台", relative_path)
            contains(source, "/global-search", relative_path)

    contains(
        static_page_verifier,
        'NAV_TEXT = ["项目看板", "任务领取", "数据中台"]',
        "static page verifier navigation",
    )
    contains(
        static_page_verifier,
        "verify_retired_review_workbench_is_absent",
        "static page verifier retired-workbench gate",
    )
    contains(
        static_page_verifier,
        'STATIC_ROOT.glob("*.html")',
        "static page verifier retained-page scan",
    )

    contains(static_pages, "title: '任务派发'", "staticPages task dispatch entry")
    contains(static_pages, "title: '数据中台'", "staticPages data center entry")
    contains(static_pages, "title: '导出中心'", "staticPages export center entry")
    not_contains(static_pages, "key: 'task-hall'", "staticPages legacy task-hall registry")
    not_contains(static_pages, "task-hall-legacy", "staticPages legacy task-hall route")
    not_contains(static_pages, "title: '任务领取'", "staticPages legacy claim title")
    not_contains(static_pages, "title: '任务大厅'", "staticPages legacy hall title")
    not_contains(static_pages, "审阅工作台", "staticPages legacy review title")

    contains(router_source, "'claim-tasks': () => import('@/views/ClaimTasksView.vue')", "router task dispatch component")
    contains(router_source, "path: 'task-hall'", "router legacy task-hall redirect")
    contains(router_source, "redirect: '/global-search'", "router legacy hall redirect")
    contains(router_source, "path: 'tasks'", "router legacy tasks redirect")
    contains(router_source, "path: 'review/:groupId'", "router legacy review redirect")
    contains(
        router_source,
        "/global-search?group_id=${encodeURIComponent(String(to.params.groupId || ''))}&page=1&page_size=20&review=1",
        "router legacy review redirect query",
    )
    not_contains(router_source, "TaskHallView", "router legacy hall component")
    not_contains(router_source, "task-hall-legacy", "router legacy hall route")
    not_contains(router_source, "path: 'task-hall',\n          redirect: '/claim-tasks'", "router legacy task-hall claim redirect")

    contains(claim_tasks, "任务派发", "ClaimTasksView dispatch title")
    contains(claim_tasks, "指派施工", "ClaimTasksView dispatch action")
    contains(claim_tasks, "改派施工", "ClaimTasksView reassign action")
    contains(claim_tasks, "优先施工", "ClaimTasksView priority action")
    contains(claim_tasks, "已施工", "ClaimTasksView completed status")

    for forbidden in [
        "任务领取",
        "领取审阅",
        "释放审阅",
        "进入审阅",
        "完成审阅",
        "审阅工作台",
        "可领取审阅",
        "释放工单",
        "已审阅",
        "我已领取",
        "已被领取",
        "导出终端包",
        "导出明细",
        "导出任务",
        "导出范围",
        "claimTaskApi",
        "releaseTaskApi",
        "releaseAllClaimedTasks",
        "module-manager:start-terminal-export",
        "exportTaskDetail",
    ]:
        not_contains(claim_tasks, forbidden, "ClaimTasksView")

    for forbidden in [
        "exportTerminalDeliveryPackage",
        "module-manager:start-terminal-export",
        "startShellExport",
        "shellExportActive",
    ]:
        not_contains(app_layout, forbidden, "AppLayout")
    not_contains(app_layout, "'task-hall': List", "AppLayout legacy task-hall icon")
    not_contains(app_layout, "task-hall", "AppLayout legacy task-hall nav")

    contains(exports_view, "createExportJob", "ExportsView single export entry")
    contains(exports_view, "downloadExportJob", "ExportsView download flow")
    contains(priority_import_dialog, "downloadConstructionPriorityTemplate", "priority import template exception")
    contains(global_search, "数据中台", "GlobalSearchView data center heading")

    for source, name in [
        (project_board, "ProjectBoardView"),
        (global_search, "GlobalSearchView"),
    ]:
        not_contains(source, "exportTaskDetail", name)
        not_contains(source, "exportExceptionMeters", name)
        not_contains(source, "exportProjectOutsideConstruction", name)

    print("verify_v3_2_0_single_export_entry: OK")


if __name__ == "__main__":
    main()
