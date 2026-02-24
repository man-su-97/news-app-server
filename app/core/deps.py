"""
app/core/deps.py — Dependency Injection Wiring
===============================================
FastAPI uses a "Dependency Injection" system: instead of creating objects
inside your route handlers, you declare what you need as function parameters,
and FastAPI creates them for you.

All repositories share the SAME db session per request — this means writes
from ingestion_service (raw_ingestion + filtered_articles + post_processed_articles)
all participate in the same database transaction.
"""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.repositories.ai_provider_repo import AIProviderRepository
from app.repositories.filter_article_repo import FilterArticleRepository
from app.repositories.final_article_repo import FinalArticleRepository
from app.repositories.master_data_repo import (
    MasterCategoryRepository,
    MasterSubCategoryRepository,
    StateRepository,
)
from app.repositories.post_processed_article_repo import PostProcessedArticleRepository
from app.repositories.raw_ingestion_repo import RawIngestionRepository
from app.repositories.source_repo import SourceRepository
from app.services.ingestion_service import IngestionService


async def get_source_repo(db: AsyncSession = Depends(get_db)) -> SourceRepository:
    return SourceRepository(db)


async def get_post_processed_repo(
    db: AsyncSession = Depends(get_db),
) -> PostProcessedArticleRepository:
    return PostProcessedArticleRepository(db)


async def get_ai_provider_repo(
    db: AsyncSession = Depends(get_db),
) -> AIProviderRepository:
    return AIProviderRepository(db)


async def get_final_article_repo(
    db: AsyncSession = Depends(get_db),
) -> FinalArticleRepository:
    return FinalArticleRepository(db)


async def get_category_repo(
    db: AsyncSession = Depends(get_db),
) -> MasterCategoryRepository:
    return MasterCategoryRepository(db)


async def get_sub_category_repo(
    db: AsyncSession = Depends(get_db),
) -> MasterSubCategoryRepository:
    return MasterSubCategoryRepository(db)


async def get_state_repo(
    db: AsyncSession = Depends(get_db),
) -> StateRepository:
    return StateRepository(db)


async def get_ingestion_service(
    db: AsyncSession = Depends(get_db),
) -> IngestionService:
    """Create an IngestionService with all required repositories.

    All repositories share the SAME db session so all writes (raw_ingestion,
    filtered_articles, post_processed_articles) are in the same transaction.
    """
    return IngestionService(
        source_repo=SourceRepository(db),
        raw_repo=RawIngestionRepository(db),
        filter_article_repo=FilterArticleRepository(db),
        post_processed_repo=PostProcessedArticleRepository(db),
        ai_provider_repo=AIProviderRepository(db),
        db=db,
    )
