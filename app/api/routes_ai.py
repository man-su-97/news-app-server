from fastapi import APIRouter, Depends

from app.core.deps import (
    get_indexing_service,
    get_rag_service,
    get_retrieval_service,
)
from app.core.rate_limit import (
    ai_ask_rate_limit,
    ai_index_rate_limit,
    ai_search_rate_limit,
)
from app.schemas.ai_schema import (
    AskRequest,
    AskResponse,
    CitationOut,
    IndexRequest,
    IndexResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)
from app.services.ai.indexing import IndexingService
from app.services.ai.rag_service import RagService
from app.services.ai.retrieval import RetrievalService

router = APIRouter()

_SNIPPET_LEN = 240


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
    """Semantic (vector) search over article chunks."""
    chunks = await service.search(body.query, k=body.k)
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
    "/ask",
    response_model=AskResponse,
    dependencies=[Depends(ai_ask_rate_limit)],
)
async def ask(
    body: AskRequest,
    service: RagService = Depends(get_rag_service),
):
    """Grounded RAG answer with citations over the news corpus."""
    result = await service.ask(body.question, k=body.k)
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
