"""Minimal async Redis client provider.

A single lazily-created client is reused across requests. `from_url` does not
open a connection until the first command, so importing this module (and booting
the app) never requires Redis to be running.
"""

from redis.asyncio import Redis, from_url

from app.core.config import settings

_client: Redis | None = None


def get_redis() -> Redis:
    """FastAPI dependency returning the shared async Redis client."""
    global _client
    if _client is None:
        _client = from_url(settings.REDIS_URL, decode_responses=True)
    return _client
