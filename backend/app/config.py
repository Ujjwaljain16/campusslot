from functools import lru_cache

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
