"""
app/services/scheduler.py — Background Job Scheduler
=====================================================
Runs the full pipeline automatically every 5 minutes.

Two scheduled jobs:
  1. ingestion_all_sources — fetch + AI filter + AI post-process for every active source
  2. publish_final_feed    — select top-ranked articles and upsert into final_articles
                             (runs 30 seconds after ingestion completes, every 5 minutes)

Architecture:
  - APScheduler (AsyncIOScheduler) integrates with Python's asyncio event loop.
  - Each source gets its OWN database session to avoid one slow source blocking others.
  - asyncio.gather() runs all sources CONCURRENTLY — fetching N sources takes as long
    as the SLOWEST single source (not N× longer).
  - max_instances=1 prevents job pile-up if a previous run is still in progress.

Scheduler lifecycle:
  - start_scheduler() called in app/main.py lifespan startup hook
  - stop_scheduler() called in the lifespan shutdown hook
"""

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
    """Fetch and process every active source concurrently.

    Full pipeline per source:
      Fetch raw items → store raw_ingestion → AI stage 1 (filter + classify)
      → store filter_articles → AI stage 2 (rewrite + score) → store post_processed_articles

    Session strategy:
      Step 1: ONE session to load the source list, then close it.
      Step 2: Per-source SEPARATE session for full ingestion.
      Why separate? Isolates DB transactions and avoids long-lived sessions.
    """
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


async def _ingest_one_source(source) -> int:
    """Run the full ingestion pipeline for ONE source in its own DB session.

    Opens a dedicated session, creates the full IngestionService with all
    required repositories (raw, filter, post-processed, AI provider), runs
    the pipeline, and returns the count of post_processed_articles written.
    """
    async with AsyncSessionLocal() as db:
        svc = IngestionService(
            source_repo=SourceRepository(db),
            raw_repo=RawIngestionRepository(db),
            filter_article_repo=FilterArticleRepository(db),
            post_processed_repo=PostProcessedArticleRepository(db),
            ai_provider_repo=AIProviderRepository(db),
            db=db,   # needed for CategoryResolver + LocationResolver queries
        )
        count = await svc.ingest(source)
        logger.info(
            "Scheduled ingest: %d articles from source_id=%s (%s)",
            count, source.id, source.name,
        )
        return count


async def run_publishing() -> None:
    """Compute rank_scores and upsert the top 20 articles into final_articles.

    Called 30 seconds after ingestion (via separate job) so that fresh
    post_processed_articles are available for ranking.

    PublishingService:
      1. Loads top 20 post_processed_articles by imp_score (non-null only)
      2. Applies time-decay to compute rank_score for each
      3. Upserts into final_articles — the public news feed table
    """
    logger.info("Scheduled publishing run starting")
    async with AsyncSessionLocal() as db:
        svc = PublishingService(
            post_processed_repo=PostProcessedArticleRepository(db),
            final_article_repo=FinalArticleRepository(db),
        )
        count = await svc.publish(top_n=settings.FEED_TOP_N)
    logger.info("Scheduled publishing complete: %d final_articles rows written", count)


def start_scheduler() -> None:
    """Register ingestion + publishing jobs and start the scheduler.

    Job 1 (ingestion_all_sources): every 5 minutes, max 1 concurrent instance.
    Job 2 (publish_final_feed):    every 5 minutes, offset 30s from ingestion,
                                    max 1 concurrent instance.

    The 30-second offset gives ingestion time to write post_processed_articles
    before publishing tries to read them.
    """
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
    """Stop the scheduler gracefully on server shutdown."""
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")
