from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings
from app.core.request_id import RequestIdMiddleware
from app.core.responses import error_response, ok
from app.core.security import decode_access_token
from app.services.local_simulation import save_all_team_states
from app.services.ezcodes_scheduler import sync_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        sync_manager.stop_periodic()


def create_app() -> FastAPI:
    production_mode = settings.app_env.lower() in {"prod", "production"}
    app = FastAPI(
        title="Module Manager V2 API",
        version="3.0.4",
        lifespan=lifespan,
        docs_url=None if production_mode else "/docs",
        redoc_url=None if production_mode else "/redoc",
        openapi_url=None if production_mode else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
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
    )

    @app.middleware("http")
    async def require_production_auth(request: Request, call_next):
        if production_mode and request.url.path.startswith(protected_prefixes):
            authorization = request.headers.get("authorization", "")
            if not authorization.lower().startswith("bearer "):
                return error_response(request, "authentication_required", "Authentication required.", status_code=401)
            try:
                request.state.auth = decode_access_token(authorization.split(" ", 1)[1].strip())
            except ValueError:
                return error_response(request, "invalid_token", "Invalid access token.", status_code=401)
        return await call_next(request)

    @app.middleware("http")
    async def block_legacy_static_html(request: Request, call_next):
        if request.url.path.startswith("/static/") and request.url.path.lower().endswith(".html"):
            return error_response(request, "legacy_static_page_removed", "Legacy static pages are no longer served.", status_code=404)
        return await call_next(request)

    @app.middleware("http")
    async def persist_local_test_state(request: Request, call_next):
        response = await call_next(request)
        if (
            request.url.path.startswith("/local-test")
            and request.method.upper() not in {"GET", "HEAD", "OPTIONS"}
            and response.status_code < 500
            and settings.state_backend.lower() in {"json", "dual"}
        ):
            save_all_team_states()
        return response

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
        return vue_index_response()

    @app.get("/claim-tasks")
    def claim_tasks_page():
        return vue_index_response()

    @app.get("/project-board")
    def project_board_page():
        return vue_index_response()

    @app.get("/unmatched")
    def unmatched_page():
        return RedirectResponse("/task-hall")

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
