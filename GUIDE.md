# News Aggregator Backend — Complete Guide

> Stack: **FastAPI · PostgreSQL · SQLAlchemy 2.0 async · APScheduler · Anthropic / OpenAI / Gemini**
> Python ≥ 3.12 · Package manager: `uv`

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Database Schema](#2-database-schema)
3. [Codebase Navigation](#3-codebase-navigation)
4. [Setup & Running](#4-setup--running)
5. [API Reference — Sources](#5-api-reference--sources)
6. [API Reference — Articles](#6-api-reference--articles)
7. [API Reference — Ingestion](#7-api-reference--ingestion)
8. [API Reference — AI Providers](#8-api-reference--ai-providers)
9. [Ingestion Pipeline Deep Dive](#9-ingestion-pipeline-deep-dive)
10. [AI Normalization System](#10-ai-normalization-system)
11. [Scheduler](#11-scheduler)
12. [Changelog — What Changed & Why](#12-changelog--what-changed--why)
13. [Extending the System](#13-extending-the-system)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        INGESTION PLANE                               │
│                                                                       │
│  ┌────────────┐    ┌───────────────────┐    ┌─────────────────────┐ │
│  │ APScheduler│───▶│  IngestionService │    │  RawIngestionRepo   │ │
│  │ (5-min job)│    │                   │───▶│  raw_ingestion_     │ │
│  └────────────┘    │  _fetch_items()   │    │  events table       │ │
│                    │  _normalize_one() │    └──────────┬──────────┘ │
│  ┌────────────┐    │  _load_ai_prov()  │               │            │
│  │ POST/ingest│───▶│                   │    mark status after write │
│  └────────────┘    └─────────┬─────────┘               │            │
│                              │                          │            │
│              ┌───────────────┼───────────────┐          │            │
│              ▼               ▼               ▼          │            │
│        RSSFetcher      RestFetcher     (future fetchers) │           │
│              │               │                          │            │
│              └───────────────┘                          │            │
│                      │                                  │            │
│               raw plain dicts                           │            │
│                      │                                  │            │
│              ┌───────▼────────────────────────────┐     │            │
│              │      Normalization Pipeline         │     │            │
│              │                                     │     │            │
│              │  1. source_normalizer.normalize()   │     │            │
│              │  2. canonical_validator.validate()  │     │            │
│              │  3. [if invalid] AIProvider.normalize│    │            │
│              │  4. canonical_validator.validate()  │     │            │
│              └───────────────┬─────────────────────┘    │            │
│                              │ valid articles only       │            │
│              ┌───────────────▼──────────┐                │            │
│              │   ArticleRepository      │◀───────────────┘            │
│              │   upsert_batch()         │                              │
│              │   ON CONFLICT DO UPDATE  │                              │
│              └───────────────┬──────────┘                             │
└──────────────────────────────┼──────────────────────────────────────┘
                               │
                  articles table (canonical read model)
                               │
┌──────────────────────────────┼──────────────────────────────────────┐
│                    SERVING PLANE                                      │
│                               │                                       │
│              ┌────────────────▼──────────────┐                       │
│              │  GET /articles                 │                       │
│              │  GET /articles/{id}            │                       │
│              │  (reads ONLY canonical table)  │                       │
│              └────────────────────────────────┘                       │
└───────────────────────────────────────────────────────────────────────┘

AI Provider resolution order (per ingest run):
  DB active provider  →  ANTHROPIC_API_KEY env var  →  deterministic only
```

### Key Design Principles

| Principle | Implementation |
|---|---|
| Raw payloads stored before normalization | `raw_ingestion_events` table — enables reprocessing without re-fetching |
| Serving layer reads only canonical data | `articles` table has no business logic; API routes never touch raw events |
| Idempotent ingestion | Content hash (SHA-256) deduplicates raw events; `ON CONFLICT DO UPDATE` deduplicates articles |
| AI as fallback only | Deterministic normalizer runs first; AI only activates when validation fails |
| Publisher corrections applied | `ON CONFLICT DO UPDATE` updates `title`, `description`, `image_url` on re-ingest |
| Single batch DB write | All articles from one source are written in one `INSERT ... VALUES (...)` |

---

## 2. Database Schema

### `sources`
Registered news sources — RSS feeds or REST API endpoints.

```
Column       Type          Constraints
────────────────────────────────────────────────────────
id           INTEGER       PRIMARY KEY, auto-increment
name         VARCHAR       NOT NULL
type         VARCHAR       NOT NULL  — "rss" | "rest"
url          VARCHAR       NOT NULL, UNIQUE
config       JSONB         nullable  — per-source settings (e.g. headers)
is_active    BOOLEAN       DEFAULT true
created_at   TIMESTAMPTZ   server DEFAULT now()
```

### `articles`
Canonical article read model served to the frontend.

```
Column        Type          Constraints
────────────────────────────────────────────────────────
id            INTEGER       PRIMARY KEY, auto-increment
source_id     INTEGER       FK → sources.id ON DELETE CASCADE, indexed
title         VARCHAR       NOT NULL, indexed
description   TEXT          nullable
content       TEXT          nullable
url           VARCHAR       NOT NULL, UNIQUE, indexed  ← dedup key
image_url     VARCHAR       nullable
published_at  TIMESTAMPTZ   nullable, indexed
raw_payload   JSONB         NOT NULL  ← original fetch payload (transition-phase)
created_at    TIMESTAMPTZ   server DEFAULT now()
updated_at    TIMESTAMPTZ   server DEFAULT now()  ← updated on re-ingest
```

### `raw_ingestion_events`
Staging / audit table. Every unique raw payload ever fetched is stored here before normalization.

```
Column         Type          Constraints
────────────────────────────────────────────────────────
id             INTEGER       PRIMARY KEY, auto-increment
source_id      INTEGER       FK → sources.id ON DELETE CASCADE, indexed
content_hash   CHAR(64)      UNIQUE  ← SHA-256(source_id + sorted JSON)
raw_payload    JSONB         NOT NULL
status         VARCHAR(20)   DEFAULT "pending"
                               "pending" | "normalized" | "failed"
normalized_by  VARCHAR(50)   nullable  — "deterministic" | "ai:anthropic:claude-..."
error_message  TEXT          nullable  — populated on status="failed"
retry_count    SMALLINT      DEFAULT 0
created_at     TIMESTAMPTZ   server DEFAULT now()
processed_at   TIMESTAMPTZ   nullable

Indexes:
  ix_raw_ingestion_events_source_id   — standard btree
  ix_raw_ingestion_events_pending     — PARTIAL on status='pending' (tiny, fast)
```

### `ai_provider_configs`
User-configured AI provider credentials. Exactly one row may be active at a time.

```
Column      Type          Constraints
────────────────────────────────────────────────────────
id          INTEGER       PRIMARY KEY, auto-increment
name        VARCHAR(100)  NOT NULL  — friendly label
provider    VARCHAR(50)   NOT NULL  — "anthropic"|"openai"|"gemini"|"custom"
model       VARCHAR(100)  NOT NULL  — provider-specific model ID
api_key     VARCHAR(500)  NOT NULL  — stored plaintext (encrypt in prod)
base_url    VARCHAR(500)  nullable  — OpenAI-compat override; auto-set for gemini
is_active   BOOLEAN       DEFAULT false
created_at  TIMESTAMPTZ   server DEFAULT now()

Indexes:
  ix_ai_provider_configs_single_active  — PARTIAL UNIQUE on is_active=true
                                          DB-level guarantee: only one active row
```

### Migration Chain

```
29df1b34a087  initial_schema          (sources + articles)
      ↓
c8f2a1e3b456  add_raw_ingestion_events
      ↓
d9e4f5a6b789  add_ai_provider_configs  ← HEAD
```

---

## 3. Codebase Navigation

```
news_app_backend/
│
├── .env                          ← Environment variables (DATABASE_URL, ANTHROPIC_API_KEY)
├── pyproject.toml                ← All dependencies — edit here, then run `uv sync`
├── alembic.ini                   ← Alembic config (URL injected at runtime from settings)
│
├── app/
│   │
│   ├── main.py                   ← FastAPI app instance, lifespan (scheduler start/stop),
│   │                               middleware, router registration
│   │
│   ├── core/
│   │   ├── config.py             ← Settings class (DATABASE_URL, DEBUG, ANTHROPIC_API_KEY)
│   │   │                           Add new env vars here.
│   │   ├── database.py           ← SQLAlchemy async engine, AsyncSessionLocal, get_db()
│   │   │                           Connection pool: 10 persistent + 20 overflow
│   │   └── deps.py               ← FastAPI dependency factories.
│   │                               One factory per repository/service.
│   │                               This is where constructor arguments are wired.
│   │
│   ├── models/                   ← SQLAlchemy ORM table definitions. Pure data — no logic.
│   │   ├── base.py               ← DeclarativeBase. All models inherit from this.
│   │   ├── source.py             ← Source  →  sources table
│   │   ├── article.py            ← Article →  articles table
│   │   ├── raw_event.py          ← RawIngestionEvent  →  raw_ingestion_events table
│   │   └── ai_provider.py        ← AIProviderConfig   →  ai_provider_configs table
│   │                               Also exports SUPPORTED_PROVIDERS, PROVIDER_BASE_URLS,
│   │                               PROVIDER_DEFAULT_MODELS constants.
│   │
│   ├── schemas/                  ← Pydantic request/response models. No DB access.
│   │   ├── source_schema.py      ← SourceCreate (input), SourceResponse (output)
│   │   ├── article_schema.py     ← ArticleResponse, ArticleListResponse (paginated)
│   │   └── ai_provider_schema.py ← AIProviderCreate (validated input),
│   │                               AIProviderResponse (api_key excluded),
│   │                               AIProviderActivateResponse
│   │
│   ├── repositories/             ← Database access only. No business logic.
│   │   │                           Each class takes AsyncSession in __init__.
│   │   ├── source_repo.py        ← SourceRepository
│   │   │                           create(), get_all(active_only), get_by_id()
│   │   ├── article_repo.py       ← ArticleRepository
│   │   │                           upsert_batch(), get_all(), get_by_id(), count()
│   │   ├── raw_ingestion_repo.py ← RawIngestionRepository + compute_content_hash()
│   │   │                           store_batch(), mark_normalized(), mark_failed()
│   │   └── ai_provider_repo.py   ← AIProviderRepository
│   │                               create(), get_all(), get_by_id(), get_active(),
│   │                               activate(), deactivate_all(), delete()
│   │
│   ├── services/
│   │   │
│   │   ├── ingestion_service.py  ← IngestionService — the main orchestrator.
│   │   │                           ingest(source) drives the full pipeline:
│   │   │                           fetch → raw store → normalize → validate →
│   │   │                           AI fallback → batch upsert → status update
│   │   │
│   │   ├── source_normalizer.py  ← Deterministic field extraction.
│   │   │                           normalize(item) → canonical dict
│   │   │                           parse_date() — RFC 2822 + ISO 8601
│   │   │                           to_plain_dict() — feedparser object coercion
│   │   │
│   │   ├── scheduler.py          ← APScheduler setup.
│   │   │                           Runs run_ingestion_for_all_active_sources()
│   │   │                           every 5 minutes. Each source gets its own
│   │   │                           DB session. max_instances=1 prevents overlap.
│   │   │
│   │   ├── fetchers/
│   │   │   ├── rss_fetcher.py    ← RSSFetcher.fetch(url)
│   │   │   │                       Uses asyncio.to_thread(feedparser.parse) to
│   │   │   │                       avoid blocking the event loop.
│   │   │   └── rest_fetcher.py   ← RestFetcher.fetch(url, headers)
│   │   │                           httpx async client, 15s/5s timeout.
│   │   │                           Unwraps common envelopes: articles/items/results/data
│   │   │
│   │   └── normalization/
│   │       │
│   │       ├── canonical_validator.py  ← validate(dict) → ValidationResult
│   │       │                             Checks: title not placeholder, url is HTTP(S).
│   │       │                             Called after BOTH deterministic and AI passes.
│   │       │
│   │       ├── ai_processor.py         ← get_env_fallback_provider()
│   │       │                             Backwards-compat: builds AnthropicProvider
│   │       │                             from ANTHROPIC_API_KEY env var if set.
│   │       │
│   │       ├── provider_factory.py     ← create_from_config(AIProviderConfig) → AIProvider
│   │       │                             create_from_env(api_key, model) → AIProvider
│   │       │                             Module-level instance cache — avoids recreating
│   │       │                             SDK HTTP clients on every ingest run.
│   │       │
│   │       └── providers/
│   │           ├── base.py             ← AIProvider ABC (abstract interface)
│   │           │                         NORMALIZATION_SYSTEM_PROMPT (shared prompt)
│   │           │                         parse_llm_output() (shared JSON parser)
│   │           │                         build_user_message() (shared message builder)
│   │           ├── anthropic_prov.py   ← AnthropicProvider(api_key, model)
│   │           │                         Uses Anthropic SDK, native system parameter.
│   │           └── openai_prov.py      ← OpenAICompatibleProvider(api_key, model, base_url)
│   │                                     Handles: OpenAI, Gemini, Ollama, vLLM, LM Studio.
│   │
│   └── api/
│       ├── routes_sources.py      ← POST/GET /sources
│       ├── routes_articles.py     ← GET /articles, GET /articles/{id}
│       ├── routes_ingest.py       ← POST /ingest
│       └── routes_ai_providers.py ← Full CRUD for /ai-providers
│
└── migrations/
    ├── env.py                    ← Async-aware Alembic runner.
    │                               IMPORTANT: import every new model here.
    └── versions/
        ├── 29df1b34a087_initial_schema.py
        ├── c8f2a1e3b456_add_raw_ingestion_events.py
        └── d9e4f5a6b789_add_ai_provider_configs.py
```

### The Request Lifecycle (one HTTP call)

```
HTTP Request
    ↓
FastAPI route function  (app/api/routes_*.py)
    ↓
Depends(get_*)          (app/core/deps.py)  — creates repo/service instances
    ↓
Service method          (app/services/)     — business logic, no HTTP knowledge
    ↓
Repository method       (app/repositories/) — SQL only, no business logic
    ↓
SQLAlchemy ORM          (app/models/)       — table definitions
    ↓
asyncpg → PostgreSQL
```

---

## 4. Setup & Running

### Prerequisites
- Python 3.12+
- `uv` package manager
- PostgreSQL database

### Environment Variables

Create `.env` in the project root:

```env
# Required
DATABASE_URL=postgresql+asyncpg://user:password@host:port/dbname

# Optional — used as AI fallback when no DB provider is active
ANTHROPIC_API_KEY=sk-ant-...

# Optional — enables SQLAlchemy query logging
DEBUG=false
```

### Install Dependencies

```bash
uv sync
```

### Apply Database Migrations

```bash
# Apply all pending migrations
uv run alembic upgrade head

# Check current state
uv run alembic current

# See full migration history
uv run alembic history --verbose
```

### Run the Server

```bash
# Development (auto-reload on file changes)
uv run uvicorn app.main:app --reload --port 8000

# Production
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Interactive API Documentation

Once running, open:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

---

## 5. API Reference — Sources

Sources define where articles come from. Each source has a `type` (`"rss"` or `"rest"`) and a `url`. Optional `config` allows per-source settings such as custom HTTP headers.

---

### `POST /sources/`

Register a new news source. Use this once per feed/API endpoint you want the system to monitor.

**When to use:** Before any ingestion can happen, you must register the source here.

**Request body:**

```json
{
  "name": "string",
  "type": "rss" | "rest",
  "url": "string",
  "config": {} | null
}
```

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Human-readable label. Only used for display. |
| `type` | Yes | `"rss"` for RSS/Atom feeds. `"rest"` for JSON REST APIs. |
| `url` | Yes | Full URL of the feed or API endpoint. Must be unique. |
| `config` | No | JSON object for extra settings. See below. |

**`config` for `type="rest"`:**
```json
{
  "headers": {
    "Authorization": "Bearer YOUR_TOKEN",
    "X-Api-Key": "YOUR_KEY"
  }
}
```

**`config` for `type="rss"`:** Usually `null` — feedparser handles auth-free feeds automatically.

**Example — RSS:**
```bash
curl -X POST http://localhost:8000/sources/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "BBC World News",
    "type": "rss",
    "url": "http://feeds.bbci.co.uk/news/world/rss.xml"
  }'
```

**Example — REST (NewsAPI):**
```bash
curl -X POST http://localhost:8000/sources/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "NewsAPI Technology",
    "type": "rest",
    "url": "https://newsapi.org/v2/top-headlines?category=technology&apiKey=YOUR_KEY",
    "config": {
      "headers": { "X-Api-Key": "YOUR_KEY" }
    }
  }'
```

**Response — 201 Created:**
```json
{
  "id": 1,
  "name": "BBC World News",
  "type": "rss",
  "url": "http://feeds.bbci.co.uk/news/world/rss.xml",
  "config": null,
  "is_active": true,
  "created_at": "2026-02-20T10:00:00Z"
}
```

**Error responses:**

| Status | Reason |
|---|---|
| `422` | Missing required field or validation error |
| `500` | Duplicate URL (unique constraint violation) |

---

### `GET /sources/`

List all active sources.

**When to use:** To see what sources are registered, or to get source IDs before triggering ingestion.

```bash
curl http://localhost:8000/sources/
```

**Response — 200 OK:**
```json
[
  {
    "id": 1,
    "name": "BBC World News",
    "type": "rss",
    "url": "http://feeds.bbci.co.uk/news/world/rss.xml",
    "config": null,
    "is_active": true,
    "created_at": "2026-02-20T10:00:00Z"
  }
]
```

---

### `GET /sources/{source_id}`

Get a single source by ID.

**When to use:** Verify a specific source's config, or check if it exists before ingesting.

```bash
curl http://localhost:8000/sources/1
```

**Response — 200 OK:** Single `SourceResponse` object (same shape as above).

**Error responses:**

| Status | Reason |
|---|---|
| `404` | Source not found |

---

## 6. API Reference — Articles

Articles are the canonical output of the ingestion pipeline. The API serves them read-only; writes happen only through ingestion.

---

### `GET /articles/`

Paginated list of articles, ordered by `published_at` descending (newest first). Articles without a publication date appear last.

**When to use:** Main feed endpoint for your frontend. Poll this to display articles.

**Query parameters:**

| Parameter | Type | Default | Range | Description |
|---|---|---|---|---|
| `limit` | int | `20` | 1–100 | Number of articles per page |
| `offset` | int | `0` | ≥ 0 | Skip this many articles |

```bash
# First page
curl "http://localhost:8000/articles/?limit=20&offset=0"

# Second page
curl "http://localhost:8000/articles/?limit=20&offset=20"
```

**Response — 200 OK:**
```json
{
  "total": 142,
  "limit": 20,
  "offset": 0,
  "items": [
    {
      "id": 88,
      "source_id": 2,
      "title": "Tech Giants Report Record Earnings",
      "description": "Major technology companies reported record quarterly earnings...",
      "content": null,
      "url": "https://example.com/tech-earnings-2026",
      "image_url": "https://example.com/images/tech.jpg",
      "published_at": "2026-02-20T09:30:00Z",
      "created_at": "2026-02-20T09:35:00Z"
    }
  ]
}
```

Note: `raw_payload` is **never** included in responses — it is an internal ingestion field.

---

### `GET /articles/{article_id}`

Retrieve a single article by its integer ID.

**When to use:** Article detail page. When the user clicks on an article in the list.

```bash
curl http://localhost:8000/articles/88
```

**Response — 200 OK:** Single `ArticleResponse` object (same shape as items above).

**Error responses:**

| Status | Reason |
|---|---|
| `404` | Article not found |

---

## 7. API Reference — Ingestion

Ingestion fetches articles from a registered source and writes them to the database. The scheduler handles this automatically every 5 minutes. Use the manual endpoint for immediate updates or testing.

---

### `POST /ingest/`

Trigger immediate ingestion for a single source.

**When to use:**
- After registering a new source and wanting articles immediately (before the scheduler fires)
- During development to test a new source
- Manually refreshing a specific source

**Request body:**

```json
{
  "source_id": 1
}
```

| Field | Required | Description |
|---|---|---|
| `source_id` | Yes | ID from `GET /sources/` |

```bash
curl -X POST http://localhost:8000/ingest/ \
  -H "Content-Type: application/json" \
  -d '{"source_id": 1}'
```

**Response — 200 OK:**
```json
{
  "source_id": 1,
  "source_type": "rss",
  "ingested": 42
}
```

`ingested` is the number of articles written or updated (not strictly new — re-ingesting a source that already has all articles will return the same count because `ON CONFLICT DO UPDATE` processes all rows).

**Error responses:**

| Status | Reason |
|---|---|
| `404` | Source not found |
| `400` | Source type is not `"rss"` or `"rest"` |

---

## 8. API Reference — AI Providers

AI providers are used as a fallback normalizer when the deterministic normalizer produces output that fails validation (missing title, invalid URL, etc.). You register providers, then activate one — only one provider is active at a time.

**Supported providers:**

| Provider | SDK used | Notes |
|---|---|---|
| `anthropic` | Anthropic SDK | Claude models |
| `openai` | OpenAI SDK | GPT models |
| `gemini` | OpenAI SDK | Google Gemini via OpenAI-compat endpoint; `base_url` auto-filled |
| `custom` | OpenAI SDK | Any OpenAI-compatible server: Ollama, vLLM, LM Studio, etc. |

**Recommended models by provider:**

| Provider | Model ID | Notes |
|---|---|---|
| `anthropic` | `claude-haiku-4-5-20251001` | Fastest, cheapest |
| `anthropic` | `claude-sonnet-4-6` | Higher quality |
| `openai` | `gpt-4o-mini` | Good quality/cost ratio |
| `openai` | `gpt-4o` | Highest quality |
| `gemini` | `gemini-1.5-flash` | Fast and free-tier friendly |
| `gemini` | `gemini-2.0-flash` | Newer, faster |
| `custom` | `llama3.2` (Ollama) | Local, no API cost |

---

### `POST /ai-providers/`

Register a new AI provider configuration. The new config starts **inactive** — call `PATCH /{id}/activate` to use it.

**When to use:** Any time you want to register a provider (even if you don't activate it yet). You can have multiple configs registered and switch between them.

**Request body:**

```json
{
  "name": "string",
  "provider": "anthropic" | "openai" | "gemini" | "custom",
  "model": "string",
  "api_key": "string",
  "base_url": "string | null"
}
```

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Friendly label, e.g. `"My Claude Haiku"` |
| `provider` | Yes | One of: `anthropic`, `openai`, `gemini`, `custom` |
| `model` | Yes | Provider-specific model identifier |
| `api_key` | Yes | Your API key for the provider |
| `base_url` | Conditional | **Required** for `custom`. Optional for others. Auto-filled for `gemini`. |

**Example — Anthropic Claude:**
```bash
curl -X POST http://localhost:8000/ai-providers/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Claude Haiku",
    "provider": "anthropic",
    "model": "claude-haiku-4-5-20251001",
    "api_key": "sk-ant-api03-..."
  }'
```

**Example — OpenAI GPT-4o-mini:**
```bash
curl -X POST http://localhost:8000/ai-providers/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "GPT-4o-mini",
    "provider": "openai",
    "model": "gpt-4o-mini",
    "api_key": "sk-proj-..."
  }'
```

**Example — Google Gemini:**
```bash
curl -X POST http://localhost:8000/ai-providers/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Gemini Flash",
    "provider": "gemini",
    "model": "gemini-1.5-flash",
    "api_key": "AIzaSy..."
  }'
```
`base_url` is automatically set to `https://generativelanguage.googleapis.com/v1beta/openai/` — do not include it.

**Example — Ollama (local):**
```bash
curl -X POST http://localhost:8000/ai-providers/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Ollama Llama3",
    "provider": "custom",
    "model": "llama3.2",
    "api_key": "ollama",
    "base_url": "http://localhost:11434/v1"
  }'
```

**Example — vLLM (self-hosted):**
```bash
curl -X POST http://localhost:8000/ai-providers/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "vLLM Mistral",
    "provider": "custom",
    "model": "mistralai/Mistral-7B-Instruct-v0.2",
    "api_key": "EMPTY",
    "base_url": "http://localhost:8000/v1"
  }'
```

**Example — LM Studio:**
```bash
curl -X POST http://localhost:8000/ai-providers/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "LM Studio Local",
    "provider": "custom",
    "model": "lmstudio-community/Meta-Llama-3-8B-Instruct-GGUF",
    "api_key": "lm-studio",
    "base_url": "http://localhost:1234/v1"
  }'
```

**Response — 201 Created:**
```json
{
  "id": 1,
  "name": "Claude Haiku",
  "provider": "anthropic",
  "model": "claude-haiku-4-5-20251001",
  "base_url": null,
  "is_active": false,
  "created_at": "2026-02-20T10:00:00Z"
}
```

Note: `api_key` is **never** returned in any response.

**Error responses:**

| Status | Reason |
|---|---|
| `422` | `provider="custom"` without `base_url`, or missing required fields |

---

### `GET /ai-providers/`

List all registered provider configs.

```bash
curl http://localhost:8000/ai-providers/
```

**Response — 200 OK:** Array of `AIProviderResponse` objects.

---

### `GET /ai-providers/active`

Return the currently active provider, or `null` if none is set.

**When to use:** Verify which provider will be used on the next ingest run.

```bash
curl http://localhost:8000/ai-providers/active
```

**Response — 200 OK:** `AIProviderResponse` object, or `null`.

---

### `GET /ai-providers/{provider_id}`

Get a specific provider config by ID.

```bash
curl http://localhost:8000/ai-providers/1
```

**Error responses:**

| Status | Reason |
|---|---|
| `404` | Provider config not found |

---

### `PATCH /ai-providers/{provider_id}/activate`

Set this provider as the active one. All other providers are deactivated atomically. The change takes effect on the **next** ingest run.

**When to use:**
- Switching from one AI provider to another
- Activating a provider after registration

```bash
curl -X PATCH http://localhost:8000/ai-providers/1/activate
```

**Response — 200 OK:**
```json
{
  "activated_id": 1,
  "message": "'Claude Haiku' (anthropic:claude-haiku-4-5-20251001) is now active"
}
```

**Error responses:**

| Status | Reason |
|---|---|
| `404` | Provider config not found |

---

### `DELETE /ai-providers/active`

Deactivate all providers. Ingestion reverts to `ANTHROPIC_API_KEY` env var fallback, or deterministic-only if no env key is set.

**When to use:** Temporarily disable AI normalization without deleting configs.

```bash
curl -X DELETE http://localhost:8000/ai-providers/active
```

**Response — 204 No Content**

---

### `DELETE /ai-providers/{provider_id}`

Permanently remove a provider config.

**When to use:** Rotating API keys (delete old, create new with updated key).

```bash
curl -X DELETE http://localhost:8000/ai-providers/1
```

**Response — 204 No Content**

**Error responses:**

| Status | Reason |
|---|---|
| `404` | Provider config not found |

---

## 9. Ingestion Pipeline Deep Dive

When `POST /ingest/` is called (or the scheduler fires), `IngestionService.ingest(source)` runs this exact sequence:

```
1. _fetch_items(source)
   ├── type="rss"  → RSSFetcher.fetch(url) via asyncio.to_thread(feedparser.parse)
   └── type="rest" → RestFetcher.fetch(url, headers) via httpx AsyncClient
   → All items coerced to plain Python dicts (to_plain_dict)
   → Returns [] on any fetch failure (logged, never raises to HTTP layer)

2. raw_repo.store_batch(source_id, raw_items)
   → Computes SHA-256(source_id + sorted JSON) for each item
   → INSERT ... ON CONFLICT DO NOTHING on content_hash
   → Returns count of *new* items actually stored
   → Idempotent: re-running never double-stores

3. _load_ai_provider()
   → Queries ai_provider_configs WHERE is_active=true
   → If found: create_from_config() → cached AIProvider instance
   → If not found: get_env_fallback_provider() → AnthropicProvider from env var
   → If no env var: None (deterministic-only mode)
   → ONE DB query for the entire batch

4. For each raw item:
   a. source_normalizer.normalize(raw)
      → Maps RSS/REST fields to canonical dict
      → parse_date handles RFC 2822 (RSS) and ISO 8601 (REST)
   b. canonical_validator.validate(data)
      → Checks title is not placeholder ("Untitled", "")
      → Checks url starts with http:// or https://
   c. If valid → add to valid_articles, record hash as "deterministic"
   d. If invalid AND ai_provider is not None:
      → ai_provider.normalize(raw, source_type) → LLM call
      → canonical_validator.validate(ai_output)
      → If valid → add to valid_articles, record hash as ai_provider.model_id
      → If invalid → add hash to failed_hashes

5. article_repo.upsert_batch(valid_articles, source_id)
   → Single INSERT ... VALUES (...) for all valid articles
   → ON CONFLICT(url) DO UPDATE SET title=..., description=..., image_url=...,
     raw_payload=..., updated_at=now()
   → One DB round-trip regardless of batch size

6. raw_repo.mark_normalized / mark_failed  (best-effort)
   → Updates raw_ingestion_events.status, normalized_by, processed_at
   → Wrapped in try/except — failure here never undoes step 5
```

### What Happens to Each Article

```
Raw item fetched
       │
       ├─→ stored in raw_ingestion_events (always, idempotent)
       │
       ▼
deterministic normalize()
       │
       ├─→ valid?  YES → written to articles, raw_event → status="normalized"
       │
       └─→ valid?  NO  → AI provider available?
                              │
                        YES ──┼──→ AI normalize()
                              │         │
                              │    valid? YES → written to articles,
                              │                 raw_event → status="normalized",
                              │                 normalized_by="ai:anthropic:claude-..."
                              │
                              │    valid? NO  → raw_event → status="failed"
                              │
                        NO ───┴──→ raw_event → status="failed"
```

---

## 10. AI Normalization System

### Provider Resolution Priority

Every `ingest()` call resolves the provider exactly once:

```
1. DB: ai_provider_configs WHERE is_active = true
   (configured via POST /ai-providers/ + PATCH /{id}/activate)

2. Env: ANTHROPIC_API_KEY in .env or environment
   (uses claude-haiku-4-5-20251001)

3. None → deterministic normalization only
```

### What the AI Does

The AI is given the raw JSON payload (exactly as fetched from the source) and asked to extract:

```json
{
  "title": "string (required)",
  "description": "string or null",
  "url": "absolute HTTP(S) URL or null",
  "published_at": "ISO 8601 UTC or null",
  "image_url": "string or null",
  "author": "string or null"
}
```

The AI output passes through `canonical_validator.validate()` — same gate as deterministic output. If it fails, the item is discarded and recorded as failed in `raw_ingestion_events`.

### Provider Instance Caching

Provider SDK clients (`AsyncAnthropic`, `AsyncOpenAI`) are long-lived objects that manage their own connection pools. The factory caches instances keyed by `(config.id, model, api_key)`. When you activate a different provider, a new instance is created from the new config — the old one stays in cache but is never looked up again.

### When AI Normalization Fires

AI only runs when the deterministic normalizer produces output that fails `validate()`. For well-formatted RSS feeds (BBC, Reuters, etc.) and standard REST APIs (NewsAPI), the deterministic path handles 100% of articles. AI is reserved for unusual sources with non-standard field names or exotic date formats.

---

## 11. Scheduler

The scheduler starts automatically when the server starts (`lifespan` in `main.py`) and stops on shutdown.

**Job:** `run_ingestion_for_all_active_sources`
- **Interval:** every 5 minutes
- **Timezone:** UTC
- **Concurrency:** `max_instances=1` — if a run takes more than 5 minutes, the next run is skipped rather than starting a parallel run
- **Session isolation:** each source gets its own `AsyncSession` so a slow or failing source does not block others

**Changing the interval:**

```python
# app/services/scheduler.py  line ~55
scheduler.add_job(
    run_ingestion_for_all_active_sources,
    trigger="interval",
    minutes=5,          # ← change this
    ...
)
```

---

## 12. Changelog — What Changed & Why

This section documents every architectural change made from the original codebase, with the reasoning.

### 1. `ON CONFLICT DO NOTHING` → `ON CONFLICT DO UPDATE`
**File:** `app/repositories/article_repo.py`

**Problem:** Publishers regularly correct articles (fix headlines, update descriptions, replace broken images). The old `DO NOTHING` strategy silently discarded every correction forever — once an article URL was in the database, its content was frozen at the first fetch.

**Fix:** `DO UPDATE` now updates `title`, `description`, `image_url`, `raw_payload`, and `updated_at` on re-ingest. `source_id` and `created_at` are excluded from the update set (they must reflect the original ingestion).

---

### 2. Per-article commits → Single batch commit
**File:** `app/repositories/article_repo.py`

**Problem:** The old loop called `await self.db.commit()` inside the `for item in feed.entries` loop. For a feed with 100 articles, this was 100 round-trips to PostgreSQL.

**Fix:** `upsert_batch(articles: list[dict], source_id: int)` takes the entire list and issues a single `INSERT ... VALUES (..., ..., ...)` with `.returning(Article.id)`. One round-trip regardless of batch size.

---

### 3. Unified `POST /ingest/` endpoint
**File:** `app/api/routes_ingest.py`

**Problem:** Two separate endpoints — `POST /ingest/rss` and `POST /ingest/api` — required callers to know what type each source was before calling. This was a leaky abstraction: the source `type` is an implementation detail of how data is fetched, not something a client should need to know.

**Fix:** Single `POST /ingest/` endpoint. The service dispatches based on `source.type` internally. The `IngestionService.ingest(source)` method already existed for this purpose.

---

### 4. `raw_ingestion_events` table + dual-write
**Files:** `app/models/raw_event.py`, `app/repositories/raw_ingestion_repo.py`, migration `c8f2a1e3b456`

**Problem:** The original system had no record of what was fetched before normalization. If the normalizer had a bug, there was no way to replay normalization on historical data without re-fetching from external sources (which may have rotated their content).

**Fix:** Every raw payload is stored in `raw_ingestion_events` before normalization. The hash (SHA-256 of `source_id + sorted payload JSON`) makes storage idempotent. To reprocess failed articles, set their `status` back to `"pending"` — no re-fetch needed.

---

### 5. `CanonicalValidator`
**File:** `app/services/normalization/canonical_validator.py`

**Problem:** The deterministic normalizer silently returned `{"title": "Untitled", "url": ""}` for broken entries. These garbage articles were written to the database and served to the frontend.

**Fix:** `validate(dict)` is called after both the deterministic and AI normalization passes. An article is only written to `articles` if it has a real title and a valid HTTP(S) URL. Invalid output is recorded in `raw_ingestion_events` with the error message.

---

### 6. APScheduler integration
**File:** `app/services/scheduler.py`, `app/main.py`

**Problem:** The system had no automatic ingestion. It only fetched articles when someone manually called `POST /ingest/`. A news aggregator that requires manual API calls to update is not an aggregator.

**Fix:** APScheduler runs `run_ingestion_for_all_active_sources()` every 5 minutes. Each source gets its own `AsyncSession` and `asyncio.gather` runs all sources concurrently. `max_instances=1` prevents pile-up.

---

### 7. Multi-model AI provider system
**Files:** `app/models/ai_provider.py`, `app/repositories/ai_provider_repo.py`, `app/schemas/ai_provider_schema.py`, `app/services/normalization/providers/`, `app/services/normalization/provider_factory.py`, `app/api/routes_ai_providers.py`, migration `d9e4f5a6b789`

**Problem:** AI normalization was hardcoded to Anthropic via `ANTHROPIC_API_KEY`. Users could not choose a different model or provider without code changes.

**Fix:** Provider abstraction layer with `AIProvider` base class and two implementations:
- `AnthropicProvider` — Claude models via Anthropic SDK (native `system` parameter)
- `OpenAICompatibleProvider` — GPT/Gemini/Ollama/vLLM/LM Studio via OpenAI SDK (configurable `base_url`)

Provider configs stored in `ai_provider_configs` table with a CRUD + activate API. One provider is active at a time. `ANTHROPIC_API_KEY` env var still works as a backwards-compatible fallback.

---

## 13. Extending the System

### Add a New RSS or REST Source

No code changes needed — use the API:
```bash
curl -X POST http://localhost:8000/sources/ \
  -H "Content-Type: application/json" \
  -d '{"name": "My Feed", "type": "rss", "url": "https://example.com/feed.xml"}'
```

### Add a New Source Type (e.g. GraphQL, WebSocket)

1. Create `app/services/fetchers/graphql_fetcher.py` with a `fetch(url, ...) -> list[dict]` method
2. In `IngestionService._fetch_items()`, add:
   ```python
   if source.type == "graphql":
       return await GraphQLFetcher().fetch(source.url, source.config)
   ```
3. Add `"graphql"` to `_SUPPORTED_SOURCE_TYPES` in `routes_ingest.py`

### Add a New AI Provider

1. Create `app/services/normalization/providers/my_provider.py`:
   ```python
   from app.services.normalization.providers.base import (
       AIProvider, NORMALIZATION_SYSTEM_PROMPT,
       build_user_message, parse_llm_output,
   )

   class MyProvider(AIProvider):
       def __init__(self, api_key: str, model: str) -> None: ...

       @property
       def model_id(self) -> str:
           return f"ai:myprovider:{self._model}"

       async def normalize(self, raw_payload: dict, source_type: str) -> dict | None:
           # call your SDK
           text = ...  # get response text
           return parse_llm_output(text, raw_payload)
   ```

2. In `app/services/normalization/provider_factory.py`, add to `_build()`:
   ```python
   if provider == "myprovider":
       return MyProvider(api_key=config.api_key, model=config.model)
   ```

3. In `app/models/ai_provider.py`, add to `SUPPORTED_PROVIDERS`:
   ```python
   SUPPORTED_PROVIDERS = {"anthropic", "openai", "gemini", "custom", "myprovider"}
   ```

4. In `app/schemas/ai_provider_schema.py`, extend `_PROVIDER_LITERAL`:
   ```python
   _PROVIDER_LITERAL = Literal["anthropic", "openai", "gemini", "custom", "myprovider"]
   ```

No migration needed — provider type is a string column.

### Add a New Database Table

1. Create `app/models/my_table.py` inheriting from `Base`
2. Import in `migrations/env.py`:
   ```python
   import app.models.my_table  # noqa: F401, E402
   ```
3. Create a repository in `app/repositories/my_repo.py`
4. Add a dependency factory in `app/core/deps.py`
5. Generate and apply migration:
   ```bash
   uv run alembic revision --autogenerate -m "add_my_table"
   # Review the generated file in migrations/versions/
   uv run alembic upgrade head
   ```

### Add a New API Endpoint

1. Add route function to relevant file in `app/api/` (or create a new `routes_*.py`)
2. If new file: register in `app/main.py`:
   ```python
   from app.api.routes_my_feature import router as my_router
   app.include_router(my_router, prefix="/my-feature", tags=["My Feature"])
   ```

---

## 14. Troubleshooting

### Articles not appearing after ingestion

Check `raw_ingestion_events` for failed rows:
```sql
SELECT source_id, status, error_message, normalized_by, created_at
FROM raw_ingestion_events
WHERE status = 'failed'
ORDER BY created_at DESC
LIMIT 20;
```

Common `error_message` values:
- `"validation_failed"` — normalizer produced `title="Untitled"` or `url=""`. The raw payload was non-standard. Activate an AI provider to handle it.
- Connection errors — the source URL was unreachable. Check server logs.

### AI normalization not firing

Check in order:
1. `curl http://localhost:8000/ai-providers/active` — is any provider active?
2. If `null`: is `ANTHROPIC_API_KEY` set in `.env`?
3. If both are missing, the system runs deterministic-only. This is expected behaviour.
4. Check application logs for `"No AI provider configured"` messages.

### Scheduler not running

Check startup logs for: `Scheduler started — ingestion every 5 minutes`

If missing, the lifespan handler may have failed. Check for import errors on startup.

### Duplicate articles appearing

The dedup key is `articles.url`. If a source publishes the same article at different URLs (e.g. with tracking parameters), they will appear as separate rows. Add URL normalisation in `source_normalizer.normalize()` before the `url` field is set.

### Migration conflict / "Target database is not up to date"

```bash
uv run alembic current          # see where DB currently is
uv run alembic history          # see the full chain
uv run alembic upgrade head     # apply missing migrations
```

### Database connection errors

Verify the `DATABASE_URL` format:
```
postgresql+asyncpg://user:password@host:port/dbname
```

The `+asyncpg` driver suffix is required. The standard `postgresql://` or `postgresql+psycopg2://` will not work with this async stack.

### `422 Unprocessable Entity` on POST requests

FastAPI returns 422 when request body validation fails. The response body contains a `detail` array explaining exactly which field failed and why:
```json
{
  "detail": [
    {
      "loc": ["body", "provider"],
      "msg": "Input should be 'anthropic', 'openai', 'gemini' or 'custom'",
      "type": "literal_error"
    }
  ]
}
```

---

## Health Check

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

This endpoint has no database dependency — it returns 200 as long as the Python process is running. Use it as a liveness probe.
