"""Application settings, loaded from environment variables (see .env.example)."""

from decimal import Decimal
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Root .env first, then backend/.env; real environment variables always win.
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "CareLedger"
    environment: str = "development"
    log_level: str = "INFO"
    log_json: bool = False

    database_url: str = "postgresql+psycopg://careledger:careledger@localhost:5432/careledger"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = Field(default="change-me-in-env", min_length=16)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7

    cors_origins: list[str] = ["http://localhost:3000"]

    # Login throttling (failed attempts per window); backend "redis" or "memory".
    rate_limit_backend: str = "redis"
    login_max_failures_per_account: int = 5
    login_max_failures_per_ip: int = 20
    login_window_seconds: int = 900

    # Demo only: every seeded user shares this password (docs/DEMO_USERS.md).
    demo_password: str = "CareLedger!2026"

    # Approval thresholds (used from Phase 1 onwards).
    manual_journal_approval_threshold: Decimal = Decimal("10000.00")
    refund_approval_threshold: Decimal = Decimal("500.00")
    write_off_approval_threshold: Decimal = Decimal("0.00")


@lru_cache
def get_settings() -> Settings:
    return Settings()
