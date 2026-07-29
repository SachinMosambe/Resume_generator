from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Slim settings for the standalone resume generator."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = "development"

    # LLM — AWS Bedrock
    BEDROCK_MODEL: str = "google.gemma-3-27b-it"
    LLM_MAX_TOKENS: int = 2048
    RESUME_GENERATION_MAX_TOKENS: int = 4096
    INTERVIEW_FALLBACK_MODELS: str = ""
    AWS_BEARER_TOKEN_BEDROCK: str | None = None
    AWS_REGION: str = "ap-south-1"

    # Files
    UPLOAD_DIR: str = "uploads"
    MAX_FILE_SIZE_MB: int = 10

    # CORS — comma-separated origins (e.g. https://app.vercel.app,http://localhost:3000)
    CORS_ORIGINS: str = "http://localhost:3000"

    @property
    def max_file_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024

    @property
    def interview_fallback_model_list(self) -> list[str]:
        return [m.strip() for m in self.INTERVIEW_FALLBACK_MODELS.split(",") if m.strip()]

    @property
    def bedrock_model(self) -> str:
        return self.BEDROCK_MODEL or "google.gemma-3-27b-it"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
