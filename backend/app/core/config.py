from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Slim settings for the standalone resume generator."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM — AWS Bedrock
    BEDROCK_MODEL: str = "google.gemma-3-27b-it"
    LLM_MAX_TOKENS: int = 2048
    # Full multi-role resumes need large JSON output; 4096/8192 truncates mid-word.
    RESUME_GENERATION_MAX_TOKENS: int = 16384
    # faithful (default): every source fact is kept, text is never rewritten; page count grows as needed.
    # condensed: legacy page-fit + optional LLM polish (RESUME_LLM_CONDENSE). Never edits the source store.
    RESUME_OUTPUT_MODE: str = "faithful"
    # Page target used only in condensed mode.
    RESUME_TARGET_PAGES: float = 5.0
    # Condensed mode only: grounded LLM readable polish after soft fit. Requires Bedrock.
    RESUME_LLM_CONDENSE: bool = False
    # OCR for image-only PDF pages (needs the tesseract-ocr system package).
    RESUME_OCR_ENABLED: bool = True
    RESUME_OCR_MAX_PAGES: int = 10
    RESUME_OCR_DPI: int = 200
    RESUME_OCR_LANG: str = "eng"
    # Optional deploy stamp so /api/health can prove which build is live.
    APP_BUILD_ID: str = "dev"
    # One-shot, source-checked LLM repair of a weak rule parse, used when line extraction
    # (below) is off or was not chosen. Rejected output is discarded. Golden CI forces it off.
    RESUME_LLM_PARSE_FALLBACK: bool = True
    RESUME_LLM_PARSE_TIMEOUT_SECONDS: float = 45.0
    # Grounded line-number extraction of work history on every resume (Bedrock). The model
    # answers with line numbers; text is copied from the source and checked. The rule parse
    # is kept whenever it explains the source as well, or when Bedrock is unavailable.
    # Golden CI and the test suite force it off (deterministic).
    RESUME_LLM_LINE_EXTRACT: bool = True
    # Reads that fail the quality gate (low coverage, a dated line outside every job
    # heading, merged jobs, many rejected fields) are retried once with those lines named.
    RESUME_LLM_LINE_EXTRACT_MAX_ATTEMPTS: int = 2
    # Post-integrity Bedrock recovery is enabled only when a Bedrock token is configured.
    RESUME_INTEGRITY_RECOVERY: bool = True
    RESUME_INTEGRITY_RECOVERY_MAX_CALLS: int = 4
    RESUME_INTEGRITY_RECOVERY_TIMEOUT_SECONDS: float = 45.0

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
    def faithful_mode(self) -> bool:
        return str(self.RESUME_OUTPUT_MODE or "faithful").strip().lower() != "condensed"

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
