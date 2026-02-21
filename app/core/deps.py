"""
app/core/deps.py — Dependency Injection Wiring
===============================================
FastAPI uses a "Dependency Injection" system: instead of creating objects
inside your route handlers, you declare what you need as function parameters,
and FastAPI creates them for you.

This file defines all the dependency functions ("deps") that routes use.
Each function here:
  1. Receives a database session (also via dependency injection)
  2. Creates a repository or service object with that session
  3. Returns it — FastAPI passes it to the route handler

Why this pattern?
  - Routes stay thin: they only contain HTTP logic (status codes, validation)
  - Repositories/services are testable without a real HTTP request
  - The database session is shared across all repos in one request,
    so they all participate in the same transaction

Example of how a route uses these:
    @router.get("/articles/")
    async def list_articles(repo: ArticleRepository = Depends(get_article_repo)):
        return await repo.get_all()
    # FastAPI automatically calls get_article_repo(), which calls get_db(),
    # which opens a DB session — all wired up automatically.
"""

from fastapi import Depends                                        # FastAPI's DI decorator
from sqlalchemy.ext.asyncio import AsyncSession                   # Type hint for DB session

from app.core.database import get_db                              # Session generator
from app.repositories.ai_provider_repo import AIProviderRepository
from app.repositories.article_repo import ArticleRepository
from app.repositories.raw_ingestion_repo import RawIngestionRepository
from app.repositories.source_repo import SourceRepository
from app.services.ingestion_service import IngestionService


async def get_source_repo(db: AsyncSession = Depends(get_db)) -> SourceRepository:
    """Create a SourceRepository bound to the current request's DB session."""
    # Depends(get_db) tells FastAPI: "call get_db() and inject its result here"
    return SourceRepository(db)


async def get_article_repo(db: AsyncSession = Depends(get_db)) -> ArticleRepository:
    """Create an ArticleRepository bound to the current request's DB session."""
    return ArticleRepository(db)


async def get_raw_ingestion_repo(
    db: AsyncSession = Depends(get_db),
) -> RawIngestionRepository:
    """Create a RawIngestionRepository bound to the current request's DB session."""
    return RawIngestionRepository(db)


async def get_ai_provider_repo(
    db: AsyncSession = Depends(get_db),
) -> AIProviderRepository:
    """Create an AIProviderRepository bound to the current request's DB session."""
    return AIProviderRepository(db)


async def get_ingestion_service(db: AsyncSession = Depends(get_db)) -> IngestionService:
    """Create an IngestionService with all required repositories.

    Architecture decision: ALL repositories share the SAME db session.
    This means if the ingestion service writes to both article_repo and raw_repo,
    both writes happen in the same database transaction — they succeed or fail together.
    If we used separate sessions, a crash halfway through would leave the DB
    in an inconsistent state (some rows written, some not).
    """
    # Pass the same `db` session to every repository — consistent transaction scope
    return IngestionService(
        source_repo=SourceRepository(db),
        article_repo=ArticleRepository(db),
        raw_repo=RawIngestionRepository(db),
        ai_provider_repo=AIProviderRepository(db),
    )
