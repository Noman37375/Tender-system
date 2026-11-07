from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from the environment (PRD §17). Secrets have no defaults."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: Literal["development", "test", "production"] = "development"
    DATABASE_URL: str
    CHECKPOINT_DB_URL: str = ""
    JWT_SECRET: str
    JWT_ACCESS_MINUTES: int = 30
    JWT_REFRESH_DAYS: int = 7
    CORS_ORIGINS: str = "http://localhost:3000"

    LLM_PROVIDER: Literal["openai", "anthropic"] = "openai"
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    LLM_MODEL_FAST: str = ""
    LLM_MODEL_STRONG: str = ""
    EMBEDDING_PROVIDER: Literal["openai"] = "openai"
    EMBEDDING_MODEL: str = ""
    LLM_CONCURRENCY: int = 4
    LLM_TIMEOUT_SECONDS: int = 120

    MAX_AUTO_REVISIONS: int = 1
    RUN_BUDGET_USD: float = 5.00
    MAX_UPLOAD_MB: int = 50
    STORAGE_BACKEND: Literal["local", "s3"] = "local"
    STORAGE_PATH: str = "/data/files"
    S3_BUCKET: str = ""
    S3_ENDPOINT: str = ""
    TRACING_ENABLED: bool = False

    def llm_keys_missing(self) -> list[str]:
        """Names of API keys needed by the configured providers that are not set."""
        missing: list[str] = []
        llm_key = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}[self.LLM_PROVIDER]
        embed_key = {"openai": "OPENAI_API_KEY"}[self.EMBEDDING_PROVIDER]
        for key in dict.fromkeys([llm_key, embed_key]):
            if not getattr(self, key):
                missing.append(key)
        return missing


@lru_cache
def get_settings() -> Settings:
    return Settings()
