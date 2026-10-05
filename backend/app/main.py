import logging

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .routes import rooms

settings = get_settings()
logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("campusslot")


def create_app() -> FastAPI:
    app = FastAPI(
        title="CampusSlot API",
        version=settings.app_version,
        description="Room and laboratory slot booking for a university campus. "
        "Overlapping bookings for the same room are rejected with 409 Conflict.",
    )

    app.include_router(rooms.router)

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

    @app.get("/ready", tags=["meta"], summary="Readiness: the database is reachable")
    def ready(db: Session = Depends(get_db)):
        try:
            db.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            logger.warning("readiness check failed: %s", exc.__class__.__name__)
            return JSONResponse(
                status_code=503,
                content={"status": "unavailable", "detail": "database unreachable"},
            )
        return {"status": "ready"}

    @app.get("/api/info", tags=["meta"], summary="Running build information")
    def info() -> dict:
        return {
            "name": "CampusSlot",
            "version": settings.app_version,
            "git_sha": settings.git_sha,
            "environment": settings.app_env,
        }

    # Probes and the metrics endpoint are excluded so request-rate panels show real user traffic.
    Instrumentator(excluded_handlers=["/metrics", "/health", "/ready"]).instrument(app).expose(
        app, include_in_schema=False
    )
    return app


app = create_app()
