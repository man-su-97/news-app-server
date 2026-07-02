# News Aggregator + AI News Intelligence

A FastAPI backend that ingests news from RSS/REST sources into PostgreSQL and
serves it over a REST API — with an **AI layer** that makes the corpus
searchable by meaning and answerable in natural language via
retrieval-augmented generation (RAG).

- **Ingestion**: pull articles from RSS feeds and JSON REST APIs, normalise them
  into a canonical `Article`, deduplicate by URL.
- **Semantic search**: embed articles (OpenAI `text-embedding-3-small`) into
  **pgvector** and search by cosine similarity (HNSW index).
- **Hybrid search + metadata filters**: opt-in `mode: "hybrid"` fuses vector search
  with Postgres full-text (`tsvector` + GIN) via Reciprocal Rank Fusion; filter by
  source and published-date range on `/ai/search`, `/ai/ask`, and the agent tool.
- **Grounded Q&A (RAG)**: answer questions using only retrieved articles, with
  inline `[n]` citations; refuses when nothing relevant is found.
- **Agent**: a LangGraph tool-using agent that searches and reads articles to
  answer multi-step questions.
- **Safety**: prompt-injection blocking and PII redaction on AI inputs.
- **Evaluation**: retrieval metrics (precision/recall/MRR) over a golden set, plus
  optional RAGAS generation scoring.
- **Production-minded**: Redis rate limiting on AI endpoints, LLM token
  optimisation (similarity threshold, context-token budget, output cap, latency +
  usage logging), and a layered, dependency-injected, test-covered codebase.

For a file-by-file deep dive, see [`ARCHITECTURE.md`](ARCHITECTURE.md); for the
AI-layer design and trade-offs, see
[`docs/design/ai-news-intelligence.md`](docs/design/ai-news-intelligence.md) and
[`docs/design/hybrid-retrieval.md`](docs/design/hybrid-retrieval.md).

## Tech stack

| Area | Choice |
|------|--------|
| Web / async | FastAPI, uvicorn |
| ORM / DB | SQLAlchemy 2.0 (async), asyncpg, PostgreSQL + **pgvector** |
| Migrations | Alembic |
| Config / validation | Pydantic v2, pydantic-settings |
| Ingestion | httpx, feedparser |
| AI | OpenAI (`text-embedding-3-small`, `gpt-4o-mini`), LangChain, LangGraph |
| Rate limiting | Redis |
| Tooling | uv, pytest, ruff |

## Architecture

Strict layered design — each layer only calls the one below it:

```
API (routers)  →  Services (business logic)  →  Repositories (SQL)  →  Models  →  PostgreSQL
```

External clients (OpenAI, Redis) are injected into services so they can be faked
in tests. AI business logic lives under `app/services/ai/`.

```
app/
├── api/            # thin HTTP routers (sources, articles, ingest, ai)
├── core/           # config, db engine, DI, redis, rate limiting
├── models/         # SQLAlchemy tables (source, article, article_chunk)
├── repositories/   # DB access only
├── schemas/        # Pydantic request/response contracts
└── services/
    ├── fetchers/   # RSS + REST fetchers
    └── ai/         # chunking, embeddings, indexing, retrieval, rag, tokens, llm
```

## Getting started

### Prerequisites

- [uv](https://docs.astral.sh/uv/) and Python 3.12
- Docker (for PostgreSQL/pgvector and Redis)
- An OpenAI API key (only needed for the AI endpoints)

### Local development

Backing services run in Docker; the API runs on your host with reload.

```bash
docker compose up -d                 # Postgres (pgvector) + Redis on localhost
cp .env.local.example .env.local     # then set OPENAI_API_KEY
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --env-file .env.local
```

API docs at http://localhost:8000/docs.

### Production (full stack in Docker)

```bash
cp .env.prod.example .env.prod       # set real secrets; never commit this file
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
```

The `api` container applies migrations (`alembic upgrade head`) before starting.

## Configuration

Settings load from the environment via pydantic-settings. `DATABASE_URL` is
required; `OPENAI_API_KEY` is required only for AI endpoints (they return `503`
without it — the rest of the app still runs). See `.env.local.example` and
`.env.prod.example` for the full list, including embedding/LLM models, chunking,
token-optimisation, and rate-limit settings.

## API

### Sources & articles

| Method | Path | Description |
|--------|------|-------------|
| POST | `/sources/` | Register an RSS or REST source |
| GET | `/sources/` | List active sources |
| GET | `/sources/{id}` | Get a source |
| GET | `/articles/` | Paginated article list |
| GET | `/articles/{id}` | Get an article |
| POST | `/ingest/rss` | Ingest a source's RSS feed |
| POST | `/ingest/api` | Ingest a source's REST API |

### AI layer

| Method | Path | Description |
|--------|------|-------------|
| POST | `/ai/index` | Chunk + embed not-yet-indexed articles (body: `{"limit": 1..100}`) |
| POST | `/ai/search` | Semantic search → ranked chunks with similarity scores |
| POST | `/ai/ask` | Grounded RAG answer with citations |
| POST | `/ai/agent` | LangGraph agent that uses tools (search/read) to answer |

Evaluation (needs a populated DB + key):

```bash
uv run python -m scripts.eval_retrieval   # precision@k / recall@k / MRR
uv sync --extra eval && uv run python -m scripts.eval_ragas   # RAGAS (optional)
```

Typical flow: register a source → ingest → `POST /ai/index` → then `POST /ai/search`
or `POST /ai/ask`.

```bash
# Register + ingest an RSS source
curl -X POST http://localhost:8000/sources -H "Content-Type: application/json" \
  -d '{"name":"BBC News","type":"rss","url":"https://feeds.bbci.co.uk/news/rss.xml"}'
curl -X POST http://localhost:8000/ingest/rss -H "Content-Type: application/json" \
  -d '{"source_id":1}'

# Embed, then ask
curl -X POST http://localhost:8000/ai/index
curl -X POST http://localhost:8000/ai/ask -H "Content-Type: application/json" \
  -d '{"question":"What did the central bank decide this week?"}'
```

## Testing

```bash
uv run pytest        # unit + route tests (no DB/API key required — clients are faked)
uv run ruff check .  # lint
```

## License

MIT
