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


SUPPORTED_PROVIDERS = {"anthropic", "openai", "gemini", "gemini_langgraph", "gemini_multimodal", "ollama", "custom"}


PROVIDER_BASE_URLS: dict[str, str | None] = {
    "anthropic": None,                                          
    "openai": None,                                             
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "gemini_langgraph": None,                                   
    "gemini_multimodal": None,                                  
    "ollama": "http://localhost:11434/v1",                      
    "custom": None,                                             
}

PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-haiku-4-5-20251001",                          
    "openai": "gpt-4o-mini",                                           
    "gemini": "gemini-2.0-flash",                                      
    "gemini_langgraph": "gemini-2.0-flash",                            
    "gemini_multimodal": "gemini-2.0-flash",                           
    "ollama": "dengcao/Qwen3-30B-A3B-Instruct-2507:latest",            
    "custom": "your-model-name",                                       
}


class AIProviderConfig(Base):
    """One row = one AI provider configuration stored in the database.

    At most ONE row has is_active=True at any time.
    That row is loaded by IngestionService at the start of each ingest run.
    """

    __tablename__ = "ai_provider_configs"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)

    provider: Mapped[str] = mapped_column(String(50), nullable=False)

    model: Mapped[str] = mapped_column(String(100), nullable=False)

    api_key: Mapped[str] = mapped_column(String(500), nullable=False)

    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
