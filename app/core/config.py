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

    # Tell pydantic-settings where to find the .env file.
    # env_file_encoding ensures proper reading of special characters in API keys.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


# Create a single global instance of Settings.
# All other files import this object: from app.core.config import settings
# It is read once at startup — pydantic validates all values immediately.
settings = Settings()
