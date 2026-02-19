import logging

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class RestFetcher:
    async def fetch(self, url: str, headers: dict | None = None) -> list[dict]:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                response = await client.get(url, headers=headers or {})
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "HTTP %s returned from %s", exc.response.status_code, url
                )
                raise
            except httpx.RequestError as exc:
                logger.error("Request error fetching %s: %s", url, exc)
                raise

        data = response.json()

        # Support bare array or common envelope shapes: {articles:[...]}, {items:[...]}, etc.
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("articles", "items", "results", "data"):
                if key in data and isinstance(data[key], list):
                    return data[key]

        logger.warning("Unexpected JSON shape from %s — expected list or envelope dict", url)
        return []
