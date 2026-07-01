"""Route-level tests for the AI endpoints: rate limiting + input validation.

Uses TestClient with dependency overrides so no real Redis, Postgres, or OpenAI
key is required.
"""

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.deps import get_indexing_service, get_retrieval_service
from app.core.redis import get_redis
from app.main import app
from tests.conftest import FakeRedis


class FakeRetrieval:
    async def search(self, query, k=None):
        return []


def test_ai_search_second_call_is_rate_limited(monkeypatch):
    # One request per minute makes the second call trip the limit. A single
    # shared FakeRedis persists the counter across both requests.
    monkeypatch.setattr(settings, "RATE_LIMIT_SEARCH_PER_MIN", 1)
    shared_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: shared_redis
    app.dependency_overrides[get_retrieval_service] = lambda: FakeRetrieval()
    try:
        client = TestClient(app)
        first = client.post("/ai/search", json={"query": "anything"})
        second = client.post("/ai/search", json={"query": "anything"})
        assert first.status_code == 200
        assert second.status_code == 429
        assert "Try again in" in second.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_index_limit_out_of_range_returns_422(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_INDEX_PER_MIN", 100)
    shared_redis = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: shared_redis
    # Body validation fails before the service is used; provide a stub so
    # dependency resolution never touches OpenAI.
    app.dependency_overrides[get_indexing_service] = lambda: object()
    try:
        client = TestClient(app)
        assert client.post("/ai/index", json={"limit": 0}).status_code == 422
        assert client.post("/ai/index", json={"limit": 101}).status_code == 422
    finally:
        app.dependency_overrides.clear()
