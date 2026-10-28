import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.config import Settings, load_settings
from app.database import init_db, make_engine, make_session_factory
from app.errors import AppError
from app.routers import assessments, candidates, finance, interviews, jobs, reports, webhooks
from app.services.fitment import ASSESSMENT_VERSION
from app.timeutils import utc_now

logger = logging.getLogger("talentflow")
STATIC_DIR = Path(__file__).parent / "static"
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
)


def _error_body(code: str, message: str, details: list[dict] | None = None) -> dict:
    body: dict = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return body


def create_app(
    settings: Settings | None = None,
    engine=None,
    clock=None,
    ai_transport=None,
) -> FastAPI:
    settings = settings or load_settings()
    settings.validate()
    engine = engine or make_engine(settings.database_url)
    init_db(engine)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Recruitment workflow MVP. Assessments are decision-support only; recruiters make all "
            "pipeline decisions. Use synthetic data only. No authentication is implemented."
        ),
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.clock = clock or utc_now
    app.state.ai_transport = ai_transport

    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError):
        return JSONResponse(_error_body(exc.code, exc.message), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError):
        # Input values are deliberately omitted so resume or candidate text is never echoed back.
        details = [
            {
                "field": ".".join(str(p) for p in err.get("loc", ()) if p != "body"),
                "message": err.get("msg", ""),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            _error_body("validation_error", "Request validation failed.", details), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException):
        code = "not_found" if exc.status_code == 404 else "http_error"
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(_error_body(code, message), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, _exc: Exception):
        logger.error("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(_error_body("internal_error", "An unexpected error occurred."), status_code=500)

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if not request.url.path.startswith(("/docs", "/openapi.json")):
            response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        return response

    app.include_router(jobs.router)
    app.include_router(candidates.router)
    app.include_router(assessments.router)
    app.include_router(interviews.router)
    app.include_router(reports.router)
    app.include_router(finance.router)
    app.include_router(webhooks.router)
    app.include_router(webhooks.runs_router)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health", tags=["system"])
    def health(request: Request) -> JSONResponse:
        try:
            with request.app.state.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            database = "ok"
        except SQLAlchemyError:
            database = "error"
        return JSONResponse(
            {
                "status": "ok" if database == "ok" else "degraded",
                "app": settings.app_name,
                "environment": settings.app_env,
                "version": __version__,
                "database": database,
                "ai_provider": settings.ai_provider,
                "assessment_version": ASSESSMENT_VERSION,
            },
            status_code=200 if database == "ok" else 503,
        )

    return app


def get_app() -> FastAPI:
    return create_app()
