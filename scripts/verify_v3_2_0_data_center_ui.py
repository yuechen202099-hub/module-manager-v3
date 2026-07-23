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
    data_center_service = read("v2-api/app/services/data_center.py")
    local_simulation = read("v2-api/app/services/local_simulation.py")
    state_repository = read("v2-api/app/services/state_repository.py")
    assert_contains(
        query_composable,
        "export const DATA_CENTER_PAGE_SIZES = [20, 50, 100] as const",
        "data center page-size choices must be exactly 20/50/100",
    )
    assert_contains(query_composable, "pageSize: 20,", "data center pagination must default to 20")
    assert_contains(
        query_composable,
        "return DATA_CENTER_PAGE_SIZES.includes(parsed as DataCenterPageSize) ? parsed as DataCenterPageSize : 20",
        "data center URL parsing must reject unsupported page sizes and fall back to 20",
    )
    assert_contains(
        global_search,
        ':page-size="query.pageSize"',
        "data center pagination must use the URL-backed page size",
    )
    assert_contains(
        global_search,
        ':page-sizes="DATA_CENTER_PAGE_SIZES"',
        "data center pagination must expose only the supported page sizes",
    )
    assert_contains(global_search, "DataCenterReviewDialog", "global search must use the unified review dialog")
    assert_contains(dialog, "重新扫码", "review dialog must expose rescan")
    assert_contains(dialog, "人工确认", "review dialog must expose manual confirmation")
    assert_contains(dialog, "框选扫码", "review dialog must expose region scan")
    assert "完成审阅" not in dialog, "ordinary complete-review action is forbidden in unified dialog"
    assert_contains(query_composable, "router.replace", "query composable must synchronize filters into the URL")
    assert_contains(query_composable, "AbortController", "query composable must cancel stale data-center requests")
    assert_contains(query_composable, "hasPhotos", "query composable must track the precise has-photos drilldown key")
    assert_contains(query_composable, "terminalStatus", "query composable must track the terminal_status drilldown key")
    assert_contains(query_composable, "activityDateFrom", "query composable must track the activity-date start key")
    assert_contains(query_composable, "activityDateTo", "query composable must track the activity-date end key")
    assert_contains(query_composable, "barcodeEligibility", "query composable must track exact barcode eligibility")
    assert_contains(query_composable, "installerSource", "query composable must track explicit installer source")
    assert_contains(filters, "exceptionOptions", "data center filters must expose exception status options")
    assert_contains(filters, "exceptionStatus", "data center exception status filter must sync through model")
    assert_contains(filters, "barcodeEligibilityOptions", "data center filters must expose barcode eligibility options")
    assert_contains(filters, "installerSourceOptions", "data center filters must expose installer source options")
    assert_contains(
        query_composable,
        "query.dataType === 'unmatched' ? 'unmatched' : 'group'",
        "direct review URL with only group_id must fall back to formal group detail",
    )
    assert_contains(
        services,
        "has_photos",
        "services must forward precise has_photos data-center filters",
    )
    assert_contains(
        services,
        "terminal_status",
        "services must forward precise terminal_status data-center filters",
    )
    assert_contains(
        services,
        "activity_date_from",
        "services must forward precise activity-date start filters",
    )
    assert_contains(
        services,
        "activity_date_to",
        "services must forward precise activity-date end filters",
    )
    assert_contains(
        services,
        "barcode_status: query.barcodeStatus || 'all'",
        "services must keep barcode_status as a first-class query contract",
    )
    assert_contains(
        services,
        "barcode_eligibility: query.barcodeEligibility || 'all'",
        "services must forward exact barcode eligibility filters",
    )
    assert_contains(
        services,
        "installer_source: query.installerSource || 'all'",
        "services must forward explicit installer source filters",
    )
    assert_contains(
        groups_route,
        "terminal_status",
        "backend data-center route must accept precise terminal status filters",
    )
    assert_contains(
        groups_route,
        "has_photos",
        "backend data-center route must accept precise has_photos filters",
    )
    assert_contains(
        groups_route,
        "activity_date_from",
        "backend data-center route must accept precise activity-date start filters",
    )
    assert_contains(
        groups_route,
        "activity_date_to",
        "backend data-center route must accept precise activity-date end filters",
    )
    assert_contains(
        groups_route,
        "barcode_eligibility",
        "backend route must accept exact barcode eligibility filters",
    )
    assert_contains(
        groups_route,
        "installer_source",
        "backend route must accept explicit installer source filters",
    )
    assert_contains(
        groups_route,
        '"verified"',
        "backend route must accept combined verified barcode drilldown status",
    )
    assert_contains(
        groups_route,
        '"needs_review"',
        "backend route must accept combined needs_review barcode drilldown status",
    )
    assert_contains(
        groups_route,
        '"manual_confirmed"',
        "backend route must preserve manual_confirmed as a single barcode filter",
    )
    assert_contains(
        groups_route,
        '"failed"',
        "backend route must preserve failed as a single barcode filter",
    )
    assert_contains(
        data_center_service,
        '{"passed", "manual_confirmed"}',
        "verified barcode filter must expand only to passed plus manual_confirmed",
    )
    assert_contains(
        data_center_service,
        '{"mismatched", "failed", "unreadable"}',
        "needs_review barcode filter must expand only to mismatched, failed, and unreadable",
    )
    assert_contains(
        data_center_service,
        "has_current_eligible_photo_set",
        "barcode eligibility must use the durable exact photo-set contract",
    )
    assert_contains(
        data_center_service,
        'durable_status != "not_eligible"',
        "ineligible barcode drilldown must include durable not_eligible in addition to photo-set failures",
    )
    assert_contains(
        local_simulation,
        "def summarize_installers_by_group",
        "JSON summary must expose installer distribution",
    )
    assert_contains(
        local_simulation,
        "_photo_upload_status_is_valid(photo)",
        "JSON installer distribution must ignore INVALID construction photos",
    )
    assert_contains(
        local_simulation,
        "_photo_is_construction_upload(photo)",
        "JSON installer distribution must only count construction-source photos",
    )
    assert_contains(
        local_simulation,
        "installer_display_name(photo.get(\"creator\"), name_cache)",
        "JSON installer distribution must preserve display-name aliases",
    )
    assert_contains(
        state_repository,
        "Photo.upload_status != PhotoUploadStatus.INVALID",
        "PG installer distribution and data-center filters must ignore INVALID photos",
    )
    assert_contains(
        state_repository,
        "_photo_construction_source_filter()",
        "PG installer distribution must only count construction-source photos",
    )
    assert_contains(
        state_repository,
        "Photo.creator.is_not(None)",
        "PG installer distribution must not create an unmatched blank-installer row",
    )
    assert_contains(
        state_repository,
        'func.nullif(func.trim(Photo.creator), "").is_not(None)',
        "PG installer distribution must trim and drop blank creators",
    )
    assert_contains(
        state_repository,
        'source.c.durable_barcode_status == "not_eligible"',
        "PG ineligible barcode drilldown must union durable not_eligible",
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
