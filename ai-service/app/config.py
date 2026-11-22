from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"

    # The model provider. Without a key the service starts, reports "degraded" and answers 503.
    anthropic_api_key: str = ""
    ai_model_conversation: str = "claude-sonnet-5-5"  # guided chat, evidence, quick tasks
    ai_model_analysis: str = "claude-opus-5-5"        # framework parsing, question writing, results

    # Callers must send this as a bearer token. Required outside development.
    ai_service_token: str = ""

    # Model calls running at the same time, across all requests of this process.
    ai_max_concurrent_calls: int = 16
    # Retries by the provider SDK on rate limits, timeouts and server errors.
    ai_max_retries: int = 3

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @model_validator(mode="after")
    def _production_needs_a_token(self) -> "Settings":
        if self.is_production and len(self.ai_service_token) < 24:
            raise ValueError("AI_SERVICE_TOKEN must be set to a long random value in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
