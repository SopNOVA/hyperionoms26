from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://hyperion:hyperion_dev@db:5432/hyperion_onms"

    # Security
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # 8 hours

    # Environment
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # === Long-term maintainability & security hardening (2026-06) ===
    # DEV_AUTO_AUTH: When true (default for dev/test), get_current_user will
    # auto-return the demo technician on missing/invalid tokens. This was
    # originally added for frictionless ngrok + real ONU field testing.
    # Set to false (or use ENVIRONMENT=production) in real deployments.
    DEV_AUTO_AUTH: bool = True

    # CORS_ORIGINS: Comma or list. Use ["*"] only in development.
    # In production set via env: CORS_ORIGINS=https://dash.example.com,https://...
    CORS_ORIGINS: str | list[str] = "*"

    # DEMO_USER_ENABLED: Controls whether the aggressive demo user seeder
    # (tech / tech123) runs at startup. Disable in production.
    DEMO_USER_ENABLED: bool = True

    # Project
    PROJECT_NAME: str = "Hyperion-ONMS"
    VERSION: str = "0.2.0"

    # Allow extra keys in .env (e.g. POSTGRES_* used by docker-compose)
    # without failing validation. Useful for mixed local + compose .env files.
    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
