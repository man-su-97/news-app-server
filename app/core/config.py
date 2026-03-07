from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    DEBUG: bool = False
    ANTHROPIC_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    OLLAMA_URL: str = "http://localhost:11434/v1"
    OLLAMA_MODEL: str | None = None
    AI_REQUESTS_PER_MINUTE: int = 5       # fallback default (overridden per provider below)
    AI_RETRY_ATTEMPTS: int = 3
    AI_RETRY_DELAY_SECONDS: float = 15.0
    INGEST_INTERVAL_MINUTES: int = 5
    PUBLISH_INTERVAL_MINUTES: int = 5
    PUBLISH_OFFSET_SECONDS: int = 30
    AI_MAX_ITEMS_PER_RUN: int = 10        # fallback default (overridden per provider below)
    FEED_TOP_N: int = 20

    # Ollama is local — no API rate limits, process as many as needed
    OLLAMA_REQUESTS_PER_MINUTE: int = 60
    OLLAMA_MAX_ITEMS_PER_RUN: int = 50

    # GPU safety for local Ollama (single GPU like RTX 3060)
    # Concurrency=1: GPU can only run 1 inference at a time — no point queuing more
    OLLAMA_CONCURRENCY: int = 1
    # Process articles in batches with a cooldown pause between each batch
    # Prevents continuous GPU load and thermal throttling
    OLLAMA_BATCH_SIZE: int = 10
    OLLAMA_BATCH_COOLDOWN_SECONDS: float = 15.0

    # Cloud free-tier APIs (Gemini AI Studio, Anthropic free) — be conservative
    CLOUD_REQUESTS_PER_MINUTE: int = 3
    CLOUD_MAX_ITEMS_PER_RUN: int = 5
    DECAY_FRESH: float = 1.00
    DECAY_RECENT: float = 0.75
    DECAY_DAY: float = 0.50
    DECAY_WEEK: float = 0.25
    DECAY_OLD: float = 0.10

    # Google Custom Search API (free tier: 100 queries/day)
    GOOGLE_SEARCH_API_KEY: str | None = None
    GOOGLE_SEARCH_ENGINE_ID: str | None = None
    # How many reference URLs to fetch per article (max 10 per Google API call)
    GOOGLE_SEARCH_RESULTS_PER_ARTICLE: int = 3
    # Delay between consecutive Google Search requests to protect free-tier quota
    GOOGLE_SEARCH_DELAY_SECONDS: float = 1.0

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8")


settings = Settings()


# .env file
#    ↓
# Environment variables
#    ↓
# Pydantic validation
#    ↓
# Typed settings object
#    ↓
# Used across app
