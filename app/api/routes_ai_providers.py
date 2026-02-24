from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import get_ai_provider_repo
from app.repositories.ai_provider_repo import AIProviderRepository
from app.schemas.ai_provider_schema import (
    AIProviderActivateResponse,
    AIProviderCreate,
    AIProviderResponse,
)

router = APIRouter()


@router.post(
    "/",
    response_model=AIProviderResponse,
    status_code=201,
    summary="Register an AI provider",
)
async def create_ai_provider(
    payload: AIProviderCreate,
    repo: AIProviderRepository = Depends(get_ai_provider_repo),
):
    """Registers a new AI provider configuration.

    The provider starts inactive. Call `PATCH /{id}/activate` to make it live.
    The `api_key` is stored securely and never returned in any response.
    """
    return await repo.create(payload)


@router.get(
    "/",
    response_model=list[AIProviderResponse],
    summary="List AI providers",
)
async def list_ai_providers(
    repo: AIProviderRepository = Depends(get_ai_provider_repo),
):
    """Returns all registered AI provider configurations. API keys are never included."""
    return await repo.get_all()


@router.get(
    "/active",
    response_model=AIProviderResponse | None,
    summary="Get the active AI provider",
)
async def get_active_provider(
    repo: AIProviderRepository = Depends(get_ai_provider_repo),
):
    """Returns the currently active AI provider, or `null` if none is configured.

    When `null`, the system falls back to the `GEMINI_API_KEY` or
    `ANTHROPIC_API_KEY` environment variables.
    """
    return await repo.get_active()


@router.get(
    "/{provider_id}",
    response_model=AIProviderResponse,
    summary="Get an AI provider by ID",
    responses={404: {"description": "Provider not found"}},
)
async def get_ai_provider(
    provider_id: int,
    repo: AIProviderRepository = Depends(get_ai_provider_repo),
):
    """Returns a single AI provider configuration by its ID."""
    config = await repo.get_by_id(provider_id)
    if config is None:
        raise HTTPException(status_code=404, detail="AI provider not found")
    return config


@router.patch(
    "/{provider_id}/activate",
    response_model=AIProviderActivateResponse,
    summary="Activate an AI provider",
    responses={404: {"description": "Provider not found"}},
)
async def activate_ai_provider(
    provider_id: int,
    repo: AIProviderRepository = Depends(get_ai_provider_repo),
):
    """Sets the given provider as active, deactivating all others.

    Takes effect on the next ingestion run. To test immediately,
    call `POST /ingest/` after activating.
    """
    config = await repo.activate(provider_id)
    if config is None:
        raise HTTPException(status_code=404, detail="AI provider not found")
    return AIProviderActivateResponse(
        activated_id=config.id,
        message=f"'{config.name}' ({config.provider}:{config.model}) is now active",
    )


@router.delete(
    "/active",
    status_code=204,
    summary="Deactivate all AI providers",
)
async def deactivate_all_providers(
    repo: AIProviderRepository = Depends(get_ai_provider_repo),
):
    """Deactivates all providers. The system falls back to environment variable keys."""
    await repo.deactivate_all()


@router.delete(
    "/{provider_id}",
    status_code=204,
    summary="Delete an AI provider",
    responses={404: {"description": "Provider not found"}},
)
async def delete_ai_provider(
    provider_id: int,
    repo: AIProviderRepository = Depends(get_ai_provider_repo),
):
    """Permanently removes an AI provider configuration."""
    deleted = await repo.delete(provider_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="AI provider not found")
