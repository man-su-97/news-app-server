from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.ai_provider import PROVIDER_DEFAULT_MODELS, SUPPORTED_PROVIDERS

_PROVIDER_LITERAL = Literal[
    "anthropic", "openai", "gemini", "gemini_langgraph", "gemini_multimodal", "custom"
]


class AIProviderCreate(BaseModel):
    """After creating, call `PATCH /ai-providers/{id}/activate` to make it live."""
    name: str = Field(..., description="Friendly label, e.g. 'My Gemini Flash'", examples=["My Gemini Flash"])

    provider: _PROVIDER_LITERAL = Field(
        ...,
        description=(
            "**gemini_multimodal** — Gemini + LangGraph, multimodal image support, structured output *(recommended)*  \n"
            "**gemini_langgraph** — Gemini + LangGraph web search agent  \n"
            "**gemini** — Gemini via Google's OpenAI-compatible endpoint  \n"
            "**anthropic** — Claude models via Anthropic SDK  \n"
            "**openai** — GPT models via OpenAI API  \n"
            "**custom** — Any OpenAI-compatible server (Ollama, vLLM, LM Studio)"
        ),
        examples=["gemini_multimodal"],
    )

    model: str = Field(
        ...,
        description=(
            "Model identifier for the chosen provider.  \n"
            "**gemini_langgraph / gemini**: `gemini-2.0-flash`, `gemini-2.5-flash`  \n"
            "**anthropic**: `claude-haiku-4-5-20251001`  \n"
            "**openai**: `gpt-4o-mini`  \n"
            "**custom**: your model name as configured in the server"
        ),
        examples=["gemini-2.5-flash"],
    )

    api_key: str = Field(
        ...,
        description="API key for the provider. Never returned in any response after saving.",
        examples=["AIzaSy..."],
    )

    base_url: str | None = Field(
        default=None,
        description=(
            "Override the provider base URL.  \n"
            "**Required** for `custom` (e.g. `http://localhost:11434/v1` for Ollama).  \n"
            "**gemini** is pre-filled automatically if omitted.  \n"
            "Leave `null` for anthropic, openai, gemini_langgraph."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "name": "Gemini 2.5 Flash",
                "provider": "gemini",
                "model": "gemini-2.5-flash",
                "api_key": "AIzaSy...",
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            }
        }
    }

    @model_validator(mode="after")
    def validate_custom_needs_base_url(self) -> "AIProviderCreate":
        if self.provider == "custom" and not self.base_url:
            raise ValueError(
                "base_url is required for provider='custom'. "
                "Example: http://localhost:11434/v1"
            )
        return self


class AIProviderResponse(BaseModel):
    id: int
    name: str
    provider: str
    model: str
    base_url: str | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AIProviderActivateResponse(BaseModel):
    activated_id: int
    message: str
