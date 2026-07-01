"""Test setup shared across the suite.

Set required env vars *before* anything imports `app.core.config`, so importing
`app.main` in route tests doesn't need a real `.env`. No real connection is
opened at import time (the DB engine and Redis client are lazy).
"""

import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")


class FakeRedis:
    """In-memory stand-in for the async Redis client used by the rate limiter."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def ttl(self, key: str) -> int:
        return 30
