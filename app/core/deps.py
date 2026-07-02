from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.repositories.article_repo import ArticleRepository
from app.repositories.chunk_repo import ChunkRepository
from app.repositories.source_repo import SourceRepository
from app.services.ai.agent.graph import AgentService
from app.services.ai.embeddings import Embedder, OpenAIEmbedder
from app.services.ai.indexing import IndexingService
from app.services.ai.llm import OpenAIChatCompleter, build_chat_model
from app.services.ai.rag_service import RagService
from app.services.ai.retrieval import RetrievalService
from app.services.ingestion_service import IngestionService


async def get_source_repo(db: AsyncSession = Depends(get_db)) -> SourceRepository:
    return SourceRepository(db)


async def get_article_repo(db: AsyncSession = Depends(get_db)) -> ArticleRepository:
    return ArticleRepository(db)


async def get_ingestion_service(db: AsyncSession = Depends(get_db)) -> IngestionService:
    return IngestionService(SourceRepository(db), ArticleRepository(db))


# --- AI News Intelligence layer ---


def _require_openai_key() -> str:
    if not settings.OPENAI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="AI features are unavailable: OPENAI_API_KEY is not configured.",
        )
    return settings.OPENAI_API_KEY


async def get_chunk_repo(db: AsyncSession = Depends(get_db)) -> ChunkRepository:
    return ChunkRepository(db)


def get_embedder() -> Embedder:
    return OpenAIEmbedder(
        api_key=_require_openai_key(), model=settings.EMBEDDING_MODEL
    )


async def get_indexing_service(
    chunk_repo: ChunkRepository = Depends(get_chunk_repo),
    embedder: Embedder = Depends(get_embedder),
) -> IndexingService:
    return IndexingService(
        chunk_repo,
        embedder,
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
    )


async def get_retrieval_service(
    chunk_repo: ChunkRepository = Depends(get_chunk_repo),
    embedder: Embedder = Depends(get_embedder),
) -> RetrievalService:
    return RetrievalService(chunk_repo, embedder, top_k=settings.RETRIEVAL_TOP_K)


async def get_rag_service(
    retrieval: RetrievalService = Depends(get_retrieval_service),
) -> RagService:
    chat = OpenAIChatCompleter(
        api_key=_require_openai_key(),
        model=settings.LLM_MODEL,
        max_tokens=settings.LLM_MAX_TOKENS,
    )
    return RagService(
        retrieval,
        chat,
        top_k=settings.RETRIEVAL_TOP_K,
        min_score=settings.RETRIEVAL_MIN_SCORE,
        max_context_tokens=settings.MAX_CONTEXT_TOKENS,
    )


async def get_agent_service(
    retrieval: RetrievalService = Depends(get_retrieval_service),
    article_repo: ArticleRepository = Depends(get_article_repo),
) -> AgentService:
    chat_model = build_chat_model(
        api_key=_require_openai_key(),
        model=settings.LLM_MODEL,
        max_tokens=settings.LLM_MAX_TOKENS,
    )
    return AgentService(
        chat_model,
        retrieval,
        article_repo,
        max_iterations=settings.AGENT_MAX_ITERATIONS,
    )
