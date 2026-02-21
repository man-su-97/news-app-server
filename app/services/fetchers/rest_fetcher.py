"""
app/services/fetchers/rest_fetcher.py — REST API Fetcher
=========================================================
Fetches articles from JSON REST API endpoints.

Used for news sources that provide a JSON API (e.g. NewsAPI.org) rather than
an RSS feed. The response can be:
  - A plain list: [{"title": "...", "url": "..."}, ...]
  - An envelope dict: {"articles": [...], "totalResults": 100}
    (various key names are tried: articles, items, results, data)

Architecture decision: We use httpx (async HTTP client) instead of the older
`requests` library because httpx is built for async/await. Using synchronous
`requests` inside an async function would block the event loop.

Timeout strategy:
  - connect=5.0s: fail fast if the server isn't reachable at all
  - total=15.0s: allow up to 15 seconds for a full response
  This prevents the fetcher from hanging indefinitely on slow/unresponsive APIs.
"""

import logging

import httpx   # Async HTTP client — the async equivalent of the `requests` library

logger = logging.getLogger(__name__)

# Global timeout configuration — applied to every request made by this fetcher.
# connect=5.0: max time to establish the TCP connection (fail fast if unreachable)
# 15.0 (first arg): max time for the entire request including reading the response
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class RestFetcher:
    """Fetches articles from a JSON REST API endpoint."""

    async def fetch(self, url: str, headers: dict | None = None) -> list[dict]:
        """Make a GET request to the URL and return the list of article dicts.

        headers: optional HTTP headers (e.g. {"Authorization": "Bearer API_KEY"})
        Stored in the Source.config["headers"] field for authenticated APIs.

        Returns a list of dicts — each dict is a raw article/item from the API.
        Returns [] if the response shape is unexpected (logs a warning).
        Raises on HTTP errors (4xx, 5xx) or network errors.
        """
        # "async with" creates the HTTP client and automatically closes it
        # when the block exits — even if an exception occurs (safe cleanup).
        # Using a per-request client (not a shared singleton) is intentional here:
        # each fetch gets fresh connection state, preventing subtle session issues.
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                # Make the GET request with optional custom headers
                response = await client.get(url, headers=headers or {})
                # raise_for_status() raises httpx.HTTPStatusError for 4xx/5xx responses.
                # This means "404 Not Found", "401 Unauthorized", etc. all become exceptions.
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                # The server responded but with an error code (4xx or 5xx)
                logger.error(
                    "HTTP %s returned from %s", exc.response.status_code, url
                )
                raise  # Re-raise — caller (IngestionService) will catch and log
            except httpx.RequestError as exc:
                # Network error: DNS failure, timeout, connection refused, etc.
                logger.error("Request error fetching %s: %s", url, exc)
                raise

        # Parse the response body as JSON
        data = response.json()

        # Handle different API response shapes:
        #
        # Shape 1: Bare list — [{"title": "...", ...}, {"title": "...", ...}]
        # Common in simple APIs and self-hosted news servers.
        if isinstance(data, list):
            return data

        # Shape 2: Envelope dict — {"articles": [...], "totalResults": 100}
        # Common in APIs like NewsAPI.org. Try standard key names.
        if isinstance(data, dict):
            for key in ("articles", "items", "results", "data"):
                if key in data and isinstance(data[key], list):
                    return data[key]  # Found the list — return it

        # Neither shape matched — the API returned something unexpected.
        # Log it and return empty list so ingestion continues with other sources.
        logger.warning("Unexpected JSON shape from %s — expected list or envelope dict", url)
        return []
