"""
app/api/routes_ai_providers.py — AI Provider Configuration Endpoints
=====================================================================
HTTP API for managing AI provider configurations.

An "AI provider" is the AI service used to:
  1. Normalize articles (extract title, url, description from messy raw data)
  2. Enrich articles (classify crime type, extract location, score importance)

Endpoints:
  POST /ai-providers/              → register a new provider config
  GET  /ai-providers/              → list all configs (no API keys in response)
  GET  /ai-providers/active        → get the currently active provider
  GET  /ai-providers/{id}          → get one config by ID
  PATCH /ai-providers/{id}/activate → set this as the active provider
  DELETE /ai-providers/active      → deactivate all (fall back to env vars)
  DELETE /ai-providers/{id}        → delete a config

Typical setup flow for a new deployment:
  1. POST /ai-providers/ with provider="gemini_langgraph", api_key="AIza..."
  2. PATCH /ai-providers/1/activate
  3. POST /ingest/ with source_id=1 to test it
"""

from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import get_ai_provider_repo
from app.repositories.ai_provider_repo import AIProviderRepository
from app.schemas.ai_provider_schema import (
    AIProviderActivateResponse,
    AIProviderCreate,
    AIProviderResponse,
)

router = APIRouter()


@router.post("/", response_model=AIProviderResponse, status_code=201)
async def create_ai_provider(
    payload: AIProviderCreate,
    repo: AIProviderRepository = Depends(get_ai_provider_repo),
):
    """Register a new AI provider configuration.

    The new config starts INACTIVE — you must call PATCH /{id}/activate to use it.
    This prevents accidentally switching providers on creation.

    Provider quick-reference:
      gemini_langgraph: provider="gemini_langgraph" model="gemini-2.0-flash" api_key="AIza..."
      anthropic:        provider="anthropic" model="claude-haiku-4-5-20251001" api_key="sk-ant-..."
      openai:           provider="openai" model="gpt-4o-mini" api_key="sk-..."
      custom (Ollama):  provider="custom" model="llama3.2" base_url="http://localhost:11434/v1" api_key="ollama"

    Note: api_key is STORED but NEVER returned in any response (security).
    """
    return await repo.create(payload)


@router.get("/", response_model=list[AIProviderResponse])
async def list_ai_providers(
    repo: AIProviderRepository = Depends(get_ai_provider_repo),
):
    """List all registered AI provider configurations.

    API keys are intentionally excluded from the response.
    Ordered by creation date, newest first.
    """
    return await repo.get_all()


@router.get("/active", response_model=AIProviderResponse | None)
async def get_active_provider(
    repo: AIProviderRepository = Depends(get_ai_provider_repo),
):
    """Return the currently active AI provider, or null if none is set.

    When null:
      - If GEMINI_API_KEY is set in .env → GeminiLangGraphProvider is used
      - If ANTHROPIC_API_KEY is set in .env → AnthropicProvider is used
      - Otherwise → deterministic-only normalization (no AI enrichment)

    IMPORTANT: This endpoint MUST be declared BEFORE "/{provider_id}"
    in the code. If it comes after, FastAPI would try to parse "active"
    as an integer ID and return a 422 validation error.
    """
    return await repo.get_active()


@router.get("/{provider_id}", response_model=AIProviderResponse)
async def get_ai_provider(
    provider_id: int,
    repo: AIProviderRepository = Depends(get_ai_provider_repo),
):
    """Get a single AI provider config by ID."""
    config = await repo.get_by_id(provider_id)
    if config is None:
        raise HTTPException(status_code=404, detail="AI provider config not found")
    return config


@router.patch("/{provider_id}/activate", response_model=AIProviderActivateResponse)
async def activate_ai_provider(
    provider_id: int,
    repo: AIProviderRepository = Depends(get_ai_provider_repo),
):
    """Set this provider as the active one for AI normalization and enrichment.

    This deactivates all other providers atomically in a single transaction.
    The change takes effect on the NEXT ingestion run.
    To test immediately: call POST /ingest/ after activating.

    Only one provider can be active at a time.
    """
    config = await repo.activate(provider_id)
    if config is None:
        raise HTTPException(status_code=404, detail="AI provider config not found")
    return AIProviderActivateResponse(
        activated_id=config.id,
        # Human-readable confirmation: "'My Gemini Flash' (gemini_langgraph:gemini-2.0-flash) is now active"
        message=f"'{config.name}' ({config.provider}:{config.model}) is now active",
    )


@router.delete("/active", status_code=204)
async def deactivate_all_providers(
    repo: AIProviderRepository = Depends(get_ai_provider_repo),
):
    """Deactivate all providers. Ingestion falls back to env vars or deterministic-only.

    Use this to temporarily disable AI processing without deleting configs.
    status_code=204: HTTP 204 No Content — success but nothing to return.
    """
    await repo.deactivate_all()


@router.delete("/{provider_id}", status_code=204)
async def delete_ai_provider(
    provider_id: int,
    repo: AIProviderRepository = Depends(get_ai_provider_repo),
):
    """Delete a provider configuration permanently.

    If the deleted config was active, ingestion falls back to env vars.
    Returns 404 if the config doesn't exist.
    status_code=204: success with no response body.
    """
    deleted = await repo.delete(provider_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="AI provider config not found")
