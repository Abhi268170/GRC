from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # "production" turns on the strict checks below, Secure cookies, and turns the API docs off.
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

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

    # Abuse limits on the endpoints anyone can call. Windows are in seconds.
    login_max_failures_per_email: int = 10       # failed logins for one email per window
    login_max_attempts_per_ip: int = 100         # logins from one address per window
    login_window_seconds: int = 900
    signup_enabled: bool = True                  # self-service signup; turn off to onboard companies by hand
    signup_max_per_ip: int = 5                   # each signup creates a database
    signup_max_total: int = 60                   # across all addresses
    signup_window_seconds: int = 3600
    max_request_bytes: int = 32 * 1024 * 1024    # any request body (the largest upload is 30 MB)

    # Company databases: each open one holds its own connection pool, so only the most recently
    # used stay open. Pool sizes are per company and per process.
    tenant_pool_cache_size: int = 50
    tenant_pool_size: int = 5
    tenant_pool_overflow: int = 5

    # Background worker: jobs running at the same time in one worker process.
    worker_max_jobs: int = 8

    # AI service: every model call goes through it (prompts and the provider key live there).
    ai_service_url: str = "http://ai-service:8100"
    ai_service_token: str = ""          # sent as a bearer token; required by the AI service in production
    ai_request_timeout_seconds: float = 900  # one model call can take minutes

    # Maximum estimated AI spend per assessment run (USD). Guided chat and evidence
    # processing pause at this point; producing results is always allowed.
    run_ai_budget_usd: float = 3.0
    # Maximum estimated AI spend per company per calendar month (USD), across all its runs.
    tenant_ai_budget_usd_month: float = 100.0
    # Runs a company can have open (not approved) at the same time. Each start costs an AI call.
    max_open_runs_per_tenant: int = 25


    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def unsafe_settings(self) -> list[str]:
        """Settings that must not reach production: placeholder or short secrets, missing tokens."""
        problems = []
        if len(self.jwt_secret) < 32 or "change-me" in self.jwt_secret:
            problems.append("JWT_SECRET must be a random value of at least 32 characters")
        if len(self.super_admin_password) < 12 or "change-me" in self.super_admin_password:
            problems.append("SUPER_ADMIN_PASSWORD must be at least 12 characters and not a placeholder")
        if "change-me" in self.s3_secret_key:
            problems.append("S3_SECRET_KEY is still a placeholder")
        if "change-me" in self.database_url:
            problems.append("the database password is still a placeholder")
        if len(self.ai_service_token) < 24:
            problems.append("AI_SERVICE_TOKEN must be set (at least 24 characters)")
        return problems

    @model_validator(mode="after")
    def _refuse_unsafe_production(self) -> "Settings":
        if self.is_production and (problems := self.unsafe_settings()):
            raise ValueError("Refusing to start in production: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
