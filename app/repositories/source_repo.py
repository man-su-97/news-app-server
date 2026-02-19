from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import Source
from app.schemas.source_schema import SourceCreate


class SourceRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, data: SourceCreate) -> Source:
        source = Source(**data.model_dump())
        self.db.add(source)
        await self.db.commit()
        await self.db.refresh(source)
        return source

    async def get_all(self, active_only: bool = True) -> list[Source]:
        stmt = select(Source)
        if active_only:
            stmt = stmt.where(Source.is_active.is_(True))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, source_id: int) -> Source | None:
        result = await self.db.execute(
            select(Source).where(Source.id == source_id)
        )
        return result.scalar_one_or_none()
