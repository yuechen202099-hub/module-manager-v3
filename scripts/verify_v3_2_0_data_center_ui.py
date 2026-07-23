from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    file_path = ROOT / path
    if not file_path.exists():
        return ""
    return file_path.read_text(encoding="utf-8")


def assert_contains(source: str, needle: str, message: str) -> None:
    assert needle in source, message


def main() -> None:
    global_search = read("v2-web/src/views/GlobalSearchView.vue")
    filters = read("v2-web/src/components/data-center/DataCenterFilters.vue")
    dialog = read("v2-web/src/components/data-center/DataCenterReviewDialog.vue")
    query_composable = read("v2-web/src/composables/useDataCenterQuery.ts")
    services = read("v2-web/src/api/services.ts")
    groups_route = read("v2-api/app/api/routes/groups.py")
    combined_list = f"{global_search}\n{filters}"

    assert_contains(combined_list, "page-sizes=\"[20, 50, 100]\"", "data center pagination must expose 20/50/100")
    assert_contains(global_search, "DataCenterReviewDialog", "global search must use the unified review dialog")
    assert_contains(dialog, "重新扫码", "review dialog must expose rescan")
    assert_contains(dialog, "人工确认", "review dialog must expose manual confirmation")
    assert_contains(dialog, "框选扫码", "review dialog must expose region scan")
    assert "完成审阅" not in dialog, "ordinary complete-review action is forbidden in unified dialog"
    assert_contains(query_composable, "router.replace", "query composable must synchronize filters into the URL")
    assert_contains(query_composable, "AbortController", "query composable must cancel stale data-center requests")
    assert_contains(filters, "exceptionOptions", "data center filters must expose exception status options")
    assert_contains(filters, "exceptionStatus", "data center exception status filter must sync through model")
    assert_contains(
        query_composable,
        "query.dataType === 'unmatched' ? 'unmatched' : 'group'",
        "direct review URL with only group_id must fall back to formal group detail",
    )
    assert_contains(
        services,
        "/groups/data-center/groups/${encodeURIComponent(groupId)}/photos/${encodeURIComponent(photoId)}/classify",
        "services must expose data-center classify endpoint",
    )
    assert_contains(
        services,
        "/groups/data-center/groups/${encodeURIComponent(groupId)}/photos/${encodeURIComponent(photoId)}/barcode-rescan",
        "services must expose data-center barcode rescan endpoint",
    )
    assert_contains(
        services,
        "/groups/data-center/groups/${encodeURIComponent(groupId)}/photos/${encodeURIComponent(photoId)}/region-scan",
        "services must expose data-center region scan endpoint",
    )
    assert_contains(
        groups_route,
        '@router.post("/data-center/groups/{group_id}/photos/{photo_id}/classify")',
        "backend must expose admin data-center classify endpoint",
    )
    assert_contains(
        groups_route,
        '@router.post("/data-center/groups/{group_id}/photos/{photo_id}/barcode-rescan")',
        "backend must expose admin data-center barcode rescan endpoint",
    )
    assert_contains(
        groups_route,
        '@router.post("/data-center/groups/{group_id}/photos/{photo_id}/region-scan")',
        "backend must expose admin data-center region scan endpoint",
    )
    assert "classifyPhotoWithGroup" not in dialog, "formal data-center dialog must not use local-test classify"
    assert "rescanPhotoBarcode" not in dialog, "formal data-center dialog must not use local-test rescan"
    assert "scanGroupPhotoRegion" not in dialog, "formal data-center dialog must not use local-test region scan"
    assert_contains(
        services,
        "signal?: AbortSignal",
        "group photo object URL fetch must accept AbortSignal",
    )
    assert_contains(
        services,
        "returnDataCenterGroupToException",
        "services must expose a data-center return exception endpoint",
    )
    assert_contains(
        services,
        "/groups/data-center/groups/${encodeURIComponent(groupId)}/return-exception",
        "data-center return exception must not call local-test",
    )
    assert_contains(
        groups_route,
        '@router.patch("/data-center/groups/{group_id}/return-exception")',
        "backend must expose admin data-center return exception endpoint",
    )
    assert_contains(
        dialog,
        "photoAbortController",
        "dialog must abort in-flight photo fetches on cleanup",
    )
    assert_contains(
        dialog,
        "fetchGroupPhotoObjectUrl(next.id, photo.id, 'preview',",
        "dialog must pass AbortSignal into photo object URL fetch",
    )
    assert_contains(
        dialog,
        "returnDataCenterGroupToException",
        "formal group dialog must use the data-center return exception service",
    )
    assert_contains(
        dialog,
        ":data-center=\"true\"",
        "data-center unmatched dialog must run in data-center mode",
    )
    assert_contains(
        dialog,
        ":finalize-match=\"finalizeDataCenterUnmatchedFromDialog\"",
        "data-center unmatched dialog must inject the data-center finalize callback",
    )
    unmatched_dialog = read("v2-web/src/components/UnmatchedReviewDialog.vue")
    assert_contains(
        unmatched_dialog,
        "finalizeMatch?:",
        "UnmatchedReviewDialog must accept an injected finalize callback",
    )
    assert_contains(
        unmatched_dialog,
        "props.dataCenter",
        "UnmatchedReviewDialog must expose data-center mode behavior",
    )


if __name__ == "__main__":
    main()
