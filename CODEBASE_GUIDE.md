# Crime News Aggregator — Complete Codebase Architecture Guide

> **Who this is for:** A beginner Python developer who knows basic Python syntax and wants to fully understand how this system works — without opening a single source file. This guide explains every decision, every file, every function, and every data flow.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [High-Level System Architecture](#2-high-level-system-architecture)
3. [Complete Project Folder Structure](#3-complete-project-folder-structure)
4. [File-by-File Codebase Exploration](#4-file-by-file-codebase-exploration)
5. [Function-Level Code Explanation](#5-function-level-code-explanation)
6. [Application Execution Flow](#6-application-execution-flow)
7. [Request Lifecycle Walkthrough](#7-request-lifecycle-walkthrough)
8. [Data Flow Through the System](#8-data-flow-through-the-system)
9. [Database Architecture](#9-database-architecture)
10. [Database Relationships](#10-database-relationships)
11. [External Services and Integrations](#11-external-services-and-integrations)
12. [Error Handling Strategy](#12-error-handling-strategy)
13. [Important Design Patterns Used](#13-important-design-patterns-used)
14. [Example End-to-End System Scenario](#14-example-end-to-end-system-scenario)
15. [How a Developer Should Navigate This Codebase](#15-how-a-developer-should-navigate-this-codebase)

---

# 1. Project Overview

## What Problem Does This Project Solve?

India generates thousands of news articles every day. Crime news — murders, fraud cases, drug busts, terror alerts — comes from dozens of different news portals, each with their own formatting, different date styles, different field names, and different quality levels.

A journalist, a researcher, or a mobile app user who wants to stay updated on crime news in India has to:
- Visit multiple news sites manually
- Sort through irrelevant sports, entertainment, and political news
- Figure out which stories are most important
- Find related articles and context for each story

This system **automates all of that**. It continuously fetches news from many sources, uses AI to determine if each article is crime-related, scores each article by importance, and publishes a clean ranked feed that any app or website can consume.

## What Does the System Do?

At its core, the system is a **news aggregation pipeline** with these capabilities:

1. **Automated fetching** — Every 5 minutes, it pulls new articles from multiple news sources (RSS feeds and REST APIs)
2. **Deduplication** — If the same article appears twice (common when news syndication repeats stories), it is stored only once
3. **Keyword pre-filtering** — A fast rule-based check discards obviously non-crime content before making expensive AI calls
4. **AI classification** — A language model reads each article and determines: Is this a crime article? What type of crime? Where did it happen? How important is it?
5. **Importance scoring** — The AI assigns a score from 1–100 based on crime severity, number of victims, geographic scope, and whether public officials are involved
6. **Search enrichment** — Google Custom Search finds related articles and reference URLs for each news story
7. **Time-decay ranking** — Fresh breaking news ranks higher than older stories of similar importance
8. **Public feed** — A clean REST API serves the ranked, deduplicated, AI-processed feed

## The Type of Application

This is a **backend API server** — it has no user interface. It exposes HTTP endpoints that a mobile app, website, or any other client can call. Internally, it also runs background jobs that process news automatically, even when no client is actively making requests.

## Primary Technologies

| Technology | What It Does |
|---|---|
| **FastAPI** | Python web framework — handles HTTP requests and responses |
| **PostgreSQL** | Database — stores all articles, sources, and AI configurations |
| **SQLAlchemy** | ORM — lets Python code interact with the database using Python objects instead of raw SQL |
| **APScheduler** | Background job scheduler — runs ingestion every 5 minutes automatically |
| **asyncio** | Python's built-in async framework — allows handling many things simultaneously without waiting |
| **Pydantic** | Data validation — ensures inputs/outputs match expected shapes |
| **Alembic** | Database migration tool — tracks schema changes over time |
| **feedparser** | RSS feed parser — reads XML news feeds |
| **httpx** | Async HTTP client — fetches data from REST APIs |
| **Ollama / Gemini / Claude / GPT** | AI providers — classify and process articles |
| **LangGraph** | AI agent framework — for more complex multi-step AI processing |

## Architecture Philosophy

The codebase follows **strict layered architecture**. This means each layer of the application has a single responsibility and can only communicate with the layers directly below it:

```
HTTP (client)
     ↓
API Routes  — receive requests, validate input, return responses
     ↓
Services    — business logic, orchestration, external calls
     ↓
Repositories — database read/write only
     ↓
Models       — table definitions only
     ↓
PostgreSQL   — stores everything
```

No layer skips over another. A route never directly queries the database. A model never calls a service. This makes the code predictable and easy to test.

---

# 2. High-Level System Architecture

## Two Modes of Operation

This system operates in two simultaneous modes:

### Mode 1: Automated Background Processing (runs every 5 minutes)

```
APScheduler triggers job
        ↓
Fetch articles from all active news sources (RSS + REST)
        ↓
Compute SHA-256 hash for each article (deduplication)
        ↓
Store raw payloads in database (skip duplicates via hash)
        ↓
Keyword pre-filter: does the article contain crime words?
        ↓
AI Processing: Is this a crime article? Score it. Classify it.
        ↓
Resolve AI text labels → database integer IDs (categories, states)
        ↓
Write to filtered_articles (Stage 1)
        ↓
Write to post_processed_articles (Stage 2, with importance score)
        ↓
Google Search: fetch reference URLs for unenriched articles
        ↓
Select top N articles by importance score
        ↓
Apply time-decay: rank_score = importance × freshness_factor
        ↓
Write ranked articles to final_articles (public feed)
```

### Mode 2: HTTP API (responds to client requests instantly)

```
Client Request (GET /final-articles/)
        ↓
FastAPI Router receives request
        ↓
FastAPI validates query parameters
        ↓
Dependency injection creates Repository with database session
        ↓
Repository runs SQL query (SELECT from final_articles ORDER BY rank_score DESC)
        ↓
SQLAlchemy maps rows to Python objects
        ↓
Pydantic serializes objects to JSON
        ↓
FastAPI sends HTTP 200 response with JSON body
```

## Complete Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        EXTERNAL WORLD                           │
│                                                                 │
│  News Sites          AI Providers          Google Search        │
│  (RSS/REST)          (Ollama/Gemini/       (Custom Search API)  │
│                       Claude/GPT)                               │
└──────┬───────────────────────┬──────────────────────┬──────────┘
       │                       │                      │
       ▼                       ▼                      ▼
┌──────────────────────────────────────────────────────────────────┐
│                     APP LAYER (FastAPI Server)                   │
│                                                                  │
│  ┌────────────────┐     ┌──────────────────────────────────────┐ │
│  │  HTTP API      │     │  Background Scheduler (APScheduler)  │ │
│  │  Routes        │     │                                      │ │
│  │  /final-       │     │  ┌─────────────────────────────────┐ │ │
│  │   articles/    │     │  │  IngestionService               │ │ │
│  │  /sources/     │     │  │  ├── RSSFetcher                 │ │ │
│  │  /ingest/      │     │  │  ├── RestFetcher                │ │ │
│  │  /ai-providers/│     │  │  ├── Keyword Pre-filter         │ │ │
│  │  /master/      │     │  │  ├── AI Provider (7 types)      │ │ │
│  │  etc.          │     │  │  └── Rate Limiter + Semaphore   │ │ │
│  └───────┬────────┘     │  └─────────────────────────────────┘ │ │
│          │              │  ┌─────────────────────────────────┐  │ │
│          │              │  │  SearchEnrichmentService        │  │ │
│          │              │  └─────────────────────────────────┘  │ │
│          │              │  ┌─────────────────────────────────┐  │ │
│          │              │  │  PublishingService              │  │ │
│          │              │  │  rank_score = imp × decay(age)  │  │ │
│          │              │  └─────────────────────────────────┘  │ │
│          │              └──────────────────────────────────────┘ │
│          │                                                        │
│  ┌───────▼────────────────────────────────────────────────────┐  │
│  │                  REPOSITORY LAYER                          │  │
│  │  SourceRepo  RawIngestionRepo  FilterArticleRepo           │  │
│  │  PostProcessedRepo  FinalArticleRepo  AIProviderRepo       │  │
│  └───────┬────────────────────────────────────────────────────┘  │
│          │                                                        │
└──────────┼────────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────┐
│                    PostgreSQL Database                           │
│                                                                  │
│  news_sources        raw_ingestion       filtered_articles       │
│  post_processed_articles  final_articles  ai_provider_configs    │
│  master_category  master_sub_category  country  state            │
└──────────────────────────────────────────────────────────────────┘
```

---

# 3. Complete Project Folder Structure

## Directory Tree

```
news-app-server/                    ← Project root
│
├── .env                            ← Secret credentials (never commit this!)
├── .python-version                 ← Specifies Python 3.12
├── .gitignore                      ← Files git should not track
├── pyproject.toml                  ← Project metadata + dependency list
├── uv.lock                         ← Exact dependency versions (like package-lock.json)
├── alembic.ini                     ← Alembic (migration tool) configuration
├── README.md                       ← User guide and quick-start instructions
├── ARCHITECTURE.md                 ← Architecture reference document
├── CODEBASE_GUIDE.md               ← This document
│
├── migrations/                     ← Database schema history (managed by Alembic)
│   ├── env.py                      ← Alembic runtime configuration
│   ├── script.py.mako              ← Template for new migration files
│   └── versions/                   ← One file per schema change
│       ├── 29df1b34a087_initial_schema.py
│       ├── c8f2a1e3b456_add_raw_ingestion_events.py
│       ├── d9e4f5a6b789_add_ai_provider_configs.py
│       ├── e1f2a3b4c567_add_enrichment_fields.py
│       ├── f2g3h4i5j678_add_article_card_fields.py
│       ├── g3h4i5j6k789_widen_normalized_by.py
│       ├── h4i5j6k7l890_pipeline_schema_redesign.py
│       ├── i5j6k7l8m901_seed_master_data.py
│       ├── j6k7l8m9n012_pipeline_enhancements.py
│       ├── k7l8m9n0o123_filtered_articles_cleanup.py
│       └── l8m9n0o1p234_performance_indexes.py  ← Current HEAD
│
└── app/                            ← All application source code lives here
    ├── __init__.py                 ← Makes `app` a Python package
    ├── main.py                     ← Server entry point — creates FastAPI app
    │
    ├── core/                       ← Application infrastructure (config, DB, DI)
    │   ├── config.py               ← All environment variables in one typed object
    │   ├── database.py             ← Database engine and session factory
    │   ├── deps.py                 ← FastAPI dependency injection wiring
    │   └── enums.py                ← Python Enum types for crime categories
    │
    ├── models/                     ← SQLAlchemy ORM table definitions
    │   ├── __init__.py             ← Imports all models so SQLAlchemy registers them
    │   ├── base.py                 ← The DeclarativeBase all models inherit from
    │   ├── source.py               ← news_sources table
    │   ├── raw_event.py            ← raw_ingestion table
    │   ├── ai_provider.py          ← ai_provider_configs table
    │   ├── category.py             ← master_category + master_sub_category tables
    │   ├── location.py             ← country + state tables
    │   ├── filter_article.py       ← filtered_articles table
    │   ├── post_processed_article.py ← post_processed_articles table
    │   └── final_article.py        ← final_articles table
    │
    ├── repositories/               ← Data access layer — all SQL queries live here
    │   ├── source_repo.py          ← CRUD for news_sources
    │   ├── raw_ingestion_repo.py   ← Batch insert + status tracking for raw_ingestion
    │   ├── filter_article_repo.py  ← Batch insert for filtered_articles
    │   ├── post_processed_article_repo.py ← Batch insert + reference URL updates
    │   ├── final_article_repo.py   ← Upsert ranked feed + read public feed
    │   ├── master_data_repo.py     ← Read-only for categories/states
    │   ├── ai_provider_repo.py     ← CRUD + activate for AI provider configs
    │   └── article_repo.py         ← Legacy alias (kept for backwards compat)
    │
    ├── schemas/                    ← Pydantic models for API input/output validation
    │   ├── source_schema.py        ← SourceCreate, SourceUpdate, SourceResponse
    │   ├── article_schema.py       ← Article response shapes
    │   ├── ai_provider_schema.py   ← AIProviderCreate, AIProviderResponse
    │   ├── final_article_schema.py ← FinalArticleResponse, FinalArticleListResponse
    │   └── master_data_schema.py   ← Category, SubCategory, State responses
    │
    ├── services/                   ← Business logic
    │   ├── ingestion_service.py    ← Complete pipeline: fetch → filter → AI → store
    │   ├── publishing_service.py   ← Ranking algorithm: imp_score × time_decay
    │   ├── scheduler.py            ← APScheduler setup + job functions
    │   ├── search_enrichment_service.py ← Google Search → reference_urls
    │   ├── source_normalizer.py    ← Rule-based normalizer + date parsing + dict conversion
    │   ├── google_search_service.py ← Google Custom Search API client
    │   │
    │   ├── fetchers/               ← Network fetching modules
    │   │   ├── rss_fetcher.py      ← feedparser-based RSS/Atom fetcher
    │   │   └── rest_fetcher.py     ← httpx-based JSON REST API fetcher
    │   │
    │   └── normalization/          ← AI provider system
    │       ├── ai_processor.py     ← Env-var fallback provider resolution
    │       ├── provider_factory.py ← Factory + cache for AIProvider instances
    │       ├── canonical_validator.py ← Field validation helpers
    │       ├── resolvers.py        ← Category and location string → DB ID lookup
    │       └── providers/          ← Concrete AI provider implementations
    │           ├── base.py         ← AIProvider abstract base class + shared prompt + parser
    │           ├── anthropic_prov.py ← Claude (Anthropic) provider
    │           ├── openai_prov.py  ← GPT and any OpenAI-compatible server (incl. Ollama)
    │           ├── gemini_langgraph_prov.py  ← Gemini + LangGraph single-graph
    │           ├── gemini_multimodal_prov.py ← Gemini + LangGraph multimodal (RECOMMENDED)
    │           └── llm_service.py  ← Deprecated / unused
    │
    └── api/                        ← HTTP route handlers
        ├── routes_sources.py       ← CRUD: POST/GET/PATCH/DELETE /sources/
        ├── routes_ingest.py        ← POST /ingest/ — manual pipeline trigger
        ├── routes_ai_providers.py  ← CRUD + activate: /ai-providers/
        ├── routes_raw_ingestion.py ← GET /raw-ingestion/ — pipeline debugging
        ├── routes_filter_articles.py ← GET /filter-articles/ — stage 1 output
        ├── routes_post_processed.py  ← GET /post-processed/ — stage 2 output
        ├── routes_final_articles.py  ← GET/POST /final-articles/ — public feed
        └── routes_master_data.py   ← GET /master/categories|sub-categories|states
```

## Folder Roles Explained

### `app/core/` — The Foundation

This is where global infrastructure lives. Nothing in `core/` knows about news articles or AI. It only handles:
- **How to read configuration** (`config.py`) — reads `.env` file, makes all settings available as typed Python attributes
- **How to connect to the database** (`database.py`) — creates the connection pool, produces sessions
- **How to inject dependencies** (`deps.py`) — the "wiring" that tells FastAPI how to build services/repos per request

Think of `core/` as the utility belt — everything else reaches into it.

### `app/models/` — The Data Shapes

Models define the **structure of your database tables** in Python. Each model class corresponds to one database table. SQLAlchemy reads these class definitions and knows what SQL to generate.

Models contain **no business logic** — they are purely data containers. You would never call a function from another service inside a model.

### `app/repositories/` — The Database Gatekeepers

Repositories are the **only place where SQL queries are written**. Every time code needs to read or write from the database, it must go through a repository.

This strict rule means: if you want to understand how data gets into the database, look at the repository. If you want to add a new query, add it to the repository. No raw SQL or database calls appear anywhere else.

### `app/schemas/` — The API Contracts

Schemas are Pydantic models — they define the expected **shape of incoming requests** and the guaranteed **shape of outgoing responses**. They provide automatic validation (FastAPI rejects malformed requests with 422 errors) and automatic documentation (the `/docs` Swagger UI is generated from schemas).

### `app/services/` — The Business Logic

Services contain the **"how does the system work"** logic. The ingestion pipeline, the ranking algorithm, the AI provider selection, the search enrichment — all of this lives in services. Services:
- Orchestrate multiple repositories
- Call external APIs (AI providers, Google Search)
- Make decisions (Is this article worth saving? Which provider should I use?)
- Are independent from HTTP — they have no knowledge of request/response objects

### `app/api/` — The HTTP Interface

Route files **receive HTTP requests** and **return HTTP responses**. They are thin — they validate inputs, call services or repositories, and format responses. Route functions contain very little logic beyond calling the right service.

---

# 4. File-by-File Codebase Exploration

## `app/main.py` — The Application Entry Point

**Purpose:** Creates and configures the FastAPI application. This is the file the web server (`uvicorn`) imports to start the application.

**Responsibilities:**
- Creates the `FastAPI` app instance with title, version, and description
- Sets up the **lifespan context** — code that runs at startup and shutdown
- Configures **CORS middleware** — allows any website/app to call this API
- Registers all **8 routers** with their URL prefixes
- Provides a simple `GET /health` health check endpoint

**Interaction with other files:**
- Imports `start_scheduler` and `stop_scheduler` from `services/scheduler.py`
- Imports all 8 router objects from `api/routes_*.py` files
- Imports `app.models` (the package) to trigger model registration

**Key design decision:** The `lifespan` function uses Python's `asynccontextmanager` pattern. The code before `yield` runs at startup; the code after `yield` runs at shutdown. This ensures the scheduler starts when the server starts and stops cleanly when the server stops.

---

## `app/core/config.py` — Configuration Management

**Purpose:** Reads all configuration from the `.env` file and provides them as typed Python attributes. Any part of the codebase that needs a setting imports `settings` from this file.

**Responsibilities:**
- Loads the `.env` file using `pydantic-settings`
- Validates types (e.g., `DATABASE_URL` must be a string, `DEBUG` must be a boolean)
- Provides default values for optional settings
- Exposes a singleton `settings` object used across the entire app

**All available settings:**

| Setting | Type | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | str | required | PostgreSQL connection string |
| `DEBUG` | bool | False | SQL query logging |
| `ANTHROPIC_API_KEY` | str | None | Claude API key |
| `GEMINI_API_KEY` | str | None | Google Gemini API key |
| `OLLAMA_URL` | str | `http://localhost:11434/v1` | Ollama server URL |
| `OLLAMA_MODEL` | str | None | Ollama model name |
| `INGEST_INTERVAL_MINUTES` | int | 5 | How often to fetch news |
| `PUBLISH_INTERVAL_MINUTES` | int | 5 | How often to update rankings |
| `PUBLISH_OFFSET_SECONDS` | int | 30 | Delay between ingest and publish |
| `FEED_TOP_N` | int | 20 | How many articles in the public feed |
| `OLLAMA_REQUESTS_PER_MINUTE` | int | 60 | Ollama rate limit |
| `OLLAMA_MAX_ITEMS_PER_RUN` | int | 50 | Max articles per Ollama run |
| `OLLAMA_CONCURRENCY` | int | 1 | Parallel Ollama requests |
| `OLLAMA_BATCH_SIZE` | int | 10 | Articles per GPU batch |
| `OLLAMA_BATCH_COOLDOWN_SECONDS` | float | 15.0 | Pause between GPU batches |
| `CLOUD_REQUESTS_PER_MINUTE` | int | 3 | Cloud API rate limit |
| `CLOUD_MAX_ITEMS_PER_RUN` | int | 5 | Max articles per cloud run |
| `DECAY_FRESH` | float | 1.00 | Multiplier for <6h old articles |
| `DECAY_RECENT` | float | 0.75 | Multiplier for <24h old articles |
| `DECAY_DAY` | float | 0.50 | Multiplier for <72h old articles |
| `DECAY_WEEK` | float | 0.25 | Multiplier for <1 week old |
| `DECAY_OLD` | float | 0.10 | Multiplier for >1 week old |
| `GOOGLE_SEARCH_API_KEY` | str | None | Google Custom Search key |
| `GOOGLE_SEARCH_ENGINE_ID` | str | None | Google Search Engine ID |
| `GOOGLE_SEARCH_RESULTS_PER_ARTICLE` | int | 3 | Reference URLs per article |
| `GOOGLE_SEARCH_DELAY_SECONDS` | float | 1.0 | Throttle between searches |
| `GOOGLE_SEARCH_MAX_PER_RUN` | int | 10 | Max searches per scheduler run |

---

## `app/core/database.py` — Database Connection

**Purpose:** Creates and manages the database connection pool and provides a session factory.

**Key objects created here:**

1. **`engine`** — The connection pool. Creates up to 10 simultaneous connections (`pool_size=10`) with 20 overflow (`max_overflow=20`). This means at peak load, up to 30 connections to PostgreSQL can exist simultaneously.

2. **`AsyncSessionLocal`** — A factory function. Every time you call `AsyncSessionLocal()`, it creates a new database session (a transaction). The session is not a connection — SQLAlchemy manages the actual connection internally.

3. **`get_db()`** — An `async generator` function. FastAPI calls this as a dependency. The `async with AsyncSessionLocal()` pattern ensures the session is always closed, even if an error occurs. The `yield` keyword is what turns it into a generator — FastAPI gets the session from the yield, uses it for the request, then the `async with` block exits and the session closes.

**Why async?** The entire application is built on Python's `asyncio` — the event loop that handles multiple things simultaneously. Using `asyncpg` (the async PostgreSQL driver) means database queries don't block the event loop. When one request is waiting for a database query, the server can handle other requests.

---

## `app/core/deps.py` — Dependency Injection Wiring

**Purpose:** Provides FastAPI-compatible "dependency" functions that create repositories and services with a properly-injected database session.

**How it works:** FastAPI's `Depends()` mechanism calls a function and injects its return value into route handlers. `deps.py` defines one function per repository/service. Each function takes a `db: AsyncSession = Depends(get_db)` parameter — this causes FastAPI to first call `get_db()` (which creates a session), then pass that session to the function, which wraps it in a repository.

**Example chain:**
```
Request arrives at GET /sources/
    → FastAPI calls get_source_repo()
        → FastAPI calls get_db() to get a session
        → get_source_repo() creates SourceRepository(session)
    → Route handler receives SourceRepository as its `repo` argument
```

**Why this matters:** This pattern means each HTTP request gets its own fresh database session. Two simultaneous requests never share a session, so they don't interfere with each other. When the request finishes (whether successfully or with an error), the session is automatically closed.

---

## `app/models/base.py` — ORM Foundation

**Purpose:** Defines `Base`, the parent class for all ORM models.

**What it does:** In SQLAlchemy 2.x, `Base = DeclarativeBase()` creates a registry that tracks all classes that inherit from it. When you run `alembic upgrade head` or `create_all()`, SQLAlchemy scans this registry to know what tables to create.

---

## `app/models/source.py` — News Sources Table

**Purpose:** Defines the `news_sources` table. A "source" represents a news feed (RSS) or API endpoint (REST) that the system fetches from.

**Why sources are stored in the database (not hardcoded):** You can add or remove sources at runtime via `POST /sources/`. The scheduler reads from this table on every run. No code changes or server restarts needed to add a new news site.

**Key fields:**
- `url` — unique constraint means you can't add the same feed twice
- `type` — either `"rss"` or `"rest"` — determines which fetcher to use
- `config` — a JSONB field for extra metadata (e.g., HTTP headers for authenticated APIs)
- `is_active` — set to `false` to pause a source without deleting it

---

## `app/models/raw_event.py` — Raw Ingestion Table

**Purpose:** Defines the `raw_ingestion` table — the "inbox" of the pipeline. Every single article fetched from every source is saved here first, before any processing.

**Why save raw data?** Three reasons:
1. **Deduplication:** The `content_hash` field (SHA-256 of source_id + raw payload) uniquely identifies each article. If the same article appears in multiple fetches, the database's `UNIQUE` constraint on `content_hash` silently discards the duplicate.
2. **Replayability:** If the AI model is upgraded later, raw payloads can be reprocessed from scratch without re-fetching from the source.
3. **Audit trail:** You can see exactly what was received, when, and what happened to it.

**Status lifecycle:**
```
"pending"      → freshly stored, not yet AI-processed
"filtered"     → AI confirmed it's a crime article; filter_articles row exists
"filtered_out" → AI said it's not a crime article
"failed"       → processing crashed; error_message has details
```

**Key fields:**
- `content_hash` — SHA-256 fingerprint; the unique deduplication key
- `raw_payload` — the complete original article JSON
- `status` — tracks where in the pipeline this article is
- `normalized_by` — which AI model processed this (audit trail)
- `retry_count` — how many times processing was attempted

---

## `app/models/filter_article.py` — Filtered Articles Table

**Purpose:** Stores articles that passed AI classification as crime-related. This is Stage 1 output of the pipeline.

**Why a separate table from raw_ingestion?** Clean layer separation. `raw_ingestion` holds everything that was fetched; `filtered_articles` holds only the crime-related subset. Querying for crime articles doesn't require scanning millions of raw payloads.

**Key fields:**
- `main_url` — unique constraint prevents duplicate articles from multiple sources
- `sub_category_ids` — JSONB array of crime type strings (e.g. `["murder", "violence"]`)
- `category_ids` — JSONB array of parent category IDs
- `location_state_id` — FK to the `state` table for geographic filtering

---

## `app/models/post_processed_article.py` — Post-Processed Articles Table

**Purpose:** Stores AI-enriched articles with structured categories, single sub-category assignment, importance score, and reference URLs. This is Stage 2 output of the pipeline.

**Why a third table?** Post-processing refines the data from `filtered_articles`:
- `sub_category_ids` (multi-label array) → `sub_category_id` (single FK to master table)
- Adds `imp_score` (integer 1-100) for ranking
- Adds `reference_urls` (array of related article URLs from Google Search)
- Links to proper FK references instead of loose JSONB arrays

**Key fields:**
- `filter_article_id` — unique FK linking back to filtered_articles (one-to-one)
- `imp_score` — importance score 1-100; the primary ranking input
- `reference_urls` — PostgreSQL ARRAY(Text); NULL means "not yet searched", `[]` means "searched, nothing found"
- `sub_category_id` — FK to master_sub_category

---

## `app/models/final_article.py` — Final Articles Table (Public Feed)

**Purpose:** The terminal stage — stores the top-ranked articles that the public API serves.

**Why a fourth table?** Because `rank_score` is recalculated on every publishing cycle. The same article's score changes as it ages (time decay) and as newer articles arrive. Having a separate `final_articles` table makes these updates cheap (upsert on a small table). The `post_processed_articles` table is the enrichment store; `final_articles` is the curated public feed.

**Key fields:**
- `rank_score` — float, indexed, recomputed every 5 minutes
- `reference_urls` — copied from post_processed_articles at publish time

---

## `app/models/ai_provider.py` — AI Provider Config Table

**Purpose:** Stores AI provider credentials and settings in the database, allowing runtime switching without server restarts.

**Why store API keys in the database?** So the admin can:
- Switch from Gemini to Claude to Ollama at runtime via `PATCH /ai-providers/{id}/activate`
- Store multiple configurations and switch between them
- Never touch the server's `.env` file after initial setup

**Constraint:** At most ONE row has `is_active=True` at any time. The `activate()` repository method first sets all rows to `is_active=False`, then sets the target row to `True` — in a transaction so there's never a moment with zero or multiple active providers.

---

## `app/models/category.py` — Crime Category Tables

**Purpose:** Two-level crime taxonomy used to classify articles.

**Structure:**
```
MasterCategory (top-level)
  ├── Violent Crime
  ├── Financial Crime
  ├── Cybercrime
  └── Drug Crime

MasterSubCategory (specific type, belongs to one category)
  ├── Murder         → Violent Crime
  ├── Assault        → Violent Crime
  ├── Fraud          → Financial Crime
  └── Cybercrime     → Cybercrime
```

These are seeded via an Alembic data migration. Articles are classified against this taxonomy by the AI.

---

## `app/models/location.py` — Geographic Tables

**Purpose:** Two-level location hierarchy for tagging articles with where crimes occurred.

```
Country
  └── India
       ├── Maharashtra
       ├── Delhi
       ├── Tamil Nadu
       └── ...
```

Articles carry a `location_id` FK pointing to a `State` row. This enables filtering by state via the API.

---

## `app/services/ingestion_service.py` — The Pipeline Orchestrator

**Purpose:** Runs the complete news ingestion pipeline for a single source. This is the largest and most complex file — it coordinates fetch, filter, AI processing, resolve, and store in one function.

**Responsibilities:**
- Fetches articles from RSS or REST sources
- Computes SHA-256 content hashes for deduplication
- Stores raw payloads via `RawIngestionRepository`
- Applies keyword pre-filtering (no AI cost for obvious non-crime articles)
- Loads the active AI provider (from DB or env vars)
- Manages rate limiting and concurrency for AI calls
- Processes articles with AI (with retry on rate limit errors)
- Resolves AI text labels → database integer IDs
- Writes filtered and post-processed articles to the database
- Updates raw_ingestion statuses (filtered / filtered_out / failed)

---

## `app/services/publishing_service.py` — The Ranking Engine

**Purpose:** Selects the top N articles by importance and computes their `rank_score` using time decay, then publishes them to the `final_articles` table.

**The ranking formula:**
```
rank_score = imp_score × time_decay_factor(published_at)
```

Where `time_decay_factor` returns:
- `1.00` if the article is less than 6 hours old (full score — breaking news)
- `0.75` if less than 24 hours old
- `0.50` if less than 72 hours old
- `0.25` if less than 1 week old
- `0.10` if older than 1 week

This means a breaking news article with `imp_score=60` ranks as `60.0`, while a 2-day-old article with `imp_score=80` ranks only as `40.0`.

---

## `app/services/scheduler.py` — The Background Job Manager

**Purpose:** Configures and runs APScheduler, which automatically triggers the ingestion pipeline, search enrichment, and publishing jobs at regular intervals.

**Jobs registered:**
1. **`ingestion_all_sources`** — runs every 5 minutes, fetches and processes all active sources, then chains search enrichment and publishing if any articles were written
2. **`publish_final_feed`** — runs every 5 minutes + 30 seconds offset (the offset ensures it runs after the ingestion cycle)

**Key design:** `max_instances=1` on each job prevents the same job from running twice simultaneously. If ingestion takes longer than 5 minutes, the next scheduled run waits rather than starting a second overlapping run.

---

## `app/services/fetchers/rss_fetcher.py` — RSS Feed Fetcher

**Purpose:** Fetches and parses RSS/Atom feeds from a URL.

**Why `asyncio.to_thread()`?** The `feedparser.parse()` function is synchronous — it makes a blocking HTTP request. Calling blocking code directly in an async function would freeze the entire server. `asyncio.to_thread()` runs the blocking call in a thread pool so the event loop can continue handling other requests while the feed loads.

**Error handling:** If the XML is malformed (`feed.bozo == True`), the fetcher logs a warning but continues — feedparser often extracts valid articles from malformed XML. Only a complete network failure raises an exception.

---

## `app/services/fetchers/rest_fetcher.py` — REST API Fetcher

**Purpose:** Fetches articles from JSON REST API endpoints.

**Response shape handling:** Different APIs return data differently:
- `[{"title": "..."}, ...]` — bare list (handled directly)
- `{"articles": [...]}` — envelope with key "articles" (NewsAPI.org format)
- `{"items": [...]}` — envelope with key "items"
- `{"results": [...]}` — envelope with key "results"

The fetcher tries all common key names before giving up.

**Timeout:** `connect=5.0s` for establishing the connection, `15.0s` total for the complete response. This prevents the fetcher from hanging indefinitely on slow or unresponsive APIs.

---

## `app/services/source_normalizer.py` — Rule-Based Normalizer

**Purpose:** Converts raw feedparser objects or REST API dicts into a standard "canonical" article dict that the rest of the pipeline understands.

**Why needed?** RSS feeds and REST APIs use different field names:
- RSS uses `"link"` for the URL; REST APIs often use `"url"`
- RSS uses `"summary"` for description; REST uses `"description"`
- RSS dates are RFC 2822 format; REST dates are ISO 8601

The normalizer smooths over these differences with fallback logic.

**Two important helper functions:**

1. **`parse_date(raw)`** — Tries RFC 2822 first (RSS format), then ISO 8601 (REST format), converts to UTC timezone
2. **`to_plain_dict(obj)`** — feedparser returns `FeedParserDict` objects (special dict subclass) and struct-like objects. SQLAlchemy's JSONB column can only store plain Python types. This function recursively converts everything to plain Python dicts/lists/scalars.

---

## `app/services/search_enrichment_service.py` — Google Search Enrichment

**Purpose:** For each article that has never been searched (i.e., `reference_urls IS NULL`), fetches related article URLs from Google Custom Search and stores them.

**Idempotency design:** An article is searched exactly once in its lifetime:
- `reference_urls IS NULL` → never searched → eligible for this run
- `reference_urls = []` → searched before, nothing found → skip forever (sentinel)
- `reference_urls = [...]` → enriched → skip

This means the Google Search quota is spent on each article exactly once, not once per scheduler run.

---

## `app/services/normalization/providers/base.py` — AI Provider Contract

**Purpose:** Defines the `AIProvider` abstract base class that all AI providers must implement, the shared prompt, the output schema (Pydantic model), and the JSON parsing/extraction logic.

**The AI Prompt (SINGLE_PROCESS_PROMPT):** The prompt instructs the AI to:
1. First determine if the article is about crime
2. If not: return only `{"is_crime": false}`
3. If yes: extract title, rewrite it, extract URL, description, rewrite description, classify the crime type, locate it, and score its importance 1-100

This single-call design is efficient — one API call per article does all the work.

**`SingleOutput` Pydantic model:** Validates the AI's JSON response. Field validators ensure:
- URLs must start with `http://` or `https://`
- `sub_category` must be one of the 10 valid crime types
- `imp_score` is clamped to 1-100

**`_extract_json(text)`:** AI models sometimes wrap JSON in code fences (`` ```json ``), thinking blocks (`<think>...</think>`), or prose. This function strips all of that and extracts the raw JSON string.

---

## `app/services/normalization/provider_factory.py` — AI Provider Factory

**Purpose:** Creates and caches `AIProvider` instances from configuration objects. This is the **Factory Pattern** in action.

**Caching:** Creating an AI provider involves instantiating an SDK client with a connection pool. This is expensive. The factory caches providers in a module-level dict using `(config.id, model, api_key)` as the key. Subsequent calls return the cached instance.

**How to add a new provider:**
1. Create `app/services/normalization/providers/your_provider.py` with a class that inherits `AIProvider`
2. Add an import in `provider_factory.py`
3. Add an `if provider == "your_type"` branch in the `_build()` function
4. Add the type name to `SUPPORTED_PROVIDERS` in `models/ai_provider.py`

---

## `app/services/normalization/ai_processor.py` — Env-Var Fallback

**Purpose:** Provides a fallback AI provider when no provider is configured in the database. Reads environment variables and creates the appropriate provider.

**Resolution order:**
1. `OLLAMA_MODEL` env var → Ollama (local, no API key needed)
2. `GEMINI_API_KEY` → GeminiMultimodalLangGraphProvider (recommended)
3. `GEMINI_API_KEY` (fallback) → GeminiLangGraphProvider (if multimodal fails)
4. `ANTHROPIC_API_KEY` → AnthropicProvider
5. None of the above → returns `None` → ingestion skips AI entirely

---

## `app/repositories/raw_ingestion_repo.py` — Raw Data Access

**Purpose:** All database operations for the `raw_ingestion` table.

**Key functions:**

- **`compute_content_hash(source_id, raw_payload)`** — SHA-256 hash of `f"{source_id}:{json_sorted_payload}"`. Sorting the JSON keys ensures the hash is deterministic regardless of dict key order.

- **`store_batch(source_id, hash_raw_pairs)`** — Bulk inserts raw articles using PostgreSQL's `ON CONFLICT DO NOTHING`. Returns two things: a mapping of `{hash → row_id}`, and a set of hashes that still need processing (new rows + previously-failed pending rows for crash recovery).

- **`mark_filtered()`, `mark_filtered_out()`, `mark_failed()`** — Update status columns after AI processing completes.

---

## `app/repositories/source_repo.py` — Source Data Access

**Purpose:** CRUD operations for the `news_sources` table.

**Key pattern — `exclude_unset=True` in updates:**
```python
for field, value in data.model_dump(exclude_unset=True).items():
    setattr(source, field, value)
```

`exclude_unset=True` means only fields that were explicitly provided in the PATCH request are updated. If a client sends `{"is_active": false}`, only `is_active` changes — other fields like `name` and `url` stay unchanged. This is the correct behavior for `PATCH` endpoints (partial updates).

---

## `app/repositories/final_article_repo.py` — Feed Data Access

**Purpose:** Upserts ranked articles and reads the public news feed.

**`upsert_batch()`** uses PostgreSQL's `INSERT ... ON CONFLICT DO UPDATE`:
```sql
INSERT INTO final_articles (post_processed_article_id, title, rank_score, ...)
VALUES (...)
ON CONFLICT (post_processed_article_id) DO UPDATE
SET rank_score = excluded.rank_score, title = excluded.title, ...
```

This means: if a row for this article already exists, update it; otherwise insert it. The `rank_score` is updated on every publishing cycle, so the same article moves up or down in ranking as it ages.

**`get_feed()`** supports:
- `ORDER BY rank_score DESC` — highest-ranked articles first
- `JOIN` to filter by sub-category
- `ILIKE` for case-insensitive keyword search in title/description

---

## `app/api/routes_sources.py` — Source Management Routes

**Purpose:** HTTP endpoints for adding and managing news sources.

| Endpoint | Method | Purpose |
|---|---|---|
| `/sources/` | POST | Register a new RSS or REST source |
| `/sources/` | GET | List all sources |
| `/sources/{id}` | GET | Get one source |
| `/sources/{id}` | PATCH | Update source (e.g., disable it) |
| `/sources/{id}` | DELETE | Permanently remove source |

---

## `app/api/routes_ingest.py` — Manual Ingest Trigger

**Purpose:** Allows manually triggering the full ingestion pipeline for a specific source without waiting for the scheduler.

**Use case:** When you add a new source and want to immediately fetch its articles, call `POST /ingest/` with `{"source_id": 2}` instead of waiting up to 5 minutes for the next scheduler run.

---

## `app/api/routes_ai_providers.py` — AI Provider Management

**Purpose:** CRUD and activation endpoints for AI provider configurations.

| Endpoint | Method | Purpose |
|---|---|---|
| `/ai-providers/` | POST | Register a new provider config |
| `/ai-providers/` | GET | List all provider configs |
| `/ai-providers/active` | GET | Get the currently active provider |
| `/ai-providers/{id}` | GET | Get one provider config |
| `/ai-providers/{id}/activate` | PATCH | Make this provider active |
| `/ai-providers/active` | DELETE | Deactivate all providers |
| `/ai-providers/{id}` | DELETE | Remove a provider config |

**Security note:** The `api_key` field is stored in the database but is never returned in any API response — the schema excludes it.

---

## `app/api/routes_final_articles.py` — Public News Feed

**Purpose:** The main public endpoint that clients (mobile apps, websites) call to get the ranked news feed.

| Endpoint | Query Params | Purpose |
|---|---|---|
| `GET /final-articles/` | `limit`, `offset`, `sub_category_id`, `q` | Paginated ranked feed |
| `GET /final-articles/{id}` | — | Single article by ID |
| `POST /final-articles/publish` | `top_n` | Force immediate re-ranking |

The `q` parameter enables keyword search across title and description using SQL `ILIKE`.

---

# 5. Function-Level Code Explanation

## `compute_content_hash` — Deduplication Key

```python
def compute_content_hash(source_id: int, raw_payload: dict) -> str:
    payload_str = json.dumps(raw_payload, sort_keys=True, default=str)
    return hashlib.sha256(f"{source_id}:{payload_str}".encode()).hexdigest()
```

### What this function does
Creates a unique fingerprint (hash) for each article. If the same article is fetched twice, the hash will be identical both times.

### Parameters
- `source_id` — The database ID of the source. Included in the hash so the same article from two different sources produces two different hashes.
- `raw_payload` — The complete raw article dict from the fetcher.

### Logic Breakdown
1. `json.dumps(raw_payload, sort_keys=True, default=str)` — Converts the dict to a JSON string. `sort_keys=True` ensures keys are always in the same alphabetical order, making the string deterministic (a dict `{"b": 1, "a": 2}` and `{"a": 2, "b": 1}` produce the same sorted JSON). `default=str` handles non-serializable objects (like dates) by converting them to strings.
2. `f"{source_id}:{payload_str}"` — Prepends the source ID with a colon separator.
3. `hashlib.sha256(...).hexdigest()` — Computes the SHA-256 hash and returns it as a 64-character hex string.

### Return Value
A 64-character hex string like `"a3f5b2c1d4..."`.

### Why this function exists
Without deduplication, the same article would be processed by AI multiple times (once per 5-minute cycle, for as long as it remains in the RSS feed). That wastes AI quota and creates duplicate database rows. The hash is the single source of truth for "have we seen this article before?"

---

## `_has_crime_keywords` — Fast Pre-Filter

```python
_CRIME_KEYWORDS: frozenset[str] = frozenset({
    "murder", "kill", "killed", "arrest", "robbery", "fraud",
    "terror", "drug", "kidnap", "gang", "corrupt", "hack",
    "crime", "criminal", "violence", "victim", ...
})

def _has_crime_keywords(raw: dict) -> bool:
    text = " ".join(filter(None, [
        str(raw.get("title", "")),
        str(raw.get("summary", "")),
        str(raw.get("description", "")),
        str(raw.get("content", "")),
    ])).lower()
    return any(kw in text for kw in _CRIME_KEYWORDS)
```

### What this function does
Checks if a raw article contains any crime-related words. Returns `True` if it does, `False` if it clearly has no crime content.

### Logic Breakdown
1. Concatenates `title`, `summary`, `description`, and `content` fields into one big string
2. `filter(None, [...])` removes empty/None values
3. `.lower()` makes the check case-insensitive
4. `any(kw in text for kw in _CRIME_KEYWORDS)` — returns `True` as soon as the first keyword is found (short-circuit evaluation — stops at first match)

### Why it uses `frozenset`
`frozenset` is immutable and has O(1) lookup. More importantly, the `in text` check (substring search) is fast because `text` is a plain string. The `frozenset` itself isn't used for the lookup — it's used to iterate keywords.

### Why this exists before AI
An AI API call costs money and time. This keyword check is instant and free. A sports article about a cricket match never contains the word "murder" or "arrest" — we can skip the AI call entirely. This reduces AI costs significantly (often 40-60% of articles are pre-filtered).

---

## `_time_decay_factor` — Freshness Score

```python
def _time_decay_factor(published_at: datetime | None) -> float:
    if published_at is None:
        return settings.DECAY_DAY   # Default to 50% if date unknown

    now = datetime.now(tz=timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)

    hours_old = (now - published_at).total_seconds() / 3600

    if hours_old < 6:
        return settings.DECAY_FRESH    # 1.00
    if hours_old < 24:
        return settings.DECAY_RECENT   # 0.75
    if hours_old < 72:
        return settings.DECAY_DAY      # 0.50
    if hours_old < 168:
        return settings.DECAY_WEEK     # 0.25
    return settings.DECAY_OLD          # 0.10
```

### What this function does
Returns a multiplier (between 0.10 and 1.00) based on how old an article is. Fresh articles get higher multipliers.

### Logic Breakdown
1. If `published_at` is `None` (date not known), uses the `DECAY_DAY` default (0.50) — a conservative middle value.
2. If the datetime has no timezone info (a "naive" datetime), assumes it's UTC.
3. Computes age in hours using Python's datetime subtraction.
4. Returns the appropriate decay factor based on age brackets.

### Why this matters
Without time decay, an important story from 2 years ago would rank above a breaking story from today if it had a higher importance score. Time decay ensures recent news dominates the feed.

---

## `_RateLimiter.wait` — API Rate Limiter

```python
class _RateLimiter:
    def __init__(self, rpm: int) -> None:
        self._interval = (60.0 / rpm) if rpm > 0 else 0.0
        self._lock = asyncio.Lock()
        self._last: float = 0.0

    async def wait(self) -> None:
        if self._interval == 0.0:
            return
        async with self._lock:
            elapsed = _time.monotonic() - self._last
            gap = self._interval - elapsed
            if gap > 0:
                await asyncio.sleep(gap)
            self._last = _time.monotonic()
```

### What this class does
Enforces a maximum number of AI API calls per minute. If you set `rpm=60`, it ensures calls are spaced at least 1 second apart.

### How `_interval` is computed
`60.0 / rpm` = seconds between calls. For `rpm=60`: interval = 1.0s. For `rpm=3`: interval = 20.0s.

### The `asyncio.Lock()`
Multiple concurrent AI calls could try to run simultaneously. The `Lock` ensures only one coroutine at a time checks and updates `_last`. Without the lock, two calls could both see that "enough time has passed" and both proceed simultaneously, defeating the rate limiting.

### `_time.monotonic()`
A monotonic clock that never goes backward (unlike `time.time()` which can jump if the system clock is adjusted). Used for measuring elapsed time accurately.

---

## `IngestionService.ingest` — The Pipeline Orchestrator

```python
async def ingest(self, source: Source) -> int:
    """Run the full ingestion pipeline for one source. Returns post_processed count."""
    raw_items = await self._fetch_items(source)
    # ... load AI provider, compute hashes, store raw, keyword filter,
    # AI process (with batching + rate limiting), resolve FKs, insert to DB
    return count
```

### What this function does
Runs the complete pipeline from fetch to post-processed article storage for a single news source.

### Step-by-step logic

**Step 1 — Fetch:**
```python
raw_items = await self._fetch_items(source)
```
Calls RSSFetcher or RestFetcher depending on `source.type`. Returns a list of raw dicts.

**Step 2 — Load AI provider:**
```python
ai_provider, provider_type = await self._load_ai_provider()
```
Tries the database first, falls back to env vars. Returns the provider object and its type string (for rate limit selection).

**Step 3 — Cap items:**
```python
_, max_items = _limits_for_provider(provider_type)
raw_items = raw_items[:max_items]
```
Cloud APIs have low rate limits; Ollama is local. The cap prevents spending the entire daily quota on one source.

**Step 4 — Hash and store raw:**
```python
all_pairs = [(compute_content_hash(source.id, raw), raw) for raw in raw_items]
hash_to_raw_id, unprocessed_hashes = await self.raw_repo.store_batch(source.id, all_pairs)
```
Computes all hashes in one pass, stores them in bulk, gets back which ones are new.

**Step 5 — Keyword pre-filter:**
```python
items = [(ch, raw) for ch, raw in new_pairs if _has_crime_keywords(raw)]
```
Discards non-crime articles without calling AI.

**Step 6 — AI processing with concurrency control:**
```python
rate_limiter, semaphore = _get_limiter_for(provider_type)

async def process_with_semaphore(content_hash, raw):
    async with semaphore:
        await rate_limiter.wait()
        result = await self._process_one(raw, source.type, ai_provider)
        return content_hash, result
```
The `semaphore` limits concurrent AI calls (e.g., 1 for Ollama). The `rate_limiter` spaces calls over time (e.g., 1 per second for 60 RPM).

**Step 7 — GPU batching (Ollama only):**
```python
batch_size = settings.OLLAMA_BATCH_SIZE if provider_type == "ollama" else len(items)
cooldown = settings.OLLAMA_BATCH_COOLDOWN_SECONDS if provider_type == "ollama" else 0.0

for batch_start in range(0, len(items), batch_size):
    batch = items[batch_start:batch_start + batch_size]
    await asyncio.gather(*[process_with_semaphore(ch, raw) for ch, raw in batch])
    await asyncio.sleep(cooldown)  # GPU cooldown between batches
```
Without batch cooldowns, continuous GPU load causes thermal throttling (the GPU slows down to cool down). A 15-second pause every 10 articles prevents this.

**Step 8 — Resolve FKs:**
```python
article["sub_category_id"] = cat_resolver.resolve(article.get("sub_category"))
article["location_id"] = loc_resolver.resolve(article.get("location"))
```
AI returns text strings like `"murder"` and `"Mumbai, Maharashtra"`. The resolvers look up the corresponding integer IDs in the master tables.

**Step 9 — Write to database:**
```python
url_to_filter_id = await self.filter_article_repo.insert_batch(crime_articles, hash_to_raw_id)
count = await self.post_processed_repo.insert_batch(crime_articles, url_to_filter_id)
```
Batch inserts are far more efficient than one-by-one inserts.

### Return Value
The number of post-processed articles written to the database.

---

## `IngestionService._call_with_retry` — Retry with Exponential Backoff

```python
async def _call_with_retry(self, coro_fn, label: str) -> dict | None:
    delay = settings.AI_RETRY_DELAY_SECONDS
    for attempt in range(settings.AI_RETRY_ATTEMPTS):
        try:
            return await coro_fn()
        except Exception as exc:
            if _is_rate_limit_error(exc) and attempt < settings.AI_RETRY_ATTEMPTS - 1:
                wait = delay * (2 ** attempt)
                await asyncio.sleep(wait)
                continue
            logger.error("%s failed: %s", label, exc)
            return None
    return None
```

### What exponential backoff means
- Attempt 1 fails with rate limit → wait `15 × 2⁰ = 15` seconds
- Attempt 2 fails → wait `15 × 2¹ = 30` seconds
- Attempt 3 fails → log error, return `None`

This respects the API's rate limit. Simply retrying immediately would hit the same limit again. Waiting longer gives the quota time to reset.

---

## `PublishingService.publish` — Feed Publication

```python
async def publish(self, top_n: int = 20) -> int:
    top_articles = await self._post_processed_repo.get_top_by_imp_score(limit=top_n)

    rows = []
    for article in top_articles:
        rank_score = _compute_rank_score(article)
        rows.append({
            "post_processed_article_id": article.id,
            "title": article.title,
            "rank_score": rank_score,
            ...
        })

    count = await self._final_article_repo.upsert_batch(rows)
    return count
```

### What this function does
Selects the top `top_n` articles by importance score, computes their rank scores (importance × decay), and upserts them into `final_articles`.

### Why "upsert" and not "insert"
An article that was in yesterday's top 20 might still be in today's top 20, but with a lower rank score (because it's older now). Upserting means: "insert if new, update if already exists." This way the article's `rank_score` is always current.

---

## `SearchEnrichmentService.enrich` — Reference URL Population

```python
async def enrich(self) -> int:
    unenriched = await self._repo.get_without_reference_urls(
        limit=settings.GOOGLE_SEARCH_MAX_PER_RUN
    )

    for article in unenriched:
        urls = await fetch_related_urls(article.title)

        if urls:
            await self._repo.update_reference_urls(article.id, urls)
        else:
            await self._repo.mark_reference_urls_searched(article.id)  # store []

        await asyncio.sleep(delay)  # quota guard
```

### What this function does
For each article that has `reference_urls IS NULL`, searches Google for related articles and stores the resulting URLs. If Google returns nothing, stores an empty list `[]` as a sentinel.

### The sentinel pattern
- `NULL` = "never searched" → eligible for future enrichment
- `[]` = "searched, found nothing" → skip forever
- `[url1, url2]` = "enriched" → skip forever

Without the sentinel, every scheduler run would search the same "no-results" articles over and over, wasting the daily Google Search quota (100 free queries/day).

---

# 6. Application Execution Flow

## Server Startup Sequence

**Step 1:** Developer runs the server:
```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Step 2:** uvicorn imports `app.main` and finds the `app` variable (the FastAPI instance).

**Step 3:** Python imports `app.main`. This triggers:
- `import app.models` — This imports the `app/models/__init__.py` file which imports all model classes. SQLAlchemy registers all the ORM tables in its internal metadata registry. This must happen before any query runs.
- All 8 `from app.api.routes_*.py import router` statements — Loads route definitions
- `from app.services.scheduler import start_scheduler, stop_scheduler` — Loads scheduler functions

**Step 4:** The `app = FastAPI(...)` line creates the application. The `lifespan=lifespan` parameter tells FastAPI to call the lifespan context manager.

**Step 5:** `app.add_middleware(CORSMiddleware, ...)` — Registers CORS middleware. Every HTTP response will include `Access-Control-Allow-Origin: *` headers, allowing any browser to call the API.

**Step 6:** Eight `app.include_router(...)` calls register all routes with their URL prefixes. FastAPI internally builds a routing table.

**Step 7:** uvicorn calls the `lifespan` context manager. The code before `yield` runs:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()  ← runs here (before yield = startup)
    yield
    stop_scheduler()   ← runs here (after yield = shutdown)
```

**Step 8:** `start_scheduler()` creates two APScheduler jobs and starts the scheduler. From this point on, the ingestion and publishing jobs fire automatically.

**Step 9:** uvicorn starts listening on port 8000. The server is ready.

## How Routes Are Registered

When `app.include_router(final_article_router, prefix="/final-articles", tags=["Feed"])` runs:
- FastAPI takes all `@router.get("/")`, `@router.get("/{id}")`, `@router.post("/publish")` decorators defined in `routes_final_articles.py`
- Prepends `/final-articles` to each path
- Resulting routes: `GET /final-articles/`, `GET /final-articles/{article_id}`, `POST /final-articles/publish`
- Adds them to the application's routing table

FastAPI builds an OpenAPI schema from all registered routes. This schema powers the `/docs` Swagger UI automatically.

---

# 7. Request Lifecycle Walkthrough

## Example: `GET /final-articles/?limit=10&q=murder`

### Step 1: Client sends request
A mobile app sends:
```
GET /final-articles/?limit=10&q=murder HTTP/1.1
Host: api.example.com
```

### Step 2: uvicorn receives the request
uvicorn (the ASGI server) receives the TCP connection and passes the HTTP request to FastAPI.

### Step 3: FastAPI matches the route
FastAPI's router looks at the path `/final-articles/` and the method `GET`. It finds the matching handler: `list_final_articles()` in `routes_final_articles.py`.

### Step 4: FastAPI validates query parameters
FastAPI reads `limit=10` and `q=murder` from the URL. It validates:
- `limit=10` is an integer, >= 1, <= 100 ✓
- `q="murder"` is a string ✓
- `offset` was not provided; defaults to 0 ✓
- `sub_category_id` was not provided; defaults to None ✓

If validation fails (e.g., `limit=abc`), FastAPI automatically returns a 422 error.

### Step 5: Dependency injection runs
FastAPI sees `repo: FinalArticleRepository = Depends(get_final_article_repo)`. It:
1. Calls `get_db()` — creates an `AsyncSession` (database session)
2. Calls `get_final_article_repo(db=session)` — wraps session in `FinalArticleRepository`
3. Passes the `FinalArticleRepository` to the route handler as `repo`

### Step 6: Route handler calls repository

```python
async def list_final_articles(limit, offset, sub_category_id, q, repo):
    items = await repo.get_feed(limit=limit, offset=offset, sub_category_id=None, q=q)
    total = await repo.count(sub_category_id=None, q=q)
    return FinalArticleListResponse(total=total, limit=limit, offset=offset, items=items)
```

### Step 7: Repository runs SQL query

`get_feed()` builds this SQL:
```sql
SELECT *
FROM final_articles
WHERE (title ILIKE '%murder%' OR description ILIKE '%murder%')
ORDER BY rank_score DESC
LIMIT 10
OFFSET 0;
```

SQLAlchemy sends this query to PostgreSQL via asyncpg. Because this is async, the event loop can handle other incoming requests while waiting for the database.

### Step 8: SQLAlchemy maps results
PostgreSQL returns rows. SQLAlchemy's ORM maps each row to a `FinalArticle` Python object.

### Step 9: Pydantic serializes the response
FastAPI sees the `response_model=FinalArticleListResponse` annotation. It calls Pydantic to:
- Validate that each `FinalArticle` object has the required fields
- Convert Python objects to plain JSON-serializable dicts
- The schema excludes any internal fields not needed by clients

### Step 10: FastAPI sends HTTP response
```
HTTP/1.1 200 OK
Content-Type: application/json

{
  "total": 47,
  "limit": 10,
  "offset": 0,
  "items": [
    {
      "id": 142,
      "title": "Three Arrested for Murder in Mumbai",
      "rank_score": 63.5,
      ...
    },
    ...
  ]
}
```

### Step 11: Cleanup
The `async with AsyncSessionLocal()` block in `get_db()` exits. The database session is closed and the connection returned to the pool.

---

# 8. Data Flow Through the System

## Complete Data Journey of One Article

Let's trace one news article — a murder story from an RSS feed — through the entire system.

```
External RSS Feed: Times of India Crime RSS
    ↓
RSSFetcher.fetch(url)
    └── feedparser.parse(url) in thread pool
    └── Returns FeedParserDict entries
    ↓
to_plain_dict(entry)
    └── Converts FeedParserDict → plain Python dict
    └── Example: {"title": "3 Held in Mumbai Murder Case", "link": "https://...", ...}
    ↓
compute_content_hash(source_id=1, raw=entry_dict)
    └── SHA-256 hash = "a3b5c2..."
    ↓
RawIngestionRepository.store_batch()
    └── INSERT INTO raw_ingestion (source_id=1, content_hash="a3b5c2...",
                                   raw_payload={...}, status="pending")
        ON CONFLICT DO NOTHING
    └── Returns: this hash is new → needs processing
    ↓
_has_crime_keywords(raw)
    └── "murder" found in title → True → keep this article for AI
    ↓
rate_limiter.wait() + semaphore.acquire()
    └── Ensures we don't exceed API rate limits
    ↓
AIProvider.process(raw_payload, source_type="rss")
    └── Builds JSON message with the raw payload
    └── Sends to AI model (e.g., Gemini)
    └── AI responds with JSON:
        {
          "is_crime": true,
          "title": "3 Held in Mumbai Murder Case",
          "rewritten_title": "Police Arrest Three Suspects in Mumbai Murder Investigation",
          "url": "https://timesofindia.com/article/...",
          "sub_category": "murder",
          "sub_category_ids": ["murder", "violence"],
          "location": "Mumbai, Maharashtra",
          "imp_score": 42,
          ...
        }
    ↓
parse_single_output(ai_text, raw_payload)
    └── Strips any thinking blocks or code fences
    └── Parses JSON
    └── Validates with SingleOutput Pydantic model
    └── Returns cleaned Python dict
    ↓
CategoryResolver.resolve("murder") → sub_category_id = 3
CategoryResolver.resolve_categories_from_ids([3]) → category_ids = [1]
LocationResolver.resolve("Mumbai, Maharashtra") → location_state_id = 12
    └── Lookups in pre-loaded dicts (from master_category + state tables)
    ↓
FilterArticleRepository.insert_batch([article], hash_to_raw_id)
    └── INSERT INTO filtered_articles
            (raw_ingestion_id, title, main_url, sub_category_ids, location_state_id, ...)
        ON CONFLICT (main_url) DO NOTHING
    └── Returns: {url → filter_article_id}
    ↓
PostProcessedArticleRepository.insert_batch([article], url_to_filter_id)
    └── INSERT INTO post_processed_articles
            (filter_article_id, title, sub_category_id, location_id, imp_score=42, ...)
        ON CONFLICT (filter_article_id) DO NOTHING
    ↓
RawIngestionRepository.mark_filtered()
    └── UPDATE raw_ingestion SET status="filtered", normalized_by="gemini-2.0-flash"
        WHERE content_hash = "a3b5c2..."
    ↓
[5 minutes later — SearchEnrichmentService runs]
    ↓
GoogleSearchService.fetch_related_urls("Police Arrest Three Suspects in Mumbai Murder")
    └── Calls Google Custom Search API
    └── Returns ["https://ndtv.com/...", "https://hindustantimes.com/..."]
    ↓
PostProcessedArticleRepository.update_reference_urls(id=47, urls=[...])
    └── UPDATE post_processed_articles SET reference_urls = ARRAY[url1, url2]
        WHERE id = 47
    ↓
[PublishingService runs]
    ↓
PostProcessedArticleRepository.get_top_by_imp_score(limit=20)
    └── SELECT * FROM post_processed_articles ORDER BY imp_score DESC LIMIT 20
    └── Article with imp_score=42 is in the top 20
    ↓
_compute_rank_score(article)
    └── published_at was 2 hours ago → hours_old < 6 → decay = 1.00 (FRESH)
    └── rank_score = 42 × 1.00 = 42.0
    ↓
FinalArticleRepository.upsert_batch([...])
    └── INSERT INTO final_articles (post_processed_article_id=47, rank_score=42.0, ...)
        ON CONFLICT (post_processed_article_id) DO UPDATE SET rank_score = 42.0
    ↓
[Client calls GET /final-articles/]
    ↓
FinalArticleRepository.get_feed()
    └── SELECT * FROM final_articles ORDER BY rank_score DESC LIMIT 20
    └── Article appears with rank_score=42.0
    ↓
JSON response returned to client
```

---

# 9. Database Architecture

## All 9 Tables Explained

### Table 1: `news_sources`

**Purpose:** Registry of all news feeds the system ingests from.

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL (auto-increment) | Primary key |
| `name` | VARCHAR | Human-readable name (e.g., "Times of India Crime RSS") |
| `type` | VARCHAR | Either `"rss"` or `"rest"` |
| `url` | VARCHAR UNIQUE | The feed URL — unique so you can't add the same feed twice |
| `config` | JSONB | Extra metadata (e.g., `{"headers": {"Authorization": "Bearer KEY"}}`) |
| `is_active` | BOOLEAN | `true` = include in scheduler runs; `false` = paused |
| `created_at` | TIMESTAMPTZ | When this source was added |

---

### Table 2: `raw_ingestion`

**Purpose:** The inbox/audit log — every article ever fetched from any source.

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL | Primary key |
| `source_id` | INTEGER FK | References `news_sources.id` (CASCADE DELETE) |
| `content_hash` | VARCHAR(64) UNIQUE | SHA-256 fingerprint; deduplication key |
| `raw_payload` | JSONB | Complete original article JSON |
| `status` | VARCHAR(20) | `pending`, `filtered`, `filtered_out`, or `failed` |
| `normalized_by` | VARCHAR(200) | Which AI model processed this article |
| `error_message` | TEXT | Error details if processing failed |
| `retry_count` | SMALLINT | How many processing attempts were made |
| `created_at` | TIMESTAMPTZ | When the article was first fetched |
| `processed_at` | TIMESTAMPTZ | When AI processing completed |

---

### Table 3: `filtered_articles`

**Purpose:** Crime-confirmed articles after the AI filtering stage.

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL | Primary key |
| `raw_ingestion_id` | INTEGER FK UNIQUE | References `raw_ingestion.id` — one-to-one |
| `title` | VARCHAR | Article headline |
| `description` | TEXT | Article summary |
| `image_url` | VARCHAR | Article thumbnail URL |
| `main_url` | VARCHAR UNIQUE | Article canonical URL — prevents cross-source duplicates |
| `published_at` | TIMESTAMPTZ | When the article was published |
| `sub_category_ids` | JSONB | Array of crime type strings (e.g., `["murder", "violence"]`) |
| `category_ids` | JSONB | Array of parent category IDs |
| `location_state_id` | INTEGER FK | References `state.id` |
| `created_at` | TIMESTAMPTZ | When this row was created |

---

### Table 4: `post_processed_articles`

**Purpose:** AI-enriched articles with importance scoring and structured categories.

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL | Primary key |
| `filter_article_id` | INTEGER FK UNIQUE | References `filtered_articles.id` — one-to-one |
| `title` | VARCHAR | AI-rewritten headline |
| `description` | TEXT | AI-rewritten description |
| `image_url` | VARCHAR | Article thumbnail URL |
| `reference_urls` | ARRAY(TEXT) | Related article URLs from Google Search |
| `published_at` | TIMESTAMPTZ | Original article publish date |
| `sub_category_id` | INTEGER FK | References `master_sub_category.id` (single category) |
| `location_id` | INTEGER FK | References `state.id` |
| `imp_score` | INTEGER | Importance score 1-100 from AI |
| `created_at` | TIMESTAMPTZ | When this row was created |

---

### Table 5: `final_articles`

**Purpose:** The public news feed — top-ranked articles ready for client consumption.

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL | Primary key |
| `post_processed_article_id` | INTEGER FK UNIQUE | References `post_processed_articles.id` |
| `title` | VARCHAR | Article headline |
| `description` | TEXT | Article description |
| `image_url` | VARCHAR | Thumbnail URL |
| `reference_urls` | ARRAY(TEXT) | Related article URLs |
| `rank_score` | FLOAT (indexed) | Computed ranking score; updated every publishing cycle |
| `created_at` | TIMESTAMPTZ | When this row was first created |

---

### Table 6: `ai_provider_configs`

**Purpose:** Runtime AI provider configuration — allows switching providers without restarting the server.

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL | Primary key |
| `name` | VARCHAR(100) | User-defined label (e.g., "My Gemini Config") |
| `provider` | VARCHAR(50) | Provider type: `ollama`, `gemini`, `anthropic`, etc. |
| `model` | VARCHAR(100) | Model name (e.g., `"gemini-2.0-flash"`) |
| `api_key` | VARCHAR(500) | API key (never returned in API responses) |
| `base_url` | VARCHAR(500) | Custom endpoint URL (for Ollama, vLLM, etc.) |
| `is_active` | BOOLEAN | At most one row is `true` at any time |
| `created_at` | TIMESTAMPTZ | When this config was created |

---

### Table 7: `master_category`

**Purpose:** Top-level crime classification taxonomy (seeded data, rarely changes).

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL | Primary key |
| `name` | VARCHAR(100) UNIQUE | Category name (e.g., "Violent Crime") |
| `description` | TEXT | Human-readable description |
| `priority_point` | INTEGER | UI ordering weight |
| `is_active` | BOOLEAN | Whether this category appears in the UI |
| `created_at` | TIMESTAMPTZ | When this row was seeded |

---

### Table 8: `master_sub_category`

**Purpose:** Specific crime types within each top-level category.

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL | Primary key |
| `category_id` | INTEGER FK | References `master_category.id` (RESTRICT delete) |
| `name` | VARCHAR(100) | Sub-category name (e.g., "Murder", "Fraud") |
| `description` | TEXT | Description |
| `priority_point` | INTEGER | UI ordering weight |
| `is_active` | BOOLEAN | Active flag |
| `created_at` | TIMESTAMPTZ | Created timestamp |

---

### Table 9: `country` and `state`

**Purpose:** Geographic reference data for location tagging.

**`country`:**

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL | Primary key |
| `name` | VARCHAR(100) UNIQUE | Country name (e.g., "India") |

**`state`:**

| Column | Type | Description |
|---|---|---|
| `id` | SERIAL | Primary key |
| `country_id` | INTEGER FK | References `country.id` (RESTRICT delete) |
| `name` | VARCHAR(100) | State/province name (e.g., "Maharashtra") |

---

# 10. Database Relationships

## Entity Relationship Overview

```
country (1)
    └── has many → state (N)

master_category (1)
    └── has many → master_sub_category (N)

news_sources (1)
    └── has many → raw_ingestion (N)
                       └── has one → filtered_articles (1)
                                         └── has one → post_processed_articles (1)
                                                            └── has one → final_articles (1)

master_sub_category (1)
    └── has many → post_processed_articles (N)

state (1)
    └── has many → post_processed_articles (N)
    └── has many → filtered_articles (N)

ai_provider_configs — standalone (no FK relationships)
```

## Relationship Details

### One-to-Many: `news_sources` → `raw_ingestion`
One news source produces many raw articles over time. Each raw article belongs to exactly one source. The `CASCADE` on delete means if a source is deleted, all its raw articles are deleted too.

### One-to-One: `raw_ingestion` → `filtered_articles`
Each raw article produces at most one filtered article. The `UNIQUE` constraint on `raw_ingestion_id` enforces this. The `SET NULL` on delete means if a raw ingestion row is deleted, the filtered article row keeps its data but its `raw_ingestion_id` becomes NULL (the filtered article is not deleted).

### One-to-One: `filtered_articles` → `post_processed_articles`
Each filtered article produces at most one post-processed article. Same unique constraint + SET NULL pattern.

### One-to-One: `post_processed_articles` → `final_articles`
Each post-processed article appears at most once in the final feed.

### Many-to-One: `post_processed_articles` → `master_sub_category`
Many articles can be classified under the same crime type. For example, hundreds of murder articles all reference the same `master_sub_category` row for "murder."

### Many-to-One: `post_processed_articles` → `state`
Many articles can be tagged to the same state.

### Many-to-One: `master_sub_category` → `master_category`
Many sub-categories belong to one parent category. `RESTRICT` on delete means you can't delete a category if sub-categories still reference it.

## Why These Relationships Exist

The chain `raw_ingestion → filtered_articles → post_processed_articles → final_articles` forms a **pipeline audit trail**. At any point in time, you can trace any final article all the way back to the exact raw JSON payload that was fetched from the original RSS feed.

This is valuable for:
- Debugging (why did this article appear in the feed?)
- Reprocessing (if AI quality improves, raw payloads can be reprocessed)
- Auditing (what was the original source content before AI rewrote it?)

---

# 11. External Services and Integrations

## RSS Feeds

**Protocol:** HTTP GET to an XML URL
**Library:** `feedparser`
**What it returns:** A structured object with `feed.entries` — a list of articles
**Fields available:** `title`, `link`, `summary`, `published`, `media_thumbnail`, `content`

**Example feed URL:**
```
https://timesofindia.indiatimes.com/rss.cms
```

**How integrated:** `RSSFetcher.fetch(url)` calls `feedparser.parse(url)` in a thread pool (to avoid blocking async), returns the parsed feed object, whose `.entries` are converted to plain dicts via `to_plain_dict()`.

---

## REST API News Sources

**Protocol:** HTTP GET returning JSON
**Library:** `httpx`
**Supported response formats:**
- Bare list: `[{"title": "..."}, ...]`
- Envelope with key "articles", "items", "results", or "data"

**Example:** NewsAPI.org format:
```json
{
  "status": "ok",
  "totalResults": 1547,
  "articles": [
    {"title": "...", "url": "...", "publishedAt": "..."},
    ...
  ]
}
```

**How integrated:** `RestFetcher.fetch(url, headers=headers)` makes the HTTP request, handles the response shape detection, and returns a flat list of article dicts.

---

## AI Language Models

### Ollama (Local)
**Protocol:** OpenAI-compatible REST API at `http://localhost:11434/v1`
**Authentication:** No real API key needed (uses `"ollama"` as placeholder)
**Rate limiting:** 60 RPM (local, no cloud quotas)
**Concurrency:** 1 (single GPU)
**Model examples:** `dengcao/Qwen3-30B-A3B-Instruct-2507:latest`

**How it works:** The `OpenAICompatibleProvider` uses the `openai` Python SDK with a custom `base_url`. The OpenAI SDK is not limited to OpenAI — any server implementing the `/v1/chat/completions` endpoint works.

### Google Gemini
**Protocol:** Google AI API (via `langchain-google-genai`)
**Authentication:** `GEMINI_API_KEY`
**Recommended provider:** `gemini_multimodal` — uses LangGraph for structured multi-step processing with DuckDuckGo web search enrichment
**Rate limiting:** 3 RPM (free tier conservative estimate)

**How LangGraph is used:** LangGraph is a framework for building AI agents as directed graphs. The multimodal provider runs a two-stage graph: Stage 1 classifies the article; Stage 2 enriches it with web search results and assigns the final importance score.

### Anthropic Claude
**Protocol:** Anthropic API
**Authentication:** `ANTHROPIC_API_KEY`
**Model used by default:** `claude-haiku-4-5-20251001`
**Rate limiting:** 3 RPM (free tier)

**How integrated:** The `AnthropicProvider` uses the `anthropic` Python SDK to make chat completion requests. The same `SINGLE_PROCESS_PROMPT` from `base.py` is used.

### OpenAI GPT
**Protocol:** OpenAI API
**Authentication:** `OPENAI_API_KEY`
**Model used by default:** `gpt-4o-mini`
**Rate limiting:** 3 RPM (conservative default)

**Custom servers (vLLM, LM Studio):** Any server implementing the OpenAI chat completions API works using the `"custom"` provider type with a custom `base_url`.

---

## Google Custom Search API

**Purpose:** Finds related articles for each crime story (reference URLs).
**Free tier:** 100 queries per day
**Results per article:** Configurable (default 3)
**Authentication:** `GOOGLE_SEARCH_API_KEY` + `GOOGLE_SEARCH_ENGINE_ID`

**How it works:**
```
Article title: "Three Arrested in Mumbai Murder Case"
    ↓
Google Custom Search query: "Three Arrested in Mumbai Murder Case"
    ↓
Returns: top 3 related URLs from configured search engine
    ↓
Stored in post_processed_articles.reference_urls
    ↓
Included in final_articles.reference_urls
    ↓
Returned to clients as context/related reading
```

**Quota management:** `GOOGLE_SEARCH_MAX_PER_RUN` caps searches per scheduler run. But since each article is searched exactly once, the real quota spend equals the number of new articles added to the system (not the number of scheduler runs).

---

# 12. Error Handling Strategy

## Layer-by-Layer Error Handling

### Fetcher Layer (Network Errors)

```python
# rss_fetcher.py
try:
    feed = await asyncio.to_thread(feedparser.parse, url)
except Exception as exc:
    logger.error("RSS fetch failed for %s: %s", url, exc)
    raise RuntimeError(f"Failed to fetch RSS feed: {url}") from exc
```

**Strategy:** Log the error and raise. The IngestionService catches it at the source level:
```python
async def _fetch_items(self, source: Source) -> list[dict]:
    try:
        if source.type == "rss":
            ...
    except Exception as exc:
        logger.error("Fetch failed for source_id=%s: %s", source.id, exc)
        return []  # ← Return empty list; don't crash the entire scheduler run
```

If one source fails, the other sources still get processed. The scheduler run continues.

### AI Processing Layer (Rate Limits + Errors)

```python
async def _call_with_retry(self, coro_fn, label: str) -> dict | None:
    for attempt in range(settings.AI_RETRY_ATTEMPTS):
        try:
            return await coro_fn()
        except Exception as exc:
            if _is_rate_limit_error(exc) and attempt < settings.AI_RETRY_ATTEMPTS - 1:
                wait = delay * (2 ** attempt)
                await asyncio.sleep(wait)
                continue
            logger.error("%s failed: %s", label, exc)
            return None
    return None
```

**Strategy:**
- Rate limit errors → retry with exponential backoff (15s, 30s, 60s)
- Other errors → log and return `None`
- Returning `None` means this article is marked as `"failed"` in `raw_ingestion` and can be retried on the next scheduler run

### Database Layer (Deduplication + Conflicts)

```python
stmt = insert(RawIngestion).values(rows).on_conflict_do_nothing(index_elements=["content_hash"])
```

**Strategy:** Use PostgreSQL's `ON CONFLICT DO NOTHING` instead of checking-then-inserting. This is atomic — it works correctly even with concurrent inserts and never raises errors for duplicates.

### API Layer (Input Validation)

FastAPI + Pydantic handle input validation automatically:
- Missing required fields → 422 Unprocessable Entity
- Wrong types (string where int expected) → 422
- Out-of-range values (limit=500 when max is 100) → 422

Route handlers handle "not found" cases:
```python
article = await repo.get_by_id(article_id)
if article is None:
    raise HTTPException(status_code=404, detail="Article not found")
```

### Scheduler Layer (Job Isolation)

```python
results = await asyncio.gather(*tasks, return_exceptions=True)
```

`return_exceptions=True` means if one source's ingest task crashes, it returns the exception as a result instead of propagating it. Other sources continue processing. The scheduler loop then logs the failures:

```python
for source, result in zip(sources, results):
    if isinstance(result, Exception):
        logger.error("Scheduled ingest failed for source_id=%s: %s", source.id, result)
```

### Resolver Layer (Missing FK)

```python
try:
    cat_resolver, loc_resolver = await load_resolvers(self._db)
except Exception as exc:
    logger.warning("Could not load resolvers (FKs will be NULL): %s", exc)
```

If the category/location resolver fails to load, articles are still saved — just with `NULL` foreign keys. The article is not lost, it's just uncategorized. Better to have uncategorized articles than to lose data.

---

# 13. Important Design Patterns Used

## 1. The Repository Pattern

**What it is:** A layer that sits between the service layer and the database. All SQL queries live in repositories. Nothing else touches the database directly.

**Beginner explanation:** Think of a repository as a "data librarian." If you want a book (data), you ask the librarian (repository) — you don't go into the shelves (database) yourself.

**In this codebase:**
```python
# Services ask repositories for data:
sources = await SourceRepository(db).get_all(active_only=True)
url_to_filter_id = await self.filter_article_repo.insert_batch(crime_articles, hash_to_raw_id)

# Repositories translate to SQL:
stmt = select(Source).where(Source.is_active.is_(True))
result = await self.db.execute(stmt)
```

**Why it exists:**
- If the database schema changes, only repository files need updating
- You can swap PostgreSQL for another database by only rewriting repositories
- Business logic in services is cleaner — no SQL mixed with application logic

---

## 2. Dependency Injection

**What it is:** Instead of creating dependencies inside a function, they are passed in from outside.

**Beginner explanation:** Instead of a chef buying their own ingredients, the restaurant provides the ingredients. The chef focuses on cooking.

**In this codebase:**
```python
# Route handler doesn't create its own database session:
async def list_final_articles(
    ...
    repo: FinalArticleRepository = Depends(get_final_article_repo),
    # FastAPI creates this for us ↑
):
    return await repo.get_feed(...)
```

**Why it exists:**
- Makes testing easy — in tests, you can inject a fake repository instead of a real database
- Each request gets its own session (no sharing between requests)
- Cleanup is automatic — sessions close when requests finish

---

## 3. The Factory Pattern

**What it is:** A function that creates objects. Instead of directly instantiating classes, you call the factory.

**In this codebase:**
```python
def create_from_config(config: AIProviderConfig) -> AIProvider:
    cache_key = (config.id, config.model, config.api_key)
    if cache_key in _provider_cache:
        return _provider_cache[cache_key]
    provider = _build(config)
    _provider_cache[cache_key] = provider
    return provider
```

**Why it exists:**
- Caching: AI SDK clients are expensive to create; the factory reuses them
- Single registration point: adding a new provider only requires changing `_build()`
- The caller doesn't need to know which concrete class to instantiate

---

## 4. The Abstract Base Class Pattern (Strategy Pattern)

**What it is:** A base class that defines what methods must exist, without implementing them. Subclasses provide the actual implementation.

**In this codebase:**
```python
class AIProvider(ABC):
    @property
    @abstractmethod
    def model_id(self) -> str:
        ...

    @abstractmethod
    async def process(self, raw_payload: dict, source_type: str) -> dict | None:
        ...
```

Every AI provider (`AnthropicProvider`, `OpenAICompatibleProvider`, `GeminiMultimodalLangGraphProvider`) inherits from `AIProvider` and implements `model_id` and `process`.

**Why it exists:** The `IngestionService` doesn't need to know which specific AI provider it's using. It just calls `ai_provider.process(raw)` and gets the same result shape regardless of whether it's talking to Gemini, Claude, or Ollama. This is the **Strategy Pattern** — different strategies (AI providers) are interchangeable.

---

## 5. The Lifespan Context Manager Pattern

**What it is:** Code that runs at application startup and shutdown, wrapped in an `async with` block using `yield`.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()   # ← startup code
    yield               # ← application runs here
    stop_scheduler()    # ← shutdown code
```

**Why it exists:** Ensures the scheduler starts when the server starts and stops cleanly when the server stops (e.g., on Ctrl+C). Without this, the scheduler might keep running after the HTTP server has stopped, causing zombie background tasks.

---

## 6. The Sentinel Value Pattern

**What it is:** Using a special value to mean "this has been done and had no results" (as opposed to NULL which means "not yet done").

**In this codebase:**
```python
# reference_urls values:
# NULL    → not yet searched (do search on next run)
# []      → searched, found nothing (never search again)
# [urls]  → enriched (never search again)
```

**Why it exists:** Without the sentinel, every scheduler run would re-search every article that previously returned no results, wasting the 100 daily Google API quota calls.

---

## 7. SHA-256 Content Hashing for Deduplication

**What it is:** Computing a cryptographic hash of each article's content and using it as a unique identifier.

```python
def compute_content_hash(source_id: int, raw_payload: dict) -> str:
    payload_str = json.dumps(raw_payload, sort_keys=True, default=str)
    return hashlib.sha256(f"{source_id}:{payload_str}".encode()).hexdigest()
```

**Why SHA-256:** It produces a 64-character string that is statistically unique for different inputs. The chance of two different articles producing the same hash is astronomically small (2^256 possible values).

**Why sort_keys=True:** Dictionaries in Python don't have a guaranteed key order. Without `sort_keys=True`, `{"a": 1, "b": 2}` and `{"b": 2, "a": 1}` would produce different JSON strings — and thus different hashes — even though they're the same content. Sorting ensures consistency.

---

## 8. Batch Operations

**What it is:** Performing database operations on multiple rows in a single SQL statement instead of one statement per row.

**In this codebase:**
```python
# Good: one INSERT for all articles
stmt = insert(RawIngestion).values(rows)
await self.db.execute(stmt)

# Bad (not used): loop with individual inserts
for row in rows:
    await self.db.execute(insert(RawIngestion).values(row))
```

**Why it exists:** A single SQL statement with 10 rows is far faster than 10 separate SQL statements. Network round-trips to PostgreSQL are expensive. Batching reduces them from N to 1.

---

# 14. Example End-to-End System Scenario

## Scenario: New Crime Story Detected and Published

**Context:** It's 2:00 PM. The APScheduler fires the ingestion job. Times of India has just published a story about a major fraud case.

### Phase 1: Scheduled Job Fires (2:00:00 PM)

```
APScheduler → run_ingestion_for_all_active_sources()
```

1. Opens a database session
2. Calls `SourceRepository(db).get_all(active_only=True)`
3. Gets back 5 active sources, including "Times of India Crime RSS"
4. Creates one `asyncio.Task` per source
5. `asyncio.gather(*tasks)` runs all 5 source ingestions concurrently

### Phase 2: Fetching (2:00:01 PM)

For the Times of India source:
```
IngestionService.ingest(source) is called
    ↓
_fetch_items(source) → RSSFetcher.fetch(url)
    ↓
asyncio.to_thread(feedparser.parse, url) — runs in thread pool
    ↓
feedparser returns 30 entries (30 articles from the feed)
    ↓
to_plain_dict(entry) converts each to plain dict
    ↓
Returns list of 30 raw article dicts
```

### Phase 3: Provider Loading + Cap (2:00:02 PM)

```
_load_ai_provider() → DB has Gemini multimodal active
Provider type: "gemini_multimodal"
Max items: 5 (CLOUD_MAX_ITEMS_PER_RUN)
30 articles → capped to 5
```

### Phase 4: Hashing and Raw Storage (2:00:02 PM)

```
5 SHA-256 hashes computed
store_batch() called:
    - 3 hashes are NEW (not seen before) → inserted
    - 2 hashes already exist in DB (from previous run) → skipped by ON CONFLICT
Returns: 3 new hashes need processing
```

### Phase 5: Keyword Pre-filter (2:00:02 PM)

```
Article 1: "Businessman Arrested for ₹500 Crore Bank Fraud"
    → "fraud", "arrested" found → KEEP
Article 2: "Mumbai Police Bust Drug Trafficking Ring"
    → "police", "drug", "trafficking" found → KEEP
Article 3: "New Cricket Stadium to Open in Pune"
    → No crime keywords → DISCARD (no AI call needed)
```

2 articles proceed to AI. 1 is marked `filtered_out` in raw_ingestion.

### Phase 6: AI Processing (2:00:03 PM – 2:00:30 PM)

The rate limiter enforces 3 requests per minute (one every 20 seconds).

**Article 1 — Bank Fraud:**
```
Wait for rate limiter (initial: no wait)
Send to Gemini API:
    Prompt: SINGLE_PROCESS_PROMPT + raw article JSON

Gemini responds (after 2-3 seconds):
{
    "is_crime": true,
    "title": "Businessman Arrested for ₹500 Crore Bank Fraud",
    "rewritten_title": "Mumbai Entrepreneur Faces Arrest Over Massive ₹500 Crore Bank Fraud",
    "url": "https://timesofindia.com/article/bank-fraud-mumbai",
    "description": "A Mumbai-based businessman was arrested...",
    "rewritten_description": "Mumbai police arrested a prominent businessman on charges of orchestrating a ₹500 crore bank fraud scheme...",
    "sub_category": "fraud",
    "sub_category_ids": ["fraud", "corruption"],
    "location": "Mumbai, Maharashtra",
    "imp_score": 65
}
```

**Article 2 — Drug Trafficking (after 20-second rate limit wait):**
```
Gemini responds:
{
    "is_crime": true,
    "sub_category": "drugs",
    "sub_category_ids": ["drugs", "trafficking"],
    "location": "Mumbai, Maharashtra",
    "imp_score": 55
}
```

### Phase 7: Resolving Foreign Keys (2:00:35 PM)

```
CategoryResolver loaded from DB:
    {"fraud": 3, "drugs": 5, "corruption": 2, "trafficking": 7, ...}

Article 1: "fraud" → sub_category_id = 3
           ["fraud", "corruption"] → category_ids lookup
LocationResolver loaded from DB:
    {"maharashtra": 12, "delhi": 5, ...}
Article 1: "Mumbai, Maharashtra" → location_state_id = 12
```

### Phase 8: Database Writes (2:00:35 PM)

```
FilterArticleRepository.insert_batch([article1, article2], hash_to_raw_id)
    → INSERT INTO filtered_articles (2 rows)
    → Returns: {"https://timesofindia.com/.../fraud": 201, ".../drugs": 202}

PostProcessedArticleRepository.insert_batch([article1, article2], url_to_filter_id)
    → INSERT INTO post_processed_articles (2 rows)
    → article1: filter_article_id=201, sub_category_id=3, location_id=12, imp_score=65
    → article2: filter_article_id=202, sub_category_id=5, location_id=12, imp_score=55

RawIngestionRepository.mark_filtered()
    → UPDATE raw_ingestion SET status="filtered", normalized_by="gemini-2.0-flash"
       WHERE content_hash IN (hash1, hash2)
```

### Phase 9: Search Enrichment (2:00:36 PM)

```
SearchEnrichmentService.enrich()
    ↓
get_without_reference_urls(limit=10)
    → Returns articles1 and article2 (reference_urls IS NULL)
    ↓
For article1: fetch_related_urls("Mumbai Entrepreneur Faces Arrest Over Massive ₹500 Crore Bank Fraud")
    → Google API returns: ["https://ndtv.com/...", "https://thehindu.com/...", "https://moneycontrol.com/..."]
    → update_reference_urls(id=201, urls=[...])
    ↓
Sleep 1 second (quota guard)
    ↓
For article2: fetch_related_urls("Mumbai Police Bust Drug Trafficking Ring")
    → Google API returns: ["https://hindustantimes.com/...", "https://theprint.in/..."]
    → update_reference_urls(id=202, urls=[...])
```

### Phase 10: Publishing (2:00:40 PM)

```
PublishingService.publish(top_n=20)
    ↓
get_top_by_imp_score(limit=20)
    → SELECT * FROM post_processed_articles ORDER BY imp_score DESC LIMIT 20
    → Returns 20 articles (including our new article1 with imp_score=65)
    ↓
For article1:
    published_at = "2024-01-15 14:00:00 UTC" (just published)
    hours_old = 0.01 hours → DECAY_FRESH = 1.00
    rank_score = 65 × 1.00 = 65.0

For existing article from 2 days ago (imp_score=80):
    hours_old = 48 → DECAY_DAY = 0.50
    rank_score = 80 × 0.50 = 40.0

→ Our new fraud article (65.0) ranks ABOVE the older article (40.0) despite lower imp_score
    ↓
FinalArticleRepository.upsert_batch([20 rows])
    → INSERT OR UPDATE 20 rows in final_articles
```

### Phase 11: Client Request (2:01:00 PM)

A user opens their news app. The app calls:
```
GET /final-articles/?limit=10
```

```
FinalArticleRepository.get_feed(limit=10)
    → SELECT * FROM final_articles ORDER BY rank_score DESC LIMIT 10
    → Returns: article1 (rank=65.0) near the top
    ↓
JSON response:
{
    "total": 20,
    "items": [
        {
            "id": 89,
            "title": "Mumbai Entrepreneur Faces Arrest Over Massive ₹500 Crore Bank Fraud",
            "description": "Mumbai police arrested a prominent businessman...",
            "reference_urls": ["https://ndtv.com/...", "https://thehindu.com/..."],
            "rank_score": 65.0,
            "image_url": "..."
        },
        ...
    ]
}
```

The user sees fresh crime news ranked by importance, with related articles linked.

---

# 15. How a Developer Should Navigate This Codebase

## Where to Start Reading

**Start with these files in order:**

1. **`app/main.py`** (69 lines) — Understand what the application is and how it's structured at the highest level
2. **`app/core/config.py`** (69 lines) — Understand all configuration options
3. **`app/core/database.py`** (32 lines) — Understand how the database connects
4. **`app/core/deps.py`** (97 lines) — Understand how services/repos get wired together

**Then understand the data:**
5. **`app/models/source.py`** → raw_event.py → filter_article.py → post_processed_article.py → final_article.py — Read them in pipeline order; the comments explain why each table exists

**Then understand the pipeline:**
6. **`app/services/scheduler.py`** — See how jobs are triggered
7. **`app/services/ingestion_service.py`** — The main pipeline logic (the most complex file)
8. **`app/services/publishing_service.py`** — The ranking algorithm
9. **`app/services/normalization/providers/base.py`** — The AI prompt and output schema

**Finally, understand the API:**
10. **`app/api/routes_final_articles.py`** — The public-facing endpoint
11. Other route files — The admin endpoints

## How to Trace a Bug

**"Why is this article not appearing in the feed?"**

Start from the end and work backwards:

1. Check `final_articles` table — is the article there? If not, did it get to `post_processed_articles`?
2. Check `post_processed_articles` — is it there? Does it have an `imp_score`? Is the `imp_score` high enough to make the top 20?
3. Check `filtered_articles` — is it there? Did it pass crime classification?
4. Check `raw_ingestion` — is it there? What's the `status`? If `failed`, what's in `error_message`?

**"Why is the pipeline not running?"**

1. Check server logs for scheduler output (look for "Scheduled ingestion run starting")
2. Check if any sources are active: `GET /sources/`
3. Check if an AI provider is configured: `GET /ai-providers/active`
4. Trigger manually: `POST /ingest/` with `{"source_id": X}`

**"Why are articles not being ranked correctly?"**

1. Check `post_processed_articles.imp_score` — is it set?
2. Check `post_processed_articles.published_at` — is it set? If NULL, time decay defaults to 0.50
3. Check `final_articles.rank_score` — is `rank_score = imp_score × expected_decay`?

## How to Add a New News Source

```bash
# Via the API:
curl -X POST http://localhost:8000/sources/ \
  -H "Content-Type: application/json" \
  -d '{"name": "NDTV Crime RSS", "type": "rss", "url": "https://feeds.ndtv.com/ndtv/crime"}'

# Trigger immediate ingestion:
curl -X POST http://localhost:8000/ingest/ \
  -H "Content-Type: application/json" \
  -d '{"source_id": <returned_id>}'
```

## How to Switch AI Providers

```bash
# Register a new Ollama config:
curl -X POST http://localhost:8000/ai-providers/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Local Llama",
    "provider": "ollama",
    "model": "llama3.2:latest",
    "api_key": "ollama"
  }'

# Activate it:
curl -X PATCH http://localhost:8000/ai-providers/1/activate
```

Takes effect on the next ingestion run (within 5 minutes) or immediately via `POST /ingest/`.

## How to Run Migrations

After pulling code changes that include new migration files:
```bash
.venv/bin/alembic upgrade head
```

To see current migration state:
```bash
.venv/bin/alembic current
```

To create a new migration (after changing a model):
```bash
.venv/bin/alembic revision --autogenerate -m "add_new_column_to_articles"
```

## Development Tips

**Accessing the API documentation:** Go to `http://localhost:8000/docs` — FastAPI generates an interactive Swagger UI from your code. You can test endpoints directly in the browser.

**Watching pipeline logs:** The application logs extensively at `INFO` level. Every stage of the pipeline logs what it's doing:
```
2024-01-15 14:00:01 INFO — Scheduled ingestion run starting
2024-01-15 14:00:02 INFO — [RAW_SAVE] 30 stored (3 to process) — source_id=1
2024-01-15 14:00:02 INFO — Keyword pre-filter: 1/3 skipped — source_id=1
2024-01-15 14:00:02 INFO — [AI_EXTRACT] 2 articles queued — source_id=1
2024-01-15 14:00:30 INFO — Filter stage: 2 crime, 1 filtered_out, 0 failed — source_id=1
2024-01-15 14:00:30 INFO — post_processed_articles: 2 written, 2 scored — source_id=1
```

**Debugging raw ingestion:** `GET /raw-ingestion/?status=failed` shows articles that failed AI processing. The `error_message` column explains why.

**Understanding rate limits:** If you see the rate limiter logging "sleeping 20.0s", your cloud AI provider is rate-limited. Consider:
- Switching to Ollama (no rate limits)
- Reducing `CLOUD_MAX_ITEMS_PER_RUN` to process fewer articles per run
- Upgrading to a paid API tier

## File Reading Priority

If you only have time to read 5 files to understand the system:

| Priority | File | Why |
|---|---|---|
| 1 | `app/main.py` | The entry point — shows the whole app at a glance |
| 2 | `app/services/ingestion_service.py` | The heart of the system |
| 3 | `app/services/normalization/providers/base.py` | The AI prompt and output contract |
| 4 | `app/repositories/final_article_repo.py` | How the public feed is built |
| 5 | `app/core/config.py` | All the knobs you can turn |

---

*This document was generated to provide a complete educational guide to the `news-app-server` codebase. It covers the architecture, every file, key functions, data flows, database schema, and practical navigation advice for developers new to the project.*
