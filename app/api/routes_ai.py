from fastapi import APIRouter, Depends

from app.api.safety_guard import enforce_input_safety
from app.core.deps import (
    get_agent_service,
    get_indexing_service,
    get_rag_service,
    get_retrieval_service,
)
from app.core.rate_limit import (
    ai_agent_rate_limit,
    ai_ask_rate_limit,
    ai_index_rate_limit,
    ai_search_rate_limit,
)
from app.repositories.chunk_repo import RetrievalFilters
from app.schemas.ai_schema import (
    AgentRequest,
    AgentResponse,
    AskRequest,
    AskResponse,
    CitationOut,
    IndexRequest,
    IndexResponse,
    RetrievalFiltersIn,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)
from app.services.ai.agent.graph import AgentService
from app.services.ai.indexing import IndexingService
from app.services.ai.rag_service import RagService
from app.services.ai.retrieval import RetrievalService

router = APIRouter()

_SNIPPET_LEN = 240


def _to_filters(f: RetrievalFiltersIn | None) -> RetrievalFilters | None:
    """Map the validated API filter model to the plain repository dataclass."""
    if f is None:
        return None
    return RetrievalFilters(
        source_id=f.source_id,
        source_name=f.source_name,
        published_from=f.published_from,
        published_to=f.published_to,
    )


@router.post(
    "/index",
    response_model=IndexResponse,
    dependencies=[Depends(ai_index_rate_limit)],
)
async def index_articles(
    body: IndexRequest | None = None,
    service: IndexingService = Depends(get_indexing_service),
):
    """Chunk + embed all not-yet-indexed articles into the vector store."""
    limit = body.limit if body else 100
    result = await service.index_pending(limit=limit)
    return IndexResponse(
        indexed_articles=result.indexed_articles,
        indexed_chunks=result.indexed_chunks,
    )


@router.post(
    "/search",
    response_model=SearchResponse,
    dependencies=[Depends(ai_search_rate_limit)],
)
async def semantic_search(
    body: SearchRequest,
    service: RetrievalService = Depends(get_retrieval_service),
):
    """Semantic search over article chunks — vector or hybrid, with filters."""
    chunks = await service.search(
        body.query, k=body.k, mode=body.mode, filters=_to_filters(body.filters)
    )
    return SearchResponse(
        query=body.query,
        results=[
            SearchResultItem(
                article_id=c.article_id,
                chunk_id=c.chunk_id,
                title=c.title,
                url=c.url,
                snippet=c.content[:_SNIPPET_LEN],
                score=round(c.score, 4),
            )
            for c in chunks
        ],
    )


@router.post(
    "/agent",
    response_model=AgentResponse,
    dependencies=[Depends(ai_agent_rate_limit)],
)
async def agent(
    body: AgentRequest,
    service: AgentService = Depends(get_agent_service),
):
    """Multi-step LangGraph agent: searches/reads articles via tools, then answers."""
    question = enforce_input_safety(body.question)
    result = await service.run(question)
    return AgentResponse(
        question=body.question,
        answer=result.answer,
        tools_used=result.tools_used,
    )


@router.post(
    "/ask",
    response_model=AskResponse,
    dependencies=[Depends(ai_ask_rate_limit)],
)
async def ask(
    body: AskRequest,
    service: RagService = Depends(get_rag_service),
):
    """Grounded RAG answer with citations over the news corpus."""
    question = enforce_input_safety(body.question)
    result = await service.ask(
        question, k=body.k, mode=body.mode, filters=_to_filters(body.filters)
    )
    return AskResponse(
        question=body.question,
        answer=result.answer,
        citations=[
            CitationOut(
                ref=c.ref,
                article_id=c.article_id,
                title=c.title,
                url=c.url,
            )
            for c in result.citations
        ],
    )
