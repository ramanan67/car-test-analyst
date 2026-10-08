"""
app/core/config.py
Pydantic settings management for the Automotive Testing Analytics Platform.
"""
from functools import lru_cache
from typing import List, Optional

from pydantic import AnyUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ---- App ----
    APP_NAME: str = "Automotive Prototype Testing Analytics Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"

    # ---- Database ----
    DATABASE_URL: str = "postgresql+asyncpg://benz_eng_admin:password@localhost:5432/test_analytics_db"
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    DATABASE_POOL_TIMEOUT: int = 30

    # ---- Redis / Celery ----
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # ---- Object Storage ----
    STORAGE_BUCKET: str = "prototype-test-telemetry"
    STORAGE_ENDPOINT: Optional[str] = None  # e.g. MinIO endpoint
    STORAGE_ACCESS_KEY: Optional[str] = None
    STORAGE_SECRET_KEY: Optional[str] = None

    # ---- JWT Auth ----
    JWT_SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION_USE_256_BIT_KEY"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ---- CORS ----
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8080"]

    # ---- Ingestion ----
    MAX_UPLOAD_SIZE_MB: int = 500
    TELEMETRY_RESAMPLE_MS: int = 10
    LARGE_FILE_THRESHOLD_MB: int = 10  # Files > this go to async queue

    # ---- Compliance ----
    DATA_RETENTION_YEARS: int = 7

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def validate_db_url(cls, v: str) -> str:
        if not v.startswith(("postgresql", "sqlite")):
            raise ValueError("DATABASE_URL must be a PostgreSQL or SQLite connection string")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
