# Crime News API — Architecture & Operations Guide

> **Who this document is for:** Anyone — beginner or experienced — who wants to understand
> exactly what this app does, why each file exists, how data flows from a news RSS feed to a
> ranked public API, and how to run, configure, and extend the system.

---

## Table of Contents

1. [What This App Does (Plain English)](#1-what-this-app-does-plain-english)
2. [Quick Glossary — Terms Used Everywhere](#2-quick-glossary--terms-used-everywhere)
3. [How to Run the App](#3-how-to-run-the-app)
4. [Tech Stack — What Each Library Does](#4-tech-stack--what-each-library-does)
5. [Project Structure](#5-project-structure)
6. [File-by-File Logic — What It Does and WHY It Exists](#6-file-by-file-logic--what-it-does-and-why-it-exists)
7. [Database Schema — The 9 Tables Explained](#7-database-schema--the-9-tables-explained)
8. [End-to-End Pipeline Flow — Step by Step](#8-end-to-end-pipeline-flow--step-by-step)
9. [AI Provider System](#9-ai-provider-system)
10. [Google Search Reference URL Enrichment — Design Deep Dive](#10-google-search-reference-url-enrichment--design-deep-dive)
11. [Scheduler Design — Why 3 Steps, Not 3 Jobs](#11-scheduler-design--why-3-steps-not-3-jobs)
12. [Request Flows — End to End](#12-request-flows--end-to-end)
13. [API Reference](#13-api-reference)
14. [Configuration Reference](#14-configuration-reference)
15. [Adding a New AI Provider](#15-adding-a-new-ai-provider)

---

## 1. What This App Does (Plain English)

Imagine you want a constantly-updated ranked list of the most important crime news stories
happening in India right now. This app does that automatically, 24/7, without human involvement.

### The big picture

```
Internet News Sources  →  This App  →  Ranked API Feed  →  Your Frontend / Mobile App
  (RSS feeds, REST)         (AI)         (final_articles)
```

### What happens every 5 minutes (automatically)

**Step 1 — Fetch:** The app downloads articles from all configured news sources (NDTV, Times of
India RSS feeds, etc.).

**Step 2 — Deduplicate:** Each article gets a unique fingerprint (SHA-256 hash). If the same
article was already fetched before, it is silently ignored.

**Step 3 — Pre-filter (keyword check):** Before spending any AI budget, the app checks if the
article even mentions crime-related words like "murder", "arrested", "fraud", etc. ~70% of
articles fail this check and are discarded instantly — no AI call needed.

**Step 4 — AI Analysis (the clever part):** The remaining articles are sent to an AI (Ollama
locally, or Gemini/Claude/GPT in the cloud). In a *single* AI call per article, the AI:
- Decides: is this actually a crime story? (if not → discard)
- Rewrites the title and description in its own words (avoids copyright issues)
- Assigns an importance score 1–100 (a kidnapping of a child scores higher than minor theft)
- Labels the crime type (murder, fraud, terrorism, cybercrime, etc.)
- Identifies the Indian state where it happened

**Step 5 — Search Enrichment:** After ingestion, the app runs Google Custom Search to find
3 related news URLs for each article. This helps the frontend show "Read more" links. Each
article is searched **exactly once** — no repeat searches waste your 100 free queries/day.

**Step 6 — Ranking & Publishing:** The top-20 articles by importance score are selected. A
time-decay formula reduces the score of older articles (fresh news scores higher). The result
is written to the `final_articles` table — the feed your frontend reads.

### What the API exposes

- **`/final-articles/`** — The ranked feed. This is what your app calls.
- **`/ingest/`** — Manually trigger a pipeline run.
- **`/ai-providers/`** — Switch AI providers without restarting the server.
- **`/raw-ingestion/`** — Debug: see every article that was ever fetched.
- **`/sources/`** — Manage which news sources to follow.

---

## 2. Quick Glossary — Terms Used Everywhere

| Term | Plain meaning |
|------|--------------|
| **Pipeline** | The chain of steps an article goes through: fetch → AI → enrich → publish |
| **Raw ingestion** | The very first storage of an article, before any processing |
| **Filtered article** | An article that passed the AI crime check (Stage 1 output) |
| **Post-processed article** | A filtered article after enrichment with reference URLs (Stage 2 output) |
| **Final article** | A ranked article in the public feed (terminal stage) |
| **imp_score** | AI-assigned importance score 1–100 |
| **rank_score** | `imp_score × time_decay_factor` — what the frontend sorts by |
| **reference_urls** | Google Search results for an article — "related news" links |
| **Sentinel value** | A special value `[]` stored in `reference_urls` meaning "searched but nothing found" |
| **Upsert** | INSERT if new, UPDATE if already exists — prevents duplicate rows |
| **Content hash** | SHA-256 fingerprint of an article — the deduplication key |
| **Provider** | An AI service (Ollama, Gemini, Claude, GPT) configured to process articles |
| **Scheduler** | APScheduler — runs background jobs on a timer without any user request |
| **Rate limiter** | Code that throttles API calls to stay under per-minute limits |
| **Repository** | A Python class that handles all database reads/writes for one table |
| **Schema** | A Pydantic class that defines what data looks like going in/out of the API |
| **ORM Model** | A Python class that represents a database table (SQLAlchemy) |
| **Dependency injection** | FastAPI automatically wires database connections into route handlers |
| **Alembic** | Tool that manages database schema changes (like Git, but for SQL tables) |

---

## 3. How to Run the App

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

> **Why `uv sync`?** `uv` reads `pyproject.toml` and `uv.lock` to install the exact same
> dependency versions on every machine. No "works on my machine" problems.

### Step 2 — Configure environment

Create a `.env` file in the project root:

```env
# REQUIRED: Your PostgreSQL database connection string.
# IMPORTANT: Must use postgresql+asyncpg:// (not postgresql://)
# The +asyncpg part tells SQLAlchemy to use the async PostgreSQL driver.
DATABASE_URL=postgresql+asyncpg://user:password@host:port/dbname

# CHOOSE ONE AI PROVIDER:

# Option A — Local Ollama (runs on your own GPU, no API key, works offline)
OLLAMA_MODEL=dengcao/Qwen3-30B-A3B-Instruct-2507:latest
# OLLAMA_URL=http://localhost:11434/v1   # this is already the default

# Option B — Google Gemini (cloud, free tier available)
# GEMINI_API_KEY=AIzaSy...

# Option C — Anthropic Claude (cloud, paid)
# ANTHROPIC_API_KEY=sk-ant-...

# OPTIONAL: Google Search for "related news" links (100 queries/day free tier)
# Without these, the app still works — articles just won't have reference_urls.
# GOOGLE_SEARCH_API_KEY=AIzaSy...
# GOOGLE_SEARCH_ENGINE_ID=abc123...
```

### Step 3 — Run database migrations

```bash
.venv/bin/alembic upgrade head
```

> **What this does:** Creates all 9 database tables if they don't exist yet. Safe to run
> multiple times — Alembic tracks which migrations have already been applied.

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

### Step 6 — Trigger manual ingest (or wait up to 5 minutes)

```bash
# Trigger ingest → enrich → publish immediately for source ID 1
curl -X POST http://localhost:8000/ingest/ \
  -H "Content-Type: application/json" \
  -d '{"source_id": 1}'

# Or force a re-publish of already-ingested articles (no new Google Search calls)
curl -X POST "http://localhost:8000/final-articles/publish?top_n=20"
```

### Step 7 — Read the feed

```bash
curl http://localhost:8000/final-articles/

# Debug: see raw pipeline inbox
curl "http://localhost:8000/raw-ingestion/?status=filtered_out&limit=50"
```

### Interactive docs

```
http://localhost:8000/docs    ← Swagger UI (try every endpoint in browser)
http://localhost:8000/redoc   ← ReDoc (better for reading)
http://localhost:8000/health  ← {"status": "ok"}
```

---

## 4. Tech Stack — What Each Library Does

| Layer | Technology | Why this specific tool? |
|-------|-----------|------------------------|
| Web framework | **FastAPI** | Async, auto-generates Swagger docs, built-in Pydantic validation |
| ORM | **SQLAlchemy 2.0 async** | Typed Python classes map to DB tables; handles async sessions |
| DB driver | **asyncpg** | Async-native PostgreSQL driver — required for non-blocking DB calls |
| Database | **PostgreSQL** | Supports JSONB, arrays, GIN indexes — needed for our complex article data |
| Migrations | **Alembic** | Versioned, reversible schema changes; auto-detects what changed |
| Scheduler | **APScheduler** | Runs background jobs (ingestion, publishing) on timers in the same process |
| Validation | **Pydantic v2** | Validates request/response data and AI JSON output with type safety |
| Settings | **pydantic-settings** | Loads `.env` file and validates every setting has the right type |
| RSS parsing | **feedparser** | Handles RSS/Atom, fixes malformed XML — battle-tested for real-world feeds |
| HTTP client | **httpx** | Async HTTP — used for REST source fetching and Google Search API calls |
| AI — local | **Ollama** | Run LLMs on your own GPU; exposes OpenAI-compatible API |
| AI — cloud | **Anthropic SDK** | Official Anthropic Python SDK for Claude models |
| AI — cloud | **OpenAI SDK** | Works for OpenAI GPT *and* any OpenAI-compatible server (Ollama, vLLM) |
| AI — cloud | **langchain-google-genai** | Gemini models with structured output (returns Pydantic object, not text) |
| AI — agents | **LangGraph** | Graph-based pipeline for Gemini: extract → classify nodes |
| ASGI server | **uvicorn** | Production-grade async Python web server |

---

## 5. Project Structure

```
news-app-server/
├── .env                                       # Secret config (never commit!)
├── .venv/                                     # Python virtual environment (uv managed)
├── alembic.ini                                # Alembic migration settings
├── pyproject.toml                             # Project dependencies + metadata
├── uv.lock                                    # Locked exact dependency versions
├── ARCHITECTURE.md                            # This document
│
├── migrations/
│   ├── env.py                                 # Async-aware Alembic runner
│   └── versions/                              # One .py file per schema change
│
└── app/
    ├── main.py                                # App entry point: wires everything together
    │
    ├── core/                                  # Shared infrastructure (not business logic)
    │   ├── config.py                          # All settings from .env — single source of truth
    │   ├── database.py                        # DB engine and session factory
    │   ├── deps.py                            # Dependency injection wiring for FastAPI
    │   └── enums.py                           # Crime category name→ID lookup tables
    │
    ├── models/                                # SQLAlchemy ORM (Python class = DB table)
    │   ├── base.py                            # Shared DeclarativeBase all models inherit from
    │   ├── source.py                          # news_sources table
    │   ├── raw_event.py                       # raw_ingestion table (pipeline inbox)
    │   ├── filter_article.py                  # filtered_articles (AI Stage 1 output)
    │   ├── post_processed_article.py          # post_processed_articles (enriched, with reference_urls)
    │   ├── final_article.py                   # final_articles (public ranked feed)
    │   ├── ai_provider.py                     # ai_provider_configs + provider metadata constants
    │   ├── category.py                        # master_category + master_sub_category (reference data)
    │   └── location.py                        # country + state (36 Indian states/UTs)
    │
    ├── repositories/                          # Data access layer — all DB reads/writes live here
    │   ├── source_repo.py
    │   ├── raw_ingestion_repo.py              # store_batch, mark_*, get_all, count
    │   ├── filter_article_repo.py             # insert_batch (upsert on main_url)
    │   ├── post_processed_article_repo.py     # insert_batch, update_reference_urls,
    │   │                                      # get_without_reference_urls, mark_reference_urls_searched
    │   ├── final_article_repo.py              # upsert_batch, get_feed (ranked)
    │   ├── ai_provider_repo.py                # get_active, activate, deactivate_all
    │   ├── master_data_repo.py                # read-only: categories, sub-categories, states
    │   └── article_repo.py                    # Alias → PostProcessedArticleRepository
    │
    ├── schemas/                               # Pydantic: defines API request/response shapes
    │   ├── source_schema.py
    │   ├── article_schema.py                  # FilterArticle, PostProcessed, RawIngestion responses
    │   ├── final_article_schema.py            # Public feed response (includes reference_urls)
    │   ├── ai_provider_schema.py              # AI provider CRUD (validates provider type)
    │   └── master_data_schema.py
    │
    ├── api/                                   # HTTP route handlers — one file per resource
    │   ├── routes_sources.py                  # /sources/
    │   ├── routes_ingest.py                   # /ingest/
    │   ├── routes_filter_articles.py          # /filter-articles/
    │   ├── routes_post_processed.py           # /post-processed/
    │   ├── routes_final_articles.py           # /final-articles/ + /publish
    │   ├── routes_raw_ingestion.py            # /raw-ingestion/ (debug monitoring)
    │   ├── routes_ai_providers.py             # /ai-providers/
    │   └── routes_master_data.py              # /master/
    │
    └── services/                              # Business logic — the "how it works"
        ├── ingestion_service.py               # Full pipeline: fetch → AI → DB write
        ├── publishing_service.py              # Ranking + feed upsert (reads pre-enriched data)
        ├── search_enrichment_service.py       # Google Search — once per article, quota-safe
        ├── google_search_service.py           # Low-level Google Custom Search API client
        ├── scheduler.py                       # APScheduler: registers jobs, chains the 3 steps
        ├── source_normalizer.py               # Converts raw feedparser objects to plain dicts
        ├── fetchers/
        │   ├── rss_fetcher.py                 # RSS/Atom feed downloader (feedparser in thread)
        │   └── rest_fetcher.py                # REST API fetcher (httpx async)
        └── normalization/
            ├── ai_processor.py                # Picks AI provider from env vars as fallback
            ├── provider_factory.py            # Creates + caches provider SDK clients
            ├── resolvers.py                   # Converts AI text labels → database FK IDs
            ├── canonical_validator.py         # Cleans/validates URLs before DB write
            └── providers/
                ├── base.py                    # Shared: prompt, JSON parser, output schema
                ├── openai_prov.py             # OpenAI, Ollama, vLLM, custom servers
                ├── anthropic_prov.py          # Anthropic Claude
                ├── gemini_langgraph_prov.py   # Gemini (text response, parsed manually)
                └── gemini_multimodal_prov.py  # Gemini (structured output via LangGraph)
```

---

## 6. File-by-File Logic — What It Does and WHY It Exists

> For every file: **What** it does + **Why** it was written this way.

---

### `app/main.py`
**What:** FastAPI application factory and startup coordinator.
**Why:** Every FastAPI app needs one central file that creates the `app` instance, registers all
the URL routes, and handles startup/shutdown. Keeping this thin (no business logic) makes it
easy to see the full picture at a glance.

- Creates `FastAPI()` with title, version, description.
- Registers all 8 routers with their URL prefixes and Swagger tags.
- Adds `CORSMiddleware` with `allow_origins=["*"]` — lets any frontend domain call the API.
- Uses `@asynccontextmanager lifespan` to call `start_scheduler()` on startup and
  `stop_scheduler()` on shutdown. This ensures scheduler jobs run only while the server is alive.
- Exposes `/health` endpoint and `/` redirect to `/docs`.

---

### `app/core/config.py`
**What:** Single source of truth for all runtime configuration.
**Why:** If settings were scattered across multiple files, changing a value (like a URL or
timeout) would require hunting through the codebase. Centralising everything in one `Settings`
class means: one place to look, and Pydantic validates types on startup (bad config = server
won't start, not a subtle runtime bug).

- Uses `pydantic-settings BaseSettings` — reads from `.env` file AND environment variables.
- Every setting has a Python type annotation — invalid values raise a `ValidationError` at startup.
- `settings` is a **module-level singleton** — imported everywhere as
  `from app.core.config import settings`.
- Grouped settings:
  - **Database:** `DATABASE_URL` (required)
  - **Ollama (local GPU):** `OLLAMA_REQUESTS_PER_MINUTE=60`, `OLLAMA_CONCURRENCY=1`,
    `OLLAMA_BATCH_SIZE=10`, `OLLAMA_BATCH_COOLDOWN_SECONDS=15`
  - **Cloud APIs (conservative limits):** `CLOUD_REQUESTS_PER_MINUTE=3`, `CLOUD_MAX_ITEMS_PER_RUN=5`
  - **Google Search:** `GOOGLE_SEARCH_API_KEY`, `GOOGLE_SEARCH_ENGINE_ID`,
    `GOOGLE_SEARCH_RESULTS_PER_ARTICLE=3`, `GOOGLE_SEARCH_DELAY_SECONDS=1.0`,
    `GOOGLE_SEARCH_MAX_PER_RUN=10`
  - **Time-decay scoring:** `DECAY_FRESH=1.00`, `DECAY_RECENT=0.75`, `DECAY_DAY=0.50`,
    `DECAY_WEEK=0.25`, `DECAY_OLD=0.10`
  - **Scheduler:** `INGEST_INTERVAL_MINUTES=5`, `PUBLISH_INTERVAL_MINUTES=5`,
    `PUBLISH_OFFSET_SECONDS=30`

---

### `app/core/database.py`
**What:** Async database engine and session management.
**Why:** Creating a new database connection for every query is expensive. This file creates a
single `AsyncEngine` (connection pool) shared across the app, and an `async_sessionmaker` that
produces one `AsyncSession` per request. The session is your "unit of work" — all reads and
writes in a request happen through it, and it's closed automatically after the response.

- Creates one `AsyncEngine` using `create_async_engine(DATABASE_URL, ...)`.
- `AsyncSessionLocal` session factory used by both HTTP routes and the scheduler.
- `get_db()` FastAPI dependency — yields one `AsyncSession` per request, auto-closes it.

---

### `app/core/deps.py`
**What:** FastAPI dependency injection wiring.
**Why:** Route handlers need repositories (to read/write DB). Instead of each handler creating
its own DB session and repo instances (duplicated boilerplate), FastAPI's `Depends` system
builds them automatically and passes them in. This file is the "wiring diagram" — pure glue,
zero business logic.

- Each `get_*_repo()` function is a FastAPI `Depends` — called per request to build a repo
  instance from the current `AsyncSession`.
- `get_ingestion_service()` wires together all 5 repositories + raw DB session.
- Nothing here contains business logic; it only instantiates and wires objects.

---

### `app/core/enums.py`
**What:** Static lookup tables for crime categories.
**Why:** The AI outputs category names as text strings like `"murder"`. We need to convert these
to integer database IDs. Doing a DB query for every article would be slow and wasteful since the
category list never changes. Enums stored in memory are instant lookups.

- `SubCategoryEnum` maps string labels (e.g. `"murder"`) to integer DB IDs.
- `CategoryEnum` maps parent category names to integer IDs.
- `SUB_TO_CATEGORY` dict maps sub-category ID → parent category ID.
- Used by `CategoryResolver` to avoid DB queries for every article.

---

### `app/models/base.py`
**What:** SQLAlchemy `DeclarativeBase` shared by all ORM models.
**Why:** All 9 ORM models must share the same `metadata` object for Alembic `autogenerate` to
see them all when creating migrations. One shared `Base` class guarantees this.

---

### `app/models/source.py`
**What:** ORM for `news_sources` table — defines where to fetch news from.

- Columns: `id`, `name`, `type` (rss/rest), `url` (unique), `config` (JSONB), `is_active`, `created_at`.
- `config` JSONB allows per-source custom headers, auth tokens, or pagination parameters.
- `is_active` flag lets you pause a source without deleting it.

---

### `app/models/raw_event.py`
**What:** ORM for `raw_ingestion` table — the pipeline inbox.
**Why:** Storing every article before processing gives you a complete audit trail. You can
always answer "did we fetch this article?" and "why was it rejected?". Also critical for
deduplication: the `content_hash` unique constraint at the DB level prevents double-processing
even if the scheduler fires twice or the app crashes mid-run.

- Every article ever fetched lands here first, before any AI processing.
- `content_hash` (SHA-256 of `source_id + json(payload)`) = **global dedup key**.
- `status` lifecycle: `pending` → `filtered` | `filtered_out` | `failed`.
- `normalized_by` records which AI model processed the article (audit trail).
- `raw_payload` (JSONB) stores the original feed data exactly as received.

---

### `app/models/filter_article.py`
**What:** ORM for `filtered_articles` — AI Stage 1 output.
**Why:** Separating AI-confirmed crime articles into their own table makes it easy to query
"all articles the AI accepted" without touching the raw inbox. The `main_url` upsert key also
handles the case where two different sources report the same story — only one row is stored.

- `main_url` = upsert key — same URL from two sources → only one row.
- Stores both original (`title`, `description`) and AI-rewritten versions.
- `sub_category_ids` and `category_ids` = JSONB integer arrays (GIN indexed for fast filtering).
- `location_state_id` FK → `state` table.

---

### `app/models/post_processed_article.py`
**What:** ORM for `post_processed_articles` — the enrichment staging table.
**Why:** This table is the "staging area" between AI classification and the public feed. It holds
all the data from `filtered_articles` plus the `reference_urls` field that gets populated by
Google Search. Keeping this separate from `final_articles` means the search enrichment step can
update `reference_urls` without touching the ranked public feed.

- Mirror of `filtered_articles` + `reference_urls` (PostgreSQL `ARRAY(Text)`).
- `filter_article_id` (unique FK) — one-to-one link back to the filtered article.
- `reference_urls` states:
  - `NULL` — never searched (eligible for enrichment)
  - `[]` — searched, no results (sentinel — never searched again)
  - `[url1, url2, ...]` — enriched successfully (never searched again)

---

### `app/models/final_article.py`
**What:** ORM for `final_articles` — the public ranked feed.
**Why:** The frontend only needs the top-N ranked articles. Keeping them in a small separate
table (instead of filtering all `post_processed_articles` every API call) makes reads fast and
simple. The upsert design means re-ranking the same article updates its score without creating
duplicate rows.

- Terminal stage of the pipeline — the only table the frontend reads.
- `post_processed_article_id` (unique FK) = upsert key.
- `rank_score = imp_score × time_decay_factor` — recomputed every publish cycle.
- `reference_urls` (ARRAY) carries Google Search links for the frontend.

---

### `app/models/ai_provider.py`
**What:** ORM for `ai_provider_configs` + provider metadata constants.
**Why:** Storing AI provider config in the DB (rather than only env vars) means you can switch
from Ollama to Gemini *at runtime* via an API call — no server restart. The DB partial unique
index `WHERE is_active = true` enforces that at most one provider is active at any time.

- `SUPPORTED_PROVIDERS` frozenset — validated on POST `/ai-providers/`.
- `PROVIDER_BASE_URLS` — auto-fills `base_url` for `ollama` and `gemini`.
- `PROVIDER_DEFAULT_MODELS` — suggested model names shown in Swagger.
- Partial unique index: `WHERE is_active = true` enforces single active provider.

---

### `app/models/category.py` and `app/models/location.py`
**What:** Read-only reference data (categories, sub-categories, Indian states).
**Why:** The AI needs to assign a category label and a location. These tables are the
"vocabulary" the AI is constrained to. Seeded once by migrations — never written to at runtime.

- 8 crime categories (Violent Crime, Economic Crime, etc.) × 10 sub-categories.
- 36 Indian states + Union Territories.

---

### `app/repositories/raw_ingestion_repo.py`
**What:** All DB operations for the `raw_ingestion` table.
**Why:** Repositories isolate database code from business logic. If you switch from PostgreSQL
to another DB, you only change this file — the service layer stays the same.

Key methods and why each exists:
- `compute_content_hash(source_id, raw_payload)` — SHA-256 fingerprint. **Why:** Consistent
  dedup key computed identically on every call.
- `store_batch(source_id, hash_raw_pairs)` — bulk INSERT with `ON CONFLICT DO NOTHING`.
  **Why:** One SQL statement for many articles is far faster than individual INSERTs.
  Returns `unprocessed_hashes` including "stuck pending" rows from crashed past runs, so
  they get retried.
- `mark_filtered / mark_filtered_out / mark_failed` — bulk UPDATE. **Why:** Audit trail;
  lets you query "what did the pipeline do with this article?"
- `get_all(limit, offset, status, source_id)` — paginated query for the monitoring endpoint.
- `count(status, source_id)` — total count for pagination metadata.
- `get_by_id(row_id)` — single row with full `raw_payload` JSON for debugging.

---

### `app/repositories/filter_article_repo.py`
**What:** DB operations for `filtered_articles`.

- `insert_batch(articles, hash_to_raw_id)` — upserts on `main_url`.
  **Why:** The same news story from two different RSS feeds should create only one row.
  Returns `url_to_filter_id` dict so `post_processed_repo` can set the FK.

---

### `app/repositories/post_processed_article_repo.py`
**What:** DB operations for `post_processed_articles`.
**Why this file has extra methods:** This table is the hub of the enrichment system. It needs
specialized methods to safely manage the `reference_urls` field without re-processing articles.

Key methods:
- `insert_batch(articles, url_to_filter_id)` — upserts on `filter_article_id`.
- `get_top_by_imp_score(limit)` — `ORDER BY imp_score DESC WHERE imp_score IS NOT NULL`.
  **Why:** `PublishingService` needs the highest-scored articles to publish.
- `update_reference_urls(article_id, urls)` — sets `reference_urls = [url1, url2, ...]`.
  **Why:** Called by `SearchEnrichmentService` after a successful Google Search response.
- `get_without_reference_urls(limit)` — `WHERE reference_urls IS NULL ORDER BY imp_score DESC`.
  **Why:** The enrichment query. Returns articles that have **never** been searched.
  Articles with `[]` (the sentinel) are *excluded* — they have been searched before.
  The `ORDER BY imp_score DESC` ensures the most important articles are enriched first
  when the per-run cap is hit.
- `mark_reference_urls_searched(article_id)` — sets `reference_urls = []` (empty list).
  **Why:** Writes the "searched, no results" sentinel. Prevents this article from ever
  appearing in `get_without_reference_urls` again — no wasted API calls on future cycles.

---

### `app/repositories/final_article_repo.py`
**What:** DB operations for `final_articles`.

- `upsert_batch(rows)` — `ON CONFLICT (post_processed_article_id) DO UPDATE SET rank_score, ...`.
  **Why:** Same article re-ranked every cycle without creating duplicate rows.
- `get_feed(limit, offset, sub_category_id, q)` — JOINs `post_processed_articles` for
  sub-category filtering; full-text search on `title ILIKE '%q%'`; ordered by `rank_score DESC`.
  **Why:** Single optimised query for the frontend's primary endpoint.

---

### `app/repositories/ai_provider_repo.py`
**What:** CRUD for `ai_provider_configs`.

- `get_active()` — `SELECT WHERE is_active = true LIMIT 1`.
  **Why:** Called at the start of every ingest run to load the current AI config.
- `activate(provider_id)` — two SQL statements: set all rows `is_active=false`, then set
  target `true`. **Why:** Atomic switch — never two active providers simultaneously.
- `deactivate_all()` — falls back to env-var provider resolution.

---

### `app/repositories/master_data_repo.py`
**What:** Read-only queries for categories, sub-categories, states.
**Why:** Simple `SELECT *` wrappers used only by the `/master/` endpoints for the frontend
to know which filter options to display.

---

### `app/schemas/` (all schema files)
**What:** Pydantic classes defining what API request and response bodies look like.
**Why:** Without schemas, any malformed request would cause cryptic internal errors. Pydantic
validates and coerces data at the boundary — before it touches business logic. Also auto-generates
the Swagger docs.

- `article_schema.py` — `FilterArticleResponse`, `PostProcessedArticleResponse`,
  `RawIngestionResponse` (includes `raw_payload: dict[str, Any]` for debugging).
- `final_article_schema.py` — `FinalArticleResponse` includes `reference_urls: list[str] | None`.
- `ai_provider_schema.py` — `AIProviderCreate` validates `provider` is a known type.
- All use `model_config = {"from_attributes": True}` — allows building from SQLAlchemy ORM objects.

---

### `app/api/routes_*.py` (all route files)
**What:** HTTP endpoint handlers for each resource.
**Why one file per resource?** Keeps each file small and focused. Routes for `/sources/` have
nothing to do with routes for `/final-articles/` — separating them means you can find and
change one without touching the other.

- `routes_sources.py` — CRUD: GET list, POST create, GET by ID, PATCH update, DELETE.
- `routes_ingest.py` — `POST /ingest/` triggers `IngestionService.ingest(source)` immediately.
- `routes_raw_ingestion.py` — read-only monitoring. Shows what was fetched, what was rejected,
  and why. Critical for debugging "why did article X not appear in the feed?"
- `routes_filter_articles.py` — read-only view of AI Stage 1 output.
- `routes_post_processed.py` — shows `imp_score` and `reference_urls` to verify enrichment works.
- `routes_final_articles.py` — the public ranked feed + `POST /publish` manual trigger.
  **Important:** `POST /publish` runs `PublishingService.publish()` only — it reads
  already-enriched `reference_urls` from DB and does **not** call Google Search.
  To also run enrichment, trigger via `POST /ingest/`.
- `routes_ai_providers.py` — POST register, PATCH activate, DELETE. Switching a provider
  takes effect on the **next** ingest run — no restart needed.
- `routes_master_data.py` — `GET /master/categories`, `/sub-categories`, `/states`.

---

### `app/services/scheduler.py`
**What:** Registers recurring background jobs and chains the 3 pipeline steps.
**Why this design:** See [Section 11](#11-scheduler-design--why-3-steps-not-3-jobs) for a
full explanation of the scheduling architecture.

Key functions:

**`start_scheduler()`** — called once at app startup. Registers two APScheduler jobs:
1. `run_ingestion_for_all_active_sources` — fires every `INGEST_INTERVAL_MINUTES` (default 5).
2. `run_publishing` — fires every `PUBLISH_INTERVAL_MINUTES` with a `PUBLISH_OFFSET_SECONDS=30`
   delay so the scheduled publish always runs after scheduled ingestion.

Both jobs use `max_instances=1` — if a run is still in progress when the next trigger fires,
the new run is **skipped** rather than creating overlapping concurrent executions.

**`run_ingestion_for_all_active_sources()`** — the main ingestion job:
1. Loads all active sources.
2. Runs `_ingest_one_source(source)` for each source concurrently via `asyncio.gather()`.
3. **If any source produced new articles** (`ok > 0`): immediately calls
   `run_search_enrichment()` then `run_publishing()` — so new articles appear in the feed
   without waiting up to 5 minutes for the next scheduled publish cycle.

**`_ingest_one_source(source)`** — creates its own DB session and `IngestionService`
for one source. **Why a separate function?** Each source gets an isolated DB session so a
failure in one source doesn't affect others.

**`run_search_enrichment()`** — creates a `SearchEnrichmentService` and calls `.enrich()`.
Not an APScheduler job — called inline between ingestion and publishing.

**`run_publishing()`** — creates a `PublishingService` and calls `.publish()`.

**`stop_scheduler()`** — called on app shutdown, cleanly stops all background jobs.

---

### `app/services/ingestion_service.py`
**What:** Orchestrates the complete article lifecycle from fetch to DB write.
**Why so many steps?** Each step handles one specific concern. The sequence is strict:
dedup must happen before AI (no point calling AI on an article we already have), keyword
pre-filter must happen before AI (saves quota), FK resolution must happen after AI
(categories/location come from AI output).

**`ingest(source)` — 13 steps:**

1. `_fetch_items(source)` → calls `RSSFetcher` or `RestFetcher` by source type.
2. `_load_ai_provider()` → DB config first, env fallback second. Returns `(provider, type)`.
   `provider_type` determines rate limits and item cap.
3. **Cap** to `max_items` (Ollama: 50, cloud: 5, default: 10). **Why:** Prevents runaway
   API costs on large feeds.
4. `compute_content_hash()` for every article — SHA-256 once, reused everywhere.
5. `raw_repo.store_batch()` → INSERT OR IGNORE. Returns only new + stuck-pending hashes.
   **Why stuck-pending?** If the app crashed mid-run last time, some rows are stuck in
   `pending` status. This recovers them on the next cycle.
6. `_has_crime_keywords(raw)` — checks ~50 crime terms in title/summary/description.
   **Why:** Calling AI on "Prime Minister visits school" wastes money. Keywords filter
   ~70% of articles before any AI call.
7. `_get_limiter_for(provider_type)` → shared `(_RateLimiter, asyncio.Semaphore)`.
   **Why shared?** Process-level singletons ensure concurrent source tasks share the
   same quota — two sources can't both max out the rate limit independently.
8. **Ollama batch loop** — for GPU safety: `OLLAMA_BATCH_SIZE` articles, then
   `OLLAMA_BATCH_COOLDOWN_SECONDS` pause. **Why:** Continuous GPU load causes thermal
   throttling. Short cooldowns keep the GPU healthy on a single card like RTX 3060.
9. `asyncio.gather()` with `process_with_semaphore()` — concurrency bounded by semaphore,
   rate bounded by `_RateLimiter.wait()`. Each call: `ai_provider.process(raw, source_type)`.
10. **Bucket results:** crime / filtered_out / failed.
11. `load_resolvers(db)` → loads `CategoryResolver` (enum, zero queries) and
    `LocationResolver` (one DB query for 36 state rows). Resolves AI text → FK integers.
12. `filter_article_repo.insert_batch()` then `post_processed_repo.insert_batch()`.
13. `_update_raw_statuses()` → marks every raw row with its final status.

**Retry logic** in `_call_with_retry()`: on rate-limit errors (HTTP 429, "quota",
"resource_exhausted"), retries with exponential back-off: `delay × 2^attempt`.
Non-rate-limit errors fail immediately. **Why:** Cloud AI APIs occasionally throttle
even under quota — transient retries recover from blips without failing the whole batch.

---

### `app/services/publishing_service.py`
**What:** Selects top articles, computes rank scores, upserts the public feed.
**Why does PublishingService NOT call Google Search?** Search enrichment was deliberately
moved into a separate `SearchEnrichmentService` that runs *before* publishing. This means
publishing is fast, deterministic, and never touches an external API. Each article's
`reference_urls` is already populated in the DB by the time publishing runs.

**`publish(top_n=20)` logic:**

1. `post_processed_repo.get_top_by_imp_score(limit=top_n)` — ordered by `imp_score DESC`.
2. For each article: `rank_score = imp_score × _time_decay_factor(published_at)`.
   `reference_urls` is read directly from the already-enriched DB row (`or []` for safety).
3. `final_article_repo.upsert_batch(rows)` — updates score each cycle without duplicates.

**`_time_decay_factor(published_at)` — why this function exists:**
A story from 1 hour ago is more important than the same-severity story from yesterday.
This function returns a multiplier between 0.10 and 1.00 based on article age, so
`rank_score = imp_score × decay` naturally surfaces fresh news.

**Time-decay table:**

| Age of article | Decay multiplier | Config variable |
|----------------|-----------------|-----------------|
| Under 6 hours  | 1.00 (full score) | `DECAY_FRESH` |
| 6–24 hours     | 0.75             | `DECAY_RECENT` |
| 1–3 days       | 0.50             | `DECAY_DAY`    |
| 3–7 days       | 0.25             | `DECAY_WEEK`   |
| Over 7 days    | 0.10             | `DECAY_OLD`    |

Example: `imp_score=80`, article 10 hours old → `80 × 0.75 = 60.0 rank_score`

---

### `app/services/search_enrichment_service.py`
**What:** Orchestrates Google Search enrichment — once per article, idempotent.
**Why a separate service class?** Separating enrichment from publishing means:
1. Each concern has one place in the code.
2. `PublishingService` stays simple (no external API calls).
3. `SearchEnrichmentService` can be reasoned about independently (quota logic lives here).

**`SearchEnrichmentService.enrich()` — what it does:**

1. Checks that `GOOGLE_SEARCH_API_KEY` and `GOOGLE_SEARCH_ENGINE_ID` are configured.
   If not → returns 0 immediately (graceful no-op, no errors).
2. Calls `post_processed_repo.get_without_reference_urls(limit=GOOGLE_SEARCH_MAX_PER_RUN)`.
   Only articles with `reference_urls IS NULL` are returned. **Why the limit?**
   Free quota guard — caps how many searches happen per scheduler run.
3. For each article:
   - `fetch_related_urls(article.title)` → calls Google Custom Search API.
   - Got URLs? → `update_reference_urls(id, urls)` stores `[url1, url2, ...]`.
   - No URLs? → `mark_reference_urls_searched(id)` stores `[]` (sentinel).
4. `asyncio.sleep(GOOGLE_SEARCH_DELAY_SECONDS)` between every request. **Why:**
   Google's free tier allows 100 queries/day but can throttle burst requests.
5. Returns count of articles that received real URLs.

**Idempotency contract — why each article is searched at most once:**

| `reference_urls` value | Meaning | Will it be searched again? |
|------------------------|---------|---------------------------|
| `NULL` | Never searched yet | ✅ Yes — included in next run |
| `[]` (empty list) | Searched, nothing found | ❌ No — `IS NULL` query excludes it |
| `[url1, url2, ...]` | Enriched successfully | ❌ No — `IS NULL` query excludes it |

This design means: even though the scheduler fires 288 times/day (every 5 minutes),
the total Google Search quota spend equals the number of **distinct new articles** —
not the number of scheduler runs.

---

### `app/services/google_search_service.py`
**What:** Low-level Google Custom Search API client.
**Why separated from `SearchEnrichmentService`?** The enrichment service handles orchestration
(which articles, quota management, DB writes). This file handles only the HTTP call to Google.
Separation makes each file testable independently.

**`fetch_related_urls(title)` — the core function:**
- Sends one GET request to `https://www.googleapis.com/customsearch/v1` with the article title.
- Extracts `item["link"]` from `data["items"]`.
- Returns `[]` on any error (HTTP error, timeout, quota exceeded) — **non-fatal**.
  The caller (`SearchEnrichmentService`) handles the empty list by storing the sentinel.
- Uses `httpx.AsyncClient` with a 10s timeout — non-blocking, won't freeze the event loop.

**`enrich_articles_with_reference_urls(articles)`** — legacy helper:
- Populates `reference_urls` in-place on a list of article dicts.
- Kept for manual or API-level use.
- `SearchEnrichmentService` calls `fetch_related_urls()` directly and handles DB persistence.

---

### `app/services/fetchers/rss_fetcher.py`
**What:** Async RSS/Atom feed downloader.
**Why `asyncio.to_thread()`?** `feedparser.parse()` is a synchronous blocking call.
Running it directly in async code would freeze the entire event loop (blocking all other
requests). Wrapping it in `to_thread()` runs it in a thread pool — async-safe.

---

### `app/services/fetchers/rest_fetcher.py`
**What:** Async REST API fetcher.

- `httpx.AsyncClient.get(url, headers=headers)` with 15s timeout.
- Handles two response shapes: a list at root `[{...}, ...]` or a dict with an
  `articles` / `items` / `results` / `data` key.
- **Why these two shapes?** Different news APIs return data differently. This normalises both.

---

### `app/services/source_normalizer.py`
**What:** Converts raw feed objects into plain dicts.
**Why needed?** `feedparser` returns `FeedParserDict` objects (not plain Python dicts) with
special types like `time.struct_time` for dates. These can't be serialised to JSON or stored
directly. `to_plain_dict()` converts everything to plain strings and datetimes.

- `to_plain_dict(entry)` — handles feedparser-specific types, HTML entity decoding.
- `parse_date(s)` — tries ISO 8601, RFC 2822, common date formats; converts to UTC datetime.

---

### `app/services/normalization/ai_processor.py`
**What:** Environment-variable fallback provider resolver.
**Why separate from the factory?** The factory builds providers from DB config. This file
handles the case when there's no DB config — it reads env vars in priority order.

- `get_env_fallback_provider()` — checks in order:
  1. `OLLAMA_MODEL` set? → Ollama provider (local GPU)
  2. `GEMINI_API_KEY` set? → Gemini Multimodal provider
  3. `ANTHROPIC_API_KEY` set? → Anthropic Claude provider
  4. None of the above → return `None` → skip AI this run

---

### `app/services/normalization/provider_factory.py`
**What:** Factory that creates and caches `AIProvider` instances.
**Why a cache?** SDK clients (like `openai.AsyncOpenAI`) are expensive to construct — they
establish connection pools. Creating a new client for every article (or even every ingest run)
wastes resources. The cache ensures one client is created once and reused.

- `_provider_cache: dict[tuple, AIProvider]` — module-level process singleton.
- Cache key = `(config.id, config.model, config.api_key)` — a new client is created only if
  the active config actually changes. Activating a different provider → cache miss → new client.
- `_build(config)` — the `if/elif` dispatch that instantiates the correct provider subclass.

---

### `app/services/normalization/providers/base.py`
**What:** ABC, shared prompt, JSON parser, output schema.
**Why put the prompt here?** All providers must use the same prompt (same task, same JSON
output schema). Defining it in one place (the base class) means changing the prompt updates
all providers simultaneously — no risk of providers diverging.

- `SINGLE_PROCESS_PROMPT` — instructs the AI to return `{"is_crime": false}` immediately for
  non-crime (minimal tokens = minimal cost), or full extraction JSON for crime articles.
- `SingleOutput` (Pydantic) — validates the AI JSON. Field validators catch bad URLs, unknown
  categories, and out-of-range scores before they reach the DB.
- `_extract_json(text)` — cleans raw AI text before parsing:
  1. Strips ` ```json ... ``` ` markdown fences (some models wrap output in code blocks).
  2. Strips `<think>...</think>` (Qwen3 reasoning models).
  3. Strips `<thinking>...</thinking>` (Claude / Gemini).
  4. Slices from first `{` to last `}` — discards any prose the model added before/after JSON.
- `parse_single_output(text, raw_payload)` — calls `_extract_json` → `json.loads` →
  `SingleOutput.model_validate`. Falls back URL to `raw_payload["link"]` if AI omitted it.
- `AIProvider` ABC — two abstract members: `model_id` property and `process()` coroutine.
  **Why an ABC?** Forces every provider to implement the same interface — the rest of the
  pipeline only needs to call `provider.process(raw, type)` regardless of which AI is active.
- `build_process_message(raw_payload, source_type)` — serialises article data for the AI.

---

### `app/services/normalization/providers/openai_prov.py`
**What:** Provider for OpenAI, Ollama, Gemini (OpenAI-compat), and custom servers.
**Why one class for all these?** They all speak the OpenAI API protocol. The only differences
are `api_key` and `base_url`. One class handles all of them.

- Uses `openai.AsyncOpenAI(api_key, base_url)` with `response_format={"type": "json_object"}`.
- Ollama: `base_url=http://localhost:11434/v1`, `api_key="ollama"` (placeholder key).
- Custom vLLM / LM Studio: same class, different `base_url`.

---

### `app/services/normalization/providers/anthropic_prov.py`
**What:** Provider for Anthropic Claude models.
**Why a separate class?** Anthropic's SDK is different from OpenAI's — different method names,
message structure, and response format. One dedicated class isolates these differences.

- Uses `anthropic.AsyncAnthropic(api_key)`.
- Same prompt and JSON parsing as other providers.

---

### `app/services/normalization/providers/gemini_multimodal_prov.py`
**What:** Recommended Gemini provider using LangGraph structured output.
**Why "structured output"?** With `with_structured_output(SingleOutput)`, Gemini returns a
Pydantic object directly — no JSON parsing needed, no risk of malformed JSON from the model.
This is more reliable than text parsing.

- LangGraph graph: `START → extract_node → classify_node → END`.
- Supports image URLs in the message for visual context (multimodal).

---

### `app/services/normalization/providers/gemini_langgraph_prov.py`
**What:** Simpler Gemini provider (single `ainvoke()` call, text response).
**Why keep it?** Fallback for models/scenarios where structured output isn't available.
Less robust than `gemini_multimodal_prov` for complex outputs.

---

### `app/services/normalization/resolvers.py`
**What:** Converts AI string outputs to FK integer IDs.
**Why not just store strings?** Integer FKs are faster to index and join than strings.
Enforcing FK constraints at the DB level prevents garbage data from the AI.

**`CategoryResolver`** (zero DB queries):
- Loaded from `SubCategoryEnum` (enum values → DB IDs).
- `resolve("murder")` → `1`
- `resolve_all(["murder", "terrorism"])` → `[1, 5]`
- `resolve_categories_from_ids([1, 5])` → `[1]` (Violent Crime parent ID)

**`LocationResolver`** (one DB query at init):
- Loads all 36 state rows into memory at construction time.
- `resolve("Mumbai, Maharashtra, India")` — tries substring match on state name, then
  checks 80+ city-to-state aliases (`"Mumbai" → "Maharashtra"`).
- Returns `None` for non-Indian locations (not stored).
- **Why load all 36 rows?** It's tiny. One query at init is faster than 36 individual
  queries (one per article).

`load_resolvers(db)` — async factory that constructs both in one call.

---

### `app/services/normalization/canonical_validator.py`
**What:** URL and field sanitisation helpers.
**Why?** AI models occasionally return relative URLs (`/crime/story`) or non-HTTP URLs.
These would fail FK constraints or look broken in the frontend. Validation at insert time
prevents bad data from ever reaching the DB.

---

## 7. Database Schema — The 9 Tables Explained

### Article lifecycle through tables

```
news_sources
    │
    └─► raw_ingestion          (inbox: every article ever fetched, deduplicated by SHA-256)
            │  status: pending → filtered / filtered_out / failed
            │
            └─► filtered_articles       (AI-confirmed crime articles only)
                    │
                    └─► post_processed_articles  (+ reference_urls from Google Search)
                                │
                                └─► final_articles  (public feed: top N ranked by rank_score)
```

### Why 4 stages instead of one table?

Each stage has a different purpose and different code writes to it:
- `raw_ingestion` = audit log + dedup gate. Written by the fetcher before any AI.
- `filtered_articles` = AI output. Written after the AI says "yes, crime".
- `post_processed_articles` = enrichment staging. Written at same time as `filtered_articles`,
  then updated by search enrichment.
- `final_articles` = public feed snapshot. Written by publishing service; re-written every cycle.

If everything were in one table, every step would require complex conditional logic to know
what had been done to each row.

### `raw_ingestion` — status values explained

| Status | What happened |
|--------|--------------|
| `pending` | Fetched and stored, not yet processed |
| `filtered` | AI confirmed crime — a row exists in `filtered_articles` |
| `filtered_out` | Keyword pre-filter rejected it, OR AI said "not crime" |
| `failed` | AI call failed (timeout, bad JSON, network error) |
| `processed` | (legacy) fully post-processed |

### `final_articles.rank_score` formula

```
rank_score = imp_score × time_decay_factor(published_at)
```

**Example calculations:**
- `imp_score=80`, article 3h old → `80 × 1.00 = 80.0` (fresh, full score)
- `imp_score=80`, article 10h old → `80 × 0.75 = 60.0` (same article, scored later)
- `imp_score=80`, article 2 days old → `80 × 0.50 = 40.0`
- `imp_score=50`, article 1h old → `50 × 1.00 = 50.0` (less important but very fresh)

### PostgreSQL `reference_urls` — ARRAY vs JSONB

`reference_urls` uses `ARRAY(Text)` rather than JSONB because:
- The data is a simple flat list of strings, not a nested structure.
- PostgreSQL's `IS NULL` vs `= '{}'` (empty array) distinction is what powers the
  idempotency logic — `NULL` means "never searched", `{}` means "searched, nothing found".

### Performance indexes

```sql
-- Fast status filtering in the monitoring endpoint
CREATE INDEX ix_raw_ingestion_status ON raw_ingestion(status);

-- Fast crime sub-type filtering in the final feed
CREATE INDEX ix_filtered_sub_category_ids ON filtered_articles USING GIN(sub_category_ids);
CREATE INDEX ix_filtered_category_ids     ON filtered_articles USING GIN(category_ids);

-- Fast top-N queries for publishing
CREATE INDEX ix_post_processed_imp_score ON post_processed_articles(imp_score)
    WHERE imp_score IS NOT NULL;
```

---

## 8. End-to-End Pipeline Flow — Step by Step

### Full automated cycle (every 5 minutes)

```
APScheduler fires: run_ingestion_for_all_active_sources()
  │
  ├── source_repo.get_all(active_only=True)
  │
  └── asyncio.gather([_ingest_one_source(s) for s in sources])  ← all sources in parallel
        │
        └── IngestionService.ingest(source)
              │
              ├── 1. FETCH
              │     RSSFetcher.fetch(url)   → feedparser.parse() in thread
              │     RestFetcher.fetch(url)  → httpx.AsyncClient.get()
              │     source_normalizer.to_plain_dict(entry)  → plain dict
              │
              ├── 2. LOAD AI PROVIDER
              │     ai_provider_repo.get_active()   → DB config row (highest priority)
              │     create_from_config(config)       → cached SDK client
              │       OR
              │     get_env_fallback_provider()      → OLLAMA_MODEL / GEMINI_API_KEY / ANTHROPIC_API_KEY
              │     → determines provider_type → determines rate limits and item cap
              │
              ├── 3. CAP
              │     slice raw_items to max_items_for_provider_type
              │     (Ollama: 50, cloud: 5, default: 10)
              │
              ├── 4. HASH + DEDUP
              │     SHA-256(source_id + json(payload)) per article
              │     raw_repo.store_batch() → INSERT OR IGNORE on content_hash
              │     returns: new hashes + previously stuck-pending hashes (recovery)
              │
              ├── 5. KEYWORD PRE-FILTER
              │     _has_crime_keywords(raw) — ~50 crime terms in title/summary
              │     no match → mark_filtered_out immediately (zero AI calls)
              │
              ├── 6. AI PROCESSING
              │     Ollama:  process in batches of OLLAMA_BATCH_SIZE, pause between batches
              │     Cloud:   process all at once
              │     asyncio.gather() with semaphore (concurrency) + rate limiter (RPM):
              │       ai_provider.process(raw, source_type)
              │         → SINGLE_PROCESS_PROMPT (system) + raw JSON (user)
              │         → model responds with JSON string
              │         → _extract_json() strips fences + think blocks
              │         → SingleOutput.model_validate() validates all fields
              │         → returns article dict or {"is_crime": false} or None (error)
              │
              ├── 7. BUCKET RESULTS
              │     is_crime=True  → crime_articles
              │     is_crime=False → filtered_out_hashes
              │     result=None / exception → failed_hashes
              │
              ├── 8. RESOLVE FKs
              │     CategoryResolver.resolve_all(sub_category strings → int list)
              │     LocationResolver.resolve(location string → state_id int or None)
              │
              ├── 9. WRITE TO DB
              │     filter_article_repo.insert_batch()   → filtered_articles (upsert on main_url)
              │     post_processed_repo.insert_batch()   → post_processed_articles
              │     (reference_urls = NULL at this point — not yet searched)
              │
              └── 10. UPDATE RAW STATUSES
                    raw_repo.mark_filtered(hashes)
                    raw_repo.mark_filtered_out(hashes)
                    raw_repo.mark_failed(hashes)

  └── (if ok > 0 — at least one source produced new articles)
        │
        ├── SearchEnrichmentService.enrich()   ← RUNS BEFORE PUBLISHING
        │     │
        │     ├── 1. QUERY UNENRICHED (quota-capped)
        │     │     get_without_reference_urls(limit=GOOGLE_SEARCH_MAX_PER_RUN)
        │     │     WHERE reference_urls IS NULL   ← NULL only; [] sentinel excluded
        │     │     ORDER BY imp_score DESC         ← most important articles first
        │     │
        │     └── 2. FOR EACH ARTICLE (sequential, not parallel — quota protection)
        │           google_search_service.fetch_related_urls(title)
        │             GET https://www.googleapis.com/customsearch/v1?q=title&num=3&key=...&cx=...
        │             → extract item["link"] from response["items"]
        │
        │           got URLs?  YES → update_reference_urls(id, [url1, url2, ...])
        │                      NO  → mark_reference_urls_searched(id)  → stores []
        │
        │           asyncio.sleep(GOOGLE_SEARCH_DELAY_SECONDS)  ← 1s between requests
        │           ← this article will NEVER appear in get_without_reference_urls again
        │
        └── PublishingService.publish(top_n=FEED_TOP_N)
              │
              ├── 1. SELECT TOP-N
              │     get_top_by_imp_score(limit=20)
              │     ORDER BY imp_score DESC WHERE imp_score IS NOT NULL
              │
              ├── 2. COMPUTE rank_score
              │     imp_score × time_decay_factor(published_at)
              │     reference_urls already in DB — no Google Search call here
              │
              └── 3. UPSERT PUBLIC FEED
                    final_article_repo.upsert_batch(rows)
                    ON CONFLICT (post_processed_article_id) DO UPDATE
                      SET rank_score, reference_urls, title, description, image_url
```

---

## 9. AI Provider System

### Provider resolution order

```
IngestionService._load_ai_provider()
  │
  ├── 1. ai_provider_repo.get_active()   ← DB config (highest priority)
  │         └── create_from_config(config) [process-lifetime cached]
  │
  └── 2. get_env_fallback_provider()    ← .env keys
            OLLAMA_MODEL set?      → OllamaProvider (local, no key needed)
            GEMINI_API_KEY set?    → GeminiMultimodalLangGraph
            ANTHROPIC_API_KEY set? → AnthropicProvider
            none of the above     → None → skip AI this run (log a warning)
```

### Supported providers

| Type | Underlying class | Notes |
|------|-----------------|-------|
| `ollama` | `OpenAICompatibleProvider` | Local GPU, no API key, `localhost:11434/v1` auto-set |
| `gemini_multimodal` | `GeminiMultimodalLangGraphProvider` | **Recommended cloud** — structured output |
| `gemini_langgraph` | `GeminiLangGraphProvider` | Simpler Gemini, text parsing fallback |
| `gemini` | `OpenAICompatibleProvider` | Gemini via OpenAI-compatible endpoint |
| `anthropic` | `AnthropicProvider` | Claude models |
| `openai` | `OpenAICompatibleProvider` | GPT models |
| `custom` | `OpenAICompatibleProvider` | vLLM, LM Studio, remote Ollama — requires `base_url` |

### Provider caching

Cache key = `(config.id, config.model, config.api_key)`.
SDK clients are created once and reused across all ingest runs until the server restarts.
Switching the active provider creates a fresh client on the next run; the old one stays
in the cache dict but is never called again.

### The AI prompt

`SINGLE_PROCESS_PROMPT` from `providers/base.py` instructs the model to:
- Return `{"is_crime": false}` immediately for non-crime articles (minimal token cost)
- Return the full extraction + rewrite + scoring JSON in **one call** for crime articles

**Why one call?** Making separate calls for "is this crime?" then "extract data" would double
the API cost and latency. A well-crafted prompt does both in a single response.

### JSON parsing pipeline

```
AI raw text response
  → _extract_json()
      strip ``` json ... ``` fences      (models often wrap output)
      strip <think>...</think>           (Qwen3 reasoning chains)
      strip <thinking>...</thinking>     (Claude / Gemini reasoning)
      slice [first '{' : last '}']       (discard prose before/after JSON)
  → json.loads()
  → SingleOutput.model_validate()
      _check_url: reject relative or non-HTTPS URLs
      _check_sub_category: reject unknown category strings
      _check_imp_score: clamp to 1–100
  → parse_single_output() returns article dict or None
```

---

## 10. Google Search Reference URL Enrichment — Design Deep Dive

### The problem this solves

When we display a crime story to users, we want to show them "Read more" links — other news
sources covering the same story. We could call Google Search every time we publish the feed,
but that would burn 20 quota units per publish cycle × 288 cycles/day = 5760 queries/day
against a 100 queries/day free limit.

### The solution: search once, store forever

```
         Article published                  Article published
         to final_articles                  again next cycle
              ↓                                   ↓
 post_processed   reference_urls = NULL       reference_urls = [url1, url2]
                        ↓                                ↓
              SearchEnrichmentService           (excluded from query)
              calls Google Search              PublishingService reads
              stores [url1, url2]              from DB — no Google call
```

The `reference_urls` field on `post_processed_articles` acts as both storage and a
"search state machine" with three states:

| State | DB value | Meaning | Will SearchEnrichmentService touch it again? |
|-------|----------|---------|---------------------------------------------|
| Unsearched | `NULL` | Never queried Google for this article | ✅ Yes — eligible |
| Searched, no results | `[]` (empty array) | Google returned nothing | ❌ No — sentinel |
| Enriched | `[url1, url2, ...]` | Has reference URLs | ❌ No — already done |

**Why the sentinel `[]` instead of a separate boolean column?**
A boolean `search_attempted` column would work too, but the ARRAY field already exists.
Storing `[]` uses the existing column as a state flag, avoiding an extra migration and
keeping all reference URL state in one place.

### Quota math

```
Free tier: 100 queries/day
Scheduler: fires every 5 minutes = 288 runs/day
GOOGLE_SEARCH_MAX_PER_RUN = 10

Worst case per-run quota spend: 10 queries
Worst case total daily spend:   10 × 288 = 2880 queries

BUT: each article is searched exactly once.
So actual daily spend = number of NEW articles passing AI filter that day.
A typical news day: ~20–50 new crime articles.
Actual quota spend: ~20–50 queries/day — well under 100.
```

The `GOOGLE_SEARCH_MAX_PER_RUN=10` cap is a *safety guard* — it limits damage if the DB
somehow accumulates thousands of unsearched articles (e.g. after a long downtime).

### Setup: enabling Google Search enrichment

1. Go to `programmablesearchengine.google.com` → create a Custom Search Engine.
   Set it to search the entire web.
2. Go to Google Cloud Console → enable the **Custom Search JSON API**.
3. Create an API key.
4. Add to `.env`:
   ```env
   GOOGLE_SEARCH_API_KEY=AIzaSy...
   GOOGLE_SEARCH_ENGINE_ID=abc123...
   # Optional tuning:
   GOOGLE_SEARCH_RESULTS_PER_ARTICLE=3    # URLs per article (max 10 per API call)
   GOOGLE_SEARCH_DELAY_SECONDS=1.0        # Seconds between sequential requests
   GOOGLE_SEARCH_MAX_PER_RUN=10           # Max articles per scheduler run (quota guard)
   ```

> If these env vars are not set, the app works normally — articles just have no `reference_urls`.
> The feature degrades gracefully.

### Triggering enrichment manually

Enrichment runs automatically after every successful ingest. To trigger it manually:

```bash
# Triggers ingest → enrich → publish immediately:
curl -X POST http://localhost:8000/ingest/ \
  -H "Content-Type: application/json" \
  -d '{"source_id": 1}'
# Check logs for: "SearchEnrichmentService: N article(s) need enrichment"

# Triggers publish only (reads already-enriched data, no new Google calls):
curl -X POST "http://localhost:8000/final-articles/publish?top_n=20"
```

---

## 11. Scheduler Design — Why 3 Steps, Not 3 Jobs

### What changed and why

An earlier design had three separate APScheduler jobs:
1. Ingestion job — every 5 minutes
2. Search enrichment job — every 5 minutes (offset)
3. Publishing job — every 5 minutes (further offset)

**Problem with 3 separate jobs:** They run on fixed timers, so:
- Ingestion might finish early, but enrichment waits for its timer to fire.
- Enrichment timer might fire before ingestion completes — enriching nothing new.
- The feed could be 10+ minutes stale after a batch of new articles arrives.
- Harder to reason about ordering guarantees.

### Current design: 2 jobs + 1 inline call

```
APScheduler job 1: run_ingestion_for_all_active_sources()
  │
  │  [ingestion completes]
  │
  ├── if any new articles:
  │     await run_search_enrichment()   ← not a job, an inline async call
  │     await run_publishing()          ← not a job, an inline async call
  │
  └── return

APScheduler job 2: run_publishing()   ← catches up if ingestion didn't run recently
  (fires every PUBLISH_INTERVAL_MINUTES + PUBLISH_OFFSET_SECONDS)
```

**Why this is better:**
- **Guaranteed ordering:** Enrichment always runs after ingestion, publishing always runs
  after enrichment. No race conditions.
- **Immediate feedback:** New articles appear in the feed seconds after ingestion completes —
  not after waiting for a separate timer.
- **Simpler mental model:** The scheduler has 2 jobs, not 3. The chain logic lives entirely
  in `run_ingestion_for_all_active_sources()`.
- **The extra publishing job** (Job 2) still exists as a safety net — in case no new
  articles came in, articles still get re-ranked periodically (their `rank_score` changes
  as they age).

### `max_instances=1` explained

Both APScheduler jobs have `max_instances=1`. This means:
- If a job is still running when its next scheduled fire time arrives, the new run is
  **skipped** entirely.
- This prevents two overlapping ingest runs from calling the AI twice for the same articles.
- Without this, a slow AI response could cause exponentially overlapping runs.

### Visual timeline

```
Time →    0m          5m           10m         15m
          │           │            │           │
          ▼           ▼            ▼           ▼
Job 1:  [ingest+enrich+publish]  [ingest+enrich+publish]
Job 2:              [publish]                 [publish]
          ↑ 0s offset  ↑ +30s offset
```

Job 2 fires 30 seconds after Job 1 in each cycle. If Job 1 published already, Job 2
is a fast no-op (nothing changed). If Job 1 is still running, Job 2's `run_publishing()`
uses whatever is in the DB at that moment.

---

## 12. Request Flows — End to End

### `POST /ingest/` — Manual pipeline trigger

```
POST /ingest/ {"source_id": 2}
  → source_repo.get_by_id(2)   → validate source exists and type is rss/rest
  → IngestionService.ingest(source)   [same 13 steps as automated run in §8]
  → return {"source_id": 2, "source_type": "rss", "ingested": 5}
```

Note: the manual `/ingest/` endpoint calls `IngestionService.ingest()` directly — it does NOT
automatically trigger search enrichment or publishing. Use the scheduler (or wait for the
automated cycle) for the full ingest → enrich → publish chain.

### `POST /final-articles/publish` — Manual publish (no Google Search)

```
POST /final-articles/publish?top_n=20
  → PublishingService.publish(top_n=20)
      → get_top_by_imp_score(20)
      → compute rank_score for each
      → reference_urls read from DB (already enriched — no Google API call)
      → upsert_batch()
  → return {"published": 20, "top_n": 20}
```

> To also run search enrichment manually, trigger ingestion via `POST /ingest/`.
> The scheduler chains enrichment automatically after each successful ingest.

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

### `PATCH /ai-providers/{id}/activate` — Switch AI provider

```
PATCH /ai-providers/3/activate
  → UPDATE ai_provider_configs SET is_active=false WHERE is_active=true
  → UPDATE ai_provider_configs SET is_active=true  WHERE id=3
  → return {"activated_id": 3, "message": "...now active"}

Next ingest run:
  → ai_provider_repo.get_active()  → config row (id=3)
  → create_from_config(config)     → cache miss → new SDK client created
  → all articles now processed by the new model
```

---

## 13. API Reference

### Public — Ranked Feed (`/final-articles/`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/final-articles/` | Ranked crime news feed (primary frontend endpoint) |
| GET | `/final-articles/{id}` | Single article by ID |
| POST | `/final-articles/publish` | Force-refresh ranking (reads DB data — no Google Search) |

**GET `/final-articles/` query params:**

| Param | Default | Description |
|-------|---------|-------------|
| `limit` | 20 | Articles per page (max 100) |
| `offset` | 0 | Pagination offset |
| `sub_category_id` | — | Filter by crime sub-type ID (from `/master/sub-categories`) |
| `q` | — | Keyword search in title + description |

---

### Pipeline Inspection (Debug)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/raw-ingestion/` | Raw inbox — every article ever fetched |
| GET | `/raw-ingestion/{id}` | Single raw row with full `raw_payload` JSON |
| GET | `/filter-articles/` | Stage-1 AI-confirmed crime articles |
| GET | `/filter-articles/{id}` | |
| GET | `/post-processed/` | Stage-2 enriched articles (with `imp_score` + `reference_urls`) |
| GET | `/post-processed/{id}` | |

**GET `/raw-ingestion/` query params:**

| Param | Description |
|-------|-------------|
| `status` | `pending` \| `filtered` \| `processed` \| `filtered_out` \| `failed` |
| `source_id` | Filter by source ID |
| `limit` / `offset` | Pagination |

---

### Admin — Sources (`/sources/`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/sources/` | List sources (`?include_inactive=true` to show paused) |
| POST | `/sources/` | Add new RSS or REST source |
| GET | `/sources/{id}` | Get by ID |
| PATCH | `/sources/{id}` | Update — pause with `{"is_active": false}` |
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
| POST | `/ai-providers/` | Register new provider config |
| GET | `/ai-providers/active` | Currently active provider |
| GET | `/ai-providers/{id}` | Get by ID |
| PATCH | `/ai-providers/{id}/activate` | Switch to this provider (takes effect next run) |
| DELETE | `/ai-providers/active` | Deactivate all (fall back to .env keys) |
| DELETE | `/ai-providers/{id}` | Delete a config |

**POST `/ai-providers/` body examples:**

```json
// Ollama (local GPU, no API key needed)
{"name": "Ollama Qwen3", "provider": "ollama",
 "model": "dengcao/Qwen3-30B-A3B-Instruct-2507:latest"}

// Gemini Multimodal (recommended cloud — structured output)
{"name": "Gemini Flash", "provider": "gemini_multimodal",
 "model": "gemini-2.0-flash", "api_key": "AIzaSy..."}

// Anthropic Claude
{"name": "Claude Haiku", "provider": "anthropic",
 "model": "claude-haiku-4-5-20251001", "api_key": "sk-ant-..."}

// OpenAI GPT
{"name": "GPT-4o Mini", "provider": "openai",
 "model": "gpt-4o-mini", "api_key": "sk-..."}

// Custom OpenAI-compatible server (vLLM, LM Studio, remote Ollama)
{"name": "Remote vLLM", "provider": "custom",
 "model": "mistral-7b", "api_key": "none",
 "base_url": "http://192.168.1.10:8080/v1"}
```

---

### Master Data (`/master/`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/master/categories` | 8 crime categories (for filter UI) |
| GET | `/master/sub-categories` | 10 crime sub-categories |
| GET | `/master/states` | 36 Indian states/UTs (for location filter) |

---

### Health

| Method | Path | Response |
|--------|------|----------|
| GET | `/health` | `{"status": "ok"}` |
| GET | `/` | Info page with link to `/docs` |

---

## 14. Configuration Reference

All settings are loaded from `.env` via `app/core/config.py` (Pydantic Settings).

### Database

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | **required** | Must be `postgresql+asyncpg://...` (async driver) |

### AI Provider — Ollama (local)

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_MODEL` | None | Set this to use Ollama as the env-fallback provider |
| `OLLAMA_URL` | `http://localhost:11434/v1` | Ollama API endpoint |
| `OLLAMA_REQUESTS_PER_MINUTE` | 60 | RPM (local = no real limit; set high) |
| `OLLAMA_MAX_ITEMS_PER_RUN` | 50 | Articles processed per ingest run |
| `OLLAMA_CONCURRENCY` | 1 | Parallel GPU inferences (1 = no queuing; single GPU) |
| `OLLAMA_BATCH_SIZE` | 10 | Articles per GPU batch before cooldown |
| `OLLAMA_BATCH_COOLDOWN_SECONDS` | 15.0 | GPU rest pause between batches |

### AI Provider — Cloud APIs

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | None | Enables Gemini env-fallback |
| `ANTHROPIC_API_KEY` | None | Enables Anthropic env-fallback |
| `CLOUD_REQUESTS_PER_MINUTE` | 3 | RPM for cloud providers (conservative free-tier default) |
| `CLOUD_MAX_ITEMS_PER_RUN` | 5 | Items per ingest run for cloud providers |
| `AI_REQUESTS_PER_MINUTE` | 5 | Generic fallback RPM |
| `AI_MAX_ITEMS_PER_RUN` | 10 | Generic fallback item cap |
| `AI_RETRY_ATTEMPTS` | 3 | Retries on rate-limit errors |
| `AI_RETRY_DELAY_SECONDS` | 15.0 | Base back-off delay for retries |

### Google Search Enrichment

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_SEARCH_API_KEY` | None | Google Cloud API key (optional — app works without it) |
| `GOOGLE_SEARCH_ENGINE_ID` | None | Programmable Search Engine ID |
| `GOOGLE_SEARCH_RESULTS_PER_ARTICLE` | 3 | Reference URLs per article (max 10) |
| `GOOGLE_SEARCH_DELAY_SECONDS` | 1.0 | Seconds between sequential search requests |
| `GOOGLE_SEARCH_MAX_PER_RUN` | 10 | Max articles searched per scheduler run (quota guard) |

### Scheduler

| Variable | Default | Description |
|----------|---------|-------------|
| `INGEST_INTERVAL_MINUTES` | 5 | How often the ingestion job fires |
| `PUBLISH_INTERVAL_MINUTES` | 5 | How often the standalone publish job fires |
| `PUBLISH_OFFSET_SECONDS` | 30 | Delay offset for publish job (runs 30s after ingest) |
| `FEED_TOP_N` | 20 | Number of articles in the published feed |

### Time-Decay Scoring

| Variable | Default | Age bracket |
|----------|---------|-------------|
| `DECAY_FRESH` | 1.00 | Under 6 hours |
| `DECAY_RECENT` | 0.75 | 6–24 hours |
| `DECAY_DAY` | 0.50 | 1–3 days |
| `DECAY_WEEK` | 0.25 | 3–7 days |
| `DECAY_OLD` | 0.10 | Over 7 days |

### Misc

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | False | FastAPI debug mode |

### Recommended `.env` templates

**Local Ollama (GPU, no cloud costs):**
```env
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db_news
OLLAMA_MODEL=dengcao/Qwen3-30B-A3B-Instruct-2507:latest
# Optional: Google Search for reference URLs
GOOGLE_SEARCH_API_KEY=AIzaSy...
GOOGLE_SEARCH_ENGINE_ID=abc123...
```

**Gemini free tier:**
```env
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db_news
GEMINI_API_KEY=AIzaSy...
CLOUD_MAX_ITEMS_PER_RUN=5        # conservative to stay within free quota
CLOUD_REQUESTS_PER_MINUTE=3
GOOGLE_SEARCH_API_KEY=AIzaSy...
GOOGLE_SEARCH_ENGINE_ID=abc123...
```

---

## 15. Adding a New AI Provider

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
        # Initialise your SDK client here (e.g. your_sdk.AsyncClient(api_key))

    @property
    def model_id(self) -> str:
        # This string is stored in raw_ingestion.normalized_by for the audit trail
        return f"ai:your_provider:{self._model}"

    async def process(self, raw_payload: dict, source_type: str) -> dict | None:
        # 1. Build the user message (serialises the raw article dict for the AI)
        user_msg = build_process_message(raw_payload, source_type)
        # 2. Call your API with SINGLE_PROCESS_PROMPT as system + user_msg as user
        text = ...   # raw text response from your API
        # 3. Parse, validate, and return the structured result (or None on failure)
        return parse_single_output(text, raw_payload)
```

### Step 2 — Register in the factory

`app/services/normalization/provider_factory.py` — add a branch to `_build()`:

```python
from app.services.normalization.providers.your_prov import YourProvider

# inside _build():
if provider == "your_provider":
    return YourProvider(api_key=api_key, model=model)
```

### Step 3 — Add metadata constants

`app/models/ai_provider.py`:

```python
SUPPORTED_PROVIDERS = {..., "your_provider"}
PROVIDER_BASE_URLS["your_provider"] = None          # or a default base URL
PROVIDER_DEFAULT_MODELS["your_provider"] = "your-default-model-name"
```

### Step 4 — Add to schema Literal

`app/schemas/ai_provider_schema.py`:

```python
_PROVIDER_LITERAL = Literal[..., "your_provider"]
```

### Test it

```bash
# Register the provider
curl -X POST http://localhost:8000/ai-providers/ \
  -H "Content-Type: application/json" \
  -d '{"name": "My Provider", "provider": "your_provider",
       "model": "your-model", "api_key": "your-key"}'

# Activate it (takes effect on next ingest run)
curl -X PATCH http://localhost:8000/ai-providers/{id}/activate

# Trigger a test ingest run
curl -X POST http://localhost:8000/ingest/ \
  -H "Content-Type: application/json" \
  -d '{"source_id": 1}'

# Verify in the logs: look for "normalized_by": "ai:your_provider:your-model"
```
