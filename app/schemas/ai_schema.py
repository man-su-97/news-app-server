from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SearchMode = Literal["vector", "hybrid"]


class RetrievalFiltersIn(BaseModel):
    """Metadata filters accepted at the API edge. Mapped to the plain
    `RetrievalFilters` dataclass before reaching the service/repository."""

    source_id: int | None = None
    source_name: str | None = None
    published_from: datetime | None = None
    published_to: datetime | None = None

    @model_validator(mode="after")
    def _check_range(self) -> "RetrievalFiltersIn":
        if (
            self.published_from is not None
            and self.published_to is not None
            and self.published_from > self.published_to
        ):
            raise ValueError("published_from must be <= published_to")
        return self


class IndexRequest(BaseModel):
    # Bounded so a single call can't try to embed an unbounded batch.
    limit: int = Field(default=100, ge=1, le=100)


class IndexResponse(BaseModel):
    indexed_articles: int
    indexed_chunks: int


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    k: int | None = Field(default=None, ge=1, le=50)
    mode: SearchMode = "vector"
    filters: RetrievalFiltersIn | None = None


class SearchResultItem(BaseModel):
    article_id: int
    chunk_id: int
    title: str
    url: str
    snippet: str
    score: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    k: int | None = Field(default=None, ge=1, le=50)
    mode: SearchMode = "vector"
    filters: RetrievalFiltersIn | None = None


class CitationOut(BaseModel):
    ref: int
    article_id: int
    title: str
    url: str


class AskResponse(BaseModel):
    question: str
    answer: str
    citations: list[CitationOut]


class AgentRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class AgentResponse(BaseModel):
    question: str
    answer: str
    tools_used: list[str]
