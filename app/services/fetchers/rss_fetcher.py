import asyncio
import logging

import feedparser

logger = logging.getLogger(__name__)


class RSSFetcher:
    async def fetch(self, url: str):
        try:
            feed = await asyncio.to_thread(feedparser.parse, url)
        except Exception as exc:
            logger.error("RSS fetch failed for %s: %s", url, exc)
            raise RuntimeError(f"Failed to fetch RSS feed: {url}") from exc

        if feed.bozo and feed.bozo_exception:
            logger.warning(
                "Malformed RSS at %s (bozo flag set): %s", url, feed.bozo_exception
            )

        if not feed.entries:
            logger.warning("No entries found in RSS feed: %s", url)

        return feed
