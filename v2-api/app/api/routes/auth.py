from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from app.core.config import settings
from app.core.rate_limit import SlidingWindowRateLimiter
from app.core.responses import error_response, ok
from app.core.security import create_access_token, decode_access_token
from app.schemas.auth import LoginRequest
from app.services.account_store import (
    authenticate_user,
    delete_user,
    ensure_user_store,
    list_users,
    normalize_team_id,
    public_user,
    update_user_password,
    upsert_user,
)

router = APIRouter(prefix="/auth")
login_limiter = SlidingWindowRateLimiter(limit=settings.security_login_rate_limit_per_minute)

DEMO_USERS = {
    "admin": {
        "password": "admin123",
        "roles": ["admin"],
        "name": "项目管理员",
        "home": "/app",
        "team_id": "demo-team",
    },
    "reviewer": {
        "password": "review123",
        "roles": ["reviewer"],
        "name": "资料审阅员",
        "home": "/app",
        "team_id": "demo-team",
    },
    "constructor": {
        "password": "construct123",
        "roles": ["constructor"],
        "name": "施工员",
        "home": "/app?page=construction",
        "team_id": "demo-team",
    },
}


class UserUpsertRequest(BaseModel):
    username: str
    password: str | None = None
    name: str = ""
    roles: list[str] = ["reviewer"]
    team_id: str = "default-team"
    status: str = "active"


class PasswordUpdateRequest(BaseModel):
    password: str


def demo_auth_is_enabled() -> bool:
    if settings.demo_auth_enabled is not None:
        return settings.demo_auth_enabled
    return settings.app_env.lower() not in {"prod", "production"}


def auth_required() -> bool:
    return settings.app_env.lower() in {"prod", "production"}


def bearer_payload(authorization: str | None) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return decode_access_token(authorization.split(" ", 1)[1].strip())
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid access token") from exc


def require_admin(authorization: str | None = Header(default=None)) -> dict:
    payload = bearer_payload(authorization)
    if "admin" not in set(payload.get("roles") or []):
        raise HTTPException(status_code=403, detail="Admin role required")
    return payload


def demo_login_user(username: str, password: str) -> dict | None:
    if not demo_auth_is_enabled():
        return None
    user = DEMO_USERS.get(username)
    if not user or password != user["password"]:
        return None
    return {
        "username": username,
        "name": user["name"],
        "roles": user["roles"],
        "team_id": user["team_id"],
        "home": user["home"],
    }


def environment_admin_login(username: str, password: str) -> dict | None:
    if username != settings.admin_username or password != settings.admin_password:
        return None
    return {
        "username": settings.admin_username,
        "name": "项目管理员",
        "roles": ["admin"],
        "team_id": getattr(settings, "admin_team_id", "default-team"),
        "home": "/app",
    }


def request_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    real_ip = request.headers.get("x-real-ip", "")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else ""


def login_rate_key(request: Request, username: str) -> str:
    client_ip = request_client_ip(request) or "unknown"
    return f"{client_ip}:{username.strip().lower()}"


def request_device(request: Request) -> str:
    return request.headers.get("user-agent", "").strip()[:256]


@router.get("/config")
def config(request: Request):
    ensure_user_store()
    demo_enabled = demo_auth_is_enabled()
    demo_accounts = []
    if demo_enabled:
        demo_accounts = [
            {
                "label": "管理员",
                "username": "admin",
                "password": DEMO_USERS["admin"]["password"],
                "role": "admin",
                "home": DEMO_USERS["admin"]["home"],
                "team_id": DEMO_USERS["admin"]["team_id"],
            },
            {
                "label": "审阅员",
                "username": "reviewer",
                "password": DEMO_USERS["reviewer"]["password"],
                "role": "reviewer",
                "home": DEMO_USERS["reviewer"]["home"],
                "team_id": DEMO_USERS["reviewer"]["team_id"],
            },
            {
                "label": "施工员",
                "username": "constructor",
                "password": DEMO_USERS["constructor"]["password"],
                "role": "constructor",
                "home": DEMO_USERS["constructor"]["home"],
                "team_id": DEMO_USERS["constructor"]["team_id"],
            },
        ]
    return ok(
        request,
            {
                "demo_auth_enabled": demo_enabled,
                "demo_accounts": demo_accounts,
                "account_config_enabled": bool(getattr(settings, "auth_users_path", "").strip()),
            },
        )


@router.post("/login")
def login(payload: LoginRequest, request: Request):
    client_ip = request_client_ip(request)
    client_device = request_device(request)
    user = (
        authenticate_user(payload.username, payload.password, ip=client_ip, device=client_device)
        or environment_admin_login(payload.username, payload.password)
        or demo_login_user(payload.username, payload.password)
    )
    if user is None:
        rate = login_limiter.check(login_rate_key(request, payload.username))
        if not rate.allowed:
            response = error_response(request, "rate_limited", "Too many login attempts.", status_code=429)
            response.headers["Retry-After"] = str(rate.retry_after_seconds)
            return response
        return error_response(request, "invalid_credentials", "Username or password is incorrect.", status_code=401)
    team_id = normalize_team_id(user.get("team_id") or payload.team_id or getattr(settings, "admin_team_id", "default-team"))
    user = {**user, "team_id": team_id, "home": user.get("home") or "/app"}
    return ok(
        request,
        {
            "access_token": create_access_token(user),
            "token_type": "bearer",
            "team_id": team_id,
            "user": public_user(user),
        },
    )


@router.get("/me")
def me(request: Request, authorization: str | None = Header(default=None)):
    payload = bearer_payload(authorization)
    return ok(
        request,
        {
            "username": payload["sub"],
            "name": payload.get("name") or payload["sub"],
            "roles": payload.get("roles") or [],
            "team_id": payload.get("team_id") or "default-team",
            "home": "/app",
        },
    )


@router.get("/users")
def users_list(request: Request, admin: dict = Depends(require_admin)):
    return ok(request, {"items": list_users()})


@router.post("/users")
def create_or_update_user(payload: UserUpsertRequest, request: Request, admin: dict = Depends(require_admin)):
    try:
        user = upsert_user(
            username=payload.username,
            password=payload.password,
            name=payload.name,
            roles=payload.roles,
            team_id=payload.team_id,
            status=payload.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, {"user": user})


@router.post("/users/{username}/password")
def change_password(
    username: str,
    payload: PasswordUpdateRequest,
    request: Request,
    admin: dict = Depends(require_admin),
):
    try:
        user = update_user_password(username, payload.password)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, {"user": user})


@router.delete("/users/{username}")
def remove_user(username: str, request: Request, admin: dict = Depends(require_admin)):
    if username == admin.get("sub"):
        raise HTTPException(status_code=400, detail="Cannot delete the current signed-in administrator")
    try:
        user = delete_user(username)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="User not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ok(request, {"user": user})
