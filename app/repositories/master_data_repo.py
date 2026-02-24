"""
app/repositories/master_data_repo.py — Master Data Read Repositories
=====================================================================
Simple read-only repositories for the four reference tables:
  MasterCategoryRepository    → master_category
  MasterSubCategoryRepository → master_sub_category
  CountryRepository           → country
  StateRepository             → state

These tables are seeded once (via Alembic data migration) and rarely change.
All methods are read-only — master data is managed via migrations, not the API.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import MasterCategory, MasterSubCategory
from app.models.location import Country, State


class MasterCategoryRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(self, active_only: bool = False) -> list[MasterCategory]:
        stmt = select(MasterCategory).order_by(MasterCategory.priority_point, MasterCategory.id)
        if active_only:
            stmt = stmt.where(MasterCategory.is_active.is_(True))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, category_id: int) -> MasterCategory | None:
        result = await self.db.execute(
            select(MasterCategory).where(MasterCategory.id == category_id)
        )
        return result.scalar_one_or_none()

    async def count(self) -> int:
        result = await self.db.execute(select(func.count()).select_from(MasterCategory))
        return result.scalar_one()


class MasterSubCategoryRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(
        self, category_id: int | None = None, active_only: bool = False
    ) -> list[MasterSubCategory]:
        stmt = select(MasterSubCategory).order_by(
            MasterSubCategory.category_id,
            MasterSubCategory.priority_point,
            MasterSubCategory.id,
        )
        if category_id is not None:
            stmt = stmt.where(MasterSubCategory.category_id == category_id)
        if active_only:
            stmt = stmt.where(MasterSubCategory.is_active.is_(True))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, sub_category_id: int) -> MasterSubCategory | None:
        result = await self.db.execute(
            select(MasterSubCategory).where(MasterSubCategory.id == sub_category_id)
        )
        return result.scalar_one_or_none()

    async def count(self) -> int:
        result = await self.db.execute(select(func.count()).select_from(MasterSubCategory))
        return result.scalar_one()


class CountryRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(self) -> list[Country]:
        result = await self.db.execute(select(Country).order_by(Country.name))
        return list(result.scalars().all())

    async def get_by_id(self, country_id: int) -> Country | None:
        result = await self.db.execute(
            select(Country).where(Country.id == country_id)
        )
        return result.scalar_one_or_none()

    async def count(self) -> int:
        result = await self.db.execute(select(func.count()).select_from(Country))
        return result.scalar_one()


class StateRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_all(self, country_id: int | None = None) -> list[State]:
        stmt = select(State).order_by(State.name)
        if country_id is not None:
            stmt = stmt.where(State.country_id == country_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, state_id: int) -> State | None:
        result = await self.db.execute(
            select(State).where(State.id == state_id)
        )
        return result.scalar_one_or_none()

    async def count(self) -> int:
        result = await self.db.execute(select(func.count()).select_from(State))
        return result.scalar_one()
