"""
app/services/search_enrichment_service.py — Google Search enrichment stage
===========================================================================
Populates reference_urls on post_processed_articles that have never been
searched. Each article is searched exactly once:

  - reference_urls IS NULL  → not yet searched; eligible for this run
  - reference_urls = []     → searched before, no results; skip forever
  - reference_urls = [...]  → enriched; skip

The daily quota guard is enforced via GOOGLE_SEARCH_MAX_PER_RUN, which caps
how many searches happen in a single scheduler run regardless of how many
unenriched articles exist. Across multiple runs the same article is never
searched twice, so the aggregate quota spend equals the number of distinct
articles — not the number of scheduler cycles.
"""

import asyncio
import logging

from app.core.config import settings
from app.repositories.post_processed_article_repo import PostProcessedArticleRepository
from app.services.google_search_service import fetch_related_urls

logger = logging.getLogger(__name__)


class SearchEnrichmentService:
    """Enrich post_processed_articles with reference_urls — once per article."""

    def __init__(self, post_processed_repo: PostProcessedArticleRepository) -> None:
        self._repo = post_processed_repo

    async def enrich(self) -> int:
        """
        Query all unenriched articles (reference_urls IS NULL), fetch Google
        Search results for each, and persist the outcome.

        Returns the number of articles that received at least one URL.
        Idempotent: safe to call on every scheduler cycle.
        """
        if not settings.GOOGLE_SEARCH_API_KEY or not settings.GOOGLE_SEARCH_ENGINE_ID:
            logger.debug("SearchEnrichmentService: Google Search not configured — skipping")
            return 0

        unenriched = await self._repo.get_without_reference_urls(
            limit=settings.GOOGLE_SEARCH_MAX_PER_RUN,
        )

        if not unenriched:
            logger.info("SearchEnrichmentService: no unenriched articles — skipping")
            return 0

        logger.info(
            "SearchEnrichmentService: %d article(s) need enrichment (quota cap=%d/run)",
            len(unenriched),
            settings.GOOGLE_SEARCH_MAX_PER_RUN,
        )

        enriched_count = 0
        delay = settings.GOOGLE_SEARCH_DELAY_SECONDS

        for article in unenriched:
            urls = await fetch_related_urls(article.title)

            if urls:
                # Store real URLs — article is fully enriched.
                await self._repo.update_reference_urls(article.id, urls)
                enriched_count += 1
                logger.debug(
                    "SearchEnrichmentService: article_id=%d enriched with %d URL(s)",
                    article.id,
                    len(urls),
                )
            else:
                # Store empty list as a sentinel: "searched, nothing found".
                # This prevents the article from being re-queried on future runs.
                await self._repo.mark_reference_urls_searched(article.id)
                logger.debug(
                    "SearchEnrichmentService: article_id=%d — no URLs found, marked as searched",
                    article.id,
                )

            # Throttle between every request to respect free-tier rate limits.
            await asyncio.sleep(delay)

        logger.info(
            "SearchEnrichmentService: %d/%d article(s) received URLs",
            enriched_count,
            len(unenriched),
        )
        return enriched_count
