from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.repositories.ai_provider_repo import AIProviderRepository
from app.repositories.article_repo import ArticleRepository
from app.repositories.raw_ingestion_repo import RawIngestionRepository
from app.repositories.source_repo import SourceRepository
from app.services.ingestion_service import IngestionService


async def get_source_repo(db: AsyncSession = Depends(get_db)) -> SourceRepository:
    return SourceRepository(db)


async def get_article_repo(db: AsyncSession = Depends(get_db)) -> ArticleRepository:
    return ArticleRepository(db)


async def get_raw_ingestion_repo(
    db: AsyncSession = Depends(get_db),
) -> RawIngestionRepository:
    return RawIngestionRepository(db)


async def get_ai_provider_repo(
    db: AsyncSession = Depends(get_db),
) -> AIProviderRepository:
    return AIProviderRepository(db)


async def get_ingestion_service(db: AsyncSession = Depends(get_db)) -> IngestionService:
    # All repos share the same session — consistent transaction scope per HTTP request.
    return IngestionService(
        source_repo=SourceRepository(db),
        article_repo=ArticleRepository(db),
        raw_repo=RawIngestionRepository(db),
        ai_provider_repo=AIProviderRepository(db),
    )
