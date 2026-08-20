from pathlib import Path
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool

from app.api.router import api_router
from app.core.config import settings
from app.core.request_id import RequestIdMiddleware
from app.core.responses import error_response, ok
from app.core.security import decode_access_token
from app.core.security_middleware import RequestSizeLimitMiddleware, SecurityHeadersMiddleware
from app.services.local_simulation import (
    abort_authoritative_json_write,
    activate_authoritative_json_write,
    begin_authoritative_json_write,
    finish_authoritative_json_write,
    save_all_team_states,
)
from app.services.export_retirement import is_retired_export_path, retired_export_response
from app.services.ezcodes_scheduler import sync_manager
from app.services.project_board_cache import (
    start_project_board_summary_cache,
    stop_project_board_summary_cache,
)
from app.services.task_snapshot_cache import start_task_snapshot_cache, stop_task_snapshot_cache


LEGACY_UNMATCHED_ADMIN_SUFFIXES = (
    "/assign",
    "/unassign",
    "/outside-project",
    "/rematch",
    "/associate",
    "/create-group",
    "/delete",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_project_board_summary_cache()
    start_task_snapshot_cache()
    try:
        yield
    finally:
        stop_task_snapshot_cache()
        stop_project_board_summary_cache()
        sync_manager.stop_periodic()


def create_app() -> FastAPI:
    production_mode = settings.app_env.lower() in {"prod", "production"}
    app = FastAPI(
        title="Module Manager V2 API",
        version="3.2.5",
        lifespan=lifespan,
        docs_url=None if production_mode else "/docs",
        redoc_url=None if production_mode else "/redoc",
        openapi_url=None if production_mode else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_origin_regex=None if production_mode else ".*",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Team-Id", "X-Request-Id"],
    )
    if production_mode:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
        app.add_middleware(SecurityHeadersMiddleware, frame_ancestors=settings.security_frame_ancestors)
    app.add_middleware(RequestSizeLimitMiddleware, max_upload_mb=settings.max_upload_mb)
    app.add_middleware(RequestIdMiddleware)

    protected_prefixes = (
        "/local-test",
        "/projects",
        "/catalog",
        "/scan",
        "/tasks",
        "/groups",
        "/exports",
        "/jobs",
        "/ezcodes",
        "/barcode-maintenance",
    )

    def required_production_write_roles(request: Request) -> tuple[set[str], str]:
        path = request.url.path.rstrip("/")
        method = request.method.upper()
        if method in {"GET", "HEAD", "OPTIONS"} or not path.startswith("/local-test"):
            return set(), ""
        if path in {"/local-test/scan/clear", "/local-test/tasks/release-all"}:
            return {"admin"}, "Administrator role required"
        if path.startswith("/local-test/construction/"):
            admin_actions = (
                "/open",
                "/close",
                "/assign",
                "/unassign",
            )
            if (
                path.startswith("/local-test/construction/tasks/")
                or path.startswith("/local-test/construction/exception-orders/")
            ) and path.endswith(admin_actions):
                return {"admin"}, "Administrator role required"
            return {"constructor", "admin"}, "Constructor or administrator role required"
        if path.startswith("/local-test/tasks/"):
            return {"reviewer", "admin"}, "Reviewer or administrator role required"
        if path == "/local-test/groups":
            return {"admin"}, "Administrator role required"
        if path.startswith("/local-test/groups/"):
            if path.endswith("/terminal"):
                return {"admin"}, "Administrator role required"
            return {"reviewer", "admin"}, "Reviewer or administrator role required"
        if path.startswith("/local-test/unmatched/"):
            if path in {"/local-test/unmatched/dedupe", "/local-test/unmatched/blank"}:
                return {"admin"}, "Administrator role required"
            if method == "POST" and path.endswith("/finalize-match"):
                return {"admin"}, "Administrator role required"
            if (
                (method == "PATCH" and path.endswith("/review"))
                or (method == "POST" and path.endswith(("/confirm", "/rescan")))
            ):
                return {"reviewer", "admin"}, "Reviewer or administrator role required"
            if path.endswith(LEGACY_UNMATCHED_ADMIN_SUFFIXES):
                return {"admin"}, "Administrator role required"
            if method == "PATCH" and path.count("/") == 3:
                return {"admin"}, "Administrator role required"
        return set(), ""

    def production_auth_rejection(request: Request):
        if not (
            production_mode
            and request.method.upper() != "OPTIONS"
            and request.url.path.startswith(protected_prefixes)
        ):
            return None
        authorization = request.headers.get("authorization", "")
        if not authorization.lower().startswith("bearer "):
            return error_response(request, "authentication_required", "Authentication required.", status_code=401)
        try:
            request.state.auth = decode_access_token(authorization.split(" ", 1)[1].strip())
        except ValueError:
            return error_response(request, "invalid_token", "Invalid access token.", status_code=401)
        required_roles, role_detail = required_production_write_roles(request)
        if required_roles and set(request.state.auth.get("roles") or []).isdisjoint(required_roles):
            return error_response(request, "forbidden", role_detail, status_code=403)
        return None

    @app.middleware("http")
    async def block_legacy_static_html(request: Request, call_next):
        if request.url.path.startswith("/static/") and request.url.path.lower().endswith(".html"):
            return error_response(request, "legacy_static_page_removed", "Legacy static pages are no longer served.", status_code=404)
        return await call_next(request)

    @app.middleware("http")
    async def persist_local_test_state(request: Request, call_next):
        if is_retired_export_path(request.url.path):
            return retired_export_response()
        rejection = production_auth_rejection(request)
        if rejection is not None:
            return rejection
        path = request.url.path.rstrip("/")
        method = request.method.upper()
        is_audited_unmatched_get = (
            method == "GET"
            and path.startswith("/local-test/unmatched/")
            and path.endswith(("/candidates", "/match-candidates"))
        )
        is_json_write = (
            path.startswith("/local-test")
            and (method not in {"GET", "HEAD", "OPTIONS"} or is_audited_unmatched_get)
            and settings.state_backend.lower() in {"json", "dual"}
        )
        transaction = None
        token = None
        if is_json_write:
            if production_mode:
                team_id = str(request.state.auth.get("team_id") or "")
            else:
                team_id = request.headers.get("X-Team-Id") or request.query_params.get("team_id") or ""
            transaction = await run_in_threadpool(begin_authoritative_json_write, team_id)
            token = activate_authoritative_json_write(transaction)
        try:
            response = await call_next(request)
            if transaction is not None:
                completed_transaction = transaction
                transaction = None
                if 200 <= response.status_code < 400:
                    finish_authoritative_json_write(
                        completed_transaction,
                        token,
                        persist=save_all_team_states,
                    )
                else:
                    abort_authoritative_json_write(completed_transaction, token)
            return response
        except BaseException:
            if transaction is not None:
                abort_authoritative_json_write(transaction, token)
            raise

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return error_response(
            request,
            code="validation_error",
            message="Request validation failed.",
            details={"errors": exc.errors()},
            status_code=422,
        )

    @app.get("/health")
    def health(request: Request):
        return ok(request, {"status": "ok"})

    static_dir = Path(__file__).resolve().parent / "static"
    upload_dir = static_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static/uploads", StaticFiles(directory=upload_dir, follow_symlink=True), name="uploads")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def index_page():
        return RedirectResponse("/login")

    @app.get("/favicon.ico")
    def favicon():
        return FileResponse(static_dir / "favicon.svg", media_type="image/svg+xml")

    vue_dir = static_dir / "vue"
    vue_assets_dir = vue_dir / "assets"
    vue_assets_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/vue/assets", StaticFiles(directory=vue_assets_dir, follow_symlink=True), name="vue-assets")

    def vue_index_response():
        index_path = vue_dir / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=503, detail="Vue production bundle is not built")
        return FileResponse(index_path)

    @app.get("/login")
    def login_page():
        return vue_index_response()

    @app.get("/v201")
    def v201_page():
        return RedirectResponse("/app?page=task-hall")

    @app.get("/app")
    def app_page():
        return vue_index_response()

    @app.get("/vue")
    @app.get("/vue/{full_path:path}")
    def vue_app(full_path: str = ""):
        return vue_index_response()

    @app.get("/task-hall")
    def task_hall_page():
        return RedirectResponse("/global-search")

    @app.get("/claim-tasks")
    def claim_tasks_page():
        return vue_index_response()

    @app.get("/project-board")
    def project_board_page():
        return vue_index_response()

    @app.get("/global-search")
    def global_search_page():
        return vue_index_response()

    @app.get("/account-management")
    def account_management_page():
        return vue_index_response()

    @app.get("/unmatched")
    def unmatched_page():
        return RedirectResponse("/global-search?review=1")

    @app.get("/review/{group_id}")
    def legacy_review_page(group_id: str):
        encoded_group_id = quote(group_id, safe="")
        return RedirectResponse(f"/global-search?group_id={encoded_group_id}&review=1")

    @app.get("/construction")
    def construction_page():
        return vue_index_response()

    @app.get("/construction-cache")
    def construction_cache_page():
        return RedirectResponse("/construction")

    @app.get("/sync-config")
    def sync_config_page():
        return vue_index_response()

    app.include_router(api_router)
    return app


app = create_app()
