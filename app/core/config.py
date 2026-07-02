from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    DEBUG: bool = False

    # --- AI News Intelligence layer ---
    # Optional so the base app still boots without it; AI endpoints 503 if unset.
    OPENAI_API_KEY: str | None = None
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 1536
    LLM_MODEL: str = "gpt-4o-mini"
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 150
    RETRIEVAL_TOP_K: int = 5

    # Token optimisation for the RAG /ai/ask path.
    LLM_MAX_TOKENS: int = 512  # cap answer length (output tokens)
    RETRIEVAL_MIN_SCORE: float = 0.2  # drop chunks below this cosine similarity
    MAX_CONTEXT_TOKENS: int = 2000  # hard cap on assembled context tokens

    # Rate limiting for the AI endpoints (per client IP, fixed 60s window).
    # Uses Redis; fails open if Redis is unavailable so the app keeps serving.
    REDIS_URL: str = "redis://localhost:6379/0"
    RATE_LIMIT_INDEX_PER_MIN: int = 5
    RATE_LIMIT_SEARCH_PER_MIN: int = 30
    RATE_LIMIT_ASK_PER_MIN: int = 20
    RATE_LIMIT_AGENT_PER_MIN: int = 15

    # LangGraph agent
    AGENT_MAX_ITERATIONS: int = 6

    # Safety: block prompt-injection attempts and redact PII from AI inputs.
    SAFETY_ENABLED: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
