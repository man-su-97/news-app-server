import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.models.post_processed_article import PostProcessedArticle
from app.repositories.final_article_repo import FinalArticleRepository
from app.repositories.post_processed_article_repo import PostProcessedArticleRepository

logger = logging.getLogger(__name__)


def _time_decay_factor(published_at: datetime | None) -> float:
    if published_at is None:
        return settings.DECAY_DAY

    now = datetime.now(tz=timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)

    hours_old = (now - published_at).total_seconds() / 3600

    if hours_old < 6:
        return settings.DECAY_FRESH
    if hours_old < 24:
        return settings.DECAY_RECENT
    if hours_old < 72:
        return settings.DECAY_DAY
    if hours_old < 168:
        return settings.DECAY_WEEK
    return settings.DECAY_OLD


def _compute_rank_score(article: PostProcessedArticle) -> float:
    imp_score = article.imp_score or 1
    decay = _time_decay_factor(article.published_at)
    return round(imp_score * decay, 2)


class PublishingService:
    def __init__(
        self,
        post_processed_repo: PostProcessedArticleRepository,
        final_article_repo: FinalArticleRepository,
    ) -> None:
        self._post_processed_repo = post_processed_repo
        self._final_article_repo = final_article_repo

    async def publish(self, top_n: int = 20) -> int:
        top_articles = await self._post_processed_repo.get_top_by_imp_score(limit=top_n)

        if not top_articles:
            logger.info("PublishingService: no scored articles to publish")
            return 0

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

        count = await self._final_article_repo.upsert_batch(rows)
        logger.info("PublishingService: %d final_articles rows written", count)
        return count
