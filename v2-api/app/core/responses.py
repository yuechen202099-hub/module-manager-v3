from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


def ok(request: Request, data: Any = None) -> dict[str, Any]:
    return {"data": data if data is not None else {}, "error": None, "request_id": request.state.request_id}


def error_response(
    request: Request,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    status_code: int = 400,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "data": None,
            "error": {"code": code, "message": message, "details": details or {}},
            "request_id": request.state.request_id,
        },
    )

