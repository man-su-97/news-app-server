"""Fixed-window rate limiting for the AI endpoints, backed by Redis.

Each caller (by client IP) gets `limit` requests per 60s window per bucket. The
window is implemented with `INCR` + `EXPIRE`: the first request in a window sets
the TTL, and the counter resets automatically when the key expires.

Fails **open** — if Redis is unreachable the request is allowed rather than
erroring, so an infra hiccup never takes the API down. Limits are read from
settings at call time so they can be overridden in tests.
"""

import logging

from fastapi import Depends, HTTPException, Request
from redis.asyncio import Redis

from app.core.config import settings
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 60


async def _check(redis: Redis, key: str, limit: int) -> tuple[bool, int]:
    """Return (allowed, retry_after_seconds)."""
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, _WINDOW_SECONDS)
        if count > limit:
            ttl = await redis.ttl(key)
            return False, ttl if ttl and ttl > 0 else _WINDOW_SECONDS
        return True, 0
    except Exception as exc:  # Redis down → fail open
        logger.warning("Rate limiter unavailable (%s); allowing request", exc)
        return True, 0


def rate_limit(bucket: str, per_min_attr: str):
    """Build a FastAPI dependency enforcing `settings.<per_min_attr>` per minute."""

    async def dependency(
        request: Request, redis: Redis = Depends(get_redis)
    ) -> None:
        limit = getattr(settings, per_min_attr)
        identity = request.client.host if request.client else "anonymous"
        allowed, retry_after = await _check(redis, f"rl:{bucket}:{identity}", limit)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
            )

    return dependency


# One named dependency per AI endpoint (limits pulled from settings at call time).
ai_index_rate_limit = rate_limit("ai_index", "RATE_LIMIT_INDEX_PER_MIN")
ai_search_rate_limit = rate_limit("ai_search", "RATE_LIMIT_SEARCH_PER_MIN")
ai_ask_rate_limit = rate_limit("ai_ask", "RATE_LIMIT_ASK_PER_MIN")
ai_agent_rate_limit = rate_limit("ai_agent", "RATE_LIMIT_AGENT_PER_MIN")
