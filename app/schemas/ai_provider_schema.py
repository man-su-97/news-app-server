"""
app/schemas/ai_provider_schema.py — AI Provider API Schemas
============================================================
Pydantic schemas for the /ai-providers API endpoints.

Three schemas:
  - AIProviderCreate:           POST body when registering a new provider
  - AIProviderResponse:         GET response (api_key intentionally excluded)
  - AIProviderActivateResponse: Response after PATCH /{id}/activate
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# Import constants from the model — single source of truth for valid values
from app.models.ai_provider import PROVIDER_DEFAULT_MODELS, SUPPORTED_PROVIDERS

# Literal type restricts the `provider` field to exactly these string values.
# Pydantic will reject any other string at the API layer with a clear error message.
# Architecture decision: Using Literal here (not just str) gives the Swagger UI
# a dropdown of valid choices and gives developers a clear error if they typo.
_PROVIDER_LITERAL = Literal["anthropic", "openai", "gemini", "gemini_langgraph", "custom"]


class AIProviderCreate(BaseModel):
    """Request body for POST /ai-providers/ — registers a new AI provider config.

    Example request body for Gemini LangGraph (recommended):
    {
        "name": "My Gemini Flash",
        "provider": "gemini_langgraph",
        "model": "gemini-2.0-flash",
        "api_key": "AIza...",
        "base_url": null
    }
    """
    # Field(...) means required (no default).
    # description= text appears in the Swagger UI documentation.
    name: str = Field(..., description="Friendly label, e.g. 'My Gemini Flash'")

    provider: _PROVIDER_LITERAL = Field(
        ...,
        description=(
            "anthropic       — Claude models via Anthropic SDK\n"
            "openai          — GPT models via OpenAI API\n"
            "gemini          — Gemini via Google's OpenAI-compatible endpoint\n"
            "gemini_langgraph— Gemini + LangGraph web search agent (recommended)\n"
            "custom          — Any OpenAI-compatible server (Ollama, vLLM, LM Studio…)"
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

    # model_validator runs AFTER all fields are validated.
    # This cross-field validation checks: if provider="custom", base_url must be set.
    # Returns self so chaining works.
    @model_validator(mode="after")
    def validate_custom_needs_base_url(self) -> "AIProviderCreate":
        if self.provider == "custom" and not self.base_url:
            raise ValueError(
                "base_url is required for provider='custom'. "
                "Example: http://localhost:11434/v1"
            )
        return self


class AIProviderResponse(BaseModel):
    """Response body for GET /ai-providers/ — never exposes the API key.

    Architecture decision: api_key is intentionally NOT included here.
    Once stored, the key can never be retrieved via the API — only used internally.
    If the user needs to change the key, they delete and recreate the config.
    """
    id: int
    name: str
    provider: str
    model: str
    # api_key field is deliberately ABSENT — never expose credentials in API responses
    base_url: str | None
    is_active: bool             # True = this provider is currently active
    created_at: datetime

    model_config = {"from_attributes": True}


class AIProviderActivateResponse(BaseModel):
    """Response body for PATCH /ai-providers/{id}/activate."""
    activated_id: int           # The ID of the provider that is now active
    message: str                # Human-readable confirmation message
