"""
Configuration management for the ISRO SIH26170 Burn-In Anomaly Detection System.
Loads environment variables from .env using Pydantic Settings.
"""

from functools import lru_cache
from typing import Optional

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application settings
    APP_NAME: str = "ISRO-BurnIn-Screening"
    APP_ENV: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str = "isro_burnin_screening_secret_key_change_in_production_2026"

    # PostgreSQL configuration
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5433
    POSTGRES_USER: str = "burnin_user"
    POSTGRES_PASSWORD: str = "burnin_secure_pass_2026"
    POSTGRES_DB: str = "burn_in_db"

    # Optional direct URLs
    DATABASE_URL: Optional[str] = None
    ASYNC_DATABASE_URL: Optional[str] = None

    # Connection pooling
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_ECHO: bool = False

    # Redis configuration
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None
    REDIS_DB: int = 0
    REDIS_URL: Optional[str] = None

    # Synthetic Data Defaults
    DEFAULT_GENERATOR: str = "physics"  # physics | legacy (data_engine/physics_generator.py)
    DEFAULT_NUM_LOTS: int = 40
    DEFAULT_COMPONENTS_PER_LOT: int = 100
    SYNTHETIC_RANDOM_SEED: int = 42

    # Datasheet Absolute Limits
    DATASHEET_LEAKAGE_MAX_UA: float = 50.0
    DATASHEET_IDDQ_MAX_MA: float = 5.0
    DATASHEET_DELAY_MAX_NS: float = 8.0

    # Browser origins allowed to call the API (comma-separated). Vite dev server defaults to :3000.
    CORS_ORIGINS: str = (
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:8080,http://127.0.0.1:8080"
    )

    # Trained screening model (thresholds, calibration) written by run_screening, read by CSV ingest.
    # Relative paths are resolved against the project root.
    MODEL_ARTIFACT_PATH: str = "artifacts/screening_model.joblib"

    # Screening decision costs (see evaluation/cost.py). A missed defect (FN) is weighted
    # FN_COST / FP_COST times a false alarm. RECALL_TARGET optionally constrains threshold choice.
    FN_COST: float = 20.0
    FP_COST: float = 1.0
    RECALL_TARGET: Optional[float] = None
    # "separate": Module A threshold and Module B safety-slope k are each cost-minimised on their own
    #             (PS 26170 requires Module B to flag on its own safety-slope rule), decision = union.
    # "joint":    the pair is optimised together for the union (may disable a module entirely).
    THRESHOLD_STRATEGY: str = "separate"
    # Judge mode guard: a path whose validation flag rate exceeds this ceiling is rejected (ml_engine/judge.py).
    JUDGE_MAX_FLAG_RATE: float = 0.40

    @computed_field
    @property
    def sync_database_url(self) -> str:
        """Returns the synchronous PostgreSQL connection URL for psycopg2/alembic."""
        if self.DATABASE_URL:
            # Normalize if protocol lacks psycopg2
            if self.DATABASE_URL.startswith("postgresql://"):
                return self.DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
            return self.DATABASE_URL
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field
    @property
    def async_database_url(self) -> str:
        """Returns the asynchronous PostgreSQL connection URL for asyncpg."""
        if self.ASYNC_DATABASE_URL:
            return self.ASYNC_DATABASE_URL
        if self.DATABASE_URL:
            return self.DATABASE_URL.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1).replace(
                "postgresql://", "postgresql+asyncpg://", 1
            )
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field
    @property
    def computed_redis_url(self) -> str:
        """Returns the Redis connection URL."""
        if self.REDIS_URL:
            return self.REDIS_URL
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


@lru_cache
def get_settings() -> Settings:
    """Cached accessor for application settings."""
    return Settings()


settings = get_settings()
