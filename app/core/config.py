"""
app/core/config.py — Application Configuration
================================================
Reads environment variables (from .env file or the OS environment) and
exposes them as a typed Python object called `settings`.

Why use this pattern?
  - Type safety: if DATABASE_URL is missing, the app crashes immediately with
    a clear error instead of failing mysteriously later.
  - Single source of truth: every other file imports `settings` from here
    instead of calling os.getenv() scattered everywhere.
  - Testability: tests can override settings by patching this object.

Architecture decision: We use pydantic-settings (BaseSettings) which
automatically reads from .env files and environment variables, validates
types, and raises clear errors for missing required fields.
"""

# BaseSettings is the pydantic-settings class that reads .env files
# and environment variables automatically.
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Required ---
    # The full PostgreSQL connection string. Example:
    #   postgresql+asyncpg://user:password@localhost:5432/newsdb
    # The +asyncpg part tells SQLAlchemy to use the async PostgreSQL driver.
    # This field has NO default — the app will refuse to start without it.
    DATABASE_URL: str

    # --- Optional with defaults ---
    # When True, SQLAlchemy prints every SQL query it runs.
    # Useful during development to see what's happening in the DB.
    # Set DEBUG=true in .env to enable.
    DEBUG: bool = False

    # Legacy env-var fallback for the Anthropic (Claude) AI provider.
    # If no AI provider is configured in the DB, the app checks this var.
    # New deployments should use POST /ai-providers instead.
    ANTHROPIC_API_KEY: str | None = None

    # Gemini env-var fallback — takes priority over ANTHROPIC_API_KEY.
    # When set, activates GeminiLangGraphProvider (LangGraph + DuckDuckGo search).
    # This is the recommended default for this crime news app.
    GEMINI_API_KEY: str | None = None

    # Maximum AI API calls per minute across the entire ingestion batch.
    # This is enforced by a single PROCESS-LEVEL rate limiter shared by all
    # concurrent sources and both pipeline stages (filter + post-process).
    #
    # Free tier defaults (set in .env to match your plan):
    #   gemini-2.5-flash       →  5 RPM  (default — 2 calls/article × 2 sources = tight)
    #   gemini-2.0-flash       → 15 RPM
    #   gemini-2.0-flash-lite  → 30 RPM
    #   anthropic claude-haiku →  5 RPM
    #   openai gpt-4o-mini     → 500 RPM
    #
    # Rule of thumb for free tier:
    #   Each article uses 2 API calls (stage 1 filter + stage 2 post-process).
    #   At RPM=5 that's ~2.5 articles/min = 150 articles/hr.
    #   Keep RPM ≤ (free_tier_rpm / num_active_sources) to avoid 429s.
    #
    # Paid plans: set to 0 for unlimited (no artificial delay added).
    AI_REQUESTS_PER_MINUTE: int = 5

    # Retry settings for transient AI API errors (HTTP 429, quota exhausted).
    # On rate limit errors the pipeline retries with exponential backoff:
    #   attempt 1 → wait AI_RETRY_DELAY_SECONDS
    #   attempt 2 → wait AI_RETRY_DELAY_SECONDS × 2
    # After AI_RETRY_ATTEMPTS the article is marked failed (not dropped silently).
    AI_RETRY_ATTEMPTS: int = 3
    AI_RETRY_DELAY_SECONDS: float = 15.0

    # --- Scheduler intervals ---
    # How often to run each background job. Change without code edits.
    INGEST_INTERVAL_MINUTES: int = 5
    PUBLISH_INTERVAL_MINUTES: int = 5
    # Seconds to wait after ingestion starts before running publish.
    # Gives the ingestion job time to write post_processed_articles first.
    PUBLISH_OFFSET_SECONDS: int = 30

    # --- Feed size ---
    # Number of articles selected by PublishingService for the final_articles feed.
    # 20 is good for a mobile card carousel; increase to 50 for a web dashboard.
    FEED_TOP_N: int = 20

    # --- DuckDuckGo web search ---
    # Timeout in seconds for each DuckDuckGo call during Stage 2 post-processing.
    # If the search hangs longer than this, it is cancelled gracefully and the
    # article proceeds without reference URLs (non-fatal).
    DUCKDUCKGO_TIMEOUT_SECONDS: float = 10.0

    # --- Time-decay ranking (PublishingService) ---
    # rank_score = imp_score × decay_factor  (result range: 0.1 – 100.0)
    # Lower decay_factor = older articles ranked lower in the final feed.
    DECAY_FRESH: float = 1.00     # published < 6 hours ago
    DECAY_RECENT: float = 0.75    # published 6-24 hours ago
    DECAY_DAY: float = 0.50       # published 1-3 days ago
    DECAY_WEEK: float = 0.25      # published 3-7 days ago
    DECAY_OLD: float = 0.10       # published > 7 days ago

    # Tell pydantic-settings where to find the .env file.
    # env_file_encoding ensures proper reading of special characters in API keys.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


# Create a single global instance of Settings.
# All other files import this object: from app.core.config import settings
# It is read once at startup — pydantic validates all values immediately.
settings = Settings()
