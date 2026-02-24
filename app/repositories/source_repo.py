"""
app/repositories/source_repo.py — Source Database Operations
=============================================================
All database operations for the "sources" table live here.
Sources are news feeds (RSS or REST) that the ingestion pipeline fetches from.

This repo is used by:
  - routes_sources.py: CRUD operations via the HTTP API
  - scheduler.py: get_all(active_only=True) to find sources to fetch
  - ingestion_service.py: not used directly, but scheduler passes Source objects
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import Source
from app.schemas.source_schema import SourceCreate, SourceUpdate


class SourceRepository:
    """Handles all database reads and writes for the sources table."""

    def __init__(self, db: AsyncSession) -> None:
        # The DB session is injected — shared with other repos in the same request.
        self.db = db

    async def create(self, data: SourceCreate) -> Source:
        """Insert a new source row into the database.

        data.model_dump() converts the Pydantic schema to a plain dict,
        which is then unpacked as keyword arguments to Source(**kwargs).
        This is idiomatic SQLAlchemy 2.0 for creating ORM objects.
        """
        source = Source(**data.model_dump())  # Create ORM object from validated input
        self.db.add(source)                   # Stage for INSERT (not yet committed)
        await self.db.commit()                # Write to disk
        await self.db.refresh(source)         # Reload from DB to get auto-set fields
        # (refresh populates id, created_at which are set by the DB, not Python)
        return source

    async def update(self, source_id: int, data: "SourceUpdate") -> Source | None:
        """Apply partial updates to a source. Returns updated source or None if not found."""
        source = await self.get_by_id(source_id)
        if source is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(source, field, value)
        await self.db.commit()
        await self.db.refresh(source)
        return source

    async def delete(self, source_id: int) -> bool:
        """Delete a source by ID. Returns True if deleted, False if not found."""
        source = await self.get_by_id(source_id)
        if source is None:
            return False
        await self.db.delete(source)
        await self.db.commit()
        return True

    async def get_all(self, active_only: bool = True) -> list[Source]:
        """Fetch all sources, optionally filtering to only active ones.

        active_only=True is the default because:
          - The scheduler should only fetch sources that are enabled.
          - The API exposes active_only=True to avoid showing disabled sources
            to the frontend by default.
        """
        stmt = select(Source)  # SELECT * FROM sources

        if active_only:
            # Add WHERE is_active = TRUE to the query
            stmt = stmt.where(Source.is_active.is_(True))
            # .is_(True) is used instead of == True for SQLAlchemy best practice
            # (avoids potential issues with Python's == vs SQL's IS)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())  # Return as a Python list of Source objects

    async def get_by_id(self, source_id: int) -> Source | None:
        """Fetch a single source by its ID. Returns None if not found.

        Used by:
          - GET /sources/{source_id} route
          - POST /ingest/ route (to verify the source exists before ingesting)
        """
        result = await self.db.execute(
            select(Source).where(Source.id == source_id)
        )
        # scalar_one_or_none(): returns the Source object, or None if no row matched.
        # Never raises an exception for "not found" — callers handle that case.
        return result.scalar_one_or_none()
