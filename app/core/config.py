from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel, Field, ValidationError


class Settings(BaseModel):
    app_name: str = "AI Product Recommendation Engine"
    app_env: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    database_url: str = "postgresql://postgres:postgres@localhost:5432/recommendations"
    redis_url: str | None = None
    redis_cache_ttl_seconds: int = 300

    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_batch_size: int = 64
    embedding_normalize: bool = True

    llm_model_name: str = "google/flan-t5-base"
    llm_max_new_tokens: int = 192
    llm_temperature: float = 0.0
    llm_device: int = -1

    default_top_k: int = 5
    max_top_k: int = 25
    ingestion_batch_size: int = 128

    request_timeout_seconds: int = Field(default=180, ge=10)
    reset_ingested_products_on_startup: bool = False

    @property
    def redis_enabled(self) -> bool:
        return bool(self.redis_url)



def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    payload = {
        "app_name": os.getenv("APP_NAME", Settings.model_fields["app_name"].default),
        "app_env": os.getenv("APP_ENV", Settings.model_fields["app_env"].default),
        "debug": _bool_env("DEBUG", Settings.model_fields["debug"].default),
        "log_level": os.getenv("LOG_LEVEL", Settings.model_fields["log_level"].default),
        "database_url": os.getenv("DATABASE_URL", Settings.model_fields["database_url"].default),
        "redis_url": os.getenv("REDIS_URL"),
        "redis_cache_ttl_seconds": int(
            os.getenv(
                "REDIS_CACHE_TTL_SECONDS",
                str(Settings.model_fields["redis_cache_ttl_seconds"].default),
            )
        ),
        "embedding_model_name": os.getenv(
            "EMBEDDING_MODEL_NAME",
            Settings.model_fields["embedding_model_name"].default,
        ),
        "embedding_batch_size": int(
            os.getenv(
                "EMBEDDING_BATCH_SIZE",
                str(Settings.model_fields["embedding_batch_size"].default),
            )
        ),
        "embedding_normalize": _bool_env(
            "EMBEDDING_NORMALIZE",
            Settings.model_fields["embedding_normalize"].default,
        ),
        "llm_model_name": os.getenv(
            "LLM_MODEL_NAME", Settings.model_fields["llm_model_name"].default
        ),
        "llm_max_new_tokens": int(
            os.getenv(
                "LLM_MAX_NEW_TOKENS",
                str(Settings.model_fields["llm_max_new_tokens"].default),
            )
        ),
        "llm_temperature": float(
            os.getenv(
                "LLM_TEMPERATURE",
                str(Settings.model_fields["llm_temperature"].default),
            )
        ),
        "llm_device": int(
            os.getenv("LLM_DEVICE", str(Settings.model_fields["llm_device"].default))
        ),
        "default_top_k": int(
            os.getenv(
                "DEFAULT_TOP_K",
                str(Settings.model_fields["default_top_k"].default),
            )
        ),
        "max_top_k": int(
            os.getenv("MAX_TOP_K", str(Settings.model_fields["max_top_k"].default))
        ),
        "ingestion_batch_size": int(
            os.getenv(
                "INGESTION_BATCH_SIZE",
                str(Settings.model_fields["ingestion_batch_size"].default),
            )
        ),
        "request_timeout_seconds": int(
            os.getenv(
                "REQUEST_TIMEOUT_SECONDS",
                str(Settings.model_fields["request_timeout_seconds"].default),
            )
        ),
        "reset_ingested_products_on_startup": _bool_env(
            "RESET_INGESTED_PRODUCTS_ON_STARTUP",
            Settings.model_fields["reset_ingested_products_on_startup"].default,
        ),
    }

    try:
        return Settings(**payload)
    except ValidationError as exc:
        raise RuntimeError(f"Invalid application configuration: {exc}") from exc
