from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse


def request_id_for(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None) or request.headers.get("x-request-id") or str(uuid4())
    request.state.request_id = request_id
    return request_id


def ok(request: Request, data: Any = None) -> dict[str, Any]:
    return {"data": data if data is not None else {}, "error": None, "request_id": request_id_for(request)}


def error_response(
    request: Request,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    status_code: int = 400,
) -> JSONResponse:
    request_id = request_id_for(request)
    return JSONResponse(
        status_code=status_code,
        content={
            "data": None,
            "error": {"code": code, "message": message, "details": details or {}},
            "request_id": request_id,
        },
        headers={"x-request-id": request_id},
    )
