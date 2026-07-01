# AI News Intelligence Layer — Design

## Goal

Add a Retrieval-Augmented Generation (RAG) layer on top of the news aggregator so
that stored articles can be searched semantically and questioned in natural
language, with answers grounded in and cited from the underlying articles.

## Scope

| Capability | Status |
|------------|--------|
| RAG pipeline (ingest → chunk → embed → vector search → prompt assembly) | Built (Phase 1) |
| Embeddings + pgvector semantic search | Built (Phase 1) |
| Grounded Q&A with citations + refusal on empty retrieval | Built (Phase 1) |
| LLM token optimisation (threshold, context budget, output cap, usage logging) | Built |
| Rate limiting on AI endpoints | Built |
| Agentic tool-use loop (LangGraph) | Planned (Phase 2) |
| Prompt-injection mitigation + PII redaction | Planned (Phase 3) |
| RAG evaluation (RAGAS) + observability | Planned (Phase 4) |

## Provider & framework decisions

- **OpenAI** for embeddings (`text-embedding-3-small`, 1536 dims) and generation
  (`gpt-4o-mini`). Single SDK, low cost.
  - `-small` over `-large`: ~1/5 the cost and lower latency; recall is sufficient
    for short-news text.
- **pgvector** over a dedicated vector DB (Pinecone/Qdrant/Chroma/FAISS): reuses
  the Postgres already in the stack, keeps embeddings transactionally consistent
  with `articles`, and adds no new infrastructure. A dedicated ANN engine wins at
  tens-of-millions of vectors, which this corpus is not near.
- **HNSW index** (`vector_cosine_ops`) over IVFFlat: better recall, no training
  step, and it handles incremental inserts well for a continuously-growing feed.
- **Cosine distance**: embeddings are direction-meaningful, not magnitude-meaningful.
- **LangChain** for the RAG chain and **LangGraph** for the agent (Phase 2).
  Chunking is written by hand rather than delegated to a splitter, to keep the
  strategy explicit and tunable.
- **Grounding + numbered citations** as the primary hallucination defence: the
  prompt instructs the model to answer only from the provided context and to say
  so when the answer is absent; every context block is numbered and cited.

## Architecture (fits the existing layered structure)

```
Client
  │  POST /ai/index  /ai/search  /ai/ask   (Phase 1)
  ▼
app/api/routes_ai.py
  ▼
app/services/ai/
  chunking.py     hand-written recursive character chunker (pure, unit-tested)
  embeddings.py   OpenAI embeddings wrapper (injectable)
  indexing.py     article → chunks → embeddings → DB
  retrieval.py    query → embed → pgvector cosine top-k
  tokens.py       tiktoken-based token counting (with fallback)
  llm.py          LangChain ChatOpenAI wrapper + token-usage logging
  rag_service.py  retrieve → filter/budget → grounded prompt → answer + citations
  ▼
app/repositories/chunk_repo.py   inserts + vector search
app/models/article_chunk.py      ArticleChunk(embedding Vector(1536))
Postgres + pgvector
```

New per-layer files mirror existing conventions (models / repositories / schemas /
services / api / deps).

## Data model

`article_chunks`
- `id` PK
- `article_id` FK → articles.id (CASCADE), indexed
- `chunk_index` int (order within article)
- `content` text (the chunk)
- `embedding` `vector(1536)`
- `created_at` timestamptz
- unique(`article_id`, `chunk_index`)
- HNSW index on `embedding` (`vector_cosine_ops`)

## Data flow

**Indexing:** `/ai/index` finds articles with no chunks → builds text from
`title + description + content` → `chunk_text()` → batch-embed → store rows.
Idempotent (only unindexed articles are processed).

**Search:** `/ai/search` embeds the query → `ORDER BY embedding <=> qvec LIMIT k`
→ returns article title/url/snippet + similarity score.

**Ask (RAG):** `/ai/ask` retrieves top-k chunks → drops chunks below a similarity
threshold and packs the rest under a token budget → numbers them as context →
grounded prompt → LLM → returns answer + the citations actually used.

## Token optimisation (RAG path)

- Drop retrieved chunks below `RETRIEVAL_MIN_SCORE` before prompting.
- Pack context under `MAX_CONTEXT_TOKENS` (tiktoken), always keeping the top chunk.
- Cap generation with `LLM_MAX_TOKENS`.
- Log per-call input/output token usage for cost visibility.

## Error handling

- Missing `OPENAI_API_KEY` → 503 with a clear message (the base app still boots).
- Empty/irrelevant retrieval → "I don't have relevant articles on that," no LLM call.
- Per-article errors during indexing are logged and skipped; the batch continues.
- AI endpoints are rate-limited per client IP (fails open if Redis is down).

## Testing

- `chunking.py` is pure and fully unit-tested (size bounds, overlap, boundaries,
  empty input) — no DB or API key required.
- Embedding/LLM clients are injected so `retrieval` and `rag_service` are tested
  with fakes, including token-optimisation behaviour.
- Route tests cover rate limiting (429) and input validation (422).

## Phases

1. **Semantic search + RAG Q&A** — model, migration, chunking, embeddings,
   indexing, retrieval, RAG service, `/ai/index|search|ask`. (Built.)
2. **LangGraph agent** — tools (`semantic_search`, `get_article`,
   `summarize_topic`), state graph, `/ai/agent`.
3. **Safety** — prompt-injection guard + PII redaction wrapping the AI endpoints.
4. **Evaluation & observability** — RAGAS golden set, token/latency metrics.
