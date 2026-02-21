"""
app/repositories/article_repo.py — Article Database Operations
===============================================================
The repository pattern: all database operations for the "articles" table
live here. Routes and services NEVER write raw SQL — they call methods on this class.

Why the repository pattern?
  - Separation of concerns: business logic (ingestion_service.py) stays clean
  - Testability: you can swap this for an in-memory fake in tests
  - Centralized SQL: if you need to change a query, you change it in one place

Key operation — upsert_batch():
  Uses PostgreSQL's "INSERT ... ON CONFLICT DO UPDATE" (upsert).
  This is more efficient and correct than "check if exists, then insert or update"
  because it's a single atomic database round-trip (no race conditions).
"""

from sqlalchemy import func, select              # func.now() for SQL NOW(), select() for queries
from sqlalchemy.dialects.postgresql import insert  # PostgreSQL-specific insert with upsert support
from sqlalchemy.ext.asyncio import AsyncSession  # Async database session type

from app.models.article import Article           # The ORM model for the articles table


class ArticleRepository:
    """Handles all database reads and writes for the articles table."""

    def __init__(self, db: AsyncSession) -> None:
        # Store the DB session — injected by FastAPI's dependency injection system.
        # All methods on this instance use this same session (same transaction).
        self.db = db

    async def upsert_batch(self, articles: list[dict], source_id: int) -> int:
        """Insert new articles or update existing ones in a single DB round-trip.

        Why upsert (ON CONFLICT DO UPDATE) instead of plain INSERT?
          Publishers correct articles after publication (fix typos, update titles,
          change images). Plain INSERT would silently ignore these corrections.
          DO UPDATE overwrites stale data with fresh data on each ingest run.

        What is NOT updated on conflict?
          - created_at: always reflects the FIRST time we saw this article
          - source_id: the article belongs to the source that first provided it

        Returns the count of rows actually written (inserted + updated).
        """
        # Early return — nothing to do if the list is empty
        if not articles:
            return 0

        # Build a list of plain dicts — one per article.
        # Each dict maps column name → value for the INSERT statement.
        # .get() returns None for missing keys (safe for nullable columns).
        rows = [
            {
                "source_id": source_id,
                "title": a["title"],
                "description": a.get("description"),
                "content": a.get("content"),
                "url": a["url"],
                "image_url": a.get("image_url"),
                "published_at": a.get("published_at"),
                "raw_payload": a["raw_payload"],
                # Enrichment fields — None if AI was not configured or failed
                "category": a.get("category"),
                "sub_category": a.get("sub_category"),
                "importance_score": a.get("importance_score"),
                "summary": a.get("summary"),
                "location": a.get("location"),
                "region": a.get("region"),
            }
            for a in articles  # one dict per article in the batch
        ]

        # Build the INSERT statement using PostgreSQL's dialect-specific insert.
        # insert(Article).values(rows) → INSERT INTO articles (...) VALUES (...)
        stmt = insert(Article).values(rows)

        # .on_conflict_do_update(...) adds: ON CONFLICT (url) DO UPDATE SET ...
        # index_elements=["url"]: the conflict is on the UNIQUE url column.
        # set_=dict(...): what to update when a conflict happens.
        # stmt.excluded.column: refers to the value we TRIED to insert (the new value).
        stmt = stmt.on_conflict_do_update(
            index_elements=["url"],   # conflict key = the unique url column
            set_=dict(
                title=stmt.excluded.title,                    # update with new title
                description=stmt.excluded.description,        # update description
                image_url=stmt.excluded.image_url,            # update image
                raw_payload=stmt.excluded.raw_payload,        # always keep latest raw data
                category=stmt.excluded.category,              # refresh AI enrichment
                sub_category=stmt.excluded.sub_category,
                importance_score=stmt.excluded.importance_score,
                summary=stmt.excluded.summary,
                location=stmt.excluded.location,
                region=stmt.excluded.region,
                updated_at=func.now(),  # mark when we last saw this article
            ),
        ).returning(Article.id)  # .returning() gets back the IDs of affected rows

        # Execute the entire batch in a SINGLE database round-trip.
        # This is much faster than looping and doing one INSERT per article.
        result = await self.db.execute(stmt)
        await self.db.commit()    # Write to disk — makes the changes permanent

        # fetchall() returns one row per affected row (inserted OR updated).
        # len() of this list = how many articles were written.
        return len(result.fetchall())

    async def get_all(self, limit: int = 20, offset: int = 0) -> list[Article]:
        """Fetch articles ordered by publish date (newest first), with pagination.

        limit + offset enable pagination:
          Page 1: limit=20, offset=0   (articles 1-20)
          Page 2: limit=20, offset=20  (articles 21-40)
        """
        stmt = (
            select(Article)
            # Order by published_at descending — newest articles first.
            # nulls_last() puts articles with no publish date at the end
            # instead of at the top (which would be unintuitive).
            .order_by(Article.published_at.desc().nulls_last())
            .limit(limit)    # max rows to return
            .offset(offset)  # skip this many rows (for pagination)
        )
        result = await self.db.execute(stmt)
        # scalars() unwraps the result rows to Article objects (not Row tuples).
        # list() materializes the cursor into a Python list.
        return list(result.scalars().all())

    async def get_by_id(self, article_id: int) -> Article | None:
        """Fetch a single article by its database ID.

        Returns None if no article with that ID exists (route returns 404).
        scalar_one_or_none() returns the single result or None (never raises).
        """
        result = await self.db.execute(
            select(Article).where(Article.id == article_id)
        )
        return result.scalar_one_or_none()

    async def count(self) -> int:
        """Return the total number of articles in the database.

        Used by the list endpoint to tell the frontend the total result count
        for pagination UI ("Showing 20 of 1,547 articles").

        func.count() → SQL: SELECT COUNT(*) FROM articles
        select_from(Article) specifies which table to count from.
        scalar_one() returns the single integer count value.
        """
        result = await self.db.execute(select(func.count()).select_from(Article))
        return result.scalar_one()
