from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.request_id import RequestIdMiddleware
from app.core.responses import error_response, ok


def create_app() -> FastAPI:
    app = FastAPI(title="Module Manager V2 API", version="2.0.0")

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

    app.include_router(api_router)
    return app


app = create_app()
