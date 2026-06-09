from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.request_id import RequestIdMiddleware
from app.core.responses import error_response, ok
from app.services.ezcodes_scheduler import sync_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    sync_manager.start_periodic()
    try:
        yield
    finally:
        sync_manager.stop_periodic()


def create_app() -> FastAPI:
    app = FastAPI(title="Module Manager V2 API", version="2.0.1", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIdMiddleware)

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
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/v201")
    def v201_page():
        return FileResponse(static_dir / "v201.html")

    @app.get("/task-hall")
    def task_hall_page():
        return FileResponse(static_dir / "task_hall.html")

    @app.get("/sync-config")
    def sync_config_page():
        return FileResponse(static_dir / "sync_config.html")

    app.include_router(api_router)
    return app


app = create_app()
