"""All configuration comes from environment variables (or a .env file)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class ApiKey:
    """One entry of the key pool. `secret` must never be logged or returned."""

    id: str  # key_1, key_2, ... by position in LLM_API_KEYS
    secret: str

    def __repr__(self) -> str:  # keep secrets out of tracebacks and logs
        return f"ApiKey(id={self.id!r}, secret='***')"


class Settings(BaseSettings):
    # Real environment variables win over files. Both locations work: the repo root
    # (running from backend/) and the current directory.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    # --- required by the assignment ---
    llm_api_keys: str = Field(default="", alias="LLM_API_KEYS")
    database_url: str = Field(default="sqlite:////data/app.db", alias="DATABASE_URL")
    allowed_origins: str = Field(default="http://localhost:3000", alias="ALLOWED_ORIGINS")
    enable_failure_simulation: bool = Field(default=False, alias="ENABLE_FAILURE_SIMULATION")

    # --- LLM ---
    llm_model: str = Field(default="gemini/gemini-3.5-flash-lite", alias="LLM_MODEL")
    # Unset by default: Gemini 3+ deprecates sampling params (LiteLLM warns on every call).
    # If set, it is sent on every call, so it stays a constant part of the cache key.
    temperature: float | None = Field(default=None, alias="TEMPERATURE")
    # Optional thinking control for reasoning models (e.g. "minimal", "low"). Gemini 3.x thinks
    # by default, which adds seconds of latency. Like temperature, it is part of the cache key.
    reasoning_effort: str | None = Field(default=None, alias="REASONING_EFFORT")
    default_system_prompt: str = Field(
        default="You are a helpful assistant.", alias="DEFAULT_SYSTEM_PROMPT"
    )
    max_history_messages: int = Field(default=40, ge=0, alias="MAX_HISTORY_MESSAGES")
    attempt_timeout_seconds: float = Field(default=25, gt=0, alias="ATTEMPT_TIMEOUT_SECONDS")
    request_budget_seconds: float = Field(default=45, gt=0, alias="REQUEST_BUDGET_SECONDS")

    # --- cache ---
    cache_enabled: bool = Field(default=True, alias="CACHE_ENABLED")
    cache_dir: str = Field(default="/data/llm_cache", alias="CACHE_DIR")
    cache_ttl_seconds: int | None = Field(default=None, alias="CACHE_TTL_SECONDS")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def keys(self) -> list[ApiKey]:
        """Comma-separated pool -> key_1, key_2, ... Whitespace and empty entries dropped."""
        secrets = [s.strip() for s in self.llm_api_keys.split(",")]
        secrets = [s for s in secrets if s]
        return [ApiKey(id=f"key_{i}", secret=s) for i, s in enumerate(secrets, start=1)]

    @property
    def origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def database_path(self) -> Path:
        """sqlite:////data/app.db -> /data/app.db ; sqlite:///./app.db -> ./app.db ; bare path ok."""
        url = self.database_url.strip()
        if url.startswith("sqlite:///"):
            return Path(url[len("sqlite:///"):])
        if "://" in url:
            raise ValueError(f"DATABASE_URL must be a sqlite URL or a file path, got {url!r}")
        return Path(url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
