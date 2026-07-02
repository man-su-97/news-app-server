from pydantic import BaseModel, Field


class IndexRequest(BaseModel):
    # Bounded so a single call can't try to embed an unbounded batch.
    limit: int = Field(default=100, ge=1, le=100)


class IndexResponse(BaseModel):
    indexed_articles: int
    indexed_chunks: int


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    k: int | None = Field(default=None, ge=1, le=50)


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
