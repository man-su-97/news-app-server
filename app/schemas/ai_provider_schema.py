from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.ai_provider import PROVIDER_DEFAULT_MODELS, SUPPORTED_PROVIDERS

_PROVIDER_LITERAL = Literal["anthropic", "openai", "gemini", "custom"]


class AIProviderCreate(BaseModel):
    name: str = Field(..., description="Friendly label, e.g. 'My GPT-4o'")
    provider: _PROVIDER_LITERAL = Field(
        ...,
        description=(
            "anthropic — Claude models via Anthropic SDK\n"
            "openai    — GPT models via OpenAI API\n"
            "gemini    — Gemini models via Google's OpenAI-compatible endpoint\n"
            "custom    — Any OpenAI-compatible server (Ollama, vLLM, LM Studio…)"
        ),
    )
    model: str = Field(
        ...,
        description=(
            "Model identifier for the chosen provider. "
            f"Defaults by provider: {PROVIDER_DEFAULT_MODELS}"
        ),
    )
    api_key: str = Field(..., description="API key for the provider")
    base_url: str | None = Field(
        default=None,
        description=(
            "Override the provider base URL. "
            "Required for 'custom'. "
            "Gemini is pre-filled automatically if omitted. "
            "Example for Ollama: http://localhost:11434/v1"
        ),
    )

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
    # api_key intentionally omitted — never expose credentials in responses
    base_url: str | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AIProviderActivateResponse(BaseModel):
    activated_id: int
    message: str
