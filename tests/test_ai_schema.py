"""API-edge schema tests: mode selection + filter validation (maps to 422).

Pure Pydantic validation — no HTTP, no DB. A raised ValidationError is what
FastAPI turns into a 422 at the route.
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.ai_schema import AskRequest, RetrievalFiltersIn, SearchRequest


def test_search_request_defaults_to_vector_mode():
    req = SearchRequest(query="hi")
    assert req.mode == "vector"
    assert req.filters is None


def test_search_request_accepts_hybrid_and_filters():
    req = SearchRequest(
        query="hi",
        mode="hybrid",
        filters={"source_name": "Reuters", "published_from": "2026-07-01T00:00:00"},
    )
    assert req.mode == "hybrid"
    assert req.filters.source_name == "Reuters"


def test_ask_request_also_supports_mode_and_filters():
    req = AskRequest(question="q", mode="hybrid")
    assert req.mode == "hybrid"


def test_invalid_mode_rejected():
    with pytest.raises(ValidationError):
        SearchRequest(query="hi", mode="fuzzy")


def test_filters_reject_inverted_date_range():
    with pytest.raises(ValidationError):
        RetrievalFiltersIn(
            published_from=datetime(2026, 7, 2),
            published_to=datetime(2026, 7, 1),
        )


def test_filters_accept_valid_range():
    f = RetrievalFiltersIn(
        published_from=datetime(2026, 7, 1),
        published_to=datetime(2026, 7, 2),
    )
    assert f.published_from < f.published_to


def test_filters_allow_open_ended_range():
    # only one bound set is fine
    assert RetrievalFiltersIn(published_from=datetime(2026, 7, 1)).published_to is None
