"""
app/repositories/ai_provider_repo.py — AI Provider Config DB Operations
========================================================================
All database operations for the "ai_provider_configs" table.

Key constraint: at most ONE row can have is_active=True at a time.
This constraint is enforced at TWO levels:
  1. Database: a partial unique index (see migration d9e4f5a6b789) prevents
     two rows with is_active=True from existing simultaneously.
  2. Application: activate() sets all rows to False, then sets the target to True,
     in a single transaction.

Why two levels? The DB constraint is the safety net — it prevents bugs even if
the application code has an error. The application-level logic ensures the right
user experience (e.g. clear error messages, not raw DB constraint violations).
"""

from sqlalchemy import select, update         
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_provider import AIProviderConfig, PROVIDER_BASE_URLS
from app.schemas.ai_provider_schema import AIProviderCreate


class AIProviderRepository:
    """Handles all DB operations for the ai_provider_configs table."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, data: AIProviderCreate) -> AIProviderConfig:
        """Insert a new AI provider configuration.

        Architecture note: new configs always start with is_active=False.
        The user must explicitly call activate() to use a config.
        This prevents accidentally activating an untested config on creation.

        base_url handling:
          - If user supplied a base_url, use it.
          - Otherwise, look up the default for this provider (e.g. Gemini's URL).
          - For "gemini_langgraph" and "anthropic", the default is None
            because their SDKs don't need a URL override.
        """
        base_url = data.base_url or PROVIDER_BASE_URLS.get(data.provider)

        config = AIProviderConfig(
            name=data.name,
            provider=data.provider,
            model=data.model,
            api_key=data.api_key,
            base_url=base_url,
            is_active=False,   
        )
        self.db.add(config)
        await self.db.commit()
        await self.db.refresh(config)  
        return config

    async def get_all(self) -> list[AIProviderConfig]:
        """Return all configs ordered by creation date (newest first).

        Used by GET /ai-providers/ to list all registered providers.
        Note: api_key is present on the ORM object but intentionally
        excluded from the response schema (AIProviderResponse).
        """
        result = await self.db.execute(
            select(AIProviderConfig).order_by(AIProviderConfig.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, config_id: int) -> AIProviderConfig | None:
        """Fetch one config by ID. Returns None if not found."""
        result = await self.db.execute(
            select(AIProviderConfig).where(AIProviderConfig.id == config_id)
        )
        return result.scalar_one_or_none()

    async def get_active(self) -> AIProviderConfig | None:
        """Return the single active provider config, or None if none is set.

        Called by IngestionService at the start of every ingest run.
        Returns None when no provider is active → ingestion uses env-var fallback
        or deterministic-only normalization.

        Performance: the partial unique index on (is_active WHERE is_active=true)
        makes this a very fast indexed lookup, not a full table scan.
        """
        result = await self.db.execute(
            select(AIProviderConfig).where(AIProviderConfig.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def activate(self, config_id: int) -> AIProviderConfig | None:
        """Set config_id as the ONLY active provider; deactivate all others.

        This operation is atomic: both the deactivation of old active configs
        and the activation of the target happen in a single transaction.
        If anything fails, the DB rolls back to the previous state.

        Returns the activated config, or None if config_id doesn't exist.
        """
        # First verify the target exists
        target = await self.get_by_id(config_id)
        if target is None:
            return None  

        # Step 1: Set ALL rows to is_active=False (including the current active one)
        # This clears the old active state before setting the new one.
        await self.db.execute(
            update(AIProviderConfig).values(is_active=False)
        )

        # Step 2: Set ONLY the target row to is_active=True
        await self.db.execute(
            update(AIProviderConfig)
            .where(AIProviderConfig.id == config_id)
            .values(is_active=True)
        )

        return target

    async def deactivate_all(self) -> None:
        """Set all configs to inactive.

        Used by DELETE /ai-providers/active to fall back to env-var or
        deterministic-only normalization without deleting any configs.
        """
        await self.db.execute(update(AIProviderConfig).values(is_active=False))
        await self.db.commit()

    async def delete(self, config_id: int) -> bool:
        """Delete a provider config by ID.

        Returns True if the config was found and deleted, False if not found.
        The route uses this to decide between 204 No Content vs 404 Not Found.
        """
        config = await self.get_by_id(config_id)
        if config is None:
            return False    # Not found — caller returns 404

        await self.db.delete(config)   # Mark for deletion
        await self.db.commit()         # Execute the DELETE
        return True
