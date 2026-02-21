"""
app/services/scheduler.py — Background Job Scheduler
=====================================================
Runs the ingestion pipeline automatically every 5 minutes.

Without this, news would only be fetched when someone manually calls POST /ingest/.
The scheduler makes the app autonomous: add a source once, and new articles
appear automatically without any human action.

Architecture:
  - APScheduler (AsyncIOScheduler) integrates with Python's asyncio event loop.
    This means scheduled jobs run in the same async context as the web server —
    no separate process or thread needed.
  - Each source gets its OWN database session to avoid one slow source blocking others.
  - asyncio.gather() runs all sources CONCURRENTLY (not sequentially), so
    fetching 10 sources takes as long as the SLOWEST single source (not 10x longer).
  - max_instances=1 prevents job pile-up: if the previous run is still in progress
    when the next trigger fires, the new trigger is skipped.

Scheduler lifecycle:
  - start_scheduler() is called in app/main.py's lifespan startup hook
  - stop_scheduler() is called in the lifespan shutdown hook
"""

import asyncio   # For asyncio.gather() — concurrent execution of multiple coroutines
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # APScheduler async variant

from app.core.database import AsyncSessionLocal      # DB session factory
from app.repositories.article_repo import ArticleRepository
from app.repositories.raw_ingestion_repo import RawIngestionRepository
from app.repositories.source_repo import SourceRepository
from app.services.ingestion_service import IngestionService

logger = logging.getLogger(__name__)

# Create the scheduler instance.
# timezone="UTC" ensures all job execution times are unambiguous.
# Without timezone, APScheduler uses local timezone which varies by server.
scheduler = AsyncIOScheduler(timezone="UTC")


async def run_ingestion_for_all_active_sources() -> None:
    """Fetch and process every active source concurrently.

    This is the main scheduled job — runs every 5 minutes.

    Session strategy:
      Step 1: Open ONE session to load the list of active sources, then CLOSE it.
      Step 2: For each source, open a SEPARATE session for its ingestion.
      Why? If we kept one session open for all sources:
        - A slow source would hold the session open for the full duration
        - SQLAlchemy sessions aren't meant to be long-lived
        - An error in one source's transaction could affect others
    """
    logger.info("Scheduled ingestion run starting")

    # Step 1: Load source list in a short-lived session, then close it
    async with AsyncSessionLocal() as db:
        sources = await SourceRepository(db).get_all(active_only=True)
    # The session is now closed — source objects are "detached" from the session.
    # expire_on_commit=False (set in database.py) means their column data stays
    # cached in memory, so we can still access source.id, source.url, etc.

    if not sources:
        logger.info("No active sources configured — skipping run")
        return

    logger.info("Ingesting %d active source(s)", len(sources))

    # Step 2: Ingest all sources CONCURRENTLY.
    # Each source runs in its own separate coroutine (_ingest_one_source).
    # asyncio.gather() starts all of them simultaneously.
    # return_exceptions=True: if one source fails, others continue running.
    # Without return_exceptions=True, ONE failure would cancel all other running tasks.
    tasks = [_ingest_one_source(source) for source in sources]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Count successes vs failures for the log summary
    ok = sum(1 for r in results if isinstance(r, int))           # int = article count = success
    failed = sum(1 for r in results if isinstance(r, Exception)) # Exception = failure

    # Log which sources specifically failed
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
    """Run the full ingestion pipeline for ONE source in its own DB session.

    Opens a dedicated session for this source, runs the full pipeline
    (fetch → normalize → enrich → upsert), logs the result, and returns
    the count of articles written.

    Architecture decision: using "async with AsyncSessionLocal()" creates
    a brand new connection pool checkout for each source. This isolates
    database transactions per source — an error in source A's transaction
    doesn't affect source B's transaction.

    Note: The scheduler (_ingest_one_source) doesn't pass ai_provider_repo
    because it creates a fresh IngestionService. IngestionService._load_ai_provider()
    will check the DB config first, then fall back to env vars.
    """
    async with AsyncSessionLocal() as db:
        # Create a fresh IngestionService with this session's repos
        svc = IngestionService(
            source_repo=SourceRepository(db),
            article_repo=ArticleRepository(db),
            raw_repo=RawIngestionRepository(db),
            # Note: ai_provider_repo is not passed here — IngestionService
            # will use get_env_fallback_provider() for the AI provider.
            # To use DB-configured providers in scheduled jobs, pass
            # ai_provider_repo=AIProviderRepository(db) here.
        )
        count = await svc.ingest(source)
        logger.info(
            "Scheduled ingest: %d articles from source_id=%s (%s)",
            count, source.id, source.name,
        )
        return count


def start_scheduler() -> None:
    """Register the ingestion job and start the scheduler.

    Called once when the FastAPI application starts (in main.py lifespan).

    Job configuration:
      trigger="interval": run on a fixed time interval
      minutes=5: every 5 minutes
      id="ingestion_all_sources": unique job ID (allows replace_existing to work)
      replace_existing=True: if this job already exists (e.g. hot reload), replace it
      max_instances=1: only ONE instance of this job runs at a time.
        Without this, if the 5-minute job takes 6 minutes, two instances
        would run simultaneously — causing duplicate writes and DB contention.
    """
    scheduler.add_job(
        run_ingestion_for_all_active_sources,   # the function to call
        trigger="interval",
        minutes=5,
        id="ingestion_all_sources",
        replace_existing=True,
        max_instances=1,    # prevents pile-up if a run takes longer than 5 minutes
    )
    scheduler.start()
    logger.info("Scheduler started — ingestion every 5 minutes")


def stop_scheduler() -> None:
    """Stop the scheduler gracefully.

    Called when the FastAPI application shuts down (in main.py lifespan).
    wait=False: don't wait for currently running jobs to finish before stopping.
    This prevents a long-running ingestion job from delaying server shutdown.
    """
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")
