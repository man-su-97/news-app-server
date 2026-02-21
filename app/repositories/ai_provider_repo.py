from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_provider import AIProviderConfig, PROVIDER_BASE_URLS
from app.schemas.ai_provider_schema import AIProviderCreate


class AIProviderRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, data: AIProviderCreate) -> AIProviderConfig:
        # Apply the provider's default base_url if the user didn't supply one
        base_url = data.base_url or PROVIDER_BASE_URLS.get(data.provider)
        config = AIProviderConfig(
            name=data.name,
            provider=data.provider,
            model=data.model,
            api_key=data.api_key,
            base_url=base_url,
            is_active=False,  # newly created configs start inactive
        )
        self.db.add(config)
        await self.db.commit()
        await self.db.refresh(config)
        return config

    async def get_all(self) -> list[AIProviderConfig]:
        result = await self.db.execute(
            select(AIProviderConfig).order_by(AIProviderConfig.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, config_id: int) -> AIProviderConfig | None:
        result = await self.db.execute(
            select(AIProviderConfig).where(AIProviderConfig.id == config_id)
        )
        return result.scalar_one_or_none()

    async def get_active(self) -> AIProviderConfig | None:
        """Return the single active provider config, or None if none is set."""
        result = await self.db.execute(
            select(AIProviderConfig).where(AIProviderConfig.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def activate(self, config_id: int) -> AIProviderConfig | None:
        """Set config_id as the active provider; deactivate all others atomically."""
        target = await self.get_by_id(config_id)
        if target is None:
            return None

        # Deactivate every row first (including the target if it was already active)
        await self.db.execute(
            update(AIProviderConfig).values(is_active=False)
        )
        # Activate only the target
        await self.db.execute(
            update(AIProviderConfig)
            .where(AIProviderConfig.id == config_id)
            .values(is_active=True)
        )
        await self.db.commit()
        await self.db.refresh(target)
        return target

    async def deactivate_all(self) -> None:
        """Clear the active provider — ingestion falls back to env vars."""
        await self.db.execute(update(AIProviderConfig).values(is_active=False))
        await self.db.commit()

    async def delete(self, config_id: int) -> bool:
        config = await self.get_by_id(config_id)
        if config is None:
            return False
        await self.db.delete(config)
        await self.db.commit()
        return True
