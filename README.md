# Crime News Aggregator Backend — Architecture Reference

This document is the single source of truth for anyone reading or extending this codebase.
It covers every file, every layer, the full data flow, and the database schema.

---

## Table of Contents

1. [Project Purpose](#1-project-purpose)
2. [Tech Stack](#2-tech-stack)
3. [Directory Structure](#3-directory-structure)
4. [Architectural Philosophy](#4-architectural-philosophy)
5. [Layer-by-Layer Breakdown](#5-layer-by-layer-breakdown)
   - [Entry Point](#51-entry-point--appmainpy)
   - [Core](#52-core-layer--appcore)
   - [Models](#53-models-layer--appmodels)
   - [Repositories](#54-repository-layer--apprepositories)
   - [Schemas](#55-schema-layer--appschemas)
   - [Services](#56-service-layer--appservices)
   - [API Routes](#57-api-layer--appapi)
   - [Migrations](#58-migrations)
6. [Full Data Flow](#6-full-data-flow)
7. [Database Schema](#7-database-schema)
8. [AI Pipeline Deep Dive](#8-ai-pipeline-deep-dive)
9. [Background Scheduler](#9-background-scheduler)
10. [Configuration Reference](#10-configuration-reference)
11. [Development Commands](#11-development-commands)

---

## 1. Project Purpose

An automated backend that:

- Pulls crime news articles from **RSS feeds** and **REST APIs** on a 5-minute schedule
- Runs every article through a **two-stage AI pipeline**:
  - **Stage 1 — Filter**: classifies crime type, extracts structured fields, resolves location
  - **Stage 2 — Post-process**: rewrites title/description in original language, scores importance 1–100, discovers reference URLs via web search
- Ranks and publishes the **top N articles** into a curated feed using importance score × time-decay
- Exposes a clean **REST API** for a frontend to consume

---

## 2. Tech Stack

| Library | Role |
|---------|------|
| **FastAPI** | Web framework — async, automatic OpenAPI/Swagger docs, Pydantic DI |
| **SQLAlchemy 2.0** | Async ORM — typed `Mapped[]` columns, JSONB support, Alembic integration |
| **asyncpg** | Async PostgreSQL driver (required by SQLAlchemy async engine) |
| **Pydantic v2** | Request/response validation and serialisation |
| **pydantic-settings** | `.env` loading with type validation — fails loudly on missing vars |
| **APScheduler** | `AsyncIOScheduler` — runs ingestion + publishing jobs every 5 minutes |
| **feedparser** | Parses RSS/Atom feeds, handles malformed XML gracefully |
| **httpx** | Async HTTP client for REST source fetching |
| **anthropic** | Official Anthropic SDK for Claude models |
| **openai** | OpenAI Python SDK — used for GPT and Gemini OpenAI-compatible endpoints |
| **langchain / langgraph** | LangGraph agent graph for Gemini providers; structured output, tool use |
| **langchain-google-genai** | Gemini model integration for LangChain |
| **langchain-community** | `DuckDuckGoSearchResults` tool for Stage 2 web search |
| **Alembic** | Schema migrations — versioned, async-aware |
| **uvicorn** | ASGI server to run FastAPI |

---

## 3. Directory Structure

```
news_app_backend/
│
├── .env                                    # DATABASE_URL, GEMINI_API_KEY, etc.
├── alembic.ini                             # Alembic config (URL injected at runtime)
├── pyproject.toml                          # Dependencies
├── ARCHITECTURE.md                         # This document
│
├── migrations/
│   ├── env.py                              # Async-aware Alembic runner
│   ├── script.py.mako                      # Template for new migration files
│   └── versions/
│       ├── 29df1b34_initial_schema.py
│       ├── c8f2a1e3_add_raw_ingestion_events.py
│       ├── d9e4f5a6_add_ai_provider_configs.py
│       ├── e1f2a3b4_add_enrichment_fields.py
│       ├── f2g3h4i5_add_article_card_fields.py
│       ├── g3h4i5j6_widen_normalized_by.py
│       ├── h4i5j6k7_pipeline_schema_redesign.py
│       ├── i5j6k7l8_seed_master_data.py
│       ├── j6k7l8m9_pipeline_enhancements.py
│       ├── k7l8m9n0_filtered_articles_cleanup.py
│       └── l8m9n0o1_performance_indexes.py  ← HEAD
│
└── app/
    ├── main.py                             # FastAPI app, middleware, router registration
    │
    ├── core/
    │   ├── config.py                       # All settings via pydantic-settings
    │   ├── database.py                     # Async engine + session factory
    │   ├── deps.py                         # FastAPI Depends factory functions
    │   └── enums.py                        # CategoryEnum, SubCategoryEnum (static lookups)
    │
    ├── models/                             # SQLAlchemy ORM table definitions
    │   ├── __init__.py                     # Imports all models (registers them with Base)
    │   ├── base.py                         # Shared DeclarativeBase
    │   ├── source.py                       # news_sources table
    │   ├── raw_event.py                    # raw_ingestion table
    │   ├── ai_provider.py                  # ai_provider_configs table
    │   ├── category.py                     # master_category + master_sub_category tables
    │   ├── location.py                     # country + state tables
    │   ├── filter_article.py               # filtered_articles table (Stage 1 output)
    │   ├── post_processed_article.py       # post_processed_articles table (Stage 2 output)
    │   └── final_article.py                # final_articles table (ranked public feed)
    │
    ├── repositories/                       # All DB access — no business logic
    │   ├── source_repo.py                  # CRUD for news_sources
    │   ├── raw_ingestion_repo.py           # store_batch, mark_filtered/failed
    │   ├── ai_provider_repo.py             # CRUD + activate for ai_provider_configs
    │   ├── master_data_repo.py             # Read-only: categories, sub-categories, states
    │   ├── filter_article_repo.py          # insert_batch + reads for filtered_articles
    │   ├── post_processed_article_repo.py  # insert_batch + reads for post_processed_articles
    │   ├── article_repo.py                 # Alias: ArticleRepository = PostProcessedArticleRepository
    │   └── final_article_repo.py           # upsert_batch + ranked feed reads
    │
    ├── schemas/                            # Pydantic request/response contracts
    │   ├── source_schema.py                # SourceCreate, SourceUpdate, SourceResponse
    │   ├── ai_provider_schema.py           # AIProviderCreate, AIProviderResponse
    │   ├── article_schema.py               # PostProcessedArticleResponse (+ alias)
    │   ├── final_article_schema.py         # FinalArticleResponse, FinalArticleListResponse
    │   └── master_data_schema.py           # Category, SubCategory, State responses
    │
    ├── services/
    │   ├── scheduler.py                    # APScheduler: ingestion every 5min, publish every 5min
    │   ├── ingestion_service.py            # Orchestrates the full two-stage pipeline
    │   ├── publishing_service.py           # Ranks articles and writes final_articles feed
    │   ├── source_normalizer.py            # Coerces raw feedparser/REST dicts to plain Python
    │   ├── fetchers/
    │   │   ├── rss_fetcher.py              # feedparser-based RSS/Atom fetcher
    │   │   └── rest_fetcher.py             # httpx-based REST API fetcher
    │   └── normalization/
    │       ├── ai_processor.py             # Resolves which AI provider to use (DB → env fallback)
    │       ├── provider_factory.py         # Instantiates + caches provider objects
    │       ├── resolvers.py                # CategoryResolver (enum), LocationResolver (DB)
    │       ├── canonical_validator.py      # Post-parse field validation helpers
    │       └── providers/
    │           ├── base.py                 # AIProvider ABC + prompts + Pydantic output models
    │           ├── openai_prov.py          # OpenAI-compatible provider (GPT, Gemini REST, custom)
    │           ├── anthropic_prov.py       # Anthropic Claude provider
    │           ├── gemini_langgraph_prov.py     # Gemini + LangGraph agent
    │           └── gemini_multimodal_prov.py    # Gemini multimodal + LangGraph (recommended)
    │
    └── api/                                # HTTP route handlers — thin controllers only
        ├── routes_final_articles.py        # GET /final-articles/ (public feed)
        ├── routes_master_data.py           # GET /master/categories|sub-categories|states
        ├── routes_sources.py               # CRUD /sources/
        ├── routes_ingest.py                # POST /ingest/
        └── routes_ai_providers.py          # CRUD + activate /ai-providers/
```

---

## 4. Architectural Philosophy

The codebase follows a strict **layered architecture** — each layer has one responsibility
and may only call the layer directly below it.

```
HTTP Request
     │
     ▼
 [API Layer]           ← validates input, calls service/repo, returns schema
     │
     ▼
 [Service Layer]       ← business logic, pipeline orchestration, error handling
     │
     ▼
 [Repository Layer]    ← database access only — no business logic
     │
     ▼
 [Model Layer]         ← table definitions only — no methods, no logic
     │
     ▼
  [PostgreSQL]
```

**Enforced rules:**
- Routes never touch `AsyncSession` directly — they receive injected repos/services via `Depends`
- Repositories never call services — data flows downward only
- Pydantic schemas never appear inside ORM models
- Business logic never appears inside schemas or models
- External HTTP / AI API calls happen only inside `services/`

---

## 5. Layer-by-Layer Breakdown

### 5.1 Entry Point — `app/main.py`

Creates the FastAPI app, attaches middleware, and registers all routers.

**Responsibilities:**
- Creates `FastAPI(title="Crime News API", version="1.0.0")` with a `lifespan` hook
- `lifespan` startup: calls `start_scheduler()` — kicks off the background jobs
- `lifespan` shutdown: calls `stop_scheduler()` — drains running jobs gracefully
- Attaches `CORSMiddleware` with `allow_origins=["*"]` (restrict to your domain in production)
- Configures `logging.basicConfig` at `INFO` level
- Registers 5 routers with prefixes and Swagger tags
- `/health` and `/` are hidden from the OpenAPI schema (`include_in_schema=False`)

---

### 5.2 Core Layer — `app/core/`

Infrastructure with no domain knowledge.

---

#### `config.py`

All environment variables in one typed object, loaded once at startup.

```python
class Settings(BaseSettings):
    DATABASE_URL: str               # required — app refuses to start if missing
    DEBUG: bool = False
    GEMINI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    AI_REQUESTS_PER_MINUTE: int = 5    # rate limiter for free-tier safety
    AI_RETRY_ATTEMPTS: int = 3
    AI_RETRY_DELAY_SECONDS: float = 15.0
    INGEST_INTERVAL_MINUTES: int = 5
    PUBLISH_INTERVAL_MINUTES: int = 5
    PUBLISH_OFFSET_SECONDS: int = 30   # delay publish job after ingest
    FEED_TOP_N: int = 20
    DUCKDUCKGO_TIMEOUT_SECONDS: float = 10.0
    DECAY_FRESH: float = 1.00          # < 6h
    DECAY_RECENT: float = 0.75         # 6–24h
    DECAY_DAY: float = 0.50            # 1–3d
    DECAY_WEEK: float = 0.25           # 3–7d
    DECAY_OLD: float = 0.10            # > 7d
```

All other files import the singleton `settings = Settings()`. Nothing else calls `os.getenv`.

---

#### `database.py`

Async SQLAlchemy engine and `get_db` session dependency.

```python
engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG, pool_size=10, max_overflow=20)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

`expire_on_commit=False` prevents "lazy load after commit" errors when route handlers access ORM attributes after a `commit()`.

---

#### `deps.py`

FastAPI `Depends` factories — the only place repositories and services are instantiated for routes.

| Function | Returns | Used by |
|----------|---------|---------|
| `get_source_repo` | `SourceRepository` | sources routes |
| `get_post_processed_repo` | `PostProcessedArticleRepository` | final-articles publish |
| `get_ai_provider_repo` | `AIProviderRepository` | ai-providers routes |
| `get_final_article_repo` | `FinalArticleRepository` | final-articles routes |
| `get_category_repo` | `MasterCategoryRepository` | master-data routes |
| `get_sub_category_repo` | `MasterSubCategoryRepository` | master-data routes |
| `get_state_repo` | `StateRepository` | master-data routes |
| `get_ingestion_service` | `IngestionService` | ingest route |

`get_ingestion_service` wires all five repos (`source`, `raw`, `filter_article`, `post_processed`, `ai_provider`) plus the raw `db` session (needed by `CategoryResolver` / `LocationResolver`).

---

#### `enums.py`

Static `IntEnum` definitions for crime taxonomy — **zero DB queries** at classification time.

```python
class CategoryEnum(IntEnum):
    VIOLENT_CRIME = 1;  TERRORISM = 2;  FINANCIAL_CRIME = 3;  CYBER_CRIME = 4
    DRUG_CRIME = 5;     PROPERTY_CRIME = 6;  SEXUAL_CRIME = 7;  OTHER = 8

class SubCategoryEnum(IntEnum):
    MURDER = 1;  VIOLENCE = 2;  TERRORISM = 3;  FRAUD = 4;  CORRUPTION = 5
    CYBERCRIME = 6;  DRUG_TRAFFICKING = 7;  THEFT = 8;  HUMAN_TRAFFICKING = 9;  OTHER = 10
```

Two lookup dicts are also defined here:
- `AI_STRING_TO_SUB_CATEGORY: dict[str, SubCategoryEnum]` — maps AI output strings (`"murder"`, `"fraud"`, …) to enum IDs
- `SUB_CATEGORY_TO_CATEGORY: dict[SubCategoryEnum, CategoryEnum]` — maps sub-category → parent category for deriving `category_ids`

IDs match the seed migration (`i5j6k7l8m901`) which uses `ON CONFLICT DO NOTHING`, so they are stable.

---

### 5.3 Models Layer — `app/models/`

SQLAlchemy ORM table definitions. **No methods, no business logic, no imports from services or schemas.**

`app/models/__init__.py` imports every model in dependency order so that all `Table` objects are registered onto `Base.metadata` before any query or migration runs.

---

#### `base.py`
```python
class Base(DeclarativeBase):
    pass
```
All models inherit from this. Alembic's `env.py` imports `Base.metadata` to autogenerate migrations.

---

#### `source.py` → `news_sources`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `name` | VARCHAR | Display label |
| `type` | VARCHAR | `"rss"` or `"rest"` — controls which fetcher is used |
| `url` | VARCHAR UNIQUE | Dedup guard — prevents registering the same feed twice |
| `config` | JSONB | Per-source extras, e.g. `{"headers": {"Authorization": "Bearer …"}}` |
| `is_active` | BOOLEAN | `false` = paused, skipped by scheduler |
| `created_at` | TIMESTAMPTZ | `server_default=NOW()` |

---

#### `raw_event.py` → `raw_ingestion`

The **pipeline inbox** — every item fetched from a source lands here first.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `source_id` | INTEGER FK → news_sources | CASCADE delete |
| `content_hash` | VARCHAR(64) UNIQUE | SHA-256 of `source_id + raw_payload` — deduplication key |
| `raw_payload` | JSONB | Complete original data from the feed/API |
| `status` | VARCHAR | `pending` → `filtered` / `filtered_out` / `failed` |
| `normalized_by` | VARCHAR(200) | e.g. `"ai:gemini_langgraph:gemini-2.0-flash"` — audit trail |
| `error_message` | TEXT | Populated on `failed` status |
| `retry_count` | INTEGER | How many AI retry attempts were made |
| `created_at` | TIMESTAMPTZ | |
| `processed_at` | TIMESTAMPTZ | When AI processing completed |

---

#### `ai_provider.py` → `ai_provider_configs`

Stores AI provider credentials — allows runtime provider switching without redeployment.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `name` | VARCHAR | Friendly label |
| `provider` | VARCHAR | `anthropic`, `openai`, `gemini`, `gemini_langgraph`, `gemini_multimodal`, `custom` |
| `model` | VARCHAR | e.g. `gemini-2.0-flash`, `claude-haiku-4-5-20251001` |
| `api_key` | VARCHAR | Stored encrypted at rest; never returned by any API endpoint |
| `base_url` | VARCHAR | Required for `gemini` and `custom`; null for `anthropic`/`openai` |
| `is_active` | BOOLEAN | Only one row may be `true` at a time (partial unique index) |
| `created_at` | TIMESTAMPTZ | |

---

#### `category.py` → `master_category` + `master_sub_category`

Reference tables seeded by migration `i5j6k7l8m901`. Rarely change after seeding.

`master_category`: id, name, description, priority_point, is_active, created_at
`master_sub_category`: id, category_id (FK), name, description, priority_point, is_active, created_at

IDs are stable (matching `enums.py`) because the seed uses `ON CONFLICT DO NOTHING`.

---

#### `location.py` → `country` + `state`

`country`: id, name
`state`: id, country_id (FK), name

Seeded with India + 36 states/UTs. `LocationResolver` loads the state table at the start of each ingest run to resolve AI-extracted location strings to a `state.id`.

---

#### `filter_article.py` → `filtered_articles`

**Stage 1 AI output.** One row per crime-relevant article.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `raw_ingestion_id` | INTEGER FK UNIQUE | One-to-one with raw_ingestion |
| `title` | VARCHAR | Extracted verbatim from source |
| `description` | TEXT | Body text extracted and HTML-cleaned |
| `image_url` | VARCHAR | |
| `main_url` | VARCHAR UNIQUE | Canonical URL — upsert dedup key |
| `published_at` | TIMESTAMPTZ | |
| `created_at` | TIMESTAMPTZ | |
| `sub_category_ids` | JSONB | Multi-label array e.g. `[1, 3]` (Murder + Terrorism). GIN indexed. |
| `category_ids` | JSONB | Parent category IDs derived from sub_category_ids. GIN indexed. |
| `location_state_id` | INTEGER FK → state | Nullable |

---

#### `post_processed_article.py` → `post_processed_articles`

**Stage 2 AI output.** Rewritten, scored, reference-enriched version.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `filter_article_id` | INTEGER FK UNIQUE | One-to-one with filtered_articles |
| `title` | VARCHAR | AI-rewritten headline |
| `description` | TEXT | AI-rewritten ~100 word summary |
| `image_url` | VARCHAR | |
| `reference_urls` | TEXT[] | Up to 5 related article URLs found via DuckDuckGo |
| `published_at` | TIMESTAMPTZ | |
| `created_at` | TIMESTAMPTZ | |
| `sub_category_id` | INTEGER FK → master_sub_category | Single best-match sub-category |
| `location_id` | INTEGER FK → state | |
| `imp_score` | INTEGER | AI importance score 1–100. Partial B-tree index (NOT NULL rows only). |

---

#### `final_article.py` → `final_articles`

**The public feed.** Top N articles ranked by `rank_score`, refreshed every 5 minutes.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `post_processed_article_id` | INTEGER FK UNIQUE | |
| `title` | VARCHAR | Denormalised from post_processed_articles at publish time |
| `description` | TEXT | |
| `image_url` | VARCHAR | |
| `reference_urls` | TEXT[] | |
| `rank_score` | FLOAT | `imp_score × time_decay_factor`. B-tree indexed. |
| `created_at` | TIMESTAMPTZ | |

---

### 5.4 Repository Layer — `app/repositories/`

The only code that executes SQL. Repositories accept an `AsyncSession` via constructor injection. They return ORM objects or primitives. Zero business logic.

---

#### `source_repo.py` — `SourceRepository`
| Method | SQL | Notes |
|--------|-----|-------|
| `create(data)` | INSERT + RETURNING | Returns populated Source ORM object |
| `get_all(active_only)` | SELECT WHERE is_active | Defaults to active only |
| `get_by_id(id)` | SELECT WHERE id | Returns `None` on miss |
| `update(id, data)` | UPDATE SET … WHERE id | Partial update (only non-None fields) |
| `delete(id)` | DELETE WHERE id | Returns `True` if deleted |

---

#### `raw_ingestion_repo.py` — `RawIngestionRepository`
| Method | SQL | Notes |
|--------|-----|-------|
| `store_batch(source_id, items)` | INSERT ON CONFLICT DO NOTHING | Returns `{content_hash: id}` for all hashes — idempotent |
| `mark_filtered(source_id, hashes_by_normalizer)` | UPDATE SET status='filtered' | Sets `normalized_by` to the model audit string |
| `mark_filtered_out(source_id, hashes, model_id)` | UPDATE SET status='filtered_out' | |
| `mark_failed(source_id, hashes, reason)` | UPDATE SET status='failed' | |

`content_hash` = SHA-256(`str(source_id) + json.dumps(payload, sort_keys=True)`). Prevents re-processing the same article on every scheduler run.

---

#### `filter_article_repo.py` — `FilterArticleRepository`
| Method | Notes |
|--------|-------|
| `insert_batch(articles, hash_to_raw_id)` | Upsert on `main_url`. Returns `{url: filter_article_id}`. |
| `get_all(limit, offset, sub_category_id, q)` | JSONB `@>` containment for sub_category_id filter |
| `get_by_id(id)` | |
| `count(sub_category_id, q)` | |

---

#### `post_processed_article_repo.py` — `PostProcessedArticleRepository`
| Method | Notes |
|--------|-------|
| `insert_batch(articles, url_to_filter_id)` | Upsert on `filter_article_id`. Falls back to Stage 1 values if Stage 2 fields are missing. |
| `get_all(limit, offset, sub_category_id, q, from_date, to_date)` | Ordered by published_at DESC |
| `get_by_id(id)` | |
| `count(…)` | |

---

#### `final_article_repo.py` — `FinalArticleRepository`
| Method | Notes |
|--------|-------|
| `upsert_batch(articles)` | Upsert on `post_processed_article_id`. Updates rank_score on re-publish. |
| `get_feed(limit, offset, sub_category_id, q)` | Ordered by `rank_score DESC` |
| `get_by_id(id)` | |
| `count(sub_category_id, q)` | |

---

#### `master_data_repo.py` — Read-only repos for reference tables

`MasterCategoryRepository`, `MasterSubCategoryRepository`, `CountryRepository`, `StateRepository` — all read-only (`get_all`, `get_by_id`, `count`).

---

#### `article_repo.py`
```python
ArticleRepository = PostProcessedArticleRepository
```
Backwards-compatible alias. Existing code that imports `ArticleRepository` continues to work.

---

### 5.5 Schema Layer — `app/schemas/`

Pydantic models defining the HTTP contract. ORM objects never leak out of route handlers — they are always serialised through a schema first.

`model_config = {"from_attributes": True}` on all response schemas enables reading from SQLAlchemy ORM objects by attribute access.

| Schema file | Key models |
|-------------|-----------|
| `source_schema.py` | `SourceCreate`, `SourceUpdate`, `SourceResponse` |
| `ai_provider_schema.py` | `AIProviderCreate` (with examples for all 5 provider types), `AIProviderResponse`, `AIProviderActivateResponse` |
| `article_schema.py` | `PostProcessedArticleResponse`, `ArticleListResponse`, `ArticleResponse` (alias) |
| `final_article_schema.py` | `FinalArticleResponse`, `FinalArticleListResponse` |
| `master_data_schema.py` | `MasterCategoryResponse`, `MasterSubCategoryResponse`, `StateResponse` |

---

### 5.6 Service Layer — `app/services/`

All business logic and orchestration lives here.

---

#### `fetchers/rss_fetcher.py` — `RSSFetcher`

Fetches and parses RSS/Atom feeds.

```python
async def fetch(self, url: str) -> feedparser.FeedParserDict:
    feed = await asyncio.to_thread(feedparser.parse, url)
    ...
```

`asyncio.to_thread` is required because `feedparser.parse` is synchronous and blocking. Calling it directly in `async def` would freeze the entire event loop. The thread pool offloads it so other requests continue being served.

If `feed.bozo` is `True` (malformed XML), it logs a warning and continues — partial feeds are better than no feed.

---

#### `fetchers/rest_fetcher.py` — `RestFetcher`

Fetches articles from a JSON REST API endpoint.

```python
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

async def fetch(self, url: str, headers: dict | None = None) -> list[dict]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(url, headers=headers or {})
        response.raise_for_status()
    ...
```

Handles four common envelope shapes (`[]`, `{"articles":[]}`, `{"items":[]}`, `{"results":[]}`) and always returns a flat `list[dict]`.

---

#### `source_normalizer.py`

Pure transformation — converts raw feedparser entries or REST API dicts into plain Python types suitable for JSONB storage.

- `_to_plain_dict(obj)`: Recursively converts `FeedParserDict` (a dict subclass with attribute access) to plain dicts. Without this, SQLAlchemy's JSONB serialiser raises `TypeError`.
- `_parse_date(raw)`: Tries RFC 2822 (RSS) then ISO 8601 (REST). Returns a UTC `datetime` or `None`.
- `normalize(item)`: Maps feed-specific field names to the canonical dict expected by `RawIngestionRepository.store_batch()`.

---

#### `normalization/providers/base.py`

The most important file in the AI pipeline. Contains:

**`COMBINED_PROCESS_PROMPT` (Stage 1)**
Instructions for the AI to extract structured fields and multi-label crime classify. Key rules:
- Extract `title` and `description` verbatim — no rephrasing
- Classify `sub_category_ids` as a multi-label integer array (e.g. `[1, 3]`)
- Extract `location` as a city/state name string

**`POST_PROCESS_PROMPT` (Stage 2)**
Instructions for rewriting and scoring. Key rules:
- Rephrase `title` and `description` in original words (anti-plagiarism)
- Description must be ~100 words
- Extract `reference_urls` only from the provided `web_search_context` — never invented
- Assign `imp_score` 1–100 based on severity, impact, and recency

**Pydantic output models:**
- `CombinedOutput` — validates Stage 1 JSON with lenient field validators (bad fields default to `None`, not hard failure)
- `PostProcessOutput` — validates Stage 2 JSON; URL validator rejects non-HTTP URLs

**Helper functions:**
- `build_process_message(raw_payload, source_type)` — builds the user message for Stage 1
- `build_post_process_message(filter_article, search_context)` — builds the user message for Stage 2
- `parse_combined_output(text, raw_payload)` — strips code fences, JSON-parses, Pydantic-validates
- `parse_post_process_output(text)` — same for Stage 2

**`AIProvider` ABC:**
```python
class AIProvider(ABC):
    @property
    @abstractmethod
    def model_id(self) -> str: ...          # e.g. "ai:gemini_langgraph:gemini-2.0-flash"

    @abstractmethod
    async def process(self, raw_payload: dict, source_type: str) -> dict | None: ...

    async def post_process(self, filter_article: dict, search_context: str = "") -> dict | None:
        return None   # default — providers override this
```

---

#### `normalization/providers/openai_prov.py` — `OpenAICompatibleProvider`

Used for: OpenAI GPT models, Gemini via its OpenAI-compatible REST endpoint, any custom server (Ollama, vLLM).

- Uses the `openai.AsyncOpenAI` client with a custom `base_url` for non-OpenAI backends
- Stage 1: sends `COMBINED_PROCESS_PROMPT` as system message with `response_format={"type": "json_object"}`
- Stage 2: sends `POST_PROCESS_PROMPT` as system message
- `max_tokens=1500` for both stages

---

#### `normalization/providers/anthropic_prov.py` — `AnthropicProvider`

Used for: Anthropic Claude models.

- Uses `anthropic.AsyncAnthropic` client with Anthropic's native `system=` parameter (better instruction adherence than injecting as a user message)
- `max_tokens=1500` for Stage 1, `600` for Stage 2

---

#### `normalization/providers/gemini_langgraph_prov.py` — `GeminiLangGraphProvider`

Used for: Gemini models via LangGraph agent graph.

- Builds a two-node LangGraph: `search_node` (DuckDuckGo context) → `process_node` (Gemini call)
- Passes search context to the AI prompt for better classification

---

#### `normalization/providers/gemini_multimodal_prov.py` — `GeminiMultimodalLangGraphProvider` *(recommended)*

Used for: Gemini with multimodal image support via LangGraph.

**Stage 1 graph** (3 nodes):
1. `extract_node` — lightweight dict traversal for candidate title/image/URL
2. `search_node` — DuckDuckGo news search for crime context
3. `classify_node` — Gemini `with_structured_output(FilterClassification)` — passes `image_url` if available for multimodal analysis

**Stage 2 graph** (separate):
Similar structure with rewrite + scoring nodes.

---

#### `normalization/provider_factory.py`

Instantiates and **caches** AI provider objects. Caching is critical — providers hold HTTP connection pools internally, and recreating them per article would add connection overhead.

```python
_cache: dict[tuple, AIProvider] = {}

def create_from_config(config: AIProviderConfig) -> AIProvider:
    key = (config.id, config.model, config.api_key)
    if key not in _cache:
        _cache[key] = _build(config)
    return _cache[key]
```

`_build()` dispatches on `config.provider` to the correct provider class.

---

#### `normalization/ai_processor.py`

Resolves which AI provider to use. Resolution order:

1. **DB active config** → `provider_factory.create_from_config(active_config)`
2. **`GEMINI_API_KEY` env** → `GeminiMultimodalLangGraphProvider` (recommended default)
3. **`ANTHROPIC_API_KEY` env** → `AnthropicProvider`
4. **`None`** → articles are dropped at AI stage

---

#### `normalization/resolvers.py`

**`CategoryResolver`** — stateless, enum-based, zero DB queries:
```python
def resolve(self, ai_str: str | None) -> int | None:
    return int(AI_STRING_TO_SUB_CATEGORY[ai_str.lower().strip()])

def resolve_all(self, ai_str_list: list[str]) -> list[int]:
    # Returns deduplicated list of SubCategoryEnum int values

def resolve_categories_from_ids(self, sub_cat_ids: list[int]) -> list[int]:
    # Maps SubCategoryEnum → CategoryEnum via SUB_CATEGORY_TO_CATEGORY dict
```

**`LocationResolver`** — DB-backed, loaded once per ingest run:
```python
def resolve(self, location: str | None) -> int | None:
    # Two-pass: direct state name match, then city → state alias lookup
    # _CITY_TO_STATE: dict of ~80 Indian cities to their state names
```

`load_resolvers(db)` is called once at the top of `IngestionService.ingest()`:
- Only queries the `state` table (36 rows)
- Returns `(CategoryResolver(), LocationResolver(state_map))`

---

#### `ingestion_service.py` — `IngestionService`

**The pipeline orchestrator.** Wires together all fetchers, AI providers, resolvers, and repositories to run the full two-stage processing pipeline.

**Constructor params:**
```python
def __init__(self, source_repo, raw_repo, filter_article_repo,
             post_processed_repo, ai_provider_repo, db=None)
```

**`ingest(source)` — full pipeline in order:**

```
1. FETCH
   RSSFetcher.fetch(url)  or  RestFetcher.fetch(url, headers)
   → list of raw items

2. STORE RAW
   raw_ingestion_repo.store_batch(source_id, items)
   → {content_hash: raw_ingestion_id}
   Skips items whose content_hash already exists (idempotent).

3. LOAD AI PROVIDER
   ai_processor.get_active_provider(ai_provider_repo)
   → AIProvider instance (cached by provider_factory)

4. STAGE 1 — AI FILTER (concurrent, rate-limited)
   For each raw item:
     acquire rate limiter token  (AI_REQUESTS_PER_MINUTE)
     acquire semaphore           (concurrency cap)
     ai_provider.process(raw_payload, source_type)
     → article dict or None
   asyncio.gather(*tasks)  ← all items processed concurrently

5. SPLIT RESULTS
   crime articles        → proceed to Stage 2
   non-crime / None      → mark raw_ingestion status = 'filtered_out'
   exceptions            → retry up to AI_RETRY_ATTEMPTS times with backoff

6. RESOLVE FOREIGN KEYS (once per batch)
   load_resolvers(db)
   For each crime article:
     sub_category_ids  = cat_resolver.resolve_all(article["sub_category_ids"])
     category_ids      = cat_resolver.resolve_categories_from_ids(sub_category_ids)
     sub_category_id   = cat_resolver.resolve(article["sub_category"])   (single best)
     location_state_id = loc_resolver.resolve(article["location"])

7. STAGE 2 — POST-PROCESS (concurrent, rate-limited)
   For each crime article:
     DuckDuckGo search for article title  ← outside rate limiter (not an AI call)
     acquire rate limiter token
     acquire semaphore
     ai_provider.post_process(article, search_context)
     → {rewritten_title, rewritten_description, reference_urls, imp_score}

8. WRITE STAGE 1
   filter_article_repo.insert_batch(crime_articles, hash_to_raw_id)
   → {main_url: filter_article_id}

9. WRITE STAGE 2
   post_processed_repo.insert_batch(crime_articles, url_to_filter_id)

10. AUDIT
    raw_ingestion_repo.mark_filtered(crime hashes, model_id)
    raw_ingestion_repo.mark_filtered_out(non-crime hashes)
    raw_ingestion_repo.mark_failed(failed hashes)
```

**Rate limiting:**

A process-level singleton `_RateLimiter` and `asyncio.Semaphore` are shared across all concurrent sources and both pipeline stages:

```python
# Rate limiter: enforces AI_REQUESTS_PER_MINUTE
# Semaphore concurrency:
#   RPM ≤ 10  → 1 concurrent AI call
#   RPM ≤ 30  → 2 concurrent AI calls
#   RPM ≤ 100 → 5 concurrent AI calls
#   RPM > 100 → 10 concurrent AI calls
```

**Retry logic:** On HTTP 429 / quota exhausted responses, retries up to `AI_RETRY_ATTEMPTS` times with exponential backoff (`delay × 2^attempt`).

**DuckDuckGo timeout:** Wrapped in `asyncio.wait_for(timeout=settings.DUCKDUCKGO_TIMEOUT_SECONDS)`. If search hangs, it is cancelled and the article proceeds without reference URLs (non-fatal).

---

#### `publishing_service.py` — `PublishingService`

Selects top N post-processed articles and writes the ranked public feed.

**`publish(top_n=20)`:**
1. `post_processed_repo.get_all(...)` ordered by `imp_score DESC WHERE imp_score IS NOT NULL` — uses partial index
2. For each article: `rank_score = imp_score × _time_decay_factor(published_at)`
3. `final_article_repo.upsert_batch(ranked_articles)`

**Time decay factors** (from `settings`):

| Age | Factor | Result for imp_score=80 |
|-----|--------|------------------------|
| < 6 hours | 1.00 | 80.0 |
| 6–24 hours | 0.75 | 60.0 |
| 1–3 days | 0.50 | 40.0 |
| 3–7 days | 0.25 | 20.0 |
| > 7 days | 0.10 | 8.0 |

---

#### `scheduler.py`

Two APScheduler jobs registered on `AsyncIOScheduler`:

| Job | Trigger | What it does |
|-----|---------|-------------|
| `ingestion_all_sources` | Every `INGEST_INTERVAL_MINUTES` | Loads active sources, runs `IngestionService.ingest()` for each concurrently via `asyncio.gather()` |
| `publish_final_feed` | Every `PUBLISH_INTERVAL_MINUTES` + `PUBLISH_OFFSET_SECONDS` | Runs `PublishingService.publish(top_n=FEED_TOP_N)` |

Each source gets its own `AsyncSession` to isolate DB transactions. `max_instances=1` prevents job pile-up if a previous run is still in progress.

---

### 5.7 API Layer — `app/api/`

Thin controllers — validate input, call a service or repository, return a typed schema. No SQL, no business logic.

---

#### `routes_final_articles.py` — prefix `/final-articles`

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| GET | `/` | `list_final_articles` | Ranked news feed, ordered by rank_score DESC |
| GET | `/{article_id}` | `get_final_article` | Single article by ID |
| POST | `/publish` | `trigger_publishing` | Force a publishing run immediately |

---

#### `routes_sources.py` — prefix `/sources`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/` | Register a new source (201) |
| GET | `/` | List sources (active only by default) |
| GET | `/{id}` | Get one source |
| PATCH | `/{id}` | Update name/url/config/is_active |
| DELETE | `/{id}` | Permanently delete (204) |

---

#### `routes_ingest.py` — prefix `/ingest`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/` | Run full pipeline for `source_id` immediately |

Validates source exists (404) and source type is supported (400) before calling `IngestionService.ingest()`.

---

#### `routes_ai_providers.py` — prefix `/ai-providers`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/` | Register config (starts inactive) |
| GET | `/` | List all configs (api_key excluded) |
| GET | `/active` | Get currently active config |
| GET | `/{id}` | Get one config |
| PATCH | `/{id}/activate` | Make active, deactivate all others |
| DELETE | `/active` | Deactivate all (fall back to env) |
| DELETE | `/{id}` | Delete permanently |

---

#### `routes_master_data.py` — prefix `/master`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/categories/` | All crime categories |
| GET | `/categories/{id}` | One category |
| GET | `/sub-categories/` | All crime sub-categories (filter by category_id) |
| GET | `/sub-categories/{id}` | One sub-category |
| GET | `/states/` | All states (filter by country_id) |
| GET | `/states/{id}` | One state |

---

### 5.8 Migrations

All migrations live in `migrations/versions/`. Applied with `alembic upgrade head`.

| Migration | Description |
|-----------|-------------|
| `29df1b34` | Initial schema: `news_sources`, `articles` |
| `c8f2a1e3` | Add `raw_ingestion` table |
| `d9e4f5a6` | Add `ai_provider_configs` table |
| `e1f2a3b4` | Add enrichment fields to articles |
| `f2g3h4i5` | Add article card fields |
| `g3h4i5j6` | Widen `normalized_by` VARCHAR(50→200) |
| `h4i5j6k7` | **Pipeline redesign** — adds `filtered_articles`, `post_processed_articles`, `master_category`, `master_sub_category`, `country`, `state` |
| `i5j6k7l8` | Seed master data (8 categories, 10 sub-categories, India + 36 states) |
| `j6k7l8m9` | Pipeline enhancements — add `sub_category_ids` JSONB, `location_state_id`, `imp_score`, `final_articles` |
| `k7l8m9n0` | Cleanup — rename `filter_articles` → `filtered_articles`, drop orphaned `category_id` FK, add `category_ids` JSONB |
| `l8m9n0o1` | **Performance indexes** — GIN on `sub_category_ids`/`category_ids`, B-tree on `raw_ingestion.status`, partial B-tree on `imp_score` |

`migrations/env.py` uses `async_engine_from_config` with `asyncio.run()` to bridge the sync Alembic runner into async context (required for asyncpg). `pool.NullPool` is used so the process exits cleanly after migration.

---

## 6. Full Data Flow

### Scheduled ingestion (every 5 minutes)

```
scheduler.py: run_ingestion_for_all_active_sources()
  │
  ├── SourceRepository.get_all(active_only=True)
  │     SELECT * FROM news_sources WHERE is_active = true
  │
  └── For each source (concurrent via asyncio.gather):
        IngestionService.ingest(source)
          │
          ├─ 1. FETCH
          │     RSSFetcher.fetch(url)  →  feedparser (thread pool)
          │  or RestFetcher.fetch(url)  →  httpx async
          │
          ├─ 2. STORE RAW
          │     raw_ingestion_repo.store_batch()
          │     INSERT INTO raw_ingestion ... ON CONFLICT (content_hash) DO NOTHING
          │
          ├─ 3. LOAD AI
          │     ai_processor.get_active_provider(ai_provider_repo)
          │     → reads ai_provider_configs WHERE is_active = true
          │     → falls back to GEMINI_API_KEY env if no DB config
          │
          ├─ 4. STAGE 1 (concurrent, rate-limited)
          │     for each raw item:
          │       [rate limiter + semaphore]
          │       ai_provider.process(raw_payload, source_type)
          │       → AI returns JSON → CombinedOutput Pydantic validation
          │
          ├─ 5. SPLIT: crime / non-crime / failed
          │
          ├─ 6. RESOLVE FKs (enum + DB state lookup)
          │     sub_category_ids, category_ids, sub_category_id, location_state_id
          │
          ├─ 7. STAGE 2 (concurrent, rate-limited)
          │     for each crime article:
          │       DuckDuckGo.ainvoke(title)  →  search_context string
          │       [rate limiter + semaphore]
          │       ai_provider.post_process(article, search_context)
          │       → AI returns JSON → PostProcessOutput Pydantic validation
          │
          ├─ 8. WRITE Stage 1
          │     filter_article_repo.insert_batch()
          │     INSERT INTO filtered_articles ... ON CONFLICT (main_url) DO UPDATE
          │
          ├─ 9. WRITE Stage 2
          │     post_processed_repo.insert_batch()
          │     INSERT INTO post_processed_articles ... ON CONFLICT (filter_article_id) DO UPDATE
          │
          └─ 10. AUDIT
                raw_ingestion_repo.mark_filtered / mark_filtered_out / mark_failed
```

### Scheduled publishing (every 5 minutes + 30s offset)

```
scheduler.py: run_publishing()
  │
  └── PublishingService.publish(top_n=20)
        │
        ├── post_processed_repo.get_all(ordered by imp_score DESC, NOT NULL)
        │     ← uses partial index: ix_post_processed_articles_imp_score_scored
        │
        ├── for each article:
        │     rank_score = imp_score × _time_decay_factor(published_at)
        │
        └── final_article_repo.upsert_batch(ranked_articles)
              INSERT INTO final_articles ... ON CONFLICT (post_processed_article_id) DO UPDATE SET rank_score = ...
```

### Frontend reads the feed

```
GET /final-articles/?limit=20&offset=0
  │
  └── FinalArticleRepository.get_feed()
        SELECT * FROM final_articles ORDER BY rank_score DESC LIMIT 20
        ← uses ix_final_articles_rank_score index
```

---

## 7. Database Schema

```
┌─────────────────────────────────────────────────────────────────┐
│                        news_sources                             │
│  id · name · type · url(UNIQUE) · config(JSONB) · is_active     │
└────────────────────────────┬────────────────────────────────────┘
                             │ 1:N  CASCADE
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                        raw_ingestion                            │
│  id · source_id · content_hash(UNIQUE) · raw_payload(JSONB)     │
│  status · normalized_by · error_message · retry_count           │
└────────────────────────────┬────────────────────────────────────┘
                             │ 1:1  SET NULL
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      filtered_articles                          │
│  id · raw_ingestion_id(UNIQUE) · title · description            │
│  main_url(UNIQUE) · image_url · published_at · created_at       │
│  sub_category_ids(JSONB GIN) · category_ids(JSONB GIN)          │
│  location_state_id ──────────────────────────────┐             │
└────────────────────────────┬─────────────────────│─────────────┘
                             │ 1:1  SET NULL        │ FK
                             ▼                      ▼
┌────────────────────────────────────────┐  ┌───────────────┐
│       post_processed_articles          │  │     state     │
│  id · filter_article_id(UNIQUE)        │  │  id · name    │
│  title · description · image_url       │  │  country_id   │
│  reference_urls(TEXT[])                │  └───────┬───────┘
│  published_at · imp_score(INT 1-100)   │          │ FK
│  sub_category_id ─────────────────┐   │  ┌───────┴───────┐
│  location_id ──────────────────────────┘  │    country    │
└────────────────────────────┬───────┘      │  id · name    │
                             │              └───────────────┘
         sub_category_id FK  │
                             ▼
┌───────────────────────────────────────┐
│          master_sub_category          │
│  id · category_id · name · is_active  │
└────────────────┬──────────────────────┘
                 │ FK
                 ▼
        ┌─────────────────────┐
        │   master_category   │
        │  id · name · ...    │
        └─────────────────────┘

post_processed_articles
         │ 1:1  SET NULL
         ▼
┌────────────────────────────────────────────────┐
│                  final_articles                │
│  id · post_processed_article_id(UNIQUE)        │
│  title · description · image_url               │
│  reference_urls(TEXT[]) · rank_score(FLOAT)    │
│  created_at                                    │
└────────────────────────────────────────────────┘

┌───────────────────────────────────────────────┐
│              ai_provider_configs              │
│  id · name · provider · model · api_key       │
│  base_url · is_active(partial UNIQUE)         │
└───────────────────────────────────────────────┘
```

---

## 8. AI Pipeline Deep Dive

### Provider selection order

```
IngestionService._load_ai_provider()
  │
  ├─ 1. ai_provider_repo.get_active()
  │       SELECT FROM ai_provider_configs WHERE is_active = true
  │       → if found: provider_factory.create_from_config(config)
  │
  ├─ 2. settings.GEMINI_API_KEY is set?
  │       → GeminiMultimodalLangGraphProvider("gemini-2.0-flash")  ← recommended
  │
  ├─ 3. settings.ANTHROPIC_API_KEY is set?
  │       → AnthropicProvider("claude-haiku-4-5-20251001")
  │
  └─ 4. None → articles dropped at AI stage, logged as warnings
```

### Stage 1 prompt output contract

```json
{
  "title": "string — extracted verbatim",
  "url": "string",
  "description": "string | null — 1–3 sentences, HTML-cleaned",
  "image_url": "string | null",
  "published_at": "ISO 8601 string | null",
  "is_crime": true,
  "sub_category_ids": [1, 3],
  "sub_category": "murder",
  "category": "Violent Crime",
  "location": "Mumbai, Maharashtra",
  "region": "West",
  "importance_score": 7
}
```

### Stage 2 prompt output contract

```json
{
  "rewritten_title": "string — rephrased, max 15 words",
  "rewritten_description": "string — ~100 words, rephrased",
  "reference_urls": ["https://...", "https://..."],
  "imp_score": 72
}
```

### Why two stages?

Stage 1 is fast and cheap — it extracts and classifies. Running it on all articles (including non-crime) at low cost lets us filter aggressively.

Stage 2 is slower and more expensive — it rewrites, searches the web, and scores. Running it only on the crime-relevant subset (typically 10–30% of all ingested articles) keeps costs manageable.

---

## 9. Background Scheduler

```
app startup (lifespan)
  └── start_scheduler()
        │
        ├── Job 1: ingestion_all_sources
        │     trigger: interval, every INGEST_INTERVAL_MINUTES minutes
        │     max_instances: 1  (no pile-up if previous run is still going)
        │
        └── Job 2: publish_final_feed
              trigger: interval, every PUBLISH_INTERVAL_MINUTES minutes
                        + PUBLISH_OFFSET_SECONDS seconds delay
              max_instances: 1
              (30s offset ensures Stage 2 data is written before ranking runs)
```

---

## 10. Configuration Reference

All values set in `.env`. Sensible defaults shown — only `DATABASE_URL` is required.

```
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname   # REQUIRED

GEMINI_API_KEY=AIzaSy...          # recommended — activates GeminiMultimodal provider
ANTHROPIC_API_KEY=sk-ant-...      # fallback if no GEMINI_API_KEY
DEBUG=false                       # true logs all SQL queries

AI_REQUESTS_PER_MINUTE=5          # free Gemini tier limit
AI_RETRY_ATTEMPTS=3
AI_RETRY_DELAY_SECONDS=15.0

INGEST_INTERVAL_MINUTES=5
PUBLISH_INTERVAL_MINUTES=5
PUBLISH_OFFSET_SECONDS=30
FEED_TOP_N=20

DUCKDUCKGO_TIMEOUT_SECONDS=10.0

DECAY_FRESH=1.00    # < 6h
DECAY_RECENT=0.75   # 6–24h
DECAY_DAY=0.50      # 1–3d
DECAY_WEEK=0.25     # 3–7d
DECAY_OLD=0.10      # > 7d
```

---

## 11. Development Commands

```bash
# Install dependencies
uv sync

# Run dev server with auto-reload
.venv/bin/uvicorn app.main:app --reload

# Apply all pending migrations
.venv/bin/alembic upgrade head

# Roll back one migration
.venv/bin/alembic downgrade -1

# Check current migration state
.venv/bin/alembic current

# View migration history
.venv/bin/alembic history

# Create a new migration after changing models
.venv/bin/alembic revision --autogenerate -m "describe_change"
```

**End-to-end manual test:**

```bash
# 1. Start server
.venv/bin/uvicorn app.main:app --reload

# 2. Register a Gemini AI provider
curl -X POST http://localhost:8000/ai-providers/ \
  -H "Content-Type: application/json" \
  -d '{"name":"Gemini","provider":"gemini_multimodal","model":"gemini-2.0-flash","api_key":"AIzaSy..."}'
# → {"id":1, ...}

# 3. Activate it
curl -X PATCH http://localhost:8000/ai-providers/1/activate

# 4. Add a crime news source
curl -X POST http://localhost:8000/sources/ \
  -H "Content-Type: application/json" \
  -d '{"name":"India News","type":"rss","url":"https://...crime-feed-url.../rss"}'
# → {"id":2, ...}

# 5. Trigger ingestion immediately
curl -X POST http://localhost:8000/ingest/ \
  -H "Content-Type: application/json" \
  -d '{"source_id": 2}'
# → {"source_id":2,"source_type":"rss","ingested":14}

# 6. Trigger publishing
curl -X POST "http://localhost:8000/final-articles/publish"

# 7. Read the ranked feed
curl "http://localhost:8000/final-articles/?limit=10"

# 8. Browse all endpoints
open http://localhost:8000/docs
```
