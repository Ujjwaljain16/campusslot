from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every value comes from the environment, nothing is hard-coded."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://campusslot:campusslot@localhost:5432/campusslot"
    app_env: str = "development"
    log_level: str = "INFO"

    # Build metadata injected by the Docker image so the running version is always visible.
    app_version: str = "1.0.0"
    git_sha: str = "dev"

    # Booking rules.
    max_booking_hours: int = 12
    day_open_hour: int = 8
    day_close_hour: int = 20

    # Tracing is off unless an OTLP endpoint is given, for example http://tempo.monitoring.svc:4318
    # (the standard OTEL_* variables). The share of the traces that are kept is between 0 and 1.
    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "campusslot-backend"
    otel_traces_sampler_arg: float = Field(default=1.0, ge=0.0, le=1.0)

    # Fault injection, for drills only: a release that passes its readiness probe and then fails
    # a share of its requests, or answers slowly. Both are off by default, and they are ignored
    # when APP_ENV is "production", so a production pod can never be switched into this mode.
    fault_error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    fault_latency_ms: int = Field(default=0, ge=0, le=5000)


@lru_cache
def get_settings() -> Settings:
    return Settings()
