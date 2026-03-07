# Crime News API — Architecture & Operations Guide

> Complete reference: every file explained, end-to-end logic flow, database schema,
> AI pipeline, multi-provider switching, Google Search enrichment, and run instructions.

---

## Table of Contents

1. [What This App Does](#1-what-this-app-does)
2. [How to Run the App](#2-how-to-run-the-app)
3. [Tech Stack](#3-tech-stack)
4. [Project Structure](#4-project-structure)
5. [File-by-File Logic](#5-file-by-file-logic)
6. [Database Schema](#6-database-schema)
7. [End-to-End Pipeline Flow](#7-end-to-end-pipeline-flow)
8. [AI Provider System](#8-ai-provider-system)
9. [Google Search Reference URL Enrichment](#9-google-search-reference-url-enrichment)
10. [Request Flows — End to End](#10-request-flows--end-to-end)
11. [API Reference](#11-api-reference)
12. [Configuration Reference](#12-configuration-reference)
13. [Adding a New AI Provider](#13-adding-a-new-ai-provider)

---

## 1. What This App Does

An **automated AI-powered crime news aggregator** for India.

Every 5 minutes the scheduler:

1. Fetches articles from all active RSS/REST news sources
2. Deduplicates by SHA-256 hash — the same article is never processed twice
3. Pre-filters using a ~50-keyword crime list — skips ~70% of articles before any AI call
4. Sends remaining articles to the configured AI provider, which in a **single call**:
   - Decides if the article is crime-related (non-crime → discard)
   - Extracts: original title, URL, description, image, published date
   - Rewrites the title and description in its own words (plagiarism-safe)
   - Assigns an importance score 1–100 based on severity, scope, and public impact
   - Labels one or more crime sub-categories (murder, fraud, terrorism, …)
   - Resolves the location to an Indian state
5. Stores crime articles across two pipeline tables (`filtered_articles` → `post_processed_articles`)
6. Runs a publishing job every 5 minutes that:
   - Picks the top 20 articles by importance score
   - Fetches related news URLs via Google Custom Search API (if configured)
   - Applies time-decay to compute `rank_score`
   - Upserts them into `final_articles` — the public ranked feed

**AI providers are fully switchable at runtime** via the `/ai-providers/` API — no restart needed.
Currently supported: **Ollama (local)**, Gemini Multimodal, Gemini LangGraph, Anthropic Claude,
OpenAI GPT, any OpenAI-compatible server.

---

## 2. How to Run the App

### Prerequisites

- Python 3.12+
- `uv` package manager (`pip install uv`)
- PostgreSQL database (connection string in `.env`)
- At least one AI provider configured (Ollama locally, or an API key)

### Step 1 — Clone and install

```bash
git clone <repo-url>
cd news-app-server
uv sync          # creates .venv/ and installs all dependencies from uv.lock
```

### Step 2 — Configure environment

Minimum required `.env`:

```env
DATABASE_URL=postgresql+asyncpg://user:password@host:port/dbname

# Choose ONE AI provider:

# Option A — Local Ollama (no API key needed, runs offline)
OLLAMA_MODEL=dengcao/Qwen3-30B-A3B-Instruct-2507:latest
# OLLAMA_URL=http://localhost:11434/v1   # default

# Option B — Google Gemini
# GEMINI_API_KEY=AIzaSy...

# Option C — Anthropic Claude
# ANTHROPIC_API_KEY=sk-ant-...

# Optional — Google Search for reference URL enrichment (100 queries/day free)
# GOOGLE_SEARCH_API_KEY=AIzaSy...
# GOOGLE_SEARCH_ENGINE_ID=abc123...
```

> **Important:** `DATABASE_URL` must use the `postgresql+asyncpg://` scheme.

### Step 3 — Run migrations

```bash
.venv/bin/alembic upgrade head
```

### Step 4 — Start the server

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Step 5 — Add a news source

```bash
curl -X POST http://localhost:8000/sources/ \
  -H "Content-Type: application/json" \
  -d '{"name": "NDTV Crime", "url": "https://feeds.feedburner.com/ndtvnews-crime",
       "type": "rss", "is_active": true, "config": {}}'
```

### Step 6 — Trigger manual ingest and publish

```bash
# Ingest a source immediately
curl -X POST http://localhost:8000/ingest/ -H "Content-Type: application/json" \
  -d '{"source_id": 1}'

# Force a publish run (also triggers Google Search enrichment)
curl -X POST "http://localhost:8000/final-articles/publish?top_n=20"
```

### Step 7 — Read the feed

```bash
curl http://localhost:8000/final-articles/

# Monitor raw ingestion inbox
curl "http://localhost:8000/raw-ingestion/?status=filtered_out&limit=50"
```

### Interactive docs

```
http://localhost:8000/docs    ← Swagger UI
http://localhost:8000/redoc   ← ReDoc
http://localhost:8000/health  ← {"status": "ok"}
```

---

## 3. Tech Stack

| Layer | Technology | Role |
|-------|-----------|------|
| Web framework | **FastAPI** | Async HTTP, automatic OpenAPI/Swagger, Pydantic DI |
| ORM | **SQLAlchemy 2.0 async** | Typed `Mapped[]` columns, JSONB support, Alembic integration |
| DB driver | **asyncpg** | Async PostgreSQL driver |
| Database | **PostgreSQL** | Primary data store |
| Migrations | **Alembic** | Versioned, async-aware schema migrations |
| Scheduler | **APScheduler** | `AsyncIOScheduler` — ingestion + publishing jobs |
| Validation | **Pydantic v2** | Request/response models, settings, AI output schemas |
| Settings | **pydantic-settings** | `.env` loading with type validation |
| RSS parsing | **feedparser** | Handles RSS/Atom, malformed XML |
| HTTP client | **httpx** | Async HTTP for REST source fetching + Google Search |
| AI — local | **Ollama** | Local LLM server, OpenAI-compatible endpoint |
| AI — cloud | **Anthropic SDK** | Claude models |
| AI — cloud | **OpenAI SDK** | GPT models + any OpenAI-compatible server |
| AI — cloud | **langchain-google-genai** | Gemini models via LangChain |
| AI — agents | **LangGraph** | Graph-based multi-node AI pipeline for Gemini |
| ASGI server | **uvicorn** | Runs FastAPI |

---

## 4. Project Structure

```
news-app-server/
├── .env                                       # Runtime config (never commit secrets)
├── .venv/                                     # Python virtual environment (uv managed)
├── alembic.ini                                # Alembic config
├── pyproject.toml                             # Project dependencies
├── uv.lock                                    # Locked dependency versions
├── ARCHITECTURE.md                            # This document
│
├── migrations/
│   ├── env.py                                 # Async-aware Alembic runner
│   └── versions/                              # 11 migration files
│
└── app/
    ├── main.py                                # FastAPI app, routers, lifespan
    │
    ├── core/
    │   ├── config.py                          # All settings from .env
    │   ├── database.py                        # AsyncEngine + session factory
    │   ├── deps.py                            # Dependency injection (repos + services)
    │   └── enums.py                           # SubCategoryEnum, CategoryEnum, lookup dicts
    │
    ├── models/                                # SQLAlchemy ORM table definitions
    │   ├── base.py
    │   ├── source.py                          # news_sources
    │   ├── raw_event.py                       # raw_ingestion (inbox + dedup)
    │   ├── filter_article.py                  # filtered_articles (AI stage 1)
    │   ├── post_processed_article.py          # post_processed_articles (AI stage 2)
    │   ├── final_article.py                   # final_articles (public feed)
    │   ├── ai_provider.py                     # ai_provider_configs + constants
    │   ├── category.py                        # master_category + master_sub_category
    │   └── location.py                        # country + state
    │
    ├── repositories/                          # Data access layer
    │   ├── source_repo.py
    │   ├── raw_ingestion_repo.py              # store_batch, mark_*, get_all, count
    │   ├── filter_article_repo.py
    │   ├── post_processed_article_repo.py     # insert_batch, update_reference_urls
    │   ├── final_article_repo.py              # upsert_batch, get_feed
    │   ├── ai_provider_repo.py
    │   ├── master_data_repo.py
    │   └── article_repo.py                    # Alias for PostProcessedArticleRepository
    │
    ├── schemas/                               # Pydantic request/response models
    │   ├── source_schema.py
    │   ├── article_schema.py                  # FilterArticle, PostProcessed,
    │   │                                      # RawIngestion response schemas
    │   ├── final_article_schema.py
    │   ├── ai_provider_schema.py
    │   └── master_data_schema.py
    │
    ├── api/                                   # HTTP route handlers
    │   ├── routes_sources.py                  # /sources/
    │   ├── routes_ingest.py                   # /ingest/
    │   ├── routes_filter_articles.py          # /filter-articles/
    │   ├── routes_post_processed.py           # /post-processed/
    │   ├── routes_final_articles.py           # /final-articles/ + /publish
    │   ├── routes_raw_ingestion.py            # /raw-ingestion/  ← NEW
    │   ├── routes_ai_providers.py             # /ai-providers/
    │   └── routes_master_data.py              # /master/
    │
    └── services/                              # Business logic
        ├── ingestion_service.py               # Full pipeline orchestrator
        ├── publishing_service.py              # Ranking + Google Search + feed refresh
        ├── google_search_service.py           # Google Custom Search API client ← NEW
        ├── scheduler.py                       # APScheduler jobs
        ├── source_normalizer.py               # to_plain_dict(), parse_date()
        ├── fetchers/
        │   ├── rss_fetcher.py
        │   └── rest_fetcher.py
        └── normalization/
            ├── ai_processor.py                # get_env_fallback_provider()
            ├── provider_factory.py            # Factory + process-lifetime cache
            ├── resolvers.py                   # CategoryResolver, LocationResolver
            ├── canonical_validator.py         # URL and field sanitation
            └── providers/
                ├── base.py                    # AIProvider ABC, prompt, JSON parser
                ├── openai_prov.py             # OpenAICompatibleProvider
                ├── anthropic_prov.py          # AnthropicProvider
                ├── gemini_langgraph_prov.py   # GeminiLangGraphProvider
                └── gemini_multimodal_prov.py  # GeminiMultimodalLangGraphProvider
```

---

## 5. File-by-File Logic

### `app/main.py`
**Role:** FastAPI application factory and startup coordinator.

- Creates the `FastAPI()` app instance with title, version, and description.
- Registers all 8 routers with their URL prefixes and Swagger tags.
- Adds `CORSMiddleware` with `allow_origins=["*"]` for frontend access.
- Uses `@asynccontextmanager lifespan` to call `start_scheduler()` on startup and
  `stop_scheduler()` on shutdown — so jobs run only while the server is alive.
- Exposes `/health` (not in schema) and `/` redirect to `/docs`.

---

### `app/core/config.py`
**Role:** Single source of truth for all runtime configuration.

- Uses `pydantic-settings BaseSettings` which auto-reads from `.env` file and environment variables.
- Every setting has a Python type annotation — invalid values raise a `ValidationError` on startup.
- Groups settings logically: database, AI provider keys, scheduler intervals, rate limits, time-decay
  factors, and Google Search credentials.
- `settings` is a **module-level singleton** — imported everywhere as `from app.core.config import settings`.
- Key groups:
  - Ollama: `OLLAMA_REQUESTS_PER_MINUTE=60`, `OLLAMA_CONCURRENCY=1`, `OLLAMA_BATCH_SIZE=10`
  - Cloud APIs: `CLOUD_REQUESTS_PER_MINUTE=3`, `CLOUD_MAX_ITEMS_PER_RUN=5`
  - Google Search: `GOOGLE_SEARCH_API_KEY`, `GOOGLE_SEARCH_ENGINE_ID`, `GOOGLE_SEARCH_RESULTS_PER_ARTICLE=3`
  - Time decay: `DECAY_FRESH=1.00` through `DECAY_OLD=0.10`

---

### `app/core/database.py`
**Role:** Async database engine and session management.

- Creates a single `AsyncEngine` using `create_async_engine(DATABASE_URL, ...)`.
- Creates an `async_sessionmaker` that produces `AsyncSession` objects.
- Provides `get_db()` as a FastAPI dependency — yields one `AsyncSession` per request,
  auto-closing it after the response. Each request gets its own isolated transaction scope.

---

### `app/core/deps.py`
**Role:** FastAPI dependency injection wiring.

- Each `get_*_repo()` function is a FastAPI `Depends` — called per request to build a repo
  instance from the current `AsyncSession`.
- `get_ingestion_service()` wires together all 5 repositories + the raw DB session that
  `IngestionService` needs for loading resolvers.
- `get_raw_ingestion_repo()` — added to expose the raw ingestion data via the new route.
- Nothing in this file contains business logic; it only instantiates and wires objects.

---

### `app/core/enums.py`
**Role:** Static lookup tables for crime categories.

- `SubCategoryEnum` maps string labels (e.g. `"murder"`) to integer DB IDs.
- `CategoryEnum` maps parent category names to integer IDs.
- `SUB_TO_CATEGORY` dict maps sub-category ID → parent category ID.
- Used by `CategoryResolver` to avoid DB queries for every article.

---

### `app/models/base.py`
**Role:** SQLAlchemy `DeclarativeBase` shared by all ORM models.

All 9 ORM models import from here. Ensures all tables are registered with the same metadata
object, which Alembic uses for `autogenerate`.

---

### `app/models/source.py`
**Role:** ORM for `news_sources` table.

- Columns: `id`, `name`, `type` (rss/rest), `url` (unique), `config` (JSONB), `is_active`, `created_at`.
- Relationship: `raw_ingestions` — one source has many raw rows.
- `config` JSONB allows per-source custom headers, auth tokens, or other fetch params.

---

### `app/models/raw_event.py`
**Role:** ORM for `raw_ingestion` table — the pipeline inbox.

- Every article ever fetched lands here first, before any AI processing.
- `content_hash` (SHA-256 of `source_id + json(payload)`) is the **global dedup key** — unique constraint prevents double-processing.
- `status` lifecycle: `pending` → `filtered` | `filtered_out` | `failed`.
- `normalized_by` records which AI model processed the article (audit trail).
- Relationships: `source` (FK), `filter_article` (one-to-one, optional).

---

### `app/models/filter_article.py`
**Role:** ORM for `filtered_articles` — AI Stage 1 output.

- Stores the AI-extracted and rewritten article after it passes the crime check.
- `main_url` is the upsert key — same URL from two sources writes only one row.
- Holds both original (`title`, `description`) and AI-rewritten (`rewritten_title`, `rewritten_description`) versions.
- `sub_category_ids` and `category_ids` are JSONB integer arrays (GIN indexed for fast filtering).
- `location_state_id` FK → `state` table; `location` is the raw AI string for debugging.

---

### `app/models/post_processed_article.py`
**Role:** ORM for `post_processed_articles` — AI Stage 2 / enrichment store.

- Mirror of `filtered_articles` structure, plus `reference_urls` (PostgreSQL `ARRAY(Text)`).
- `filter_article_id` links back (unique FK) so each filtered article maps to exactly one post-processed row.
- `reference_urls` is populated by Google Custom Search during the publish cycle.
- This is the source table for the publishing service — it queries `imp_score` to select top articles.

---

### `app/models/final_article.py`
**Role:** ORM for `final_articles` — the public ranked feed.

- Terminal stage of the pipeline — the only table the frontend reads.
- `post_processed_article_id` (unique FK) is the upsert key; the same article can be re-ranked across cycles.
- `rank_score = imp_score × time_decay_factor` — recomputed every publish cycle.
- `reference_urls` (ARRAY) carries Google Search links for the frontend to display.
- Kept intentionally small — only the current top-N articles live here.

---

### `app/models/ai_provider.py`
**Role:** ORM for `ai_provider_configs` + provider metadata constants.

- `SUPPORTED_PROVIDERS` frozenset — validated on POST /ai-providers/.
- `PROVIDER_BASE_URLS` dict — auto-fills `base_url` for `ollama` (`http://localhost:11434/v1`) and `gemini`.
- `PROVIDER_DEFAULT_MODELS` dict — suggested model per provider (shown in Swagger examples).
- DB partial unique index: `WHERE is_active = true` — enforces at most one active provider.

---

### `app/models/category.py`
**Role:** ORM for `master_category` and `master_sub_category` tables.

- Read-only reference data seeded by migrations.
- 8 top-level categories (e.g. Violent Crime, Economic Crime).
- 10 sub-categories each linked to a parent category.
- Used by `CategoryResolver` for string-to-ID mapping.

---

### `app/models/location.py`
**Role:** ORM for `country` and `state` tables.

- `state` has 36 rows (Indian states + UTs), seeded by migration.
- Each `state` has `name` and `country_id` (FK → `country`).
- `LocationResolver` loads this table once at resolver init time.

---

### `app/repositories/raw_ingestion_repo.py`
**Role:** All DB operations for the `raw_ingestion` table.

Key methods:
- `compute_content_hash(source_id, raw_payload)` — SHA-256, called once per article in `IngestionService`.
- `store_batch(source_id, hash_raw_pairs)` — bulk INSERT with `ON CONFLICT DO NOTHING` on `content_hash`.
  Returns: `hash_to_raw_id` (all hashes → DB ids) and `unprocessed_hashes` (new + previously stuck-pending).
  The "stuck pending" recovery ensures articles that were stored but never finished processing in a crashed
  run get retried on the next cycle.
- `mark_filtered / mark_filtered_out / mark_failed` — bulk UPDATE with `processed_at` timestamp.
- `get_all(limit, offset, status, source_id)` — paginated query for the frontend monitoring endpoint.
- `count(status, source_id)` — total count for pagination metadata.
- `get_by_id(row_id)` — single row with full `raw_payload` JSON.

---

### `app/repositories/filter_article_repo.py`
**Role:** DB operations for `filtered_articles`.

- `insert_batch(articles, hash_to_raw_id)` — upserts on `main_url` (canonical URL dedup across sources).
  Returns `url_to_filter_id` dict so `post_processed_repo` can set the FK.

---

### `app/repositories/post_processed_article_repo.py`
**Role:** DB operations for `post_processed_articles`.

- `insert_batch(articles, url_to_filter_id)` — upserts on `filter_article_id`.
- `get_top_by_imp_score(limit)` — ordered by `imp_score DESC WHERE imp_score IS NOT NULL`.
  Used by `PublishingService` to select candidates for the feed.
- `update_reference_urls(article_id, urls)` — called by `PublishingService` after Google Search
  to persist found URLs back, preventing re-fetching on the next publish cycle.

---

### `app/repositories/final_article_repo.py`
**Role:** DB operations for `final_articles`.

- `upsert_batch(rows)` — `ON CONFLICT (post_processed_article_id) DO UPDATE SET rank_score, reference_urls, ...`.
  Re-ranks the same article without creating duplicate rows.
- `get_feed(limit, offset, sub_category_id, q)` — JOINs with `post_processed_articles` for sub-category
  filtering; full-text search on `title ILIKE '%q%'`; ordered by `rank_score DESC`.
- `count(sub_category_id, q)` — pagination total.
- `get_by_id(article_id)` — single article fetch.

---

### `app/repositories/ai_provider_repo.py`
**Role:** CRUD for `ai_provider_configs`.

- `get_active()` — `SELECT WHERE is_active = true LIMIT 1`. Returns `None` if none configured.
- `activate(provider_id)` — two-step: set all rows `is_active=false`, then set the target row `true`.
- `deactivate_all()` — sets `is_active=false` on all rows (fall back to env vars).

---

### `app/repositories/master_data_repo.py`
**Role:** Read-only queries for categories, sub-categories, states.

- Used only by the `/master/` endpoints to list reference data for the frontend.
- `MasterCategoryRepository`, `MasterSubCategoryRepository`, `StateRepository` — each wraps a simple `SELECT *`.

---

### `app/schemas/article_schema.py`
**Role:** Pydantic response models for pipeline inspection endpoints.

- `FilterArticleResponse` — fields for `/filter-articles/` endpoint.
- `PostProcessedArticleResponse` / `ArticleListResponse` — fields for `/post-processed/` endpoint.
- `RawIngestionResponse` — includes `raw_payload: dict[str, Any]` for the raw inbox endpoint.
- `RawIngestionListResponse` — wraps list + pagination metadata.
- All use `model_config = {"from_attributes": True}` to work with SQLAlchemy ORM objects directly.

---

### `app/schemas/final_article_schema.py`
**Role:** Pydantic response models for the public feed.

- `FinalArticleResponse` includes `reference_urls: list[str] | None` for Google Search links.
- `FinalArticleListResponse` wraps list + `total`, `limit`, `offset` for pagination.

---

### `app/schemas/ai_provider_schema.py`
**Role:** Pydantic models for the AI provider CRUD API.

- `AIProviderCreate` — validates `provider` is a known `Literal` type.
- Auto-fills `base_url` for `ollama` provider if not supplied.
- `AIProviderResponse` — returns config without exposing the full API key in listing.

---

### `app/api/routes_sources.py`
**Role:** CRUD for news sources (`/sources/`).

- GET list (with `?include_inactive=true`), POST create, GET by ID, PATCH update, DELETE.
- Source pause/resume via `PATCH {"is_active": false}`.

---

### `app/api/routes_ingest.py`
**Role:** Manual pipeline trigger (`POST /ingest/`).

- Takes `{"source_id": N}`, validates source exists and has a supported type.
- Calls `IngestionService.ingest(source)` immediately (same as the scheduler does automatically).
- Returns `{"source_id", "source_type", "ingested"}` — `ingested` is the count of new post-processed rows written.

---

### `app/api/routes_raw_ingestion.py`  *(NEW)*
**Role:** Read-only monitoring endpoint for the pipeline inbox (`/raw-ingestion/`).

- `GET /raw-ingestion/` — paginated list of raw rows, filterable by `?status=` and `?source_id=`.
  Validates `status` against the 5 known values; returns 400 on invalid input.
- `GET /raw-ingestion/{id}` — single row including the full `raw_payload` JSONB.
- Useful for debugging: see exactly what was fetched, what the AI rejected as non-crime,
  what failed, and what the original JSON looked like.

---

### `app/api/routes_filter_articles.py`
**Role:** Read-only view of Stage 1 AI output (`/filter-articles/`).

- GET list (paginated) and GET by ID.
- Useful for auditing: confirms which articles survived AI crime classification.

---

### `app/api/routes_post_processed.py`
**Role:** Read-only view of Stage 2 enriched articles (`/post-processed/`).

- GET list with `?from_date=` / `?to_date=` (ISO 8601) filters.
- Shows `imp_score` and `reference_urls` so you can verify enrichment is working.

---

### `app/api/routes_final_articles.py`
**Role:** Public ranked news feed + manual publish trigger (`/final-articles/`).

- `GET /` — main frontend endpoint; supports `limit`, `offset`, `sub_category_id`, `q` (search).
- `GET /{id}` — single article by ID.
- `POST /publish` — **manual publish trigger**: immediately runs `PublishingService.publish()`,
  which includes Google Search enrichment for articles missing `reference_urls`.
  Use this to force a refresh without waiting for the 5-min scheduler cycle.

---

### `app/api/routes_ai_providers.py`
**Role:** CRUD for AI provider configurations (`/ai-providers/`).

- POST register, GET list, GET active, GET by ID, PATCH activate, DELETE active, DELETE by ID.
- Activating a provider takes effect on the **next** ingest/publish run — no restart needed.

---

### `app/api/routes_master_data.py`
**Role:** Read-only reference data (`/master/`).

- `GET /master/categories` — 8 crime categories for frontend filter UI.
- `GET /master/sub-categories` — 10 sub-categories.
- `GET /master/states` — 36 Indian states/UTs for location filtering.

---

### `app/services/scheduler.py`
**Role:** Registers and manages the two recurring background jobs.

Two APScheduler `IntervalTrigger` jobs:
1. **Ingestion job** — every `INGEST_INTERVAL_MINUTES` (default 5). Calls `IngestionService.ingest()`
   for every active source concurrently via `asyncio.gather()`.
2. **Publishing job** — every `PUBLISH_INTERVAL_MINUTES` (default 5) with a `PUBLISH_OFFSET_SECONDS=30`
   head-start delay so it runs after ingestion finishes.

After a successful ingestion batch, publishing is also triggered **immediately** (in addition to the
scheduled interval) so new articles appear in the feed without a 5-minute wait.

Both jobs use `max_instances=1` — if a run is still in progress when the next trigger fires,
the new run is skipped rather than creating overlapping concurrent executions.

---

### `app/services/ingestion_service.py`
**Role:** Orchestrates the complete article lifecycle from fetch to DB write.

**Constructor** accepts 5 repositories + raw `AsyncSession`. All are optional — if a repo is `None`,
that step is skipped (useful for testing or lightweight operation).

**`ingest(source)` logic — 13 steps:**

1. `_fetch_items(source)` → calls `RSSFetcher` or `RestFetcher` based on `source.type`.
2. `_load_ai_provider()` → DB config first, env fallback second. Returns `(provider, provider_type)`.
   `provider_type` determines which rate limits and item cap to apply.
3. Cap to `max_items` (Ollama: 50, cloud: 5, default: 10).
4. `compute_content_hash()` for every article — SHA-256 once, reused everywhere.
5. `raw_repo.store_batch()` → INSERT OR IGNORE. Returns only new + stuck-pending hashes.
6. `_has_crime_keywords(raw)` — checks ~50 crime terms in title/summary/description.
   Skipped articles go straight to `mark_filtered_out` without any AI call.
7. `_get_limiter_for(provider_type)` → returns the shared `(_RateLimiter, asyncio.Semaphore)`.
   Limiters are process-level singletons so all concurrent source tasks share the same quota.
8. **Ollama batch loop**: for GPU safety, processes articles in `OLLAMA_BATCH_SIZE` chunks with
   `OLLAMA_BATCH_COOLDOWN_SECONDS` pause between batches. Cloud providers process all at once.
9. `asyncio.gather()` with `process_with_semaphore()` — concurrency bounded by semaphore,
   rate bounded by `_RateLimiter.wait()`. Each call: `ai_provider.process(raw, source_type)`.
10. **Bucket results**: crime / filtered_out / failed.
11. `load_resolvers(db)` → loads `CategoryResolver` (enum-based, zero queries) and
    `LocationResolver` (one DB query: full `state` table). Resolves AI string labels to FK integers.
12. `filter_article_repo.insert_batch()` then `post_processed_repo.insert_batch()`.
13. `_update_raw_statuses()` → marks every raw row with its final status.

**Retry logic** in `_call_with_retry()`: on rate-limit errors (HTTP 429, "quota", "resource_exhausted"),
retries with exponential back-off: `delay × 2^attempt`. Non-rate-limit errors fail immediately.

---

### `app/services/publishing_service.py`
**Role:** Selects top articles, enriches with reference URLs, computes rank scores, upserts feed.

**`publish(top_n=20)` logic:**

1. `post_processed_repo.get_top_by_imp_score(limit=top_n)` — ordered by `imp_score DESC`.
2. Build row dicts with `rank_score = imp_score × _time_decay_factor(published_at)`.
3. **Google Search enrichment** (if `GOOGLE_SEARCH_API_KEY` configured):
   - Finds rows where `reference_urls` is `None` or empty.
   - Calls `enrich_articles_with_reference_urls(needs_search)` — sequential with delay.
   - Persists found URLs back to `post_processed_articles` via `update_reference_urls()`
     so the next publish cycle skips them and saves API quota.
4. `final_article_repo.upsert_batch(rows)` — ON CONFLICT updates `rank_score` + `reference_urls`.

**Time-decay table:**

| Age | Factor | Config var |
|-----|--------|-----------|
| < 6 hours | 1.00 | `DECAY_FRESH` |
| 6–24 hours | 0.75 | `DECAY_RECENT` |
| 1–3 days | 0.50 | `DECAY_DAY` |
| 3–7 days | 0.25 | `DECAY_WEEK` |
| > 7 days | 0.10 | `DECAY_OLD` |

---

### `app/services/google_search_service.py`  *(NEW)*
**Role:** Google Custom Search API client for reference URL enrichment.

- `fetch_related_urls(title)` — single `httpx.AsyncClient` GET to the Custom Search JSON API.
  Returns a list of URLs from `data["items"][*]["link"]`. Returns `[]` on any error (non-fatal).
- `enrich_articles_with_reference_urls(articles)` — iterates over article dicts, skips any
  that already have `reference_urls` set (quota conservation). Calls `fetch_related_urls()` for
  each, writes results into `article["reference_urls"]` in-place.
- Between every request: `asyncio.sleep(GOOGLE_SEARCH_DELAY_SECONDS)` to stay within the
  100 queries/day free tier. Default delay: 1 second.
- Both functions check `settings.GOOGLE_SEARCH_API_KEY` and `settings.GOOGLE_SEARCH_ENGINE_ID`
  at the start and return early if either is missing — the service degrades gracefully to no-op.

---

### `app/services/fetchers/rss_fetcher.py`
**Role:** Async RSS/Atom feed fetcher.

- Wraps `feedparser.parse(url)` in `asyncio.to_thread()` — feedparser is synchronous/blocking;
  running it in a thread prevents it from blocking the async event loop.
- Returns `feed` object (callers use `feed.entries`).

---

### `app/services/fetchers/rest_fetcher.py`
**Role:** Async REST API fetcher.

- `httpx.AsyncClient.get(url, headers=headers)` with 15s timeout.
- Handles two response shapes: a list at root `[{...}, ...]` or a dict with an
  `articles` / `items` / `results` / `data` key containing the list.
- Returns `list[dict]`.

---

### `app/services/source_normalizer.py`
**Role:** Converts raw feed objects into plain dicts.

- `to_plain_dict(entry)` — handles feedparser-specific types (`feedparser.FeedParserDict`,
  `time.struct_time`), HTML entity decoding, nested objects → strings.
- `parse_date(s)` — tries ISO 8601, RFC 2822, and common formats; converts to UTC-aware `datetime`.

---

### `app/services/normalization/ai_processor.py`
**Role:** Environment-variable fallback provider resolver.

- `get_env_fallback_provider()` — checks env vars in priority order:
  1. `OLLAMA_MODEL` set? → `create_ollama_from_env()`
  2. `GEMINI_API_KEY` set? → `create_gemini_multimodal_from_env()`
  3. `ANTHROPIC_API_KEY` set? → `create_from_env()`
  4. Nothing → return `None`
- Called by `IngestionService._load_ai_provider()` when no DB config is active.

---

### `app/services/normalization/provider_factory.py`
**Role:** Factory that creates and caches `AIProvider` instances.

- `_provider_cache: dict[tuple, AIProvider]` — module-level process singleton.
- Cache key = `(config.id, config.model, config.api_key)` — ensures a new SDK client
  is created if the key changes, but the same client is reused across all ingest runs.
- `create_from_config(config)` — used for DB-configured providers.
- `create_ollama_from_env(base_url, model)` — builds `OpenAICompatibleProvider` with `api_key="ollama"`.
- `create_gemini_multimodal_from_env(api_key, model)` — recommended Gemini path.
- `_build(config)` — the `if/elif` dispatch that instantiates the correct provider subclass.

---

### `app/services/normalization/providers/base.py`
**Role:** ABC, shared prompt, JSON parser, output schema.

- `SINGLE_PROCESS_PROMPT` — the system prompt used by all providers. Instructs the model to
  return `{"is_crime": false}` immediately for non-crime (minimal tokens) or the full JSON for crime.
- `SingleOutput` (Pydantic model) — validates the AI JSON response. Field validators:
  - `_check_url` — rejects relative or non-HTTP URLs.
  - `_check_sub_category` — rejects unknown category strings.
  - `_check_imp_score` — clamps to 1–100.
- `_extract_json(text)` — cleans raw AI text before `json.loads()`:
  1. Strips ` ```json ... ``` ` markdown fences.
  2. Strips `<think>...</think>` (Qwen3).
  3. Strips `<thinking>...</thinking>` (Claude/Gemini).
  4. Slices from first `{` to last `}` to discard preamble prose.
- `parse_single_output(text, raw_payload)` — calls `_extract_json` → `json.loads` → `SingleOutput.model_validate`.
  Falls back URL to `raw_payload["link"]` if the AI omitted it.
- `AIProvider` ABC defines two abstract members: `model_id` property and `process()` coroutine.
- `build_process_message(raw_payload, source_type)` — serializes the input JSON for the AI user message.

---

### `app/services/normalization/providers/openai_prov.py`
**Role:** Provider for OpenAI, Ollama, Gemini (OpenAI-compat), and custom servers.

- Uses `openai.AsyncOpenAI(api_key, base_url)` with `response_format={"type": "json_object"}` (JSON mode).
- Works for Ollama (no real key needed, `base_url=http://localhost:11434/v1`), standard OpenAI,
  and any vLLM / LM Studio / remote Ollama server.
- `model_id` returns `"ai:{base_host}:{model}"` for the audit trail.

---

### `app/services/normalization/providers/anthropic_prov.py`
**Role:** Provider for Anthropic Claude models.

- Uses `anthropic.AsyncAnthropic(api_key)`.
- Same `SINGLE_PROCESS_PROMPT` as system message; same `parse_single_output()` for JSON parsing.
- `model_id` returns `"ai:anthropic:{model}"`.

---

### `app/services/normalization/providers/gemini_multimodal_prov.py`
**Role:** Recommended Gemini provider using LangGraph structured output.

- Uses `langchain-google-genai` with `with_structured_output(SingleOutput)` — model returns a
  Pydantic object directly, no regex/JSON parsing needed.
- LangGraph graph: `START → extract_node (zero-cost: just formats the message) → classify_node
  (one Gemini API call) → END`.
- Supports image URLs in the message for visual context (multimodal).
- `model_id` returns `"ai:gemini_multimodal:{model}"`.

---

### `app/services/normalization/providers/gemini_langgraph_prov.py`
**Role:** Simpler Gemini provider (single `ainvoke()` call).

- Uses `langchain-google-genai` without structured output — parses the raw text response
  via `parse_single_output()` fallback.
- Less robust than `gemini_multimodal_prov` for complex outputs.

---

### `app/services/normalization/resolvers.py`
**Role:** Converts AI string outputs to FK integer IDs.

**`CategoryResolver`** (zero DB queries):
- Loaded from `SubCategoryEnum` (enum values → DB IDs).
- `resolve("murder")` → `1`
- `resolve_all(["murder", "terrorism"])` → `[1, 5]`
- `resolve_categories_from_ids([1, 5])` → `[1]` (Violent Crime parent)

**`LocationResolver`** (one DB query at init):
- Loads the entire `state` table (36 rows) into memory.
- `resolve("Mumbai, Maharashtra, India")` — tries substring match on state name, then
  checks 80+ city aliases (`"Mumbai" → "Maharashtra"`), then returns `None` for non-Indian locations.

`load_resolvers(db)` — async factory that runs both in one call, used by `IngestionService`.

---

### `app/services/normalization/canonical_validator.py`
**Role:** URL and field sanitation helpers.

- Validates that URLs are absolute HTTP(S) and normalizes trailing slashes.
- Used during the insert_batch phase to clean up any AI-returned values before DB write.

---

## 6. Database Schema

### Article lifecycle

```
news_sources
    │
    └─► raw_ingestion          (every article ever seen — deduped by SHA-256)
            │  status: pending → filtered / filtered_out / failed
            │
            └─► filtered_articles       (AI-confirmed crime articles)
                    │
                    └─► post_processed_articles  (enriched: reference_urls added)
                                │
                                └─► final_articles  (public ranked feed: top N by rank_score)
```

### `raw_ingestion` — status values explained

| Status | Meaning |
|--------|---------|
| `pending` | Fetched, stored, not yet processed |
| `filtered` | AI confirmed crime — row exists in `filtered_articles` |
| `filtered_out` | Keyword pre-filter OR AI said not crime |
| `failed` | AI call failed (timeout, bad JSON, etc.) |
| `processed` | (legacy) fully post-processed |

### `final_articles.rank_score` formula

```
rank_score = imp_score × time_decay_factor(published_at)
```

Example: `imp_score=80`, article 10h old → `80 × 0.75 = 60.0`

### Performance indexes

```sql
CREATE INDEX ix_raw_ingestion_status      ON raw_ingestion(status);
CREATE INDEX ix_filtered_sub_category_ids ON filtered_articles USING GIN(sub_category_ids);
CREATE INDEX ix_filtered_category_ids     ON filtered_articles USING GIN(category_ids);
CREATE INDEX ix_post_processed_imp_score  ON post_processed_articles(imp_score)
    WHERE imp_score IS NOT NULL;
```

---

## 7. End-to-End Pipeline Flow

### Full automated cycle (every 5 minutes)

```
APScheduler fires: run_ingestion_for_all_active_sources()
  │
  ├── source_repo.get_all(active_only=True)
  │
  └── asyncio.gather([_ingest_one_source(s) for s in sources])
        │
        └── IngestionService.ingest(source)
              │
              ├── 1. FETCH
              │     RSSFetcher.fetch(url)   → feedparser.parse() in thread
              │     RestFetcher.fetch(url)  → httpx.AsyncClient.get()
              │     source_normalizer.to_plain_dict(entry)  → plain dict
              │
              ├── 2. LOAD PROVIDER
              │     ai_provider_repo.get_active()   → DB config row (priority)
              │     create_from_config(config)       → cached SDK client
              │       OR
              │     get_env_fallback_provider()      → from .env keys
              │     → determines provider_type (ollama / gemini_multimodal / etc.)
              │     → determines rate limits + item cap
              │
              ├── 3. CAP
              │     slice raw_items to max_items_for_provider_type
              │
              ├── 4. HASH + DEDUP
              │     SHA-256(source_id + json(payload)) per article
              │     raw_repo.store_batch() → INSERT OR IGNORE on content_hash
              │     returns new hashes + previously stuck-pending hashes
              │
              ├── 5. KEYWORD PRE-FILTER
              │     _has_crime_keywords(raw) — ~50 crime terms
              │     no match → mark_filtered_out (no AI call)
              │
              ├── 6. AI PROCESSING
              │     For Ollama: batches of OLLAMA_BATCH_SIZE with cooldown pause
              │     For cloud: all at once
              │     asyncio.gather():
              │       process_with_semaphore(hash, raw)
              │         async with semaphore:        ← concurrency limit
              │           await rate_limiter.wait()  ← RPM limit
              │           ai_provider.process(raw, source_type)
              │             → SINGLE_PROCESS_PROMPT + raw JSON
              │             → model returns JSON string
              │             → _extract_json() strips fences + think blocks
              │             → SingleOutput.model_validate() checks all fields
              │             → returns article dict or {"is_crime": false} or None
              │
              ├── 7. BUCKET RESULTS
              │     is_crime=True  → crime_articles list
              │     is_crime=False → filtered_out_hashes
              │     result=None    → failed_hashes
              │     exception      → failed_hashes
              │
              ├── 8. RESOLVE FKs
              │     load_resolvers(db) — loads state table + enums
              │     CategoryResolver.resolve_all(sub_category_ids strings → int list)
              │     CategoryResolver.resolve_categories_from_ids(→ parent int list)
              │     LocationResolver.resolve(location string → state_id int or None)
              │
              ├── 9. WRITE TO DB
              │     filter_article_repo.insert_batch()   → filtered_articles
              │     post_processed_repo.insert_batch()   → post_processed_articles
              │
              └── 10. UPDATE RAW STATUSES
                    raw_repo.mark_filtered(filtered_hashes)
                    raw_repo.mark_filtered_out(filtered_out_hashes)
                    raw_repo.mark_failed(failed_hashes)

  └── (if any source returned count > 0) → PublishingService.publish(top_n=20)
        │
        ├── 1. SELECT
        │     post_processed_repo.get_top_by_imp_score(limit=20)
        │     ordered by imp_score DESC WHERE imp_score IS NOT NULL
        │
        ├── 2. COMPUTE rank_score
        │     imp_score × time_decay_factor(published_at)
        │     1.00 / 0.75 / 0.50 / 0.25 / 0.10 by age bracket
        │
        ├── 3. GOOGLE SEARCH ENRICHMENT (if keys configured)
        │     finds rows where reference_urls is None
        │     enrich_articles_with_reference_urls(needs_search)
        │       for each article:
        │         fetch_related_urls(title)
        │           → GET https://www.googleapis.com/customsearch/v1?q=title&num=3
        │           → extract item["link"] list
        │         article["reference_urls"] = urls
        │         asyncio.sleep(GOOGLE_SEARCH_DELAY_SECONDS)  ← quota guard
        │     post_processed_repo.update_reference_urls()  ← persist, skip next cycle
        │
        └── 4. UPSERT FEED
              final_article_repo.upsert_batch(rows)
              ON CONFLICT (post_processed_article_id) DO UPDATE
                SET rank_score, reference_urls, title, description, image_url
```

---

## 8. AI Provider System

### Provider resolution order

```
IngestionService._load_ai_provider()
  │
  ├── 1. ai_provider_repo.get_active()   ← DB (highest priority)
  │         └── create_from_config(config) [process-lifetime cached]
  │
  └── 2. get_env_fallback_provider()    ← .env keys
            OLLAMA_MODEL set?      → OllamaProvider (local, offline)
            GEMINI_API_KEY set?    → GeminiMultimodalLangGraph
            ANTHROPIC_API_KEY set? → AnthropicProvider
            none                   → None → skip AI this run
```

### Supported providers

| Type | Class | Notes |
|------|-------|-------|
| `ollama` | `OpenAICompatibleProvider` | Local, no key, `localhost:11434/v1` auto-set |
| `gemini_multimodal` | `GeminiMultimodalLangGraphProvider` | **Recommended cloud** — structured output |
| `gemini_langgraph` | `GeminiLangGraphProvider` | Simpler Gemini, text parsing fallback |
| `gemini` | `OpenAICompatibleProvider` | Gemini via OpenAI-compat endpoint |
| `anthropic` | `AnthropicProvider` | Claude models |
| `openai` | `OpenAICompatibleProvider` | GPT models |
| `custom` | `OpenAICompatibleProvider` | vLLM, LM Studio, remote Ollama — requires `base_url` |

### Provider caching

Cache key = `(config.id, config.model, config.api_key)`.
SDK clients are created once and reused across all ingest runs until the server restarts.
Switching the active provider creates a fresh client on the next run; the old one stays
in cache but is never accessed again.

### The AI prompt

`SINGLE_PROCESS_PROMPT` from `providers/base.py` instructs the model to:
- Return `{"is_crime": false}` immediately for non-crime (minimal token cost)
- Return the full extraction + rewrite + scoring JSON in one call for crime articles

### JSON parsing pipeline

```
AI raw text
  → _extract_json()
      → strip ``` fences
      → strip <think>...</think>  (Qwen3)
      → strip <thinking>...</thinking>  (Claude / Gemini)
      → slice [first '{' : last '}']
  → json.loads()
  → SingleOutput.model_validate()  (Pydantic — rejects bad URLs, unknown categories, etc.)
  → parse_single_output() returns article dict or None
```

---

## 9. Google Search Reference URL Enrichment

### What it does

After selecting top articles for the feed, `PublishingService` calls the Google Custom Search API
to find 3 related news URLs per article. These are stored in `reference_urls` on both
`post_processed_articles` (permanent cache) and `final_articles` (served to frontend).

### Setup

1. Create a Google Custom Search Engine at `programmablesearchengine.google.com`
2. Enable the Custom Search JSON API in Google Cloud Console
3. Add to `.env`:
   ```env
   GOOGLE_SEARCH_API_KEY=AIzaSy...
   GOOGLE_SEARCH_ENGINE_ID=abc123...
   GOOGLE_SEARCH_RESULTS_PER_ARTICLE=3   # optional, default 3
   GOOGLE_SEARCH_DELAY_SECONDS=1.0        # optional, default 1s
   ```

### Quota management

- Free tier: 100 queries/day.
- Each `POST /final-articles/publish` with `top_n=20` sends at most 20 queries (once per article).
- Articles already enriched (non-null `reference_urls`) are skipped on future cycles.
- `GOOGLE_SEARCH_DELAY_SECONDS=1.0` — 1-second gap between requests.
- If either env var is missing, the entire feature is silently skipped — app works without it.

### Flow

```
PublishingService.publish()
  → finds rows with reference_urls = None
  → google_search_service.enrich_articles_with_reference_urls(needs_search)
      for each article (sequentially):
        fetch_related_urls(article["title"])
          httpx GET /customsearch/v1?q=title&num=3&key=...&cx=...
          → extract item["link"] from response["items"]
          → return list of URLs (or [] on error)
        article["reference_urls"] = urls
        sleep(GOOGLE_SEARCH_DELAY_SECONDS)
  → post_processed_repo.update_reference_urls(id, urls)  ← cached permanently
  → final_article_repo.upsert_batch()  ← written to public feed
```

### Manual trigger

To force enrichment immediately (without waiting for scheduler):

```bash
curl -X POST "http://localhost:8000/final-articles/publish?top_n=20"
# Logs will show: "fetching reference_urls for N articles via Google Search"
```

---

## 10. Request Flows — End to End

### `POST /ingest/` — Manual pipeline trigger

```
POST /ingest/ {"source_id": 2}
  → source_repo.get_by_id(2)   → validate type
  → IngestionService.ingest(source)   [same as automated §7]
  → return {"source_id": 2, "source_type": "rss", "ingested": 5}
```

### `POST /final-articles/publish` — Manual publish + enrichment

```
POST /final-articles/publish?top_n=20
  → PublishingService.publish(top_n=20)
      → get_top_by_imp_score(20)
      → compute rank_score for each
      → Google Search enrichment for articles without reference_urls
      → upsert_batch()
  → return {"published": 20, "top_n": 20}
```

### `GET /final-articles/` — Public ranked feed

```
GET /final-articles/?limit=20&sub_category_id=1&q=arrest
  → final_article_repo.get_feed(...)
      SELECT fa.*, pp.sub_category_id
      FROM final_articles fa
      JOIN post_processed_articles pp ON pp.id = fa.post_processed_article_id
      WHERE pp.sub_category_id = 1 AND fa.title ILIKE '%arrest%'
      ORDER BY fa.rank_score DESC
      LIMIT 20
  → return FinalArticleListResponse(total=N, items=[...])
```

### `GET /raw-ingestion/` — Pipeline inbox monitoring

```
GET /raw-ingestion/?status=filtered_out&source_id=1&limit=50
  → raw_ingestion_repo.get_all(status="filtered_out", source_id=1, limit=50)
  → raw_ingestion_repo.count(status="filtered_out", source_id=1)
  → return RawIngestionListResponse(total=N, items=[...])
```

### `PATCH /ai-providers/{id}/activate` — Switch provider

```
PATCH /ai-providers/3/activate
  → UPDATE ai_provider_configs SET is_active=false WHERE is_active=true
  → UPDATE ai_provider_configs SET is_active=true  WHERE id=3
  → return {"activated_id": 3, "message": "...now active"}

Next ingest run:
  → ai_provider_repo.get_active()  → config row (id=3)
  → create_from_config(config)     → cache miss → new provider client
  → articles now processed by the new model
```

---

## 11. API Reference

### Public — Ranked Feed (`/final-articles/`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/final-articles/` | Ranked crime news feed (frontend primary endpoint) |
| GET | `/final-articles/{id}` | Single article by ID |
| POST | `/final-articles/publish` | Force-refresh ranking + Google Search enrichment |

**GET `/final-articles/` query params:**

| Param | Default | Description |
|-------|---------|-------------|
| `limit` | 20 | Articles per page (max 100) |
| `offset` | 0 | Pagination offset |
| `sub_category_id` | — | Filter by crime sub-type ID |
| `q` | — | Keyword search in title + description |

---

### Pipeline Inspection (Debug)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/raw-ingestion/` | Raw inbox — every article ever fetched |
| GET | `/raw-ingestion/{id}` | Single raw row with full `raw_payload` JSON |
| GET | `/filter-articles/` | Stage-1 AI-confirmed crime articles |
| GET | `/filter-articles/{id}` | |
| GET | `/post-processed/` | Stage-2 enriched articles (with `reference_urls`) |
| GET | `/post-processed/{id}` | |

**GET `/raw-ingestion/` query params:**

| Param | Description |
|-------|-------------|
| `status` | Filter: `pending` \| `filtered` \| `processed` \| `filtered_out` \| `failed` |
| `source_id` | Filter by source |
| `limit` / `offset` | Pagination |

---

### Admin — Sources (`/sources/`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/sources/` | List sources (`?include_inactive=true`) |
| POST | `/sources/` | Add new RSS or REST source |
| GET | `/sources/{id}` | Get by ID |
| PATCH | `/sources/{id}` | Update (pause: `{"is_active": false}`) |
| DELETE | `/sources/{id}` | Delete permanently |

---

### Admin — Ingestion (`/ingest/`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/ingest/` | Trigger immediate ingest for one source |

---

### Admin — AI Providers (`/ai-providers/`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/ai-providers/` | List all registered providers |
| POST | `/ai-providers/` | Register new provider |
| GET | `/ai-providers/active` | Currently active provider |
| GET | `/ai-providers/{id}` | Get by ID |
| PATCH | `/ai-providers/{id}/activate` | Switch active provider |
| DELETE | `/ai-providers/active` | Deactivate all (fall back to .env) |
| DELETE | `/ai-providers/{id}` | Delete a config |

**POST `/ai-providers/` body examples:**

```json
// Ollama (local, no key)
{"name": "Ollama Qwen3", "provider": "ollama",
 "model": "dengcao/Qwen3-30B-A3B-Instruct-2507:latest"}

// Gemini Multimodal (recommended cloud)
{"name": "Gemini Flash", "provider": "gemini_multimodal",
 "model": "gemini-2.0-flash", "api_key": "AIzaSy..."}

// Anthropic Claude
{"name": "Claude Haiku", "provider": "anthropic",
 "model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-..."}

// OpenAI GPT
{"name": "GPT-4o Mini", "provider": "openai",
 "model": "gpt-4o-mini", "api_key": "sk-..."}

// Custom OpenAI-compatible (base_url required)
{"name": "Remote vLLM", "provider": "custom",
 "model": "mistral-7b", "api_key": "none",
 "base_url": "http://192.168.1.10:8080/v1"}
```

---

### Master Data (`/master/`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/master/categories` | 8 crime categories |
| GET | `/master/sub-categories` | 10 crime sub-categories |
| GET | `/master/states` | 36 Indian states/UTs |

---

### Health

| Method | Path | Response |
|--------|------|----------|
| GET | `/health` | `{"status": "ok"}` |
| GET | `/` | Redirect info to `/docs` |

---

## 12. Configuration Reference

All settings loaded from `.env` via `app/core/config.py`.

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | **required** | Must be `postgresql+asyncpg://...` |
| `OLLAMA_MODEL` | None | Enables Ollama env-fallback |
| `OLLAMA_URL` | `http://localhost:11434/v1` | Ollama endpoint |
| `OLLAMA_REQUESTS_PER_MINUTE` | 60 | RPM for local Ollama |
| `OLLAMA_MAX_ITEMS_PER_RUN` | 50 | Items per ingest run for Ollama |
| `OLLAMA_CONCURRENCY` | 1 | Parallel GPU inferences (1 = no queuing) |
| `OLLAMA_BATCH_SIZE` | 10 | Articles per GPU batch |
| `OLLAMA_BATCH_COOLDOWN_SECONDS` | 15.0 | GPU rest between batches |
| `GEMINI_API_KEY` | None | Enables Gemini env-fallback |
| `ANTHROPIC_API_KEY` | None | Enables Anthropic env-fallback |
| `CLOUD_REQUESTS_PER_MINUTE` | 3 | RPM for cloud APIs (free-tier safe) |
| `CLOUD_MAX_ITEMS_PER_RUN` | 5 | Items per ingest run for cloud |
| `AI_REQUESTS_PER_MINUTE` | 5 | Fallback RPM |
| `AI_MAX_ITEMS_PER_RUN` | 10 | Fallback item cap |
| `AI_RETRY_ATTEMPTS` | 3 | Retries on rate-limit errors |
| `AI_RETRY_DELAY_SECONDS` | 15.0 | Base back-off delay |
| `INGEST_INTERVAL_MINUTES` | 5 | Ingestion scheduler interval |
| `PUBLISH_INTERVAL_MINUTES` | 5 | Publishing scheduler interval |
| `PUBLISH_OFFSET_SECONDS` | 30 | Publishing job offset after ingestion |
| `FEED_TOP_N` | 20 | Articles per publish cycle |
| `DECAY_FRESH` | 1.00 | Time-decay: < 6 hours |
| `DECAY_RECENT` | 0.75 | Time-decay: 6–24 hours |
| `DECAY_DAY` | 0.50 | Time-decay: 1–3 days |
| `DECAY_WEEK` | 0.25 | Time-decay: 3–7 days |
| `DECAY_OLD` | 0.10 | Time-decay: > 7 days |
| `GOOGLE_SEARCH_API_KEY` | None | Google Custom Search key (optional) |
| `GOOGLE_SEARCH_ENGINE_ID` | None | Google CSE ID (optional) |
| `GOOGLE_SEARCH_RESULTS_PER_ARTICLE` | 3 | URLs per article (max 10 per API call) |
| `GOOGLE_SEARCH_DELAY_SECONDS` | 1.0 | Delay between search requests |
| `DEBUG` | False | FastAPI debug mode |

**Recommended `.env` for local Ollama:**

```env
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db_news
OLLAMA_MODEL=dengcao/Qwen3-30B-A3B-Instruct-2507:latest
GOOGLE_SEARCH_API_KEY=AIzaSy...
GOOGLE_SEARCH_ENGINE_ID=abc123...
```

**Recommended `.env` for Gemini free tier:**

```env
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db_news
GEMINI_API_KEY=AIzaSy...
GOOGLE_SEARCH_API_KEY=AIzaSy...
GOOGLE_SEARCH_ENGINE_ID=abc123...
```

---

## 13. Adding a New AI Provider

**4 files to touch — nothing else.**

### Step 1 — Create the provider class

`app/services/normalization/providers/your_prov.py`:

```python
from app.services.normalization.providers.base import (
    AIProvider, SINGLE_PROCESS_PROMPT,
    build_process_message, parse_single_output,
)

class YourProvider(AIProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        # init your SDK client here

    @property
    def model_id(self) -> str:
        return f"ai:your_provider:{self._model}"

    async def process(self, raw_payload: dict, source_type: str) -> dict | None:
        user_msg = build_process_message(raw_payload, source_type)
        # call your API with SINGLE_PROCESS_PROMPT as system + user_msg as user
        text = ...   # raw text from your API
        return parse_single_output(text, raw_payload)
```

### Step 2 — Register in the factory

`app/services/normalization/provider_factory.py` — add to `_build()`:

```python
from app.services.normalization.providers.your_prov import YourProvider

if provider == "your_provider":
    return YourProvider(api_key=api_key, model=model)
```

### Step 3 — Add to model constants

`app/models/ai_provider.py`:

```python
SUPPORTED_PROVIDERS = {..., "your_provider"}
PROVIDER_BASE_URLS["your_provider"] = None
PROVIDER_DEFAULT_MODELS["your_provider"] = "your-default-model"
```

### Step 4 — Add to schema Literal

`app/schemas/ai_provider_schema.py`:

```python
_PROVIDER_LITERAL = Literal[..., "your_provider"]
```

### Test it

```bash
curl -X POST http://localhost:8000/ai-providers/ \
  -d '{"name": "My Provider", "provider": "your_provider",
       "model": "your-model", "api_key": "key"}'
curl -X PATCH http://localhost:8000/ai-providers/{id}/activate
curl -X POST http://localhost:8000/ingest/ -d '{"source_id": 1}'
```
