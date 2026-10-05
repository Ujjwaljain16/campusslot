import logging
import time

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .logging_config import configure_logging
from .routes import bookings, rooms

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("campusslot")

# Probe and metrics requests would drown out real traffic in the logs.
QUIET_PATHS = {"/health", "/ready", "/metrics"}


def create_app() -> FastAPI:
    app = FastAPI(
        title="CampusSlot API",
        version=settings.app_version,
        description="Room and laboratory slot booking for a university campus. "
        "Overlapping bookings for the same room are rejected with 409 Conflict.",
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        if request.url.path not in QUIET_PATHS:
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
        return response

    app.include_router(rooms.router)
    app.include_router(bookings.router)

    @app.get("/", tags=["meta"], summary="Service banner")
    def root() -> dict:
        return {
            "service": "campusslot-api",
            "docs": "/docs",
            "health": "/health",
            "ready": "/ready",
        }

    @app.get("/health", tags=["meta"], summary="Liveness: the process is up")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/ready", tags=["meta"], summary="Readiness: the database is reachable and migrated")
    def ready(db: Session = Depends(get_db)):
        try:
            db.execute(text("SELECT 1"))
            schema_present = inspect(db.get_bind()).has_table("bookings")
        except SQLAlchemyError as exc:
            logger.warning("readiness check failed: %s", exc.__class__.__name__)
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "detail": "database unreachable"},
            )
        if not schema_present:
            # Traffic must not arrive before the migration Job has created the tables.
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "detail": "database schema is not migrated yet"},
            )
        return {"status": "ready"}

    @app.get("/api/info", tags=["meta"], summary="Running build information")
    def info() -> dict:
        return {
            "name": "CampusSlot",
            "version": settings.app_version,
            "git_sha": settings.git_sha,
            "environment": settings.app_env,
            "day_open_hour": settings.day_open_hour,
            "day_close_hour": settings.day_close_hour,
        }

    # Probes and the metrics endpoint are excluded so request-rate panels show real user traffic.
    Instrumentator(excluded_handlers=["/metrics", "/health", "/ready"]).instrument(app).expose(
        app, include_in_schema=False
    )
    return app


app = create_app()
