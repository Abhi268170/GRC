from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    environment: str = "development"

    # Database
    database_url: str  # postgresql+asyncpg://user:pass@postgres:5432/db

    # Redis (job queue)
    redis_url: str = "redis://redis:6379/0"

    # Object storage (RustFS, S3-compatible)
    s3_endpoint_url: str = "http://rustfs:9000"
    s3_access_key: str
    s3_secret_key: str
    s3_bucket: str = "grc"
    s3_region: str = "us-east-1"

    # Auth
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 12

    # Bootstrap super admin (created by the migrate service if missing)
    super_admin_email: str
    super_admin_password: str
    super_admin_name: str = "Super Admin"

    # AI service: every model call goes through it (prompts and the provider key live there).
    ai_service_url: str = "http://ai-service:8100"
    ai_service_token: str = ""          # sent as a bearer token; required by the AI service in production
    ai_request_timeout_seconds: float = 900  # one model call can take minutes

    # Maximum estimated AI spend per assessment run (USD). Guided chat and evidence
    # processing pause at this point; producing results is always allowed.
    run_ai_budget_usd: float = 3.0


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
