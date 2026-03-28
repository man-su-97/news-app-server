"""
app/services/google_search_service.py — Google Custom Search API client
========================================================================
Fetches related news URLs for a given article title using the
Google Custom Search JSON API (free tier: 100 queries/day).

Usage is intentionally conservative:
  - Sequential calls only (no concurrency)
  - Configurable delay between requests (GOOGLE_SEARCH_DELAY_SECONDS)
  - Returns at most GOOGLE_SEARCH_RESULTS_PER_ARTICLE URLs per article
"""

import asyncio
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_SEARCH_ENDPOINT = "https://www.googleapis.com/customsearch/v1"


async def fetch_related_urls(title: str) -> list[str]:
    """Search Google for news related to *title*; return list of URLs.

    Returns an empty list if the API keys are not configured or if the
    request fails — caller should treat this as a non-fatal no-op.
    """
    if not settings.GOOGLE_SEARCH_API_KEY or not settings.GOOGLE_SEARCH_ENGINE_ID:
        return []

    params = {
        "key": settings.GOOGLE_SEARCH_API_KEY,
        "cx": settings.GOOGLE_SEARCH_ENGINE_ID,
        "q": title,
        "num": settings.GOOGLE_SEARCH_RESULTS_PER_ARTICLE,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_SEARCH_ENDPOINT, params=params)
            resp.raise_for_status()
            data = resp.json()

        urls = [item["link"] for item in data.get("items", []) if item.get("link")]
        logger.debug("Google Search for %r → %d URLs", title[:60], len(urls))
        return urls

    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Google Search HTTP error %d for %r: %s",
            exc.response.status_code,
            title[:60],
            exc.response.text[:200],
        )
    except Exception as exc:
        logger.warning("Google Search failed for %r: %s", title[:60], exc)

    return []


async def enrich_articles_with_reference_urls(
    articles: list[dict],
    title_key: str = "title",
) -> None:
    """Populate ``reference_urls`` in-place for each article dict that lacks them.

    Requests are made one-at-a-time with GOOGLE_SEARCH_DELAY_SECONDS between
    each call to stay within the free-tier quota.
    """
    if not settings.GOOGLE_SEARCH_API_KEY or not settings.GOOGLE_SEARCH_ENGINE_ID:
        return

    delay = settings.GOOGLE_SEARCH_DELAY_SECONDS

    for article in articles:
        if article.get("reference_urls"):
            # Already populated — skip to save quota.
            continue

        title = article.get(title_key, "")
        if not title:
            continue

        urls = await fetch_related_urls(title)
        if urls:
            article["reference_urls"] = urls

        # Throttle: wait between every request, including after the last one,
        # because the caller may run multiple batches.
        await asyncio.sleep(delay)
