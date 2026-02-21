import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.database import AsyncSessionLocal
from app.repositories.article_repo import ArticleRepository
from app.repositories.raw_ingestion_repo import RawIngestionRepository
from app.repositories.source_repo import SourceRepository
from app.services.ingestion_service import IngestionService

logger = logging.getLogger(__name__)

# timezone="UTC" ensures job timestamps are always unambiguous
scheduler = AsyncIOScheduler(timezone="UTC")


async def run_ingestion_for_all_active_sources() -> None:
    """Fetch every active source and ingest concurrently.

    Each source gets its own DB session so a slow or failing source cannot
    hold a session open for the duration of the entire batch.
    The source ORM objects are read in one session, then that session is closed.
    Attribute access on the detached objects is safe because expire_on_commit=False
    keeps the column data cached in memory (no relationship lazy-loads are used).
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
        "Scheduled ingestion run complete: %d sources OK, %d failed", ok, failed
    )


async def _ingest_one_source(source) -> int:
    """Run the full ingestion pipeline for one source in a dedicated DB session."""
    async with AsyncSessionLocal() as db:
        svc = IngestionService(
            source_repo=SourceRepository(db),
            article_repo=ArticleRepository(db),
            raw_repo=RawIngestionRepository(db),
        )
        count = await svc.ingest(source)
        logger.info(
            "Scheduled ingest: %d articles from source_id=%s (%s)",
            count, source.id, source.name,
        )
        return count


def start_scheduler() -> None:
    scheduler.add_job(
        run_ingestion_for_all_active_sources,
        trigger="interval",
        minutes=5,
        id="ingestion_all_sources",
        replace_existing=True,
        # Prevents a second run from starting if the first is still in progress.
        # Without this, a slow batch of sources can cause an unbounded pile-up.
        max_instances=1,
    )
    scheduler.start()
    logger.info("Scheduler started — ingestion every 5 minutes")


def stop_scheduler() -> None:
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")
