from fastapi import APIRouter, Request

from app.core.config import settings
from app.core.responses import error_response, ok
from app.schemas.auth import LoginRequest

router = APIRouter(prefix="/auth")


@router.post("/login")
def login(payload: LoginRequest, request: Request):
    if payload.username != settings.admin_username or payload.password != settings.admin_password:
        return error_response(request, "invalid_credentials", "Username or password is incorrect.", status_code=401)
    return ok(request, {"access_token": "dev-admin-token", "token_type": "bearer"})


@router.get("/me")
def me(request: Request):
    return ok(request, {"id": 1, "username": settings.admin_username, "roles": ["admin"]})

