from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", str(PROJECT_ROOT / ".env"), str(BACKEND_DIR / ".env")),
        extra="ignore",
    )

    app_name: str = "Yunchuan Zhihui MVP"
    app_env: str = "local"
    debug: bool = True
    schema_version: str = "1.0"
    api_v1_prefix: str = "/api/v1"
    frontend_origin: str = "http://localhost:5173"
    jwt_secret_key: str = "local-development-secret-change-me"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    cookie_secure: bool = False
    redis_url: str = "redis://localhost:6379/0"
    initial_admin_username: str = "admin"
    initial_admin_password: str | None = None
    initial_admin_display_name: str = "系统管理员"

    database_url: str = Field(
        default="mysql+pymysql://yunchuan:yunchuan_dev@localhost:3306/yunchuan_zhihui"
    )
    chroma_host: str = "localhost"
    chroma_port: int = 8000

    openai_api_base: str | None = None
    openai_api_key: str | None = None
    primary_llm_model: str | None = None
    primary_review_model: str | None = None
    secondary_review_model: str | None = None
    embedding_model: str | None = None
    llm_timeout_seconds: int = 30
    allow_fixture_llm: bool = False
    enable_evaluation_overrides: bool = False
    review_rule_version: str = "review-v1"

    log_level: str = "INFO"
    enable_full_debug_payloads: bool = False

    def validate_auth_config(self) -> None:
        if self.app_env not in {"local", "test"} and (
            self.jwt_secret_key == "local-development-secret-change-me"
            or len(self.jwt_secret_key.encode("utf-8")) < 32
        ):
            raise RuntimeError("JWT_SECRET_KEY must be a non-default secret of at least 32 bytes")

@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
