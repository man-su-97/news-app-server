from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Supported provider identifiers — validated at the API layer, not the DB layer,
# so adding a new provider never requires a schema migration.
# "anthropic" → Anthropic SDK (Claude models)
# "openai"    → OpenAI API  (GPT models)
# "gemini"    → Google Gemini via its OpenAI-compatible endpoint
# "custom"    → Any OpenAI-compatible server (Ollama, vLLM, LM Studio, etc.)
SUPPORTED_PROVIDERS = {"anthropic", "openai", "gemini", "custom"}

# Base URLs used when the user does not supply one
PROVIDER_BASE_URLS: dict[str, str | None] = {
    "anthropic": None,   # Anthropic SDK handles this internally
    "openai": None,      # openai SDK default
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "custom": None,      # must be supplied by the user
}

# Suggested default model IDs shown in documentation / error messages
PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-1.5-flash",
    "custom": "your-model-name",
}


class AIProviderConfig(Base):
    __tablename__ = "ai_provider_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # "anthropic" | "openai" | "gemini" | "custom"
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    # Stored as plaintext. In production deployments encrypt with pgcrypto or
    # application-level encryption before storing.
    api_key: Mapped[str] = mapped_column(String(500), nullable=False)
    # OpenAI-compatible base URL. Required for "custom"; auto-filled for "gemini".
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Only one row may have is_active=True at a time — enforced by activate().
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
