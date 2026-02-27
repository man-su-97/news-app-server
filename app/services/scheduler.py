import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.repositories.ai_provider_repo import AIProviderRepository
from app.repositories.filter_article_repo import FilterArticleRepository
from app.repositories.final_article_repo import FinalArticleRepository
from app.repositories.post_processed_article_repo import PostProcessedArticleRepository
from app.repositories.raw_ingestion_repo import RawIngestionRepository
from app.repositories.source_repo import SourceRepository
from app.services.ingestion_service import IngestionService
from app.services.publishing_service import PublishingService

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")


async def run_ingestion_for_all_active_sources() -> None:
    logger.info("Scheduled ingestion run starting")

    async with AsyncSessionLocal() as db:
        sources = await SourceRepository(db).get_all(active_only=True)

    if not sources:
        logger.info("No active sources configured — skipping run")
        return

    logger.info("Ingesting %d active source(s)", len(sources))

    tasks = [_ingest_one_source(source) for source in sources]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    ok = sum(1 for r in results if isinstance(r, int))
    failed = sum(1 for r in results if isinstance(r, Exception))

    for source, result in zip(sources, results):
        if isinstance(result, Exception):
            logger.error(
                "Scheduled ingest failed for source_id=%s (%s): %s",
                source.id, source.name, result,
            )

    logger.info(
        "Scheduled ingestion complete: %d sources OK, %d failed", ok, failed
    )

    if ok > 0:
        logger.info("Triggering publish after ingestion completed")
        await run_publishing()


async def _ingest_one_source(source) -> int:
    async with AsyncSessionLocal() as db:
        svc = IngestionService(
            source_repo=SourceRepository(db),
            raw_repo=RawIngestionRepository(db),
            filter_article_repo=FilterArticleRepository(db),
            post_processed_repo=PostProcessedArticleRepository(db),
            ai_provider_repo=AIProviderRepository(db),
            db=db,
        )
        count = await svc.ingest(source)
        logger.info(
            "Scheduled ingest: %d articles from source_id=%s (%s)",
            count, source.id, source.name,
        )
        return count


async def run_publishing() -> None:
    logger.info("Scheduled publishing run starting")
    async with AsyncSessionLocal() as db:
        svc = PublishingService(
            post_processed_repo=PostProcessedArticleRepository(db),
            final_article_repo=FinalArticleRepository(db),
        )
        count = await svc.publish(top_n=settings.FEED_TOP_N)
    logger.info("Scheduled publishing complete: %d final_articles rows written", count)


def start_scheduler() -> None:
    scheduler.add_job(
        run_ingestion_for_all_active_sources,
        trigger="interval",
        minutes=settings.INGEST_INTERVAL_MINUTES,
        id="ingestion_all_sources",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        run_publishing,
        trigger="interval",
        minutes=settings.PUBLISH_INTERVAL_MINUTES,
        seconds=settings.PUBLISH_OFFSET_SECONDS,
        id="publish_final_feed",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info(
        "Scheduler started — ingestion every %dmin, publishing every %dmin (+%ds offset)",
        settings.INGEST_INTERVAL_MINUTES,
        settings.PUBLISH_INTERVAL_MINUTES,
        settings.PUBLISH_OFFSET_SECONDS,
    )


def stop_scheduler() -> None:
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")
