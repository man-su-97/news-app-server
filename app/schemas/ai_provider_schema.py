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
        examples=["gemini-2.0-flash"],
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
        examples=[None],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Gemini Multimodal LangGraph (recommended)",
                    "value": {
                        "name": "My Gemini Multimodal",
                        "provider": "gemini_multimodal",
                        "model": "gemini-2.0-flash",
                        "api_key": "AIzaSy...",
                        "base_url": None,
                    },
                },
                {
                    "summary": "Gemini LangGraph",
                    "value": {
                        "name": "My Gemini Flash",
                        "provider": "gemini_langgraph",
                        "model": "gemini-2.0-flash",
                        "api_key": "AIzaSy...",
                        "base_url": None,
                    },
                },
                {
                    "summary": "Anthropic Claude",
                    "value": {
                        "name": "My Claude Haiku",
                        "provider": "anthropic",
                        "model": "claude-haiku-4-5-20251001",
                        "api_key": "sk-ant-...",
                        "base_url": None,
                    },
                },
                {
                    "summary": "OpenAI GPT",
                    "value": {
                        "name": "My GPT-4o Mini",
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "api_key": "sk-...",
                        "base_url": None,
                    },
                },
                {
                    "summary": "Custom / Ollama",
                    "value": {
                        "name": "Local Llama3",
                        "provider": "custom",
                        "model": "llama3.2",
                        "api_key": "ollama",
                        "base_url": "http://localhost:11434/v1",
                    },
                },
            ]
        }
    }

    # model_validator runs AFTER all fields are validated.
    # This cross-field validation checks: if provider="custom", base_url must be set.
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
