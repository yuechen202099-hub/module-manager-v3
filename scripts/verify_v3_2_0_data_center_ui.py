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
    combined_list = f"{global_search}\n{filters}"

    assert_contains(combined_list, "page-sizes=\"[20, 50, 100]\"", "data center pagination must expose 20/50/100")
    assert_contains(global_search, "DataCenterReviewDialog", "global search must use the unified review dialog")
    assert_contains(dialog, "重新扫码", "review dialog must expose rescan")
    assert_contains(dialog, "人工确认", "review dialog must expose manual confirmation")
    assert_contains(dialog, "框选扫码", "review dialog must expose region scan")
    assert "完成审阅" not in dialog, "ordinary complete-review action is forbidden in unified dialog"
    assert_contains(query_composable, "router.replace", "query composable must synchronize filters into the URL")
    assert_contains(query_composable, "AbortController", "query composable must cancel stale data-center requests")


if __name__ == "__main__":
    main()
