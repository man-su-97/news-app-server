import logging

from app.models.source import Source
from app.repositories.article_repo import ArticleRepository
from app.repositories.source_repo import SourceRepository
from app.services.fetchers.rest_fetcher import RestFetcher
from app.services.fetchers.rss_fetcher import RSSFetcher
from app.services.source_normalizer import normalize

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(
        self, source_repo: SourceRepository, article_repo: ArticleRepository
    ) -> None:
        self.source_repo = source_repo
        self.article_repo = article_repo

    async def ingest_rss(self, source: Source) -> int:
        feed = await RSSFetcher().fetch(source.url)
        count = 0
        for item in feed.entries:
            try:
                data = normalize(item)
                if not data["url"]:
                    logger.warning(
                        "Skipping RSS entry with no URL (source_id=%s)", source.id
                    )
                    continue
                await self.article_repo.upsert(data, source.id)
                count += 1
            except Exception as exc:
                logger.error(
                    "Failed to process RSS entry from source_id=%s: %s", source.id, exc
                )
        logger.info(
            "RSS ingestion complete: %d articles from source_id=%s", count, source.id
        )
        return count

    async def ingest_api(self, source: Source) -> int:
        headers = (source.config or {}).get("headers", {})
        items = await RestFetcher().fetch(source.url, headers=headers)
        count = 0
        for item in items:
            try:
                data = normalize(item)
                if not data["url"]:
                    logger.warning(
                        "Skipping API item with no URL (source_id=%s)", source.id
                    )
                    continue
                await self.article_repo.upsert(data, source.id)
                count += 1
            except Exception as exc:
                logger.error(
                    "Failed to process API item from source_id=%s: %s", source.id, exc
                )
        logger.info(
            "API ingestion complete: %d articles from source_id=%s", count, source.id
        )
        return count

    async def ingest(self, source: Source) -> int:
        if source.type == "rss":
            return await self.ingest_rss(source)
        if source.type == "rest":
            return await self.ingest_api(source)
        raise ValueError(f"Unknown source type: {source.type!r}")
