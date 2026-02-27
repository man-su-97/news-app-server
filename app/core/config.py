from dotenv import variables
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    DEBUG: bool = False
    ANTHROPIC_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    AI_REQUESTS_PER_MINUTE: int = 5
    AI_RETRY_ATTEMPTS: int = 3
    AI_RETRY_DELAY_SECONDS: float = 15.0
    INGEST_INTERVAL_MINUTES: int = 5
    PUBLISH_INTERVAL_MINUTES: int = 5
    PUBLISH_OFFSET_SECONDS: int = 30
    AI_MAX_ITEMS_PER_RUN: int = 10
    FEED_TOP_N: int = 20
    DECAY_FRESH: float = 1.00
    DECAY_RECENT: float = 0.75
    DECAY_DAY: float = 0.50
    DECAY_WEEK: float = 0.25
    DECAY_OLD: float = 0.10

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
