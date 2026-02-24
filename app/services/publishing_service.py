"""
app/services/publishing_service.py — News Feed Publishing Service
==================================================================
Selects top-ranked post-processed articles and publishes them to final_articles.

Pipeline position:  post_processed_articles → [here] → final_articles

Called by the scheduler after every ingestion cycle. Flow:
  1. Load top N post_processed_articles ordered by imp_score (from DB)
  2. For each, compute rank_score = time-decay(imp_score, published_at)
  3. Upsert into final_articles (insert new, update rank_score on existing)

Ranking formula:
  rank_score = imp_score * time_decay_factor(hours_old)

  time_decay_factor:
    articles published < 6h ago  → 1.0   (full score)
    articles published 6-24h ago → 0.75  (25% decay)
    articles published 1-3d ago  → 0.50  (50% decay)
    articles published 3-7d ago  → 0.25  (75% decay)
    articles older than 7 days   → 0.10  (90% decay)

  This ensures fresh breaking news beats older articles even if they scored
  similarly on severity — the feed shows what's happening NOW.

Design decisions:
  - Idempotent: running publish() multiple times for the same set of articles
    just updates rank_score, never creates duplicates.
  - Best-effort: if one article fails to insert, others continue.
  - top_n configurable: default 20 is appropriate for a mobile news card feed.
    Increase to 50+ for a web dashboard showing more articles.
"""

import logging
from datetime import datetime, timezone

from app.models.post_processed_article import PostProcessedArticle
from app.repositories.final_article_repo import FinalArticleRepository
from app.repositories.post_processed_article_repo import PostProcessedArticleRepository

logger = logging.getLogger(__name__)

# --- Ranking constants ---
_DECAY_FULL = 1.0      # articles published < 6h ago
_DECAY_RECENT = 0.75   # 6-24h
_DECAY_DAY = 0.50      # 1-3 days
_DECAY_WEEK = 0.25     # 3-7 days
_DECAY_OLD = 0.10      # > 7 days


def _time_decay_factor(published_at: datetime | None) -> float:
    """Return a 0.1-1.0 time decay multiplier based on article age."""
    if published_at is None:
        # No publish time → treat as 1 day old (moderate decay)
        return _DECAY_DAY

    now = datetime.now(tz=timezone.utc)
    # Ensure timezone-aware comparison
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)

    hours_old = (now - published_at).total_seconds() / 3600

    if hours_old < 6:
        return _DECAY_FULL
    if hours_old < 24:
        return _DECAY_RECENT
    if hours_old < 72:       # 3 days
        return _DECAY_DAY
    if hours_old < 168:      # 7 days
        return _DECAY_WEEK
    return _DECAY_OLD


def _compute_rank_score(article: PostProcessedArticle) -> float:
    """Compute the rank_score for a post-processed article.

    rank_score = imp_score * time_decay_factor

    Null imp_score → uses 1 (minimum, so it still appears but ranked last).
    Result range: approximately 0.1 – 100.0
    """
    imp_score = article.imp_score or 1
    decay = _time_decay_factor(article.published_at)
    return round(imp_score * decay, 2)


class PublishingService:
    """Selects and publishes top-ranked articles to the final news feed.

    Constructor takes repositories — no raw DB sessions.
    This keeps the service testable: tests can pass mock repos.
    """

    def __init__(
        self,
        post_processed_repo: PostProcessedArticleRepository,
        final_article_repo: FinalArticleRepository,
    ) -> None:
        self._post_processed_repo = post_processed_repo
        self._final_article_repo = final_article_repo

    async def publish(self, top_n: int = 20) -> int:
        """Select top N articles by imp_score and publish to final_articles.

        Called by the scheduler after each ingestion run.

        Args:
            top_n: how many articles to include in the final feed.
                   Default 20 is good for a mobile news card carousel.

        Returns:
            Count of rows inserted or updated in final_articles.
        """
        # Step 1: Load top candidates by imp_score
        top_articles = await self._post_processed_repo.get_top_by_imp_score(limit=top_n)

        if not top_articles:
            logger.info("PublishingService: no scored articles to publish")
            return 0

        # Step 2: Compute rank_score for each and build the upsert rows
        rows = []
        for article in top_articles:
            rank_score = _compute_rank_score(article)
            rows.append({
                "post_processed_article_id": article.id,
                "title": article.title,
                "description": article.description,
                "image_url": article.image_url,
                "reference_urls": article.reference_urls,
                "rank_score": rank_score,
            })

        logger.info(
            "PublishingService: publishing %d articles, top rank_score=%.1f",
            len(rows),
            max(r["rank_score"] for r in rows),
        )

        # Step 3: Upsert into final_articles
        count = await self._final_article_repo.upsert_batch(rows)
        logger.info("PublishingService: %d final_articles rows written", count)
        return count
