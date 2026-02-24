"""
app/core/deps.py — Dependency Injection Wiring
===============================================
FastAPI uses a "Dependency Injection" system: instead of creating objects
inside your route handlers, you declare what you need as function parameters,
and FastAPI creates them for you.

All repositories share the SAME db session per request — this means writes
from ingestion_service (raw_ingestion + filter_articles + post_processed_articles)
all participate in the same database transaction.

Updated for pipeline redesign:
  - get_article_repo()   → PostProcessedArticleRepository (via ArticleRepository alias)
  - get_filter_article_repo() → FilterArticleRepository (new)
  - get_post_processed_repo() → PostProcessedArticleRepository (new, explicit)
  - get_ingestion_service()   → updated to use new pipeline repos
"""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.repositories.ai_provider_repo import AIProviderRepository
from app.repositories.article_repo import ArticleRepository          # alias for PostProcessedArticleRepository
from app.repositories.filter_article_repo import FilterArticleRepository
from app.repositories.final_article_repo import FinalArticleRepository
from app.repositories.master_data_repo import (
    CountryRepository,
    MasterCategoryRepository,
    MasterSubCategoryRepository,
    StateRepository,
)
from app.repositories.post_processed_article_repo import PostProcessedArticleRepository
from app.repositories.raw_ingestion_repo import RawIngestionRepository
from app.repositories.source_repo import SourceRepository
from app.services.ingestion_service import IngestionService


async def get_source_repo(db: AsyncSession = Depends(get_db)) -> SourceRepository:
    """Create a SourceRepository bound to the current request's DB session."""
    return SourceRepository(db)


async def get_article_repo(
    db: AsyncSession = Depends(get_db),
) -> ArticleRepository:
    """Create an ArticleRepository (= PostProcessedArticleRepository) for this request.

    Used by routes_articles.py for GET /articles/ and GET /articles/{id}.
    """
    return ArticleRepository(db)


async def get_filter_article_repo(
    db: AsyncSession = Depends(get_db),
) -> FilterArticleRepository:
    """Create a FilterArticleRepository for this request."""
    return FilterArticleRepository(db)


async def get_post_processed_repo(
    db: AsyncSession = Depends(get_db),
) -> PostProcessedArticleRepository:
    """Create a PostProcessedArticleRepository for this request."""
    return PostProcessedArticleRepository(db)


async def get_raw_ingestion_repo(
    db: AsyncSession = Depends(get_db),
) -> RawIngestionRepository:
    """Create a RawIngestionRepository for this request."""
    return RawIngestionRepository(db)


async def get_ai_provider_repo(
    db: AsyncSession = Depends(get_db),
) -> AIProviderRepository:
    """Create an AIProviderRepository for this request."""
    return AIProviderRepository(db)


async def get_final_article_repo(
    db: AsyncSession = Depends(get_db),
) -> FinalArticleRepository:
    """Create a FinalArticleRepository for this request.

    Used by routes_final_articles.py for GET /final-articles/ and the publish endpoint.
    """
    return FinalArticleRepository(db)


async def get_category_repo(
    db: AsyncSession = Depends(get_db),
) -> MasterCategoryRepository:
    return MasterCategoryRepository(db)


async def get_sub_category_repo(
    db: AsyncSession = Depends(get_db),
) -> MasterSubCategoryRepository:
    return MasterSubCategoryRepository(db)


async def get_country_repo(
    db: AsyncSession = Depends(get_db),
) -> CountryRepository:
    return CountryRepository(db)


async def get_state_repo(
    db: AsyncSession = Depends(get_db),
) -> StateRepository:
    return StateRepository(db)


async def get_ingestion_service(
    db: AsyncSession = Depends(get_db),
) -> IngestionService:
    """Create an IngestionService with all required repositories.

    All repositories share the SAME db session so all writes (raw_ingestion,
    filter_articles, post_processed_articles) are in the same transaction.
    """
    return IngestionService(
        source_repo=SourceRepository(db),
        raw_repo=RawIngestionRepository(db),
        filter_article_repo=FilterArticleRepository(db),
        post_processed_repo=PostProcessedArticleRepository(db),
        ai_provider_repo=AIProviderRepository(db),
        db=db,   # used by resolvers to load sub_category and state lookups
    )
