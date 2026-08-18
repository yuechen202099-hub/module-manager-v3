from typing import Final

from starlette.responses import JSONResponse


RETIREMENT_MESSAGE: Final = "导出中心已下线，请联系管理员由 OSS 导出到本机。"
RETIRED_EXACT_PATHS: Final = frozenset(
    {
        "/local-test/export-manifest/final-delivery",
        "/local-test/unmatched/export",
        "/local-test/photo-barcode/review-groups/export",
    }
)


class ExportCenterRetiredError(RuntimeError):
    pass


def is_retired_export_path(path: str) -> bool:
    normalized = "/" + str(path or "").lstrip("/")
    normalized = normalized.rstrip("/") or "/"
    return (
        normalized == "/exports"
        or normalized.startswith("/exports/")
        or normalized in RETIRED_EXACT_PATHS
    )


def retired_export_response() -> JSONResponse:
    return JSONResponse({"detail": RETIREMENT_MESSAGE}, status_code=410)
