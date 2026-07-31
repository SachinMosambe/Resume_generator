from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Slim settings for the standalone resume generator."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = "development"

    # LLM — AWS Bedrock
    BEDROCK_MODEL: str = "google.gemma-3-27b-it"
    LLM_MAX_TOKENS: int = 2048
    # Full multi-role resumes need large JSON output; 4096/8192 truncates mid-word.
    RESUME_GENERATION_MAX_TOKENS: int = 16384
    # Target readable client resume length (pages). Soft fit + LLM readable polish.
    # Long careers scale toward ~5 pages with essence kept (not 2-page stubs).
    RESUME_TARGET_PAGES: float = 5.0
    # When true (default), run grounded LLM readable polish after soft fit.
    # Skills always stay exact source tokens. Full rewrite is still blocked for long resumes.
    RESUME_LLM_CONDENSE: bool = True
    # Optional deploy stamp so /api/health can prove which build is live.
    APP_BUILD_ID: str = "dev"
    # When false (default), skip slow full-document LLM polish loops.
    RESUME_LLM_POLISH: bool = False

    # Multi-agent pipeline (extract -> plan -> write -> critique -> refine).
    # Runs inside the same service; enable per-deploy to compare against classic.
    RESUME_AGENT_PIPELINE: bool = False
    AGENT_MAX_ROUNDS: int = 2
    AGENT_MAX_LLM_CALLS: int = 8
    AGENT_SCORE_THRESHOLD: float = 85.0
    AGENT_TIME_BUDGET_SECONDS: float = 90.0
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
