"""
app/models/ai_provider.py — AI Provider Configuration Table
============================================================
Stores AI provider credentials and settings in the database.
This allows changing the AI provider at runtime via the API without
restarting the server or editing .env files.

Why store AI config in the DB instead of .env?
  - Runtime switching: call PATCH /ai-providers/{id}/activate to switch providers
    without redeployment. Changes take effect on the next ingestion run.
  - Multiple configs: you can store configs for several providers and switch
    between them (e.g. switch from Claude to Gemini if one has an outage).
  - Only ONE provider can be active at a time (enforced by a partial unique index
    in the migration and by the activate() method in the repository).

Supported providers:
  "anthropic"        → Claude models (Haiku, Sonnet, Opus)
  "openai"           → GPT models (gpt-4o, gpt-4o-mini)
  "gemini"           → Gemini via its OpenAI-compatible REST endpoint
  "gemini_langgraph" → Gemini + LangGraph agent with DuckDuckGo search (RECOMMENDED)
  "ollama"           → Local Ollama server (auto base_url, no real api_key needed)
  "custom"           → Any OpenAI-compatible server (vLLM, LM Studio, remote Ollama)
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Set of valid provider strings — validated in the API schema layer.
# Adding a new provider here is step 1; also update provider_factory.py.
SUPPORTED_PROVIDERS = {"anthropic", "openai", "gemini", "gemini_langgraph", "gemini_multimodal", "ollama", "custom"}

# Default base URLs for each provider.
# The user can override these when creating a config, but these are the defaults.
# "anthropic" and "openai" use None because their SDKs know the URL internally.
# "gemini" needs an explicit URL because we use the OpenAI-compatible endpoint.
# "gemini_langgraph" uses None because langchain-google-genai handles auth natively.
PROVIDER_BASE_URLS: dict[str, str | None] = {
    "anthropic": None,                                          # Anthropic SDK handles base URL internally
    "openai": None,                                             # OpenAI SDK uses api.openai.com/v1 by default
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "gemini_langgraph": None,                                   # langchain-google-genai uses google-auth natively
    "gemini_multimodal": None,                                  # same — langchain-google-genai handles auth natively
    "ollama": "http://localhost:11434/v1",                      # Local Ollama OpenAI-compatible endpoint
    "custom": None,                                             # User MUST supply this (validated in schema)
}

# Suggested model IDs shown in documentation and error messages.
# These are sensible defaults — users can override with any model their provider supports.
PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-haiku-4-5-20251001",                          # Fast and cheap Claude model
    "openai": "gpt-4o-mini",                                           # Fast and cheap GPT model
    "gemini": "gemini-2.0-flash",                                      # Fast Gemini model
    "gemini_langgraph": "gemini-2.0-flash",                            # LangGraph + DuckDuckGo search
    "gemini_multimodal": "gemini-2.0-flash",                           # Multimodal + structured output (RECOMMENDED)
    "ollama": "dengcao/Qwen3-30B-A3B-Instruct-2507:latest",            # Local Ollama default model
    "custom": "your-model-name",                                       # Placeholder for user to fill in
}


class AIProviderConfig(Base):
    """One row = one AI provider configuration stored in the database.

    At most ONE row has is_active=True at any time.
    That row is loaded by IngestionService at the start of each ingest run.
    """

    __tablename__ = "ai_provider_configs"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Friendly display name chosen by the user, e.g. "My Gemini Flash"
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # One of SUPPORTED_PROVIDERS above — determines which Python class to use
    provider: Mapped[str] = mapped_column(String(50), nullable=False)

    # Model identifier for the chosen provider, e.g. "gemini-2.0-flash"
    model: Mapped[str] = mapped_column(String(100), nullable=False)

    # The API key for this provider.
    # Architecture decision: stored as plaintext here for simplicity.
    # Production systems should encrypt this with pgcrypto or a secrets manager.
    api_key: Mapped[str] = mapped_column(String(500), nullable=False)

    # Optional custom base URL (required for "custom", optional for others).
    # Examples:
    #   Ollama:    http://localhost:11434/v1
    #   LM Studio: http://localhost:1234/v1
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Whether this config is currently the active provider.
    # Only one row should have is_active=True at a time.
    # The DB enforces this with a partial unique index (see migration).
    # The activate() method in the repo also enforces this.
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
