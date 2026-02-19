# News Aggregator Backend — Architecture Reference

This document explains every file in the repository: what it is, why it exists,
and what it is responsible for. It is meant to be the single source of truth for
anyone reading or extending this codebase.

---

## Table of Contents

1. [Project Purpose](#1-project-purpose)
2. [Tech Stack & Why](#2-tech-stack--why)
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
   - [Migrations](#58-migrations--migrations)
6. [Data Flow](#6-data-flow)
7. [Database Schema](#7-database-schema)
8. [Dependency Graph](#8-dependency-graph)
9. [Development Commands](#9-development-commands)

---

## 1. Project Purpose

A backend that:

- Ingests news articles from **RSS feeds** and **external REST APIs**
- Normalises them into a single canonical `Article` structure
- Stores everything in **PostgreSQL**
- Exposes a clean **REST API** for a frontend to consume

---

## 2. Tech Stack & Why

| Library | Version | Role | Why chosen |
|---------|---------|------|------------|
| **FastAPI** | 0.129+ | Web framework | Native async, automatic OpenAPI docs, Pydantic integration, Depends DI |
| **SQLAlchemy 2.0** | 2.0.46+ | ORM | Typed `Mapped[]` columns, async-first, JSONB support, Alembic integration |
| **asyncpg** | 0.31+ | PostgreSQL driver | Only fully async Postgres driver; required by SQLAlchemy async engine |
| **Pydantic v2** | 2.12+ | Validation & serialisation | Replaces Marshmallow; native FastAPI integration; `BaseSettings` for config |
| **pydantic-settings** | 2.13+ | Settings management | Reads `.env` with type validation; fails loudly on missing vars |
| **httpx** | 0.28+ | HTTP client | Async-native; no thread-pool hack needed unlike `requests` |
| **feedparser** | 6.0+ | RSS/Atom parsing | De-facto standard; handles malformed feeds gracefully (bozo flag) |
| **Alembic** | 1.18+ | Schema migrations | Tracks schema changes as versioned scripts; works with async SQLAlchemy |
| **uvicorn** | 0.41+ | ASGI server | Required to run FastAPI; supports `--reload` for development |
| **uv** | — | Package manager | Faster than pip; lockfile-based reproducible installs |

---

## 3. Directory Structure

```
news_app_backend/
│
├── .env                          # Environment variables (DATABASE_URL, DEBUG)
├── .python-version               # Pins Python 3.12 for uv/pyenv
├── pyproject.toml                # Project metadata and dependency declarations
├── uv.lock                       # Exact locked dependency versions
├── alembic.ini                   # Alembic configuration file
├── ARCHITECTURE.md               # This document
│
├── migrations/                   # Alembic migration scripts
│   ├── env.py                    # Async-aware migration runner
│   ├── script.py.mako            # Template for new migration files
│   └── versions/
│       └── 29df1b34a087_initial_schema.py   # Initial tables migration
│
└── app/                          # Application package
    ├── __init__.py               # Empty — marks app as a Python package
    ├── main.py                   # FastAPI app instance, middleware, router registration
    │
    ├── core/                     # Infrastructure: config, DB engine, DI wiring
    │   ├── config.py             # Settings loaded from .env via pydantic-settings
    │   ├── database.py           # Async SQLAlchemy engine and session factory
    │   └── deps.py               # FastAPI Depends factory functions
    │
    ├── models/                   # SQLAlchemy ORM table definitions
    │   ├── base.py               # Shared DeclarativeBase all models inherit from
    │   ├── source.py             # Source table (RSS feeds / REST APIs registered)
    │   └── article.py            # Article table (normalised article storage)
    │
    ├── repositories/             # Database access — only SELECT/INSERT/UPDATE/DELETE
    │   ├── source_repo.py        # CRUD for sources table
    │   └── article_repo.py       # Upsert + queries for articles table
    │
    ├── schemas/                  # Pydantic contracts for request bodies and responses
    │   ├── source_schema.py      # SourceCreate (input), SourceResponse (output)
    │   └── article_schema.py     # ArticleResponse, ArticleListResponse
    │
    ├── services/                 # Business logic and orchestration
    │   ├── ingestion_service.py  # Orchestrates fetch → normalise → store pipeline
    │   ├── source_normalizer.py  # Converts raw RSS/REST data into canonical dict
    │   └── fetchers/
    │       ├── rss_fetcher.py    # Fetches and parses RSS feeds
    │       └── rest_fetcher.py   # Fetches JSON from REST news APIs
    │
    └── api/                      # HTTP route handlers (thin controllers only)
        ├── routes_sources.py     # POST /sources, GET /sources, GET /sources/{id}
        ├── routes_articles.py    # GET /articles, GET /articles/{id}
        └── routes_ingest.py      # POST /ingest/rss, POST /ingest/api
```

---

## 4. Architectural Philosophy

The codebase follows a strict **layered architecture** where each layer has one job
and is only allowed to call the layer directly below it.

```
HTTP Request
    │
    ▼
[ API Layer ]          ← Validates input, calls service, returns schema
    │
    ▼
[ Service Layer ]      ← Business logic, orchestration, error handling
    │
    ▼
[ Repository Layer ]   ← Database access only — no business logic
    │
    ▼
[ Model Layer ]        ← Table definitions only — no methods or logic
    │
    ▼
[ PostgreSQL ]
```

**Rules enforced by this structure:**

- Routes never touch `AsyncSession` directly — they receive injected services/repos
- Repositories never call services — data flows one way
- Schemas (Pydantic) never appear inside ORM models
- Business logic never appears inside schemas or models
- External HTTP calls happen only inside `services/fetchers/`

---

## 5. Layer-by-Layer Breakdown

### 5.1 Entry Point — `app/main.py`

**What it is:** The root of the FastAPI application.

**Responsibilities:**
- Creates the `FastAPI` app instance with title and version
- Attaches `CORSMiddleware` — required for any browser-based frontend to call this API
- Configures `logging.basicConfig` at `INFO` level with timestamps and module names
- Registers all three routers with their URL prefixes and Swagger tags
- Exposes `GET /health` — a liveness probe with no DB dependency

**Why it exists:** FastAPI requires a single application object. This file is the composition
root — it imports and wires together things that should not know about each other directly.

**What it must NOT contain:** Business logic, DB access, schemas, or any imports from
`models/`, `repositories/`, or `services/`.

---

### 5.2 Core Layer — `app/core/`

This package contains infrastructure that the rest of the app depends on but that has
no knowledge of the application's domain (news, articles, sources).

---

#### `app/core/config.py`

**What it is:** Application settings, loaded and validated once at startup.

```python
class Settings(BaseSettings):
    DATABASE_URL: str   # required — app will not start if missing
    DEBUG: bool = False # optional — controls SQL echo and log verbosity
```

**Why `pydantic-settings` instead of `os.getenv`:**

`os.getenv("DATABASE_URL")` returns `None` silently if the variable is missing.
The engine then receives `None` and the error surfaces later as a cryptic
`AttributeError` or `TypeError` deep in SQLAlchemy internals.

`BaseSettings` validates the presence and type of every field at startup,
raising a clear `ValidationError` that lists exactly which variables are missing.

**What it must NOT contain:** Business logic, database connections, or imports from
other app modules.

---

#### `app/core/database.py`

**What it is:** The async SQLAlchemy engine and session factory.

```python
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,   # only logs SQL in DEBUG mode
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
```

**Key decisions explained:**

| Setting | Value | Reason |
|---------|-------|--------|
| `echo` | `settings.DEBUG` | SQL logging floods production logs; only on in debug |
| `pool_size=10` | 10 persistent connections | Avoids connection exhaustion under load |
| `max_overflow=20` | 20 burst connections | Handles traffic spikes without crashing |
| `expire_on_commit=False` | Disabled | Without this, accessing ORM attributes after `commit()` would trigger a new DB query (N+1 risk) |

**`get_db()` generator:**

```python
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
```

This is a FastAPI dependency. FastAPI calls `next()` to get the session before the
route handler runs, then after the response is sent, resumes the generator — which
exits the `async with` block, automatically closing and returning the session to the
pool. You never need `session.close()` manually.

**Why `asyncpg`:** SQLAlchemy's async mode requires an async DBAPI driver.
`asyncpg` is the only mature, fully-async PostgreSQL driver for Python.

---

#### `app/core/deps.py`

**What it is:** FastAPI dependency factories — the glue between the DI system and
the repository/service layer.

```python
async def get_source_repo(db: AsyncSession = Depends(get_db)) -> SourceRepository:
    return SourceRepository(db)

async def get_article_repo(db: AsyncSession = Depends(get_db)) -> ArticleRepository:
    return ArticleRepository(db)

async def get_ingestion_service(db: AsyncSession = Depends(get_db)) -> IngestionService:
    return IngestionService(SourceRepository(db), ArticleRepository(db))
```

**Why this file exists:**

Routes should not know how to construct services or repositories. Without this file,
every route would need to `import get_db` and `import SourceRepository` and build
them inline. That is tightly coupled and untestable (you cannot override `get_db`
in tests without patching every route).

With `deps.py`, a test only needs to override `get_source_repo` in the FastAPI
dependency overrides dict — one line — to inject a mock repository across all routes.

**Session sharing:** FastAPI caches `Depends` results per request. Both
`get_source_repo` and `get_ingestion_service` depend on `get_db`. FastAPI calls
`get_db` only once per request and passes the same session to both. They share one
transaction boundary.

---

### 5.3 Models Layer — `app/models/`

ORM table definitions. Models describe the shape of the database.
They contain **no methods, no business logic, and no imports from services or schemas.**

---

#### `app/models/base.py`

**What it is:** The SQLAlchemy declarative base.

```python
class Base(DeclarativeBase):
    pass
```

All ORM models inherit from this single `Base`. Alembic's `env.py` imports this
`Base.metadata` to know which tables exist and to generate migrations.

**Why a separate file:** If `Base` lived inside one of the model files, every other
model file would need to import from it — creating circular imports when models
reference each other via foreign keys. A dedicated `base.py` breaks that cycle.

---

#### `app/models/source.py`

**What it is:** The `sources` database table.

**Represents:** A registered news source — either an RSS feed URL or a REST API endpoint.

```
Column       Type             Constraints          Purpose
-----------  ---------------  -------------------  ----------------------------------
id           INTEGER          PK, auto-increment   Surrogate primary key
name         VARCHAR          NOT NULL             Human-readable label
type         VARCHAR          NOT NULL             "rss" or "rest" — controls fetcher
url          VARCHAR          NOT NULL, UNIQUE     The feed/API endpoint; unique to
                                                   prevent duplicate source registration
config       JSONB            nullable             Flexible per-source config (e.g.,
                                                   {"headers": {"X-Api-Key": "..."}})
is_active    BOOLEAN          default TRUE         Soft-disable without deletion
created_at   TIMESTAMPTZ      server_default NOW() Audit timestamp set by the DB
```

**Why `config` is JSONB:** Different REST APIs require different headers, pagination
params, or response field names. Rather than adding columns for every possible API's
quirks, `config` provides a flexible key-value store. The ingestion service reads
`source.config.get("headers", {})` to pass custom auth headers.

**Why `url` is UNIQUE:** Prevents registering the same feed twice. Without this,
running `POST /sources` twice with the same URL creates duplicate sources, and all
their articles get duplicated per ingestion run.

---

#### `app/models/article.py`

**What it is:** The `articles` database table.

**Represents:** A single normalised news article, regardless of whether it came from
RSS or a REST API.

```
Column        Type             Constraints                  Purpose
------------  ---------------  ---------------------------  ---------------------------------
id            INTEGER          PK, auto-increment           Surrogate primary key
source_id     INTEGER          FK → sources.id CASCADE      Which source produced this article
title         VARCHAR          NOT NULL, indexed             Article headline; indexed for search
description   TEXT             nullable                      Subtitle or excerpt from the feed
content       TEXT             nullable                      Full body text (when available)
url           VARCHAR          NOT NULL, UNIQUE, indexed     Canonical article URL;
                                                            UNIQUE enforces deduplication
image_url     VARCHAR          nullable                      Hero image for frontend cards
published_at  TIMESTAMPTZ      nullable, indexed             Original publication time (UTC);
                                                            indexed for chronological queries
raw_payload   JSONB            NOT NULL                     Complete original data from feed/API;
                                                            allows re-processing without re-fetching
created_at    TIMESTAMPTZ      server_default NOW()         When we ingested this article
updated_at    TIMESTAMPTZ      server_default NOW(),        Last time the row was modified
                               onupdate NOW()
```

**Why `url` is the deduplication key:**

The same article can appear in multiple ingestion runs (RSS feeds repeat old articles).
Using `url` as the unique key means `INSERT ... ON CONFLICT DO NOTHING` will silently
skip any article whose URL we have already stored, making ingestion idempotent.

**Why `raw_payload` is JSONB:**

Storing the complete original feed entry serves two purposes:
1. **Debugging:** If normalisation produces wrong data, you can re-process the raw payload
   without re-fetching the feed
2. **Forward compatibility:** If you add a new derived field later, you can backfill it
   from `raw_payload` instead of re-ingesting everything

**Why `ondelete="CASCADE"` on `source_id`:**

Deleting a source automatically deletes all its articles. This prevents orphaned
article rows with a broken foreign key reference.

---

### 5.4 Repository Layer — `app/repositories/`

Repositories are the **only** part of the application allowed to execute SQL.
They accept an `AsyncSession` via constructor injection, execute queries, and return
ORM objects or primitives. They contain **zero business logic**.

---

#### `app/repositories/source_repo.py`

**Responsibility:** CRUD operations on the `sources` table.

| Method | SQL | Purpose |
|--------|-----|---------|
| `create(data)` | `INSERT` | Register a new source; refreshes to get DB-generated `id` and `created_at` |
| `get_all(active_only=True)` | `SELECT WHERE is_active` | List sources; defaults to active only so disabled sources don't get ingested |
| `get_by_id(source_id)` | `SELECT WHERE id` | Lookup by PK; returns `None` on miss (route converts to 404) |

**Why `scalar_one_or_none()`:** Unlike `.first()`, it returns `None` on no-result and
raises `MultipleResultsFound` if the query returns more than one row — a useful
invariant check for PK lookups.

---

#### `app/repositories/article_repo.py`

**Responsibility:** Write and read operations on the `articles` table.

| Method | SQL | Purpose |
|--------|-----|---------|
| `upsert(data, source_id)` | `INSERT ... ON CONFLICT DO NOTHING` | Core deduplication insert; skips if URL already exists |
| `get_all(limit, offset)` | `SELECT ORDER BY published_at DESC` | Paginated article list, newest first; `nulls_last()` ensures articles without dates don't float to the top |
| `get_by_id(article_id)` | `SELECT WHERE id` | Single article lookup |
| `count()` | `SELECT COUNT(*)` | Total row count for pagination metadata |

**Why `INSERT ... ON CONFLICT DO NOTHING` instead of `MERGE` or ORM `add()`:**

This uses the PostgreSQL-native `ON CONFLICT` clause which handles the race condition
atomically at the database level. Two concurrent ingestion runs for the same source
cannot produce duplicate articles because the conflict check and insert happen in a
single atomic operation. ORM-level deduplication (`get_or_create`) would require
a SELECT first, then an INSERT, with a race window between them.

---

### 5.5 Schema Layer — `app/schemas/`

Pydantic models that define the **contract at the HTTP boundary**. They are completely
separate from ORM models. Routes accept schemas as request bodies and return schemas
as responses. SQLAlchemy ORM objects never leak out of routes.

---

#### `app/schemas/source_schema.py`

**`SourceCreate`** — Request body for `POST /sources`

```python
class SourceCreate(BaseModel):
    name: str
    type: str      # "rss" or "rest"
    url: str
    config: dict | None = None
```

Pydantic validates this before the route handler is called. FastAPI returns a `422`
automatically if the body does not match.

**`SourceResponse`** — Response for all source endpoints

```python
class SourceResponse(BaseModel):
    id: int
    name: str
    type: str
    url: str
    config: dict | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
```

`from_attributes=True` enables ORM mode — Pydantic will read attributes from the
SQLAlchemy `Source` object by attribute access instead of requiring a dict.
Without this, `return source` in a route would fail because Pydantic cannot read
from an ORM object by default.

---

#### `app/schemas/article_schema.py`

**`ArticleResponse`** — Response for single article endpoints

```python
class ArticleResponse(BaseModel):
    id: int
    source_id: int
    title: str
    description: str | None
    content: str | None
    url: str
    image_url: str | None
    published_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
```

Note: `raw_payload` is deliberately **excluded**. The JSONB blob is for internal
use and debugging — it should not be sent to the frontend.

**`ArticleListResponse`** — Paginated list response

```python
class ArticleListResponse(BaseModel):
    total: int      # total matching rows (for frontend pagination controls)
    limit: int      # echoed back for client convenience
    offset: int     # echoed back for client convenience
    items: list[ArticleResponse]
```

---

### 5.6 Service Layer — `app/services/`

Business logic lives here. Services orchestrate fetchers and repositories to
implement the ingestion pipeline. Nothing in this layer does HTTP routing or
schema validation.

---

#### `app/services/source_normalizer.py`

**What it is:** A pure transformation module. Takes a raw feed entry or API response
item and produces the canonical `dict` expected by `ArticleRepository.upsert()`.

**`_to_plain_dict(obj)`**

```python
def _to_plain_dict(obj) -> object:
    if isinstance(obj, dict): ...
    if isinstance(obj, list): ...
    if isinstance(obj, (str, int, float, bool)) or obj is None: return obj
    try:
        return {k: _to_plain_dict(v) for k, v in obj.items()}
    except Exception:
        return str(obj)
```

**Why this exists:** `feedparser` returns `FeedParserDict` — a dict subclass with
attribute access. When stored directly into SQLAlchemy's JSONB column, the
serialiser raises a `TypeError` because it expects plain Python types.
This function recursively coerces the entire structure into plain dicts and lists.

**`_parse_date(raw)`**

Tries two date formats in order:
1. **RFC 2822** (`parsedate_to_datetime`) — used by RSS: `"Tue, 18 Feb 2026 10:00:00 GMT"`
2. **ISO 8601** (`datetime.fromisoformat`) — used by REST APIs: `"2026-02-18T10:00:00Z"`

Returns a UTC-normalised `datetime` object or `None` on failure. PostgreSQL's
`TIMESTAMPTZ` column requires a proper `datetime`, not a string.

**`normalize(item)`** — The public function

Maps field names from both source types to the canonical article dict:

| Canonical field | RSS source | REST API source |
|----------------|------------|-----------------|
| `title` | `entry.title` | `item["title"]` |
| `description` | `entry.summary` | `item["description"]` |
| `url` | `entry.link` | `item["url"]` |
| `image_url` | `media_thumbnail[0].url` | `item["image_url"]` |
| `published_at` | `entry.published` (RFC 2822) | `item["publishedAt"]` (ISO 8601) |
| `raw_payload` | entire entry (coerced) | entire item (plain dict) |

---

#### `app/services/fetchers/rss_fetcher.py`

**What it is:** Fetches and parses an RSS or Atom feed from a URL.

```python
class RSSFetcher:
    async def fetch(self, url: str):
        feed = await asyncio.to_thread(feedparser.parse, url)
        ...
        return feed
```

**Why `asyncio.to_thread`:** `feedparser.parse()` is a blocking synchronous function.
Calling it directly inside an `async def` would block the entire event loop,
preventing all other requests from being served until the feed download completes.
`asyncio.to_thread` offloads it to the default thread pool, keeping the event loop free.

**Bozo flag:** feedparser sets `feed.bozo = True` when the feed is malformed XML
but still parseable. Rather than raising an exception (which would discard valid
articles from a partially-broken feed), this is logged as a warning and parsing
continues. A hard failure raises `RuntimeError` with the original cause chained.

---

#### `app/services/fetchers/rest_fetcher.py`

**What it is:** Fetches articles from a JSON REST API endpoint.

```python
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

class RestFetcher:
    async def fetch(self, url: str, headers: dict | None = None) -> list[dict]:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, headers=headers or {})
            response.raise_for_status()
        ...
```

**Why `httpx` instead of `aiohttp` or `requests`:**
- `requests` is synchronous — same problem as feedparser without `to_thread`
- `httpx` is async-native, has a clean API identical to `requests`, and is already
  in the FastAPI ecosystem

**Timeout:** 15s total / 5s connect. Without a timeout, a slow API can hold a connection
open indefinitely, exhausting the connection pool.

**Envelope unwrapping:** REST APIs return articles in different shapes:
- `[{...}, {...}]` — bare array
- `{"articles": [{...}]}` — NewsAPI style
- `{"items": [{...}]}` — generic envelope
- `{"results": [{...}]}` — another common pattern

The fetcher tries each known key and returns the first matching list, so the
ingestion service always receives a `list[dict]` regardless of the upstream API shape.

---

#### `app/services/ingestion_service.py`

**What it is:** The orchestrator of the ingestion pipeline. The highest-level service.

**Responsibilities:**
- Receives a `Source` ORM object (already loaded from DB by the route)
- Delegates to the correct fetcher based on `source.type`
- Calls `normalize()` on each raw item
- Persists valid articles via the repository
- Logs progress and skips/errors per item without aborting the full batch

```python
class IngestionService:
    def __init__(self, source_repo: SourceRepository, article_repo: ArticleRepository):
        ...

    async def ingest_rss(self, source: Source) -> int: ...
    async def ingest_api(self, source: Source) -> int: ...
    async def ingest(self, source: Source) -> int:     # dispatcher
```

**Why per-item error handling:**

```python
for item in feed.entries:
    try:
        data = normalize(item)
        await self.article_repo.upsert(data, source.id)
        count += 1
    except Exception as exc:
        logger.error("Failed to process entry: %s", exc)
```

Without this, a single malformed article (e.g., missing `title`, non-serialisable
field) would raise an exception that bubbles up and discards all remaining articles
in the feed. With per-item handling, one bad entry is logged and skipped while the
rest are saved normally.

**Why `ingest_rss` and `ingest_api` are separate methods instead of one `ingest`:**

The API routes call them directly — `POST /ingest/rss` calls `ingest_rss`, not `ingest`.
This makes the route's intent explicit and avoids the type check (`if source.type == "rss"`)
being duplicated between the route and the service. The `ingest` dispatcher is kept
as a convenience for calling from non-route contexts (e.g., background tasks or CLI scripts).

---

### 5.7 API Layer — `app/api/`

Routes are **thin controllers**. Each route does exactly three things:
1. Receive validated input (Pydantic handles this automatically)
2. Call a service or repository
3. Return a typed response schema

Routes contain **no SQL, no business logic, no direct HTTP calls**.

---

#### `app/api/routes_sources.py`

| Endpoint | Method | Handler | Purpose |
|----------|--------|---------|---------|
| `/sources/` | POST | `create_source` | Register a new RSS feed or REST API source |
| `/sources/` | GET | `list_sources` | List all active sources |
| `/sources/{id}` | GET | `get_source` | Get a single source by ID |

`create_source` returns `201 Created` (not the default `200`) because HTTP semantics
define 201 as the correct code for a resource creation that persists to the database.

All three routes receive `SourceRepository` via `Depends(get_source_repo)`. They
know nothing about `AsyncSession` or `get_db`.

---

#### `app/api/routes_articles.py`

| Endpoint | Method | Handler | Purpose |
|----------|--------|---------|---------|
| `/articles/` | GET | `list_articles` | Paginated article list |
| `/articles/{id}` | GET | `get_article` | Single article by ID |

`list_articles` accepts `limit` (1–100, default 20) and `offset` (≥0, default 0)
as query parameters validated by FastAPI's `Query()`. Returns `ArticleListResponse`
including total count for frontend pagination controls.

---

#### `app/api/routes_ingest.py`

| Endpoint | Method | Handler | Purpose |
|----------|--------|---------|---------|
| `/ingest/rss` | POST | `ingest_rss` | Trigger RSS ingestion for a source |
| `/ingest/api` | POST | `ingest_api` | Trigger REST API ingestion for a source |

Request body: `{"source_id": 1}`

Both routes validate that the source exists (404 on miss) and that its `type`
matches the route being called (400 if you POST to `/ingest/rss` with a `rest` source).
Returns `{"ingested": N}` — the count of new articles saved.

**Design note:** Ingestion is triggered manually via these endpoints. A future
enhancement would be a background scheduler (APScheduler or Celery beat) that
calls `IngestionService.ingest()` on a cron schedule for all active sources.

---

### 5.8 Migrations — `migrations/`

---

#### `alembic.ini`

Alembic's configuration file. The `sqlalchemy.url` value is intentionally left as
a placeholder — the actual URL is injected at runtime inside `env.py` from
`settings.DATABASE_URL`. This means the `.env` file is the single source of truth
for the database URL and you never hardcode it in two places.

---

#### `migrations/env.py`

**What it is:** The migration runner that Alembic executes when you run
`alembic upgrade head` or `alembic revision --autogenerate`.

**Why it was rewritten from the Alembic default:**

The default `env.py` uses the **synchronous** `engine_from_config` and `connect()`.
This is incompatible with `asyncpg`, which is an async-only driver. Running the
default env.py would raise `sqlalchemy.exc.InvalidRequestError`.

The rewritten version uses `async_engine_from_config` with `asyncio.run()` to
bridge the sync Alembic runner into an async context:

```python
async def run_async_migrations() -> None:
    connectable = async_engine_from_config(..., poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())
```

`pool.NullPool` is used instead of the default connection pool because Alembic
migrations run once and exit — a persistent pool would prevent the process from
terminating cleanly.

**Model imports:** All model modules are imported at the top of `env.py`:

```python
import app.models.article
import app.models.source
```

This is required so their `Table` objects are registered onto `Base.metadata` before
Alembic reads `target_metadata`. Without these imports, autogenerate would see
an empty metadata and try to drop all tables.

---

#### `migrations/versions/29df1b34a087_initial_schema.py`

The first (and currently only) migration. Applied to the database by running
`alembic upgrade head`.

**`upgrade()` creates:**
- `sources` table with all 7 columns, unique constraint on `url`
- `articles` table with all 11 columns, 4 indexes, foreign key constraint
- Drops the legacy `news` table that existed before this refactor

**`downgrade()` reverses:**
- Drops `articles` and `sources`
- Recreates the original `news` table (for emergency rollback)

---

## 6. Data Flow

### Registering a source and ingesting articles

```
Client
  │
  │  POST /sources {"name":"BBC","type":"rss","url":"https://..."}
  ▼
routes_sources.create_source()
  │  Pydantic validates SourceCreate
  │  Calls repo.create(payload)
  ▼
SourceRepository.create()
  │  INSERT INTO sources (...) RETURNING *
  ▼
PostgreSQL → returns Source ORM object → SourceResponse → Client (201)


Client
  │
  │  POST /ingest/rss {"source_id": 1}
  ▼
routes_ingest.ingest_rss()
  │  Calls source_repo.get_by_id(1)
  │  Validates source.type == "rss"
  │  Calls svc.ingest_rss(source)
  ▼
IngestionService.ingest_rss(source)
  │  Creates RSSFetcher()
  │  Calls fetcher.fetch(source.url)
  ▼
RSSFetcher.fetch()
  │  asyncio.to_thread(feedparser.parse, url)  ← runs in thread pool
  │  Returns feedparser.FeedParserDict
  ▼
IngestionService (continues)
  │  For each entry in feed.entries:
  │    normalize(entry)         ← coerce types, parse dates, map fields
  │    article_repo.upsert()   ← INSERT ON CONFLICT DO NOTHING
  ▼
ArticleRepository.upsert()
  │  INSERT INTO articles (...) ON CONFLICT (url) DO NOTHING
  ▼
PostgreSQL → {"ingested": 42} → Client (200)
```

### Reading articles

```
Client
  │
  │  GET /articles?limit=20&offset=0
  ▼
routes_articles.list_articles()
  │  Calls repo.get_all(limit=20, offset=0)
  │  Calls repo.count()
  ▼
ArticleRepository
  │  SELECT ... ORDER BY published_at DESC LIMIT 20 OFFSET 0
  │  SELECT COUNT(*) FROM articles
  ▼
PostgreSQL → list[Article] ORM objects
  │
  ▼
ArticleListResponse(total=N, limit=20, offset=0, items=[ArticleResponse, ...])
  │  Pydantic serialises ORM objects via from_attributes=True
  │  raw_payload excluded from response
  ▼
Client receives clean JSON
```

---

## 7. Database Schema

```
┌──────────────────────────────────────────┐
│                  sources                 │
├──────────┬───────────┬──────────────────-┤
│ id       │ INTEGER   │ PK                │
│ name     │ VARCHAR   │ NOT NULL          │
│ type     │ VARCHAR   │ NOT NULL          │  "rss" | "rest"
│ url      │ VARCHAR   │ NOT NULL, UNIQUE  │
│ config   │ JSONB     │ nullable          │  {"headers": {...}}
│ is_active│ BOOLEAN   │ default TRUE      │
│ created_at│TIMESTAMPTZ│ server NOW()     │
└──────────┴───────────┴───────────────────┘
                    │ 1
                    │
                    │ CASCADE DELETE
                    │ N
┌──────────────────────────────────────────┐
│                 articles                 │
├──────────┬──────────────┬────────────────┤
│ id       │ INTEGER      │ PK             │
│ source_id│ INTEGER      │ FK → sources   │  indexed
│ title    │ VARCHAR      │ NOT NULL       │  indexed
│ description│ TEXT       │ nullable       │
│ content  │ TEXT         │ nullable       │
│ url      │ VARCHAR      │ UNIQUE         │  indexed — dedup key
│ image_url│ VARCHAR      │ nullable       │
│published_at│TIMESTAMPTZ │ nullable       │  indexed — sort key
│ raw_payload│ JSONB      │ NOT NULL       │
│ created_at │TIMESTAMPTZ │ server NOW()   │
│ updated_at │TIMESTAMPTZ │ server NOW()   │
└──────────┴──────────────┴────────────────┘
```

---

## 8. Dependency Graph

Arrows mean "imports from / depends on":

```
main.py
  ├── api/routes_sources.py
  │     ├── core/deps.py → get_source_repo
  │     └── schemas/source_schema.py
  │
  ├── api/routes_articles.py
  │     ├── core/deps.py → get_article_repo
  │     └── schemas/article_schema.py
  │
  └── api/routes_ingest.py
        ├── core/deps.py → get_source_repo, get_ingestion_service
        └── (no schema imports — uses inline IngestRequest)

core/deps.py
  ├── core/database.py → get_db
  ├── repositories/source_repo.py
  ├── repositories/article_repo.py
  └── services/ingestion_service.py

core/database.py
  └── core/config.py → settings

repositories/source_repo.py
  ├── models/source.py
  └── schemas/source_schema.py  (SourceCreate type hint only)

repositories/article_repo.py
  └── models/article.py

services/ingestion_service.py
  ├── models/source.py            (Source type hint)
  ├── repositories/source_repo.py (type hints)
  ├── repositories/article_repo.py
  ├── services/fetchers/rss_fetcher.py
  ├── services/fetchers/rest_fetcher.py
  └── services/source_normalizer.py

models/*.py
  └── models/base.py              (Base)

migrations/env.py
  ├── models/base.py              (Base.metadata)
  ├── models/article.py           (registers table)
  ├── models/source.py            (registers table)
  └── core/config.py              (DATABASE_URL)
```

**Key invariant:** No arrows point upward from `models/` to `repositories/`,
`services/`, or `api/`. The model layer has zero knowledge of anything above it.

---

## 9. Development Commands

```bash
# Install dependencies
uv sync

# Run dev server with auto-reload
uv run uvicorn app.main:app --reload

# Create a new migration after changing models
uv run alembic revision --autogenerate -m "describe_change"

# Apply all pending migrations
uv run alembic upgrade head

# Roll back one migration
uv run alembic downgrade -1

# Check current migration state
uv run alembic current

# View migration history
uv run alembic history --verbose
```

**End-to-end test flow:**

```bash
# 1. Start server
uv run uvicorn app.main:app --reload

# 2. Register an RSS source
curl -X POST http://localhost:8000/sources \
  -H "Content-Type: application/json" \
  -d '{"name":"BBC News","type":"rss","url":"https://feeds.bbci.co.uk/news/rss.xml"}'
# Response: {"id":1, ...}

# 3. Trigger ingestion
curl -X POST http://localhost:8000/ingest/rss \
  -H "Content-Type: application/json" \
  -d '{"source_id":1}'
# Response: {"ingested":42}

# 4. Read articles
curl "http://localhost:8000/articles?limit=5&offset=0"

# 5. Read single article
curl "http://localhost:8000/articles/1"

# 6. Full API docs
open http://localhost:8000/docs
```
