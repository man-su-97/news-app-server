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

    The new config starts inactive. Call PATCH /{id}/activate to use it.

    Provider quick-reference:
    - anthropic: model="claude-haiku-4-5-20251001"  api_key=sk-ant-...
    - openai:    model="gpt-4o-mini"                 api_key=sk-...
    - gemini:    model="gemini-1.5-flash"             api_key=AIza...  (base_url auto-filled)
    - custom:    model="llama3.2"  base_url="http://localhost:11434/v1"  api_key="ollama"
    """
    return await repo.create(payload)


@router.get("/", response_model=list[AIProviderResponse])
async def list_ai_providers(
    repo: AIProviderRepository = Depends(get_ai_provider_repo),
):
    """List all registered AI provider configs. API keys are never included in responses."""
    return await repo.get_all()


@router.get("/active", response_model=AIProviderResponse | None)
async def get_active_provider(
    repo: AIProviderRepository = Depends(get_ai_provider_repo),
):
    """Return the currently active provider, or null if none is set.

    When null, ingestion falls back to ANTHROPIC_API_KEY env var (if set),
    then runs deterministic-only normalization.
    """
    return await repo.get_active()


@router.get("/{provider_id}", response_model=AIProviderResponse)
async def get_ai_provider(
    provider_id: int,
    repo: AIProviderRepository = Depends(get_ai_provider_repo),
):
    config = await repo.get_by_id(provider_id)
    if config is None:
        raise HTTPException(status_code=404, detail="AI provider config not found")
    return config


@router.patch("/{provider_id}/activate", response_model=AIProviderActivateResponse)
async def activate_ai_provider(
    provider_id: int,
    repo: AIProviderRepository = Depends(get_ai_provider_repo),
):
    """Set this provider as the active one used for AI normalization fallback.

    All other providers are deactivated atomically. The change takes effect on
    the next ingest run (scheduler fires every 5 minutes, or trigger manually
    via POST /ingest).
    """
    config = await repo.activate(provider_id)
    if config is None:
        raise HTTPException(status_code=404, detail="AI provider config not found")
    return AIProviderActivateResponse(
        activated_id=config.id,
        message=f"'{config.name}' ({config.provider}:{config.model}) is now active",
    )


@router.delete("/active", status_code=204)
async def deactivate_all_providers(
    repo: AIProviderRepository = Depends(get_ai_provider_repo),
):
    """Clear the active provider. Ingestion reverts to env-var fallback or deterministic-only."""
    await repo.deactivate_all()


@router.delete("/{provider_id}", status_code=204)
async def delete_ai_provider(
    provider_id: int,
    repo: AIProviderRepository = Depends(get_ai_provider_repo),
):
    deleted = await repo.delete(provider_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="AI provider config not found")
