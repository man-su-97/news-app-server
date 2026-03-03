# Crime News API — Architecture & Operations Guide

> Complete reference: every file, every layer, the full AI pipeline, multi-provider
> switching, database schema, and step-by-step run instructions.

---

## Table of Contents

1. [What This App Does](#1-what-this-app-does)
2. [How to Run the App](#2-how-to-run-the-app)
3. [Tech Stack](#3-tech-stack)
4. [Project Structure](#4-project-structure)
5. [Database Schema](#5-database-schema)
6. [Pipeline — Bird's Eye View](#6-pipeline--birds-eye-view)
7. [Service Layer — Deep Dive](#7-service-layer--deep-dive)
8. [AI Provider System](#8-ai-provider-system)
9. [Request Flows — End to End](#9-request-flows--end-to-end)
10. [API Reference](#10-api-reference)
11. [Configuration Reference](#11-configuration-reference)
12. [Adding a New AI Provider](#12-adding-a-new-ai-provider)

---

## 1. What This App Does

An **automated AI-powered crime news aggregator** for India.

Every 5 minutes the scheduler:

1. Fetches articles from all active RSS/REST news sources
2. Deduplicates by SHA-256 hash — the same article is never processed twice
3. Pre-filters using a ~50-keyword crime list — skips ~70% of articles before any AI call
4. Sends remaining articles concurrently to the configured AI provider, which in a **single call**:
   - Decides if the article is crime-related (non-crime → discard, near-zero tokens)
   - Extracts: original title, URL, description, image, published date
   - Rewrites the title and description in its own words (plagiarism-safe)
   - Assigns an importance score 1–100 based on severity, scope, and public impact
   - Labels one or more crime sub-categories (murder, fraud, terrorism, …)
   - Resolves the location to an Indian state
5. Stores crime articles across two pipeline tables (`filtered_articles` → `post_processed_articles`)
6. Runs a publishing job every 5 minutes that picks the top 20 articles, applies time-decay,
   and upserts them into `final_articles` — the public ranked feed

**AI providers are fully switchable at runtime** via the `/ai-providers/` API — no restart needed.
Currently supported: **Ollama (local)**, Gemini Multimodal, Gemini LangGraph, Anthropic Claude,
OpenAI GPT, any OpenAI-compatible server.

---

## 2. How to Run the App

### Prerequisites

- Python 3.12+
- `uv` package manager (`pip install uv` or see https://docs.astral.sh/uv/)
- PostgreSQL database (connection string in `.env`)
- At least one AI provider configured (Ollama locally, or an API key)

### Step 1 — Clone and install dependencies

```bash
git clone <repo-url>
cd news-app-server
uv sync          # creates .venv/ and installs all dependencies from uv.lock
```

### Step 2 — Configure environment

Copy the template and fill in your values:

```bash
cp .env.example .env   # if it exists, otherwise edit .env directly
```

Minimum required `.env`:

```env
DATABASE_URL=postgresql+asyncpg://user:password@host:port/dbname

# Choose ONE AI provider (or configure via API after startup):

# Option A — Local Ollama (no API key needed, runs 100% offline)
OLLAMA_MODEL=dengcao/Qwen3-30B-A3B-Instruct-2507:latest
# OLLAMA_URL=http://localhost:11434/v1   # default — only change for remote Ollama

# Option B — Google Gemini
# GEMINI_API_KEY=AIzaSy...

# Option C — Anthropic Claude
# ANTHROPIC_API_KEY=sk-ant-...
```

> **Important:** `DATABASE_URL` must use the `postgresql+asyncpg://` scheme.
> Using `postgresql://` will cause a startup error.

### Step 3 — Run database migrations

```bash
.venv/bin/alembic upgrade head
```

This creates all tables and seeds master data (categories, sub-categories, Indian states).

### Step 4 — Start the server

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The server starts on `http://localhost:8000`.
The scheduler starts automatically — ingestion runs every 5 minutes.

### Step 5 — Add a news source

```bash
curl -X POST http://localhost:8000/sources/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "NDTV Crime",
    "url": "https://feeds.feedburner.com/ndtvnews-crime",
    "type": "rss",
    "is_active": true,
    "config": {}
  }'
```

### Step 6 — Trigger a manual ingest to test

```bash
curl -X POST http://localhost:8000/ingest/ \
  -H "Content-Type: application/json" \
  -d '{"source_id": 1}'
```

Watch server logs to see the AI provider processing articles in real time.

### Step 7 — Read the feed

```bash
curl http://localhost:8000/final-articles/
```

### Interactive API docs

```
http://localhost:8000/docs    ← Swagger UI (try every endpoint)
http://localhost:8000/redoc   ← ReDoc
http://localhost:8000/health  ← {"status": "ok"}
```

---

## 3. Tech Stack

| Layer | Technology | Role |
|-------|-----------|------|
| Web framework | **FastAPI** | Async HTTP, automatic OpenAPI/Swagger, Pydantic DI |
| ORM | **SQLAlchemy 2.0 async** | Typed `Mapped[]` columns, JSONB support, Alembic integration |
| DB driver | **asyncpg** | Async PostgreSQL driver required by SQLAlchemy async |
| Database | **PostgreSQL** | Primary data store |
| Migrations | **Alembic** | Versioned, async-aware schema migrations |
| Scheduler | **APScheduler** | `AsyncIOScheduler` — ingestion + publishing jobs |
| Validation | **Pydantic v2** | Request/response models, settings, AI output schemas |
| Settings | **pydantic-settings** | `.env` loading with type validation |
| RSS parsing | **feedparser** | Handles RSS/Atom, malformed XML |
| HTTP client | **httpx** | Async HTTP for REST source fetching |
| AI — local | **Ollama** | Local LLM server, OpenAI-compatible endpoint |
| AI — cloud | **Anthropic SDK** | Claude models (Haiku, Sonnet, Opus) |
| AI — cloud | **OpenAI SDK** | GPT models + any OpenAI-compatible server |
| AI — cloud | **langchain-google-genai** | Gemini models via LangChain |
| AI — agents | **LangGraph** | Graph-based multi-node AI pipeline for Gemini providers |
| Web search | **ddgs** | DuckDuckGo search for context enrichment |
| ASGI server | **uvicorn** | Runs FastAPI |

---

## 4. Project Structure

```
news-app-server/
├── .env                                       # Runtime config (never commit secrets)
├── .venv/                                     # Python virtual environment (managed by uv)
├── alembic.ini                                # Alembic config (DATABASE_URL injected at runtime)
├── pyproject.toml                             # Project dependencies
├── uv.lock                                    # Locked dependency versions
├── ARCHITECTURE.md                            # This document
│
├── migrations/
│   ├── env.py                                 # Async-aware Alembic runner
│   ├── script.py.mako                         # Migration file template
│   └── versions/                              # 11 migration files (initial → performance indexes)
│
└── app/
    ├── main.py                                # FastAPI app factory, router registration, lifespan
    │
    ├── core/
    │   ├── config.py                          # All settings from .env (pydantic-settings)
    │   ├── database.py                        # AsyncEngine + session factory + get_db()
    │   ├── deps.py                            # FastAPI dependency injection (repos + services)
    │   └── enums.py                           # SubCategoryEnum, CategoryEnum, lookup dicts
    │
    ├── models/                                # SQLAlchemy ORM table definitions
    │   ├── base.py                            # DeclarativeBase
    │   ├── source.py                          # news_sources table
    │   ├── raw_event.py                       # raw_ingestion table (dedup inbox)
    │   ├── filter_article.py                  # filtered_articles table (AI stage 1)
    │   ├── post_processed_article.py          # post_processed_articles table (AI stage 2)
    │   ├── final_article.py                   # final_articles table (public ranked feed)
    │   ├── ai_provider.py                     # ai_provider_configs table + constants
    │   ├── category.py                        # master_category + master_sub_category
    │   └── location.py                        # country + state tables
    │
    ├── repositories/                          # Data access layer — one class per table
    │   ├── source_repo.py                     # SourceRepository
    │   ├── raw_ingestion_repo.py              # RawIngestionRepository (store_batch, mark_*)
    │   ├── filter_article_repo.py             # FilterArticleRepository
    │   ├── post_processed_article_repo.py     # PostProcessedArticleRepository
    │   ├── final_article_repo.py              # FinalArticleRepository (upsert_batch, get_feed)
    │   ├── ai_provider_repo.py                # AIProviderRepository (CRUD + activate)
    │   ├── master_data_repo.py                # Categories, sub-categories, states (read-only)
    │   └── article_repo.py                    # Alias: ArticleRepository = PostProcessedArticleRepository
    │
    ├── schemas/                               # Pydantic request/response models
    │   ├── source_schema.py                   # SourceCreate, SourceUpdate, SourceResponse
    │   ├── article_schema.py                  # FilterArticleResponse, PostProcessedArticleResponse
    │   ├── final_article_schema.py            # FinalArticleResponse, FinalArticleListResponse
    │   ├── ai_provider_schema.py              # AIProviderCreate, AIProviderResponse
    │   └── master_data_schema.py              # MasterCategoryResponse, StateResponse
    │
    ├── api/                                   # HTTP route handlers
    │   ├── routes_sources.py                  # GET/POST/PATCH/DELETE /sources/
    │   ├── routes_ingest.py                   # POST /ingest/
    │   ├── routes_filter_articles.py          # GET /filter-articles/
    │   ├── routes_post_processed.py           # GET /post-processed/
    │   ├── routes_final_articles.py           # GET /final-articles/, POST /publish
    │   ├── routes_ai_providers.py             # GET/POST/PATCH/DELETE /ai-providers/
    │   └── routes_master_data.py              # GET /master/categories, /states
    │
    └── services/                              # Business logic
        ├── ingestion_service.py               # Main pipeline orchestrator
        ├── publishing_service.py              # Ranking + feed refresh
        ├── scheduler.py                       # APScheduler job registration
        ├── source_normalizer.py               # to_plain_dict(), parse_date()
        ├── fetchers/
        │   ├── rss_fetcher.py                 # feedparser wrapped in asyncio.to_thread()
        │   └── rest_fetcher.py                # httpx async GET → list[dict]
        └── normalization/
            ├── ai_processor.py                # get_env_fallback_provider() — env-var AI fallback
            ├── provider_factory.py            # Factory + process-lifetime provider cache
            ├── resolvers.py                   # CategoryResolver, LocationResolver
            ├── canonical_validator.py         # URL and field sanitation helpers
            └── providers/
                ├── base.py                    # AIProvider ABC, prompt, JSON parser, SingleOutput
                ├── openai_prov.py             # OpenAICompatibleProvider (OpenAI / Gemini / Ollama)
                ├── anthropic_prov.py          # AnthropicProvider (Claude)
                ├── gemini_langgraph_prov.py   # GeminiLangGraphProvider (LangGraph simple)
                └── gemini_multimodal_prov.py  # GeminiMultimodalLangGraphProvider (RECOMMENDED)
```

---

## 5. Database Schema

### Table flow (article lifecycle)

```
news_sources
    │
    └─► raw_ingestion          (every article ever seen — deduped by SHA-256)
            │
            └─► filtered_articles       (AI-confirmed crime: extracted + scored)
                    │
                    └─► post_processed_articles  (rewritten content + importance score)
                                │
                                └─► final_articles  (public ranked feed: top N by rank_score)
```

### Reference / lookup tables

```
master_category       (8 top-level crime types)
master_sub_category   (10 specific crime types, each linked to a category)
country               (seeded once: India + others)
state                 (36 Indian states/UTs — used as location FK)
ai_provider_configs   (runtime AI provider credentials + active flag)
```

---

### `news_sources`

| Column | Type | Notes |
|--------|------|-------|
| `id` | PK | |
| `name` | VARCHAR | Display name |
| `type` | VARCHAR | `rss` or `rest` |
| `url` | VARCHAR UNIQUE | Feed URL |
| `config` | JSONB | Extra fetch config (headers, auth, etc.) |
| `is_active` | BOOL | `false` = paused |
| `created_at` | TIMESTAMPTZ | |

---

### `raw_ingestion`

| Column | Type | Notes |
|--------|------|-------|
| `id` | PK | |
| `source_id` | FK → news_sources | |
| `content_hash` | VARCHAR(64) UNIQUE | SHA-256 of `source_id + json(raw_payload)` — dedup key |
| `raw_payload` | JSONB | Full original article dict |
| `status` | VARCHAR | `pending` → `filtered` / `filtered_out` / `failed` |
| `normalized_by` | VARCHAR(200) | e.g. `ai:localhost:11434:qwen3` or `ai:gemini_multimodal:gemini-2.0-flash` |
| `error_message` | TEXT | Set on failure |
| `retry_count` | INT | |
| `created_at` | TIMESTAMPTZ | |
| `processed_at` | TIMESTAMPTZ | |

---

### `filtered_articles` (stage 1)

| Column | Type | Notes |
|--------|------|-------|
| `id` | PK | |
| `raw_ingestion_id` | FK UNIQUE | Links back to raw payload |
| `title` | TEXT | Original headline from source |
| `rewritten_title` | TEXT | AI-rephrased headline (≤15 words, active voice) |
| `main_url` | TEXT UNIQUE | Canonical article URL — upsert key |
| `description` | TEXT | Original source description |
| `rewritten_description` | TEXT | AI-rewritten 3–5 sentences |
| `image_url` | TEXT | |
| `published_at` | TIMESTAMPTZ | Parsed to UTC |
| `sub_category_id` | FK → master_sub_category | Primary crime type |
| `sub_category_ids` | JSONB | `[1, 4]` — multi-label int array (GIN indexed) |
| `category_ids` | JSONB | Parent category IDs derived from sub_category_ids (GIN indexed) |
| `location_state_id` | FK → state | Resolved from AI location string |
| `location` | TEXT | Raw AI location string |
| `imp_score` | INT | 1–100 importance score |
| `created_at` | TIMESTAMPTZ | |

---

### `post_processed_articles` (stage 2)

Same structure as `filtered_articles`, plus:

| Column | Type | Notes |
|--------|------|-------|
| `filter_article_id` | FK UNIQUE | Links to filtered_articles |
| `reference_urls` | JSONB TEXT[] | Web search reference links |

---

### `final_articles` (public feed)

| Column | Type | Notes |
|--------|------|-------|
| `id` | PK | |
| `post_processed_article_id` | FK UNIQUE | Upsert key |
| `title` | TEXT | Copied from post_processed_articles |
| `description` | TEXT | rewritten_description |
| `image_url` | TEXT | |
| `reference_urls` | JSONB | |
| `rank_score` | FLOAT | `imp_score × time_decay_factor` |
| `created_at` | TIMESTAMPTZ | |

---

### `ai_provider_configs`

| Column | Type | Notes |
|--------|------|-------|
| `id` | PK | |
| `name` | VARCHAR(100) | Friendly label, e.g. `Local Ollama Qwen3` |
| `provider` | VARCHAR(50) | One of the 7 supported provider types |
| `model` | VARCHAR(100) | Model identifier |
| `api_key` | VARCHAR(500) | API key (or `"ollama"` for local Ollama) |
| `base_url` | VARCHAR(500) | Override endpoint URL (auto-set for `ollama`) |
| `is_active` | BOOL | Only one row `true` at a time (DB partial unique index) |
| `created_at` | TIMESTAMPTZ | |

---

### Performance indexes (latest migration)

```sql
CREATE INDEX ix_raw_ingestion_status        ON raw_ingestion(status);
CREATE INDEX ix_filtered_sub_category_ids   ON filtered_articles USING GIN(sub_category_ids);
CREATE INDEX ix_filtered_category_ids       ON filtered_articles USING GIN(category_ids);
CREATE INDEX ix_post_processed_imp_score    ON post_processed_articles(imp_score)
    WHERE imp_score IS NOT NULL;
```

---

## 6. Pipeline — Bird's Eye View

```
┌──────────────────────────────────────────────────────────────────┐
│                    SCHEDULER (every 5 min)                       │
│                                                                  │
│  run_ingestion_for_all_active_sources()                          │
│    ├── for each active source → IngestionService.ingest(source)  │
│    └── on any OK → PublishingService.publish(top_n=20)           │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────────┐
│                   IngestionService.ingest()                      │
│                                                                  │
│  1. FETCH         RSSFetcher / RestFetcher → list[dict]          │
│  2. CAP           slice to AI_MAX_ITEMS_PER_RUN (default 10)     │
│  3. HASH          SHA-256(source_id + json(payload)) per article │
│  4. DEDUP         raw_repo.store_batch() → INSERT OR IGNORE      │
│                   returns only NEW (unseen) hashes               │
│  5. KEYWORD FILTER ~50 crime terms → skip non-crime early        │
│  6. LOAD PROVIDER  DB config → env fallback → None               │
│  7. AI PIPELINE   asyncio.gather() with semaphore + rate limiter │
│                   per article → ai_provider.process()            │
│  8. BUCKET        crime / filtered_out / failed                  │
│  9. RESOLVE FKs   CategoryResolver + LocationResolver            │
│ 10. SAVE          filter_article_repo + post_processed_repo      │
│ 11. UPDATE STATUS raw_repo.mark_filtered / filtered_out / failed │
└──────────────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────────┐
│                  PublishingService.publish()                     │
│                                                                  │
│  1. SELECT   post_processed_repo.get_top_by_imp_score(limit=20)  │
│  2. RANK     rank_score = imp_score × time_decay_factor          │
│              1.00 (<6h) / 0.75 (<24h) / 0.50 (<3d) /            │
│              0.25 (<7d) / 0.10 (older)                           │
│  3. UPSERT   final_article_repo.upsert_batch()                   │
│              ON CONFLICT post_processed_article_id → UPDATE      │
└──────────────────────────────────────────────────────────────────┘
```

### Article lifecycle (`raw_ingestion.status`)

```
pending
  ├── keyword filter miss  → filtered_out
  ├── AI says not crime    → filtered_out
  ├── AI call error        → failed
  └── AI says crime, saved → filtered
```

---

## 7. Service Layer — Deep Dive

### 7.1 `IngestionService` (`ingestion_service.py`)

Orchestrates the entire article lifecycle from fetch to DB write.

**Dependencies injected:**

```python
IngestionService(
    source_repo,           # read news_sources
    raw_repo,              # store raw payloads, update statuses
    filter_article_repo,   # write stage-1 results
    post_processed_repo,   # write stage-2 results
    ai_provider_repo,      # read active AI config from DB
    db,                    # AsyncSession — passed to resolvers
)
```

**`ingest(source)` pipeline steps:**

| Step | Method | What it does |
|------|--------|--------------|
| 1 | `_fetch_items(source)` | RSSFetcher or RestFetcher based on `source.type` |
| 2 | slice | Cap to `AI_MAX_ITEMS_PER_RUN` |
| 3 | `compute_content_hash()` | SHA-256 per article |
| 4 | `raw_repo.store_batch()` | INSERT OR IGNORE; returns new hashes only |
| 5 | `_load_ai_provider()` | DB config → env fallback → None |
| 6 | `_has_crime_keywords()` | Frozenset of ~50 terms |
| 7 | `asyncio.gather()` | Concurrent AI calls, rate-limited |
| 8 | bucket | crime / filtered_out / failed |
| 9 | `load_resolvers(db)` | One DB query (states); categories use enum |
| 10 | resolve | AI strings → FK ints |
| 11 | `filter_article_repo.insert_batch()` | Upsert on `main_url` |
| 12 | `post_processed_repo.insert_batch()` | Upsert on `filter_article_id` |
| 13 | `_update_raw_statuses()` | Mark each raw row |

**Concurrency model:**

```
_global_rate_limiter = _RateLimiter(rpm=AI_REQUESTS_PER_MINUTE)
_global_semaphore    = asyncio.Semaphore(concurrency_from_rpm(rpm))

rpm=5  → concurrency=1   (1 request at a time, ~12s between calls)
rpm=30 → concurrency=2
rpm=60 → concurrency=5
```

Both are **process-level singletons** — all source tasks share the same limiter.
For local Ollama (no rate limit needed): set `AI_REQUESTS_PER_MINUTE=60` in `.env`.

**Retry logic:**

`_call_with_retry()` wraps every AI call. On rate-limit errors
(HTTP 429 / "quota" / "resource_exhausted") → exponential back-off:
`delay × 2^attempt`. Non-rate-limit errors fail immediately.
Configured via `AI_RETRY_ATTEMPTS` (default 3) and `AI_RETRY_DELAY_SECONDS` (default 15s).

---

### 7.2 `PublishingService` (`publishing_service.py`)

Selects top N articles and computes final ranked scores.

**`publish(top_n=20)` steps:**

1. `get_top_by_imp_score(limit=top_n)` — ordered by `imp_score DESC`
2. `rank_score = imp_score × _time_decay_factor(published_at)`
3. `upsert_batch()` — `ON CONFLICT ... DO UPDATE SET rank_score = ...`

**Time-decay table (configurable via `.env`):**

| Age | `.env` variable | Default |
|-----|-----------------|---------|
| < 6 hours | `DECAY_FRESH` | 1.00 |
| 6–24 hours | `DECAY_RECENT` | 0.75 |
| 1–3 days | `DECAY_DAY` | 0.50 |
| 3–7 days | `DECAY_WEEK` | 0.25 |
| > 7 days | `DECAY_OLD` | 0.10 |

**Example:** `imp_score=80`, article is 10 hours old → `rank_score = 80 × 0.75 = 60.0`

---

### 7.3 `Scheduler` (`scheduler.py`)

Two APScheduler jobs registered at server startup:

```python
# Job 1 — ingestion (every 5 min, max 1 instance)
run_ingestion_for_all_active_sources()

# Job 2 — publishing (every 5 min + 30s offset, max 1 instance)
run_publishing()
```

After every successful ingestion, `run_publishing()` is also called immediately —
so a good ingest run refreshes the feed at once without waiting for the next interval.

---

### 7.4 Fetchers

**`RSSFetcher`** — wraps `feedparser.parse()` in `asyncio.to_thread()` (non-blocking).
Returns `feed.entries` → passed to `to_plain_dict()`.

**`RestFetcher`** — `httpx.AsyncClient.get(url)` with 15s timeout.
Handles both a list-at-root response and a dict with `articles/items/results/data` key.

---

### 7.5 `source_normalizer.py`

**`to_plain_dict(entry)`:** Converts feedparser or REST API objects to a plain `dict[str, Any]`.
Handles HTML entities, `time.struct_time`, nested dicts, feedparser-specific types.

**`parse_date(s)`:** Parses ISO 8601, RFC 2822, and common formats into UTC-aware `datetime`.

---

### 7.6 `resolvers.py`

**`CategoryResolver`** (zero DB queries — uses `app.core.enums`):

```python
resolve("murder")                     → 1   (SubCategoryEnum.MURDER)
resolve_all(["murder", "terrorism"])  → [1, 3]
resolve_categories_from_ids([1, 3])   → [1]  (Violent Crime)
```

**`LocationResolver`** (one DB query at startup — loads entire `state` table):

```python
resolve("Mumbai, Maharashtra, India") → 14  (Maharashtra state_id)
resolve("Bengaluru")                  → 9   (Karnataka via city alias map)
resolve("Germany")                    → None
```

Strategy: (1) substring match on state name → (2) city alias map (80+ Indian cities) → (3) None.

---

## 8. AI Provider System

### 8.1 Overview

The system supports **7 provider types**. At any given time one is active;
switching is instant via a single API call. No server restart required.

```
┌────────────────────────────────────────────────────────────────────┐
│                     AI PROVIDER RESOLUTION                         │
│                                                                    │
│  IngestionService._load_ai_provider()                              │
│    │                                                               │
│    ├── 1. ai_provider_repo.get_active()  ← DB config (priority)   │
│    │         └── create_from_config(config)  [process-cached]      │
│    │                                                               │
│    └── 2. get_env_fallback_provider()   ← .env keys (fallback)    │
│              OLLAMA_MODEL set?  → OllamaProvider (local)           │
│              GEMINI_API_KEY?    → GeminiMultimodalLangGraph         │
│              ANTHROPIC_API_KEY? → AnthropicProvider                │
│              nothing            → None → skip AI this run          │
└────────────────────────────────────────────────────────────────────┘
```

### 8.2 Supported Providers

| Provider type | Class | API | Notes |
|---------------|-------|-----|-------|
| `ollama` | `OpenAICompatibleProvider` | `localhost:11434/v1` | Local, no key, offline |
| `gemini_multimodal` | `GeminiMultimodalLangGraphProvider` | Google API | **Best quality**, structured output, image support |
| `gemini_langgraph` | `GeminiLangGraphProvider` | Google API | Simpler LangGraph, no multimodal |
| `gemini` | `OpenAICompatibleProvider` | Google OpenAI-compat | Direct Gemini via OpenAI format |
| `anthropic` | `AnthropicProvider` | Anthropic API | Claude models |
| `openai` | `OpenAICompatibleProvider` | OpenAI API | GPT models |
| `custom` | `OpenAICompatibleProvider` | Your URL | vLLM, LM Studio, remote Ollama |

### 8.3 Switching Providers via API

**Register a provider:**

```bash
# Ollama (local, no key needed)
curl -X POST http://localhost:8000/ai-providers/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Local Ollama Qwen3",
    "provider": "ollama",
    "model": "dengcao/Qwen3-30B-A3B-Instruct-2507:latest"
  }'

# Gemini
curl -X POST http://localhost:8000/ai-providers/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Gemini 2.5 Flash",
    "provider": "gemini_multimodal",
    "model": "gemini-2.0-flash",
    "api_key": "AIzaSy..."
  }'

# Anthropic Claude
curl -X POST http://localhost:8000/ai-providers/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Claude Haiku",
    "provider": "anthropic",
    "model": "claude-haiku-4-5-20251001",
    "api_key": "sk-ant-..."
  }'

# Remote / custom OpenAI-compatible server
curl -X POST http://localhost:8000/ai-providers/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My vLLM Server",
    "provider": "custom",
    "model": "mistral-7b",
    "api_key": "none",
    "base_url": "http://192.168.1.10:8080/v1"
  }'
```

**Activate a provider** (takes effect on the next ingest run):

```bash
curl -X PATCH http://localhost:8000/ai-providers/{id}/activate
```

**Deactivate all** (falls back to `.env` keys):

```bash
curl -X DELETE http://localhost:8000/ai-providers/active
```

**Check what's active:**

```bash
curl http://localhost:8000/ai-providers/active
```

### 8.4 Provider Caching

Provider instances (SDK clients with connection pools) are created **once per process**
and reused across all ingest runs:

```python
# Cache key = (config.id, model, api_key)
# Hit  → return existing instance (no new objects, no reconnection)
# Miss → build new instance → cache it
```

This means switching providers (activate a different row) creates a fresh client
on the next ingest run, while the old one stays in cache but is never used again.

### 8.5 The AI Prompt

All providers use the same `SINGLE_PROCESS_PROMPT` from `providers/base.py`.
It instructs the model to:

- **Return `{"is_crime": false}` immediately** for non-crime articles (zero tokens wasted)
- **Return the full JSON** for crime articles in one pass — no separate extract/rewrite stages

```
Input: {"source_type": "rss", "raw_payload": {...}}

Output (non-crime): {"is_crime": false}

Output (crime):
{
  "is_crime": true,
  "title": "original headline",
  "rewritten_title": "AI rephrased ≤15 words",
  "url": "https://...",
  "description": "original 1-3 sentences",
  "rewritten_description": "AI 3-5 sentences",
  "image_url": "https://...",
  "published_at": "2026-01-15T10:30:00Z",
  "sub_category": "murder",
  "sub_category_ids": ["murder", "violence"],
  "location": "Mumbai, India",
  "imp_score": 72
}
```

### 8.6 JSON Parsing & Think-Block Stripping

`_extract_json()` in `base.py` cleans AI output before `json.loads()`:

1. Strips markdown code fences (` ```json ... ``` `)
2. Strips `<think>...</think>` blocks (Qwen3 / local models)
3. Strips `<thinking>...</thinking>` blocks (some Gemini/Claude variants)
4. Slices `text[first '{' : last '}']` to handle prose preamble

After parsing, `SingleOutput` (Pydantic model) validates and normalises all fields.

### 8.7 Importance Score (1–100)

The AI assigns a score based on severity, victim count, scope, and official involvement:

| Range | Label | Examples |
|-------|-------|---------|
| 1–20 | Hyperlocal / minor | Petty theft in a small town |
| 21–40 | Local / notable | Single murder in a major city |
| 41–60 | Regional / significant | Gang bust, notable fraud |
| 61–80 | National / high impact | Terror plot foiled, senior official arrested |
| 81–100 | International / breaking | Multi-city attack, political assassination |

### 8.8 Provider-Specific Notes

**`OpenAICompatibleProvider`** — Used for: `openai`, `gemini`, `ollama`, `custom`.
Uses `response_format={"type": "json_object"}` (JSON mode) for reliable output.
Ollama supports this natively.

**`GeminiMultimodalLangGraphProvider`** — Uses LangGraph `with_structured_output(SingleOutput)` —
returns a Pydantic object directly, no JSON parsing needed.
LangGraph graph: `START → extract_node (zero AI cost) → classify_node (one Gemini call) → END`.
Supports image URLs in the message for visual classification.

**`GeminiLangGraphProvider`** — Simpler single `ainvoke()` with `parse_single_output()` fallback.

**`AnthropicProvider`** — Uses `anthropic.AsyncAnthropic`, same `SINGLE_PROCESS_PROMPT`,
same `parse_single_output()` for JSON parsing.

---

## 9. Request Flows — End to End

### 9.1 Automated Ingestion (Scheduler)

```
APScheduler (every 5 min)
  │
  ├── SourceRepository.get_all(active_only=True)
  │
  └── asyncio.gather([_ingest_one_source(s) for s in sources])
        │
        └── IngestionService.ingest(source)
              │
              ├── RSSFetcher.fetch(url) → feedparser.entries → to_plain_dict()
              ├── slice to AI_MAX_ITEMS_PER_RUN
              ├── compute_content_hash() per article
              ├── raw_repo.store_batch()    [INSERT OR IGNORE on content_hash]
              ├── _load_ai_provider()       [DB config → env → None]
              ├── keyword pre-filter
              ├── asyncio.gather(process_with_semaphore per article)
              │     rate_limiter.wait() + semaphore
              │     → ai_provider.process(raw, source_type)
              ├── bucket: crime / filtered_out / failed
              ├── load_resolvers(db)        [state table query]
              ├── resolve sub_category_ids → int list
              ├── resolve location → state_id
              ├── filter_article_repo.insert_batch()
              ├── post_processed_repo.insert_batch()
              └── raw_repo.mark_filtered / mark_filtered_out / mark_failed

  └── (if any OK) → PublishingService.publish(top_n=20)
        ├── post_processed_repo.get_top_by_imp_score(limit=20)
        ├── rank_score = imp_score × time_decay_factor
        └── final_article_repo.upsert_batch()
```

### 9.2 `POST /ingest/` — Manual Trigger

```
HTTP POST /ingest/  {"source_id": 2}
  └── source_repo.get_by_id(2)
  └── IngestionService.ingest(source)    [same as §9.1]
  └── return {"source_id": 2, "source_type": "rss", "ingested": 5}
```

### 9.3 `GET /final-articles/` — Public Feed

```
HTTP GET /final-articles/?limit=20&sub_category_id=1&q=arrest
  └── final_article_repo.get_feed(limit, offset, sub_category_id, q)
        SELECT fa.*, pp.sub_category_id
        FROM final_articles fa
        JOIN post_processed_articles pp ON pp.id = fa.post_processed_article_id
        [WHERE pp.sub_category_id = 1 AND fa.title ILIKE '%arrest%']
        ORDER BY fa.rank_score DESC
        LIMIT 20
  └── return FinalArticleListResponse(total=N, items=[...])
```

### 9.4 Switching AI Provider

```
POST /ai-providers/          → INSERT INTO ai_provider_configs
PATCH /ai-providers/{id}/activate
  └── UPDATE ai_provider_configs SET is_active=false WHERE is_active=true
  └── UPDATE ai_provider_configs SET is_active=true  WHERE id=?
  └── return {"activated_id": 3, "message": "...now active"}

Next ingest run:
  └── ai_provider_repo.get_active()    → config row
  └── create_from_config(config)       → cache miss → new provider instance
  └── Articles now processed by the new model
```

---

## 10. API Reference

### Base URL
```
http://localhost:8000
```

### Public — Ranked Feed

| Method | Path | Description |
|--------|------|-------------|
| GET | `/final-articles/` | Ranked crime news feed |
| GET | `/final-articles/{id}` | Single article |
| POST | `/final-articles/publish` | Force-refresh ranking |

**GET `/final-articles/` query params:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 20 | Articles per page |
| `offset` | int | 0 | Pagination offset |
| `sub_category_id` | int | — | Filter by crime type |
| `q` | string | — | Keyword search in title + description |

---

### Admin — Sources

| Method | Path | Description |
|--------|------|-------------|
| GET | `/sources/` | List sources (`?include_inactive=true`) |
| POST | `/sources/` | Add new RSS or REST source |
| GET | `/sources/{id}` | Get by ID |
| PATCH | `/sources/{id}` | Update (pause: `{"is_active": false}`) |
| DELETE | `/sources/{id}` | Delete permanently |

---

### Admin — Ingestion

| Method | Path | Description |
|--------|------|-------------|
| POST | `/ingest/` | Trigger immediate ingest for one source |

---

### Admin — AI Providers

| Method | Path | Description |
|--------|------|-------------|
| GET | `/ai-providers/` | List all registered providers |
| POST | `/ai-providers/` | Register a new provider |
| GET | `/ai-providers/active` | Get currently active provider |
| GET | `/ai-providers/{id}` | Get by ID |
| PATCH | `/ai-providers/{id}/activate` | **Switch active provider** |
| DELETE | `/ai-providers/active` | Deactivate all (fall back to .env) |
| DELETE | `/ai-providers/{id}` | Delete a provider config |

**POST `/ai-providers/` body — all provider examples:**

```json
// Ollama (local, no key)
{"name": "Ollama Qwen3", "provider": "ollama",
 "model": "dengcao/Qwen3-30B-A3B-Instruct-2507:latest"}

// Gemini Multimodal (recommended for cloud)
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

### Pipeline Inspection (Debug)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/filter-articles/` | Stage-1 AI-confirmed crime articles |
| GET | `/filter-articles/{id}` | |
| GET | `/post-processed/` | Stage-2 enriched articles |
| GET | `/post-processed/{id}` | |

`/post-processed/` supports `from_date` / `to_date` query params (ISO 8601).

---

### Master Data

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
| GET | `/` | Info message |

---

## 11. Configuration Reference

All settings loaded from `.env` via `app/core/config.py` (pydantic-settings).

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `DATABASE_URL` | str | **required** | Must be `postgresql+asyncpg://...` |
| `OLLAMA_MODEL` | str | None | Enables Ollama env-fallback (e.g. `qwen3:latest`) |
| `OLLAMA_URL` | str | `http://localhost:11434/v1` | Ollama base URL (change for remote) |
| `GEMINI_API_KEY` | str | None | Enables Gemini env-fallback |
| `ANTHROPIC_API_KEY` | str | None | Enables Anthropic env-fallback |
| `AI_REQUESTS_PER_MINUTE` | int | 5 | Rate limit. Set `60` for local Ollama |
| `AI_RETRY_ATTEMPTS` | int | 3 | Retries on rate-limit errors |
| `AI_RETRY_DELAY_SECONDS` | float | 15.0 | Base delay for exponential back-off |
| `AI_MAX_ITEMS_PER_RUN` | int | 10 | Max articles processed per source per run |
| `INGEST_INTERVAL_MINUTES` | int | 5 | Ingestion job interval |
| `PUBLISH_INTERVAL_MINUTES` | int | 5 | Publishing job interval |
| `PUBLISH_OFFSET_SECONDS` | int | 30 | Publishing job offset after ingestion |
| `FEED_TOP_N` | int | 20 | Articles per publish cycle |
| `DECAY_FRESH` | float | 1.00 | Time-decay: < 6 hours |
| `DECAY_RECENT` | float | 0.75 | Time-decay: 6–24 hours |
| `DECAY_DAY` | float | 0.50 | Time-decay: 1–3 days |
| `DECAY_WEEK` | float | 0.25 | Time-decay: 3–7 days |
| `DECAY_OLD` | float | 0.10 | Time-decay: > 7 days |
| `DEBUG` | bool | False | FastAPI debug mode |

**Recommended `.env` for local Ollama (no API rate limits):**

```env
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db_news
OLLAMA_MODEL=dengcao/Qwen3-30B-A3B-Instruct-2507:latest
OLLAMA_URL=http://localhost:11434/v1
AI_REQUESTS_PER_MINUTE=60
AI_MAX_ITEMS_PER_RUN=20
```

**Recommended `.env` for Gemini free tier (5 RPM):**

```env
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db_news
GEMINI_API_KEY=AIzaSy...
AI_REQUESTS_PER_MINUTE=5
AI_MAX_ITEMS_PER_RUN=10
AI_RETRY_ATTEMPTS=3
AI_RETRY_DELAY_SECONDS=15
```

---

## 12. Adding a New AI Provider

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
        # initialise your SDK client here

    @property
    def model_id(self) -> str:
        return f"ai:your_provider:{self._model}"

    async def process(self, raw_payload: dict, source_type: str) -> dict | None:
        user_msg = build_process_message(raw_payload, source_type)
        # call your API with SINGLE_PROCESS_PROMPT as system + user_msg as user
        text = ...   # get text from your API response
        return parse_single_output(text, raw_payload)
```

### Step 2 — Register in the factory

`app/services/normalization/provider_factory.py`:

```python
from app.services.normalization.providers.your_prov import YourProvider

# in _build():
if provider == "your_provider":
    return YourProvider(api_key=api_key, model=model)
```

### Step 3 — Add to model constants

`app/models/ai_provider.py`:

```python
SUPPORTED_PROVIDERS = {..., "your_provider"}
PROVIDER_BASE_URLS["your_provider"] = None        # or a default URL
PROVIDER_DEFAULT_MODELS["your_provider"] = "your-default-model"
```

### Step 4 — Add to schema Literal

`app/schemas/ai_provider_schema.py`:

```python
_PROVIDER_LITERAL = Literal[..., "your_provider"]
```

### Done — test it

```bash
curl -X POST http://localhost:8000/ai-providers/ \
  -d '{"name": "My Provider", "provider": "your_provider",
       "model": "your-model", "api_key": "key"}'
curl -X PATCH http://localhost:8000/ai-providers/{id}/activate
curl -X POST http://localhost:8000/ingest/ -d '{"source_id": 1}'
```
