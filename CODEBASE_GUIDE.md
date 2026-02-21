# News App Backend — Complete Developer Guide

> A full map of every file, folder, database table, and line of code.
> Written so a new developer can open this once and understand *everything*.

---

## Table of Contents

1. [What This Project Does](#1-what-this-project-does)
2. [Tech Stack at a Glance](#2-tech-stack-at-a-glance)
3. [Directory Tree (Annotated)](#3-directory-tree-annotated)
4. [Where to Enter — The Request Lifecycle](#4-where-to-enter--the-request-lifecycle)
5. [Layer-by-Layer Walkthrough](#5-layer-by-layer-walkthrough)
   - [Entry Point — `app/main.py`](#51-entry-point--appmainpy)
   - [Core Infrastructure — `app/core/`](#52-core-infrastructure--appcore)
   - [ORM Models — `app/models/`](#53-orm-models--appmodels)
   - [Repositories — `app/repositories/`](#54-repositories--apprepositories)
   - [Pydantic Schemas — `app/schemas/`](#55-pydantic-schemas--appschemas)
   - [Services — `app/services/`](#56-services--appservices)
   - [API Routes — `app/api/`](#57-api-routes--appapi)
   - [Migrations — `migrations/`](#58-migrations--migrations)
6. [Database Tables — Full Reference](#6-database-tables--full-reference)
7. [The Ingestion Pipeline (Step-by-Step)](#7-the-ingestion-pipeline-step-by-step)
8. [AI Normalization System](#8-ai-normalization-system)
9. [Scheduler](#9-scheduler)
10. [Configuration & Environment](#10-configuration--environment)
11. [How Data Flows (End-to-End Diagram)](#11-how-data-flows-end-to-end-diagram)
12. [Line-by-Line Code Reference](#12-line-by-line-code-reference)

---

## 1. What This Project Does

This is a **news aggregator backend** that:

1. Lets you register news **sources** (RSS feeds or REST APIs).
2. **Fetches** those sources every 5 minutes via a background scheduler (or on-demand via API).
3. **Normalizes** raw payloads into a canonical article shape — first with deterministic field mapping, then with an AI fallback if the deterministic pass fails.
4. **Stores** articles in PostgreSQL with upsert semantics (so if a publisher corrects a typo, your DB is corrected too).
5. Keeps a raw **audit trail** of every fetched payload before normalization.
6. Lets you configure **AI providers** (Anthropic Claude, OpenAI GPT, Google Gemini, or any OpenAI-compatible server) via API rather than hardcoding.
7. Exposes a **REST API** to the frontend for sources, articles, ingestion triggers, and AI provider management.

---

## 2. Tech Stack at a Glance

| Concern | Library | Why |
|---|---|---|
| Web framework | **FastAPI** | Async-first, auto OpenAPI docs, Pydantic integration |
| Database | **PostgreSQL** | JSONB for raw payloads, partial indexes, reliable upsert |
| Async DB driver | **asyncpg** | Non-blocking PostgreSQL over pure Python |
| ORM | **SQLAlchemy 2.0** | Async sessions, typed mapped columns |
| Migrations | **Alembic** | Version-controlled schema changes |
| Validation | **Pydantic v2** | Fast, composable, typed request/response models |
| RSS parsing | **feedparser** | Battle-tested, handles malformed feeds gracefully |
| HTTP client | **httpx** | Async-first, modern API, timeouts |
| Scheduling | **APScheduler** | In-process async scheduler, no external queue needed |
| AI (Anthropic) | **anthropic** SDK | Claude models |
| AI (OpenAI compat) | **openai** SDK | GPT, Gemini, Ollama, vLLM, LM Studio |
| Settings | **pydantic-settings** | Typed env-var loading from `.env` |

---

## 3. Directory Tree (Annotated)

```
news_app_backend/
│
├── app/                          ← All application code lives here
│   ├── __init__.py               ← Empty; makes `app` a Python package
│   ├── main.py                   ← FastAPI app creation, router registration, lifespan
│   │
│   ├── core/                     ← Shared infrastructure (config, DB engine, DI)
│   │   ├── config.py             ← Reads .env into a typed Settings object
│   │   ├── database.py           ← Creates async SQLAlchemy engine + session factory
│   │   └── deps.py               ← FastAPI dependency functions (repo factories, service factory)
│   │
│   ├── models/                   ← SQLAlchemy ORM table definitions
│   │   ├── base.py               ← DeclarativeBase all models inherit from
│   │   ├── source.py             ← `sources` table
│   │   ├── article.py            ← `articles` table
│   │   ├── raw_event.py          ← `raw_ingestion_events` table
│   │   └── ai_provider.py        ← `ai_provider_configs` table + provider constants
│   │
│   ├── repositories/             ← Data access layer — all SQL lives here
│   │   ├── source_repo.py        ← CRUD for sources
│   │   ├── article_repo.py       ← Batch upsert + queries for articles
│   │   ├── raw_ingestion_repo.py ← Insert/status-update for raw events
│   │   └── ai_provider_repo.py   ← CRUD + activate/deactivate for AI configs
│   │
│   ├── schemas/                  ← Pydantic models for HTTP request/response bodies
│   │   ├── source_schema.py      ← SourceCreate, SourceResponse
│   │   ├── article_schema.py     ← ArticleResponse, ArticleListResponse
│   │   └── ai_provider_schema.py ← AIProviderCreate, AIProviderResponse, ActivateResponse
│   │
│   ├── services/                 ← Business logic (no HTTP, no SQL here)
│   │   ├── source_normalizer.py  ← Deterministic field mapping (RSS/REST → canonical)
│   │   ├── ingestion_service.py  ← Orchestrates the full fetch→normalize→store pipeline
│   │   ├── scheduler.py          ← APScheduler setup; runs ingestion every 5 min
│   │   │
│   │   ├── fetchers/             ← Source-type-specific HTTP clients
│   │   │   ├── rss_fetcher.py    ← Wraps feedparser in asyncio.to_thread
│   │   │   └── rest_fetcher.py   ← httpx async GET with envelope unwrapping
│   │   │
│   │   └── normalization/        ← AI normalization subsystem
│   │       ├── canonical_validator.py  ← Gate check: valid title + valid URL required
│   │       ├── ai_processor.py         ← Env-var fallback loader (backwards compat)
│   │       ├── provider_factory.py     ← Instantiates + caches provider objects
│   │       └── providers/
│   │           ├── base.py             ← AIProvider ABC + shared prompt + parser
│   │           ├── anthropic_prov.py   ← Claude via Anthropic SDK
│   │           └── openai_prov.py      ← GPT/Gemini/custom via OpenAI SDK
│   │
│   └── api/                      ← FastAPI route handlers
│       ├── routes_sources.py     ← POST/GET /sources
│       ├── routes_articles.py    ← GET /articles (paginated)
│       ├── routes_ingest.py      ← POST /ingest (trigger ingestion)
│       └── routes_ai_providers.py ← CRUD + activate/deactivate /ai-providers
│
├── migrations/                   ← Alembic migration files
│   ├── env.py                    ← Alembic runtime config (async engine, imports models)
│   ├── README                    ← Single-line placeholder
│   ├── script.py.mako            ← Template for auto-generated migration files
│   └── versions/
│       ├── 29df1b34a087_initial_schema.py          ← Creates sources + articles tables
│       ├── c8f2a1e3b456_add_raw_ingestion_events.py ← Adds raw_ingestion_events
│       └── d9e4f5a6b789_add_ai_provider_configs.py  ← Adds ai_provider_configs
│
├── .env                          ← Secret values (DATABASE_URL, API keys) — never commit
├── .gitignore                    ← Excludes .env, __pycache__, .venv
├── .python-version               ← Pins Python 3.12 (used by pyenv/uv)
├── alembic.ini                   ← Alembic logging + script_location config
├── pyproject.toml                ← Project metadata + all dependencies
├── GUIDE.md                      ← High-level developer guide (pre-existing)
├── ARCHITECTURE.md               ← Architecture reference (pre-existing)
└── CODEBASE_GUIDE.md             ← This file — complete line-by-line reference
```

---

## 4. Where to Enter — The Request Lifecycle

**A new developer should start reading in this order:**

```
1. app/main.py          ← What is the app? What routes exist? What runs at startup?
2. app/core/config.py   ← What env vars are needed?
3. app/core/database.py ← How does the DB connection work?
4. app/core/deps.py     ← How do routes get their repositories and services?
5. app/models/          ← What tables exist in PostgreSQL?
6. app/repositories/    ← How is data read/written?
7. app/schemas/         ← What does the API accept/return?
8. app/api/             ← What HTTP endpoints exist?
9. app/services/        ← Where is the business logic?
10. migrations/         ← How did the DB schema get created?
```

**For a specific API request, trace it like this:**

```
HTTP Request
    ↓
app/main.py            (which router handles this prefix?)
    ↓
app/api/routes_*.py    (which handler function?)
    ↓
app/core/deps.py       (FastAPI Depends → which repo/service is injected?)
    ↓
app/repositories/*.py  (how is the DB queried?)
    ↓
app/models/*.py        (what SQLAlchemy ORM class maps to which table?)
    ↓
PostgreSQL             (actual data)
    ↓ (back up)
app/schemas/*.py       (what Pydantic model shapes the response?)
    ↓
HTTP Response (JSON)
```

**For understanding ingestion specifically:**

```
POST /ingest  OR  scheduler fires every 5 min
    ↓
app/api/routes_ingest.py → IngestionService.ingest()
    ↓
app/services/ingestion_service.py
    ↓ fetch
app/services/fetchers/rss_fetcher.py  OR  rest_fetcher.py
    ↓ raw store
app/repositories/raw_ingestion_repo.py
    ↓ normalize (deterministic)
app/services/source_normalizer.py
    ↓ validate
app/services/normalization/canonical_validator.py
    ↓ (if invalid) AI fallback
app/services/normalization/ai_processor.py
    → app/services/normalization/provider_factory.py
    → app/services/normalization/providers/anthropic_prov.py OR openai_prov.py
    ↓ batch upsert
app/repositories/article_repo.py
```

---

## 5. Layer-by-Layer Walkthrough

### 5.1 Entry Point — `app/main.py`

**Purpose:** Creates the FastAPI application, wires up routers, adds middleware, and manages the scheduler lifecycle.

```python
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_ai_providers import router as ai_provider_router
from app.api.routes_articles import router as article_router
from app.api.routes_ingest import router as ingest_router
from app.api.routes_sources import router as source_router
from app.services.scheduler import start_scheduler, stop_scheduler
```
**Lines 1-13:** Standard imports. Each `routes_*.py` exports a single `router` object. The scheduler start/stop functions are imported to hook into the app lifecycle.

```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
```
**Lines 15-18:** Configures Python's standard logger for the whole process. Every module uses `logging.getLogger(__name__)` so logs show which module produced them.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()
```
**Lines 20-23:** FastAPI's lifespan protocol (replaces the deprecated `on_event` hooks).
- Code **before** `yield` runs at startup → starts the APScheduler.
- Code **after** `yield` runs at shutdown → stops it gracefully.
- Without this, ingestion would never run automatically.

```python
app = FastAPI(title="News Aggregator API", version="0.2.0", lifespan=lifespan)
```
**Line 25:** Creates the FastAPI application instance. `lifespan=lifespan` attaches the lifecycle manager. The title/version appear in the auto-generated `/docs` OpenAPI UI.

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```
**Lines 27-33:** Adds CORS headers so any browser (any origin) can call this API. `allow_origins=["*"]` is open for development — in production you would restrict this to your frontend's domain.

```python
app.include_router(source_router,      prefix="/sources",      tags=["Sources"])
app.include_router(article_router,     prefix="/articles",     tags=["Articles"])
app.include_router(ingest_router,      prefix="/ingest",       tags=["Ingestion"])
app.include_router(ai_provider_router, prefix="/ai-providers", tags=["AI Providers"])
```
**Lines 35-38:** Mounts each router under its URL prefix. The `tags` group endpoints in the `/docs` UI. All routes in `routes_sources.py` will be under `/sources/*`, etc.

```python
@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}
```
**Lines 40-42:** Simple health check endpoint. Load balancers and monitoring tools hit this to verify the server is running.

---

### 5.2 Core Infrastructure — `app/core/`

#### `app/core/config.py`

**Purpose:** Reads environment variables (from `.env` or the shell) into a typed Python object. All other modules import `settings` from here — nothing reads `os.environ` directly.

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str           # Required — app crashes at startup if missing
    DEBUG: bool = False         # Optional — enables SQLAlchemy query echo
    ANTHROPIC_API_KEY: str | None = None  # Optional — enables env-var AI fallback

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
```

- `BaseSettings` automatically reads matching env vars or `.env` file entries.
- `DATABASE_URL: str` has no default, so the app fails loudly at startup if it's missing.
- `ANTHROPIC_API_KEY: str | None = None` means the app works without AI — articles just use deterministic normalization only.
- `settings = Settings()` is a module-level singleton — it's created once when first imported.

#### `app/core/database.py`

**Purpose:** Creates the async SQLAlchemy engine and session factory. This is the one place where the database connection is configured.

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,  # e.g. "postgresql+asyncpg://user:pass@host/db"
    echo=settings.DEBUG,    # If DEBUG=True, all SQL is printed to stdout
    pool_size=10,           # Keep 10 connections open in the pool
    max_overflow=20,        # Allow 20 extra connections when pool is exhausted
)
```
- `create_async_engine` uses **asyncpg** (the `+asyncpg` in the URL) for non-blocking PostgreSQL.
- Connection pool: up to 10 persistent + 20 overflow = 30 concurrent DB operations max.

```python
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
```
- A **session factory**. Call `AsyncSessionLocal()` to get a new `AsyncSession`.
- `expire_on_commit=False` means ORM objects remain accessible after a commit (important for async code where you don't want implicit lazy-loads).

```python
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
```
- A FastAPI dependency generator. Used in `deps.py` via `Depends(get_db)`.
- `async with` ensures the session is **closed** even if an exception occurs.
- `yield` turns it into a generator so FastAPI can inject it into route handlers.

#### `app/core/deps.py`

**Purpose:** FastAPI dependency injection wiring. Route handlers declare what they need (a repo, a service) via `Depends(...)`, and these functions provide them — all wired to the same DB session for that request.

```python
async def get_source_repo(db: AsyncSession = Depends(get_db)) -> SourceRepository:
    return SourceRepository(db)
```
Every `get_*_repo` function follows this pattern: get a DB session, wrap it in a repository, return it. FastAPI creates a fresh DB session per request and injects it here.

```python
async def get_ingestion_service(db: AsyncSession = Depends(get_db)) -> IngestionService:
    return IngestionService(
        source_repo=SourceRepository(db),
        article_repo=ArticleRepository(db),
        raw_repo=RawIngestionRepository(db),
        ai_provider_repo=AIProviderRepository(db),
    )
```
`IngestionService` needs all four repositories. They all share the **same `db` session instance** for that request — this means operations are part of the same transaction scope.

---

### 5.3 ORM Models — `app/models/`

#### `app/models/base.py`

```python
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass
```
All ORM models inherit from `Base`. SQLAlchemy uses this to track the `metadata` (all tables) needed for Alembic migrations. Nothing else goes here.

#### `app/models/source.py` → `sources` table

```python
class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Auto-increment integer PK

    name: Mapped[str] = mapped_column(String, nullable=False)
    # Human-readable label, e.g. "BBC World News"

    type: Mapped[str] = mapped_column(String, nullable=False)
    # "rss" or "rest" — controls which fetcher is used

    url: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    # The feed or API URL — must be unique (can't register same URL twice)

    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Flexible extra config, e.g. {"headers": {"X-API-Key": "..."}} for REST sources

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # If False, scheduler skips this source

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Set by PostgreSQL at INSERT time (not Python) — timezone-aware
```

#### `app/models/article.py` → `articles` table

```python
class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)

    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    # Links to sources.id. CASCADE means: delete a source → all its articles are deleted too.
    # index=True speeds up queries like "give me all articles from source X"

    title: Mapped[str] = mapped_column(String, index=True)
    # Indexed for potential full-text or prefix searches

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 1-3 sentence summary. Text (not String) = unlimited length in PostgreSQL.

    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Full article body. Currently always None — reserved for future full-text fetch.

    url: Mapped[str] = mapped_column(String, unique=True, index=True)
    # Canonical article URL. UNIQUE constraint = dedup key.
    # The upsert in article_repo.py uses this as the conflict target.

    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Hero image URL extracted from RSS media:thumbnail or REST payload

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )
    # Publisher's publication time. Indexed — the default sort in list_articles.
    # Nullable because some sources don't include a date.

    raw_payload: Mapped[dict] = mapped_column(JSONB)
    # The complete original payload as fetched, stored as JSONB.
    # Updated on every re-fetch so you always have the latest version.

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # First time this article was ever ingested.

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # Updated every time the article is modified (on conflict do update).
```

#### `app/models/raw_event.py` → `raw_ingestion_events` table

```python
class RawIngestionEvent(Base):
    __tablename__ = "raw_ingestion_events"

    id: Mapped[int] = mapped_column(primary_key=True)

    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )

    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # SHA-256 of (source_id + canonical JSON of raw_payload).
    # This is the dedup key — inserting the same payload twice is a no-op.
    # 64 chars = hex-encoded SHA-256.

    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Exact raw dict as fetched (before any normalization).

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # Lifecycle: "pending" → "normalized" or "failed"

    normalized_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Which normalizer succeeded: "deterministic", "ai:anthropic:claude-haiku-...", etc.

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # If status="failed", why?

    retry_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    # How many times normalization was attempted.

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # When the raw payload was first stored.

    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # When it was normalized or marked failed.
```

#### `app/models/ai_provider.py` → `ai_provider_configs` table

```python
# Module-level constants (not DB columns — just Python dicts used elsewhere):

SUPPORTED_PROVIDERS = {"anthropic", "openai", "gemini", "custom"}
# Validated in AIProviderCreate schema

PROVIDER_BASE_URLS: dict[str, str | None] = {
    "anthropic": None,     # Anthropic SDK uses its own default
    "openai": None,        # OpenAI SDK uses its own default
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    # Gemini needs an explicit base URL because it uses the OpenAI-compatible endpoint
    "custom": None,        # User must supply their own base_url
}

PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-1.5-flash",
    "custom": "your-model-name",
}

class AIProviderConfig(Base):
    __tablename__ = "ai_provider_configs"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Friendly label: "My Claude Haiku", "Production GPT-4o", etc.

    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    # One of: "anthropic", "openai", "gemini", "custom"

    model: Mapped[str] = mapped_column(String(100), nullable=False)
    # Model identifier: "claude-haiku-4-5-20251001", "gpt-4o-mini", etc.

    api_key: Mapped[str] = mapped_column(String(500), nullable=False)
    # Stored in plaintext. Consider encrypting in production.

    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Override provider's default endpoint. Required for "custom".

    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Only ONE row can have is_active=True (enforced by partial unique index in migration).
    # Default is False — must explicitly activate after creation.

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

---

### 5.4 Repositories — `app/repositories/`

Repositories are the **only** place that writes SQL. Services and routes call repository methods — they never use `session.execute(select(...))` directly.

#### `app/repositories/source_repo.py`

```python
class SourceRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
    # Constructor takes the session injected by deps.py

    async def create(self, data: SourceCreate) -> Source:
        source = Source(**data.model_dump())
        # Unpacks the Pydantic schema into keyword args for the ORM model
        self.db.add(source)
        # Stages the INSERT (not sent to DB yet)
        await self.db.commit()
        # Sends the INSERT, commits the transaction
        await self.db.refresh(source)
        # Re-fetches the row from DB to populate server-default columns (id, created_at)
        return source

    async def get_all(self, active_only: bool = True) -> list[Source]:
        stmt = select(Source)
        if active_only:
            stmt = stmt.where(Source.is_active.is_(True))
        # .is_(True) generates "WHERE is_active IS TRUE" — handles NULL correctly
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
        # .scalars() extracts the ORM objects from the result rows

    async def get_by_id(self, source_id: int) -> Source | None:
        result = await self.db.execute(
            select(Source).where(Source.id == source_id)
        )
        return result.scalar_one_or_none()
        # Returns None if not found (vs scalar_one() which raises)
```

#### `app/repositories/article_repo.py`

```python
async def upsert_batch(self, articles: list[dict], source_id: int) -> int:
    """The most important method in the repo layer."""
    if not articles:
        return 0

    rows = [
        {
            "source_id": source_id,
            "title": a["title"],
            "description": a.get("description"),
            "content": a.get("content"),
            "url": a["url"],
            "image_url": a.get("image_url"),
            "published_at": a.get("published_at"),
            "raw_payload": a["raw_payload"],
        }
        for a in articles
    ]
    # Transforms list of canonical dicts into list of DB row dicts

    stmt = insert(Article).values(rows)
    # PostgreSQL-dialect INSERT (from sqlalchemy.dialects.postgresql)
    # Sends all rows in a single statement — much faster than N individual INSERTs

    stmt = stmt.on_conflict_do_update(
        index_elements=["url"],
        # If a row with the same `url` already exists...
        set_=dict(
            title=stmt.excluded.title,
            description=stmt.excluded.description,
            image_url=stmt.excluded.image_url,
            raw_payload=stmt.excluded.raw_payload,
            updated_at=func.now(),
        ),
        # ...UPDATE these fields with the new values.
        # `stmt.excluded` refers to the values that would have been inserted.
        # Note: source_id and created_at are NOT in set_ — they never change on update.
    ).returning(Article.id)
    # Return the id of every row touched (inserted or updated)

    result = await self.db.execute(stmt)
    await self.db.commit()
    return len(result.fetchall())
    # Count of rows written (INSERT + UPDATE both count)

async def get_all(self, limit: int = 20, offset: int = 0) -> list[Article]:
    stmt = (
        select(Article)
        .order_by(Article.published_at.desc().nulls_last())
        # Newest articles first. nulls_last() puts articles with no date at the bottom.
        .limit(limit)
        .offset(offset)
        # Standard pagination
    )

async def count(self) -> int:
    result = await self.db.execute(select(func.count()).select_from(Article))
    return result.scalar_one()
    # SELECT COUNT(*) FROM articles — used for pagination total
```

#### `app/repositories/raw_ingestion_repo.py`

```python
def compute_content_hash(source_id: int, raw_payload: dict) -> str:
    """Module-level function (not a method) so IngestionService can import it too."""
    payload_str = json.dumps(raw_payload, sort_keys=True, default=str)
    # sort_keys=True: ensures {"b":1,"a":2} and {"a":2,"b":1} produce the same hash
    # default=str: handles non-JSON-serializable values (datetimes, etc.)
    return hashlib.sha256(f"{source_id}:{payload_str}".encode()).hexdigest()
    # Prefix with source_id so the same payload from different sources has different hashes

async def store_batch(self, source_id: int, raw_items: list[dict]) -> int:
    rows = [
        {
            "source_id": source_id,
            "content_hash": compute_content_hash(source_id, item),
            # Computed before INSERT — unique constraint is on this column
            "raw_payload": item,
            "status": "pending",
        }
        for item in raw_items
    ]
    stmt = (
        insert(RawIngestionEvent)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["content_hash"])
        # If we've seen this exact payload before (same hash), silently skip it.
        # This is the idempotency guarantee — re-fetching a source never duplicates events.
        .returning(RawIngestionEvent.id)
        # Only returns IDs of *newly inserted* rows (conflicts return nothing)
    )
    result = await self.db.execute(stmt)
    await self.db.commit()
    return len(result.fetchall())  # Count of genuinely new events

async def mark_normalized(self, source_id: int, hashes_by_normalizer: dict[str, list[str]]) -> None:
    """Called after successful normalization to update status."""
    for normalizer, hashes in hashes_by_normalizer.items():
        await self.db.execute(
            update(RawIngestionEvent)
            .where(
                RawIngestionEvent.source_id == source_id,
                RawIngestionEvent.content_hash.in_(hashes),
                RawIngestionEvent.status == "pending",
                # Only update pending rows — idempotent if called twice
            )
            .values(
                status="normalized",
                normalized_by=normalizer,   # "deterministic" or "ai:anthropic:..."
                processed_at=datetime.now(timezone.utc),
            )
        )
    await self.db.commit()

async def mark_failed(self, source_id, content_hashes, error) -> None:
    await self.db.execute(
        update(RawIngestionEvent)
        .where(...)
        .values(
            status="failed",
            error_message=error,
            retry_count=RawIngestionEvent.retry_count + 1,
            # Increments in SQL, not Python — avoids race conditions
            processed_at=datetime.now(timezone.utc),
        )
    )
```

#### `app/repositories/ai_provider_repo.py`

```python
async def create(self, data: AIProviderCreate) -> AIProviderConfig:
    base_url = data.base_url or PROVIDER_BASE_URLS.get(data.provider)
    # If user didn't supply base_url, use the provider's known default (e.g. Gemini's URL)
    config = AIProviderConfig(
        ...
        is_active=False,  # Always starts inactive — must explicitly activate
    )

async def activate(self, config_id: int) -> AIProviderConfig | None:
    """Atomic swap: deactivate all, then activate the target."""
    await self.db.execute(
        update(AIProviderConfig).values(is_active=False)
        # Deactivate ALL providers first
    )
    await self.db.execute(
        update(AIProviderConfig)
        .where(AIProviderConfig.id == config_id)
        .values(is_active=True)
        # Then activate only the target
    )
    await self.db.commit()
    # Single commit = both updates are atomic. Can't end up with two active providers.

async def get_active(self) -> AIProviderConfig | None:
    result = await self.db.execute(
        select(AIProviderConfig).where(AIProviderConfig.is_active.is_(True))
    )
    return result.scalar_one_or_none()
    # Returns None if no provider is active (deterministic-only mode)
```

---

### 5.5 Pydantic Schemas — `app/schemas/`

Schemas are **not** ORM models. They define the shape of HTTP request bodies and response bodies. They live in `schemas/` so the API layer never exposes raw SQLAlchemy objects.

#### `app/schemas/source_schema.py`

```python
class SourceCreate(BaseModel):
    name: str        # Required — what to call this source
    type: str        # Required — "rss" or "rest"
    url: str         # Required — the feed/API URL
    config: dict | None = None  # Optional extra config

class SourceResponse(BaseModel):
    id: int
    name: str
    type: str
    url: str
    config: dict | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
    # This tells Pydantic to read attributes from SQLAlchemy ORM objects
    # (not just dicts). Without this, `return source` in routes wouldn't work.
```

#### `app/schemas/article_schema.py`

```python
class ArticleListResponse(BaseModel):
    total: int              # Total count of all articles (for pagination UI)
    limit: int              # How many were requested
    offset: int             # Starting position
    items: list[ArticleResponse]  # The actual articles
```

#### `app/schemas/ai_provider_schema.py`

```python
class AIProviderCreate(BaseModel):
    name: str
    provider: _PROVIDER_LITERAL  # Literal["anthropic", "openai", "gemini", "custom"]
    model: str
    api_key: str
    base_url: str | None = None

    @model_validator(mode="after")
    def validate_custom_needs_base_url(self) -> "AIProviderCreate":
        if self.provider == "custom" and not self.base_url:
            raise ValueError("base_url is required for provider='custom'")
        return self
    # model_validator runs after all fields are validated.
    # Cross-field validation: "custom" provider requires base_url.

class AIProviderResponse(BaseModel):
    # NOTE: api_key is intentionally absent — never returned to the client
    id: int
    name: str
    provider: str
    model: str
    base_url: str | None
    is_active: bool
    created_at: datetime
    model_config = {"from_attributes": True}
```

---

### 5.6 Services — `app/services/`

Services contain business logic. They orchestrate repositories and external calls, but never deal with HTTP or raw SQL.

#### `app/services/source_normalizer.py`

**Purpose:** Deterministic (no AI) conversion of raw RSS/REST payloads to the canonical article shape.

```python
def parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc)
        # RFC 2822 format: "Mon, 08 Mar 2021 09:00:00 +0000" (used by RSS)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(raw).astimezone(timezone.utc)
        # ISO 8601: "2021-03-08T09:00:00Z" (used by REST APIs)
    except Exception:
        pass
    logger.warning("Could not parse date string: %r", raw)
    return None
    # Returns None instead of raising — a missing date is not fatal
```

```python
def to_plain_dict(obj) -> object:
    """Converts feedparser's FeedParserDict to a plain Python dict."""
    if isinstance(obj, dict):
        return {k: to_plain_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_plain_dict(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj      # Already a JSON-serializable primitive
    try:
        return {k: to_plain_dict(v) for k, v in obj.items()}
        # feedparser's FeedParserDict has an .items() method — treat like a dict
    except Exception:
        return str(obj)  # Last resort: stringify unknown types
```

```python
def normalize(item) -> dict:
    """The canonical mapping: raw payload keys → article fields."""
    raw: dict = to_plain_dict(item)

    # Image URL extraction — RSS uses media:thumbnail, REST might use image_url
    image_url: str | None = None
    thumbnails = raw.get("media_thumbnail")
    if isinstance(thumbnails, list) and thumbnails:
        image_url = thumbnails[0].get("url")
    if not image_url:
        image_url = raw.get("image_url")

    return {
        "title": raw.get("title") or "Untitled",
        # Falls back to "Untitled" — the validator will reject this as a placeholder
        "description": raw.get("summary") or raw.get("description"),
        # "summary" is feedparser's key; REST APIs usually use "description"
        "content": None,
        # Never populated by the deterministic normalizer — reserved for future
        "url": raw.get("link") or raw.get("url") or "",
        # "link" is feedparser; "url" is typical REST
        "image_url": image_url,
        "published_at": parse_date(
            raw.get("published") or raw.get("publishedAt") or raw.get("published_at")
            # Handles all common date key names across RSS and REST sources
        ),
        "raw_payload": raw,
        # Always store the full original payload
    }
```

#### `app/services/ingestion_service.py`

**Purpose:** The central orchestrator for the ingestion pipeline. Called by both the API route (`POST /ingest`) and the scheduler.

```python
class IngestionService:
    def __init__(
        self,
        source_repo: SourceRepository,
        article_repo: ArticleRepository,
        raw_repo: RawIngestionRepository | None = None,
        # raw_repo is Optional so the scheduler's old path still works
        ai_provider_repo: AIProviderRepository | None = None,
        # Optional — if None, falls back to env vars
    ) -> None:

    async def ingest(self, source: Source) -> int:
        """Step 1: Fetch raw items"""
        raw_items = await self._fetch_items(source)
        if not raw_items:
            return 0

        """Step 2: Store raw items for audit trail"""
        if self.raw_repo:
            new_count = await self.raw_repo.store_batch(source.id, raw_items)

        """Step 3: Load AI provider (may be None)"""
        ai_provider = await self._load_ai_provider()

        """Step 4: Normalize each item"""
        valid_articles: list[dict] = []
        normalized_hashes: dict[str, str] = {}
        failed_hashes: list[str] = []

        for raw in raw_items:
            content_hash = compute_content_hash(source.id, raw)
            article, label = await self._normalize_one(raw, source.type, ai_provider)
            if article is not None:
                valid_articles.append(article)
                normalized_hashes[content_hash] = label
            else:
                failed_hashes.append(content_hash)

        """Step 5: Batch upsert valid articles"""
        count = await self.article_repo.upsert_batch(valid_articles, source.id)

        """Step 6: Update raw event statuses"""
        if self.raw_repo:
            await self._update_raw_statuses(source.id, normalized_hashes, failed_hashes)

        return count

    async def _load_ai_provider(self) -> AIProvider | None:
        """Resolution order:
        1. DB-active provider (set via /ai-providers/{id}/activate)
        2. ANTHROPIC_API_KEY env var (legacy fallback)
        3. None → deterministic normalization only
        """
        if self.ai_provider_repo is not None:
            try:
                config = await self.ai_provider_repo.get_active()
                if config is not None:
                    return create_from_config(config)
            except Exception as exc:
                logger.warning("Could not load DB AI provider, falling back to env: %s", exc)
        return get_env_fallback_provider()

    async def _fetch_items(self, source: Source) -> list[dict]:
        if source.type == "rss":
            feed = await RSSFetcher().fetch(source.url)
            return [to_plain_dict(entry) for entry in feed.entries]
        if source.type == "rest":
            headers = (source.config or {}).get("headers", {})
            # REST sources can store custom headers in source.config JSONB
            items = await RestFetcher().fetch(source.url, headers=headers)
            return [to_plain_dict(item) for item in items]

    async def _normalize_one(self, raw, source_type, ai_provider) -> tuple[dict | None, str]:
        """Two-pass normalization:"""
        # Pass 1: Deterministic
        try:
            data = normalize(raw)
            if validate(data).valid:
                return data, "deterministic"
        except Exception as exc:
            logger.error("Deterministic normalization raised: %s", exc)

        # Pass 2: AI fallback (only if deterministic failed AND provider is configured)
        if ai_provider is not None:
            try:
                ai_data = await ai_provider.normalize(raw, source_type)
                if ai_data is not None and validate(ai_data).valid:
                    return ai_data, ai_provider.model_id
            except Exception as exc:
                logger.error("AI provider raised: %s", exc)

        return None, ""  # Both passes failed
```

#### `app/services/fetchers/rss_fetcher.py`

```python
class RSSFetcher:
    async def fetch(self, url: str):
        try:
            feed = await asyncio.to_thread(feedparser.parse, url)
            # feedparser is synchronous (blocking). asyncio.to_thread() runs it
            # in a thread pool so it doesn't block the async event loop.
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch RSS feed: {url}") from exc

        if feed.bozo and feed.bozo_exception:
            logger.warning("Malformed RSS at %s: %s", url, feed.bozo_exception)
            # feedparser sets bozo=True for malformed XML but still parses what it can.
            # We warn but don't fail — partial data is better than none.

        return feed
        # Returns the full feedparser FeedParserDict. Caller accesses feed.entries.
```

#### `app/services/fetchers/rest_fetcher.py`

```python
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
# 15 seconds total, 5 seconds to establish the connection.
# Without timeouts, a slow API could block a scheduler run forever.

class RestFetcher:
    async def fetch(self, url: str, headers: dict | None = None) -> list[dict]:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, headers=headers or {})
            response.raise_for_status()
            # Raises httpx.HTTPStatusError for 4xx/5xx responses

        data = response.json()

        # Envelope unwrapping: REST APIs rarely return a bare array at the top level.
        # They usually return {"articles": [...]} or {"items": [...]} etc.
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("articles", "items", "results", "data"):
                if key in data and isinstance(data[key], list):
                    return data[key]

        logger.warning("Unexpected JSON shape from %s", url)
        return []
```

#### `app/services/normalization/canonical_validator.py`

```python
_PLACEHOLDER_TITLES = frozenset({"untitled", "", "no title", "n/a", "none"})
# frozenset for O(1) lookup. Lowercase for case-insensitive check.

def validate(article: dict) -> ValidationResult:
    errors: list[str] = []

    title = (article.get("title") or "").strip()
    if title.lower() in _PLACEHOLDER_TITLES:
        errors.append(f"title is absent or placeholder: {article.get('title')!r}")
    # "Untitled" from source_normalizer.py would fail this check,
    # causing the AI fallback to be invoked.

    url = article.get("url") or ""
    if not url.startswith(("http://", "https://")):
        errors.append(f"url is missing or not HTTP(S): {url!r}")
    # An article with no URL is useless to the frontend.

    if errors:
        return ValidationResult(valid=False, errors=errors)
    return ValidationResult(valid=True)
```

#### `app/services/normalization/ai_processor.py`

```python
_ENV_FALLBACK_MODEL = "claude-haiku-4-5-20251001"
# Haiku is the fastest/cheapest Claude model — good for high-volume normalization.

def get_env_fallback_provider() -> AIProvider | None:
    """Returns an Anthropic provider if ANTHROPIC_API_KEY is set, else None."""
    if not settings.ANTHROPIC_API_KEY:
        return None
    try:
        return create_from_env(
            api_key=settings.ANTHROPIC_API_KEY,
            model=_ENV_FALLBACK_MODEL,
        )
    except Exception as exc:
        logger.error("Failed to build env-var AI provider: %s", exc)
        return None
```

#### `app/services/normalization/provider_factory.py`

```python
_provider_cache: dict[tuple, AIProvider] = {}
# Module-level cache. Key is (config.id, model, api_key).
# This means: same DB config → same provider object reused.
# Prevents creating a new SDK client on every article normalization.

def create_from_config(config: AIProviderConfig) -> AIProvider:
    cache_key = (config.id, config.model, config.api_key)
    if cache_key in _provider_cache:
        return _provider_cache[cache_key]
    provider = _build(config)
    _provider_cache[cache_key] = provider
    return provider

def _build(config: AIProviderConfig) -> AIProvider:
    if config.provider == "anthropic":
        return AnthropicProvider(api_key=config.api_key, model=config.model)

    if config.provider in ("openai", "gemini", "custom"):
        return OpenAICompatibleProvider(
            api_key=config.api_key,
            model=config.model,
            base_url=config.base_url or PROVIDER_BASE_URLS.get(config.provider),
            # For Gemini: uses the pre-configured Google endpoint.
            # For custom: uses whatever the user supplied.
        )

    raise ValueError(f"Unknown provider {config.provider!r}")
    # This is the place to add new provider types (e.g. "cohere", "mistral")
```

#### `app/services/normalization/providers/base.py`

```python
NORMALIZATION_SYSTEM_PROMPT = """\
You are a structured data extraction engine for a news aggregation system.
...
Output schema (return exactly this shape, nothing else):
{
  "title": "string",
  "description": "string or null",
  "url": "string or null",
  "published_at": "ISO 8601 string or null",
  "image_url": "string or null",
  "author": "string or null"
}"""
# The same system prompt is used by ALL providers — Anthropic and OpenAI-compat alike.
# This ensures consistent output regardless of which model is active.

class _NormOutput(BaseModel):
    """Internal Pydantic model — validates the JSON the LLM returns."""
    title: str
    description: str | None = None
    url: str | None = None
    published_at: str | None = None
    image_url: str | None = None
    author: str | None = None

def build_user_message(raw_payload: dict, source_type: str) -> str:
    return (
        f"Source type: {source_type}\n\n"
        f"Raw payload:\n{json.dumps(raw_payload, default=str, indent=2)}"
    )
# Shared message builder — both providers call this exact function.

def parse_llm_output(text: str, raw_payload: dict) -> dict | None:
    """Parse and validate LLM response. Returns canonical article dict or None."""
    try:
        data = json.loads(text.strip())
        output = _NormOutput.model_validate(data)
        # If LLM returned malformed JSON or wrong field types, this raises.
    except json.JSONDecodeError as exc:
        logger.warning("AI provider returned non-JSON: %s", exc)
        return None
    except ValidationError as exc:
        logger.warning("AI output failed schema validation: %s", exc)
        return None

    published_at = parse_date(output.published_at) if output.published_at else None

    return {
        "title": output.title,
        "description": output.description,
        "content": None,
        "url": output.url or "",
        "image_url": output.image_url,
        "published_at": published_at,
        "raw_payload": raw_payload,  # Always the original — not from the LLM
    }

class AIProvider(ABC):
    """Abstract base class. All providers must implement these two members."""

    @property
    @abstractmethod
    def model_id(self) -> str:
        # Returns e.g. "ai:anthropic:claude-haiku-4-5-20251001"
        # Stored in raw_ingestion_events.normalized_by for auditing

    @abstractmethod
    async def normalize(self, raw_payload: dict, source_type: str) -> dict | None:
        # Call the AI API, parse the response, return canonical dict or None
```

#### `app/services/normalization/providers/anthropic_prov.py`

```python
class AnthropicProvider(AIProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        # AsyncAnthropic: the async version of the SDK client.
        # Reused across all normalize() calls (cached in provider_factory).

    @property
    def model_id(self) -> str:
        return f"ai:anthropic:{self._model}"

    async def normalize(self, raw_payload: dict, source_type: str) -> dict | None:
        user_message = build_user_message(raw_payload, source_type)
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=512,
                # 512 tokens is enough for the JSON output schema (short response)
                system=NORMALIZATION_SYSTEM_PROMPT,
                # Anthropic API has a dedicated `system` parameter (not a system message)
                messages=[{"role": "user", "content": user_message}],
            )
            text = response.content[0].text
        except anthropic.APIError as exc:
            logger.error("Anthropic API error: %s", exc)
            return None

        return parse_llm_output(text, raw_payload)
        # Shared parser from base.py
```

#### `app/services/normalization/providers/openai_prov.py`

```python
class OpenAICompatibleProvider(AIProvider):
    """One class handles OpenAI, Gemini, AND custom servers — just different base_url."""

    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        self._model = model
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        # base_url=None → uses OpenAI's default API endpoint
        # base_url="https://generativelanguage.googleapis.com/v1beta/openai/" → Gemini
        # base_url="http://localhost:11434/v1" → Ollama
        self._provider_label = "openai" if base_url is None else base_url.split("/")[2]
        # Extracts domain from URL for the model_id label

    async def normalize(self, raw_payload: dict, source_type: str) -> dict | None:
        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=512,
            response_format={"type": "json_object"},
            # OpenAI's "JSON mode" — forces the model to output valid JSON.
            # (Anthropic doesn't have this; its system prompt is strict enough.)
            messages=[
                {"role": "system", "content": NORMALIZATION_SYSTEM_PROMPT},
                # OpenAI-compat uses system as a message role, not a separate parameter
                {"role": "user", "content": user_message},
            ],
        )
        text = response.choices[0].message.content or ""
        return parse_llm_output(text, raw_payload)
```

#### `app/services/scheduler.py`

```python
scheduler = AsyncIOScheduler(timezone="UTC")
# Module-level singleton. AsyncIOScheduler runs jobs in the existing asyncio event loop.
# timezone="UTC" ensures scheduled times are unambiguous.

async def run_ingestion_for_all_active_sources() -> None:
    # Step 1: Get all active sources in one DB session
    async with AsyncSessionLocal() as db:
        sources = await SourceRepository(db).get_all(active_only=True)
    # Session is closed here — important for the next step

    # Step 2: Ingest each source concurrently with its own session
    tasks = [_ingest_one_source(source) for source in sources]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # return_exceptions=True: if one source fails, others continue.
    # Without this, one exception would cancel all remaining ingestions.

async def _ingest_one_source(source) -> int:
    async with AsyncSessionLocal() as db:
        # Each source gets its OWN DB session.
        # Why? A slow source can't block others from committing.
        # If source A takes 30s, source B can commit independently.
        svc = IngestionService(
            source_repo=SourceRepository(db),
            article_repo=ArticleRepository(db),
            raw_repo=RawIngestionRepository(db),
            # Note: ai_provider_repo is NOT passed here.
            # Scheduler uses env-var fallback only (not DB-configured providers).
            # This is a known limitation — can be extended.
        )
        return await svc.ingest(source)

def start_scheduler() -> None:
    scheduler.add_job(
        run_ingestion_for_all_active_sources,
        trigger="interval",
        minutes=5,           # Every 5 minutes
        id="ingestion_all_sources",
        replace_existing=True,  # Safe to call start_scheduler() multiple times
        max_instances=1,     # Don't run overlapping jobs if one takes >5 min
    )
    scheduler.start()

def stop_scheduler() -> None:
    scheduler.shutdown(wait=False)
    # wait=False: don't wait for running jobs to finish on shutdown.
    # Appropriate for a web server where fast shutdown is preferred.
```

---

### 5.7 API Routes — `app/api/`

#### `app/api/routes_sources.py`

```
POST   /sources/          → create_source      → SourceRepository.create()
GET    /sources/          → list_sources       → SourceRepository.get_all()
GET    /sources/{id}      → get_source         → SourceRepository.get_by_id()
```

All handlers follow the same pattern:
1. Accept `Depends(get_source_repo)` — FastAPI injects the repository.
2. Call the repository method.
3. Return the result — FastAPI serializes it using `response_model`.
4. If not found, `raise HTTPException(status_code=404)`.

#### `app/api/routes_articles.py`

```
GET    /articles/         → list_articles      → ArticleRepository.get_all() + count()
GET    /articles/{id}     → get_article        → ArticleRepository.get_by_id()
```

`list_articles` accepts `?limit=20&offset=0` query params:
- `limit: int = Query(20, ge=1, le=100)` — default 20, min 1, max 100.
- Returns `ArticleListResponse` with `total`, `limit`, `offset`, `items`.

#### `app/api/routes_ingest.py`

```
POST   /ingest/           → trigger_ingest     → IngestionService.ingest()
```

```python
class IngestRequest(BaseModel):
    source_id: int

@router.post("/")
async def trigger_ingest(payload: IngestRequest, ...):
    source = await source_repo.get_by_id(payload.source_id)
    if source is None:
        raise HTTPException(404)
    if source.type not in _SUPPORTED_SOURCE_TYPES:
        raise HTTPException(400)
    count = await svc.ingest(source)
    return {"source_id": source.id, "source_type": source.type, "ingested": count}
```

The route looks up the source first (validates it exists and is a supported type), then delegates to the service. The service decides internally whether to use an RSS fetcher or REST fetcher based on `source.type`.

#### `app/api/routes_ai_providers.py`

```
POST   /ai-providers/              → create_ai_provider      → repo.create()
GET    /ai-providers/              → list_ai_providers       → repo.get_all()
GET    /ai-providers/active        → get_active_provider     → repo.get_active()
GET    /ai-providers/{id}          → get_ai_provider         → repo.get_by_id()
PATCH  /ai-providers/{id}/activate → activate_ai_provider    → repo.activate()
DELETE /ai-providers/active        → deactivate_all_providers → repo.deactivate_all()
DELETE /ai-providers/{id}          → delete_ai_provider      → repo.delete()
```

**Important route ordering:** `GET /ai-providers/active` must be declared **before** `GET /ai-providers/{id}` in the file, otherwise FastAPI would try to interpret `"active"` as an integer `provider_id` and return 422. FastAPI matches routes in declaration order.

---

### 5.8 Migrations — `migrations/`

Migrations are versioned SQL schema changes. Never modify the database directly — always create a new migration.

#### `migrations/env.py`

```python
# Critical imports — these side-effects register models with Base.metadata
import app.models.ai_provider
import app.models.article
import app.models.raw_event
import app.models.source
# Without these imports, Alembic can't see the tables and will try to drop everything.

config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
# Overrides the sqlalchemy.url in alembic.ini with the actual DATABASE_URL from .env.
# This way alembic.ini stays secret-free.

target_metadata = Base.metadata
# Tells Alembic what the schema SHOULD look like (from ORM definitions).
# Alembic diffs this against the actual DB to generate migration SQL.
```

#### Migration Versions

**`29df1b34a087_initial_schema.py`**
- Creates `sources` table (id, name, type, url, config JSONB, is_active, created_at)
- Creates `articles` table (id, source_id FK, title, description, content, url, image_url, published_at, raw_payload JSONB, created_at, updated_at)
- Drops a legacy `news` table from the very first schema
- Adds indexes: `ix_articles_published_at`, `ix_articles_source_id`, `ix_articles_title`, `ix_articles_url`

**`c8f2a1e3b456_add_raw_ingestion_events.py`**
- Creates `raw_ingestion_events` table (id, source_id FK, content_hash, raw_payload JSONB, status, normalized_by, error_message, retry_count, created_at, processed_at)
- Adds `ix_raw_ingestion_events_source_id`
- Adds **partial index** `ix_raw_ingestion_events_pending` on `(source_id) WHERE status = 'pending'`
  - Partial indexes only index rows matching the WHERE clause — much smaller and faster for polling pending events

**`d9e4f5a6b789_add_ai_provider_configs.py`**
- Creates `ai_provider_configs` table (id, name, provider, model, api_key, base_url, is_active, created_at)
- Adds **partial unique index** `ix_ai_provider_configs_single_active` on `(id) WHERE is_active = true`
  - This enforces "at most one active provider" at the DB level — even if application code has a bug, the DB prevents two active rows

---

## 6. Database Tables — Full Reference

### `sources`

| Column | Type | Constraints | Description |
|---|---|---|---|
| id | INTEGER | PK, auto-increment | Unique source identifier |
| name | VARCHAR | NOT NULL | Human-readable label |
| type | VARCHAR | NOT NULL | `"rss"` or `"rest"` |
| url | VARCHAR | NOT NULL, UNIQUE | Feed or API endpoint |
| config | JSONB | nullable | Extra config (e.g. `{"headers": {...}}` for auth) |
| is_active | BOOLEAN | default TRUE | Scheduler skips inactive sources |
| created_at | TIMESTAMPTZ | server_default NOW() | When registered |

**Primary use:** Scheduler reads active sources every 5 min. Ingestion route reads by ID.

---

### `articles`

| Column | Type | Constraints | Description |
|---|---|---|---|
| id | INTEGER | PK, auto-increment | |
| source_id | INTEGER | FK → sources.id CASCADE, indexed | Which source this came from |
| title | VARCHAR | NOT NULL, indexed | Article headline |
| description | TEXT | nullable | 1-3 sentence summary |
| content | TEXT | nullable | Full body (currently unused) |
| url | VARCHAR | UNIQUE, indexed | Canonical article URL — dedup key |
| image_url | VARCHAR | nullable | Hero image |
| published_at | TIMESTAMPTZ | nullable, indexed | Publisher's date (default sort) |
| raw_payload | JSONB | NOT NULL | Full original payload (updated on re-fetch) |
| created_at | TIMESTAMPTZ | server_default NOW() | First ingestion time |
| updated_at | TIMESTAMPTZ | server_default NOW() | Last update time |

**Indexes:** `url` (unique — upsert target), `published_at` (sort), `source_id` (filter by source), `title` (search).

**Upsert behavior:** ON CONFLICT on `url` → UPDATE `title`, `description`, `image_url`, `raw_payload`, `updated_at`. Source corrections are captured automatically.

---

### `raw_ingestion_events`

| Column | Type | Constraints | Description |
|---|---|---|---|
| id | INTEGER | PK, auto-increment | |
| source_id | INTEGER | FK → sources.id CASCADE, indexed | |
| content_hash | VARCHAR(64) | UNIQUE, NOT NULL | SHA-256(source_id + canonical JSON) |
| raw_payload | JSONB | NOT NULL | Exact as-fetched payload |
| status | VARCHAR(20) | NOT NULL, default `"pending"` | `pending` → `normalized` or `failed` |
| normalized_by | VARCHAR(50) | nullable | `"deterministic"` or `"ai:anthropic:..."` |
| error_message | TEXT | nullable | Failure reason if status=`failed` |
| retry_count | SMALLINT | NOT NULL, default 0 | How many normalization attempts |
| created_at | TIMESTAMPTZ | server_default NOW() | When first stored |
| processed_at | TIMESTAMPTZ | nullable | When normalized or failed |

**Indexes:** `source_id` (standard), `(source_id) WHERE status='pending'` (partial — fast pending poll).

**Purpose:** Audit trail. Every fetched payload is stored before normalization. Useful for debugging why an article failed, replaying normalization with a different provider, or understanding what changed between fetches.

---

### `ai_provider_configs`

| Column | Type | Constraints | Description |
|---|---|---|---|
| id | INTEGER | PK, auto-increment | |
| name | VARCHAR(100) | NOT NULL | Friendly label |
| provider | VARCHAR(50) | NOT NULL | `anthropic`, `openai`, `gemini`, `custom` |
| model | VARCHAR(100) | NOT NULL | Model identifier |
| api_key | VARCHAR(500) | NOT NULL | API key (plaintext) |
| base_url | VARCHAR(500) | nullable | Custom endpoint override |
| is_active | BOOLEAN | NOT NULL, default FALSE | Only one can be TRUE |
| created_at | TIMESTAMPTZ | server_default NOW() | |

**Indexes:** Partial unique index on `(id) WHERE is_active = true` — enforces single active provider at DB level.

**Purpose:** Allows switching AI providers via API without restarting the server or changing environment variables. New configs start inactive and must be explicitly activated.

---

## 7. The Ingestion Pipeline (Step-by-Step)

When `POST /ingest` is called (or the scheduler fires):

```
Step 1: FETCH
  ├── source.type == "rss" → RSSFetcher.fetch(url)
  │     feedparser.parse() runs in thread pool (asyncio.to_thread)
  │     Returns FeedParserDict with .entries list
  │
  └── source.type == "rest" → RestFetcher.fetch(url, headers)
        httpx.AsyncClient.get() (truly async, no thread needed)
        Unwraps envelope: {"articles": [...]} → [...]

Step 2: RAW STORE
  RawIngestionRepository.store_batch()
  For each item:
    - Compute SHA-256(source_id + canonical JSON of item)
    - INSERT with ON CONFLICT DO NOTHING on content_hash
  Returns count of genuinely new events (duplicates silently skipped)

Step 3: LOAD AI PROVIDER
  Resolution order:
    1. ai_provider_configs WHERE is_active=TRUE (DB)
    2. ANTHROPIC_API_KEY env var
    3. None (deterministic only)
  Provider is cached in provider_factory._provider_cache

Step 4: NORMALIZE EACH ITEM
  For each raw_item:
    a. Deterministic pass: source_normalizer.normalize(raw_item)
       Maps known field names to canonical shape
    b. Validate: canonical_validator.validate(article)
       Check: title not placeholder, URL starts with http(s)
    c. If valid → mark as "deterministic", continue
    d. If invalid AND ai_provider is set:
       → ai_provider.normalize(raw_item, source_type)
       → parse_llm_output() validates JSON schema
       → canonical_validator.validate() again
       → If valid → mark as "ai:{provider}:{model}"
    e. If both fail → mark as failed

Step 5: BATCH UPSERT
  ArticleRepository.upsert_batch(valid_articles, source_id)
  Single PostgreSQL INSERT ... ON CONFLICT DO UPDATE statement
  Returns count of rows written

Step 6: UPDATE RAW EVENT STATUSES
  RawIngestionRepository.mark_normalized(source_id, hashes_by_normalizer)
  RawIngestionRepository.mark_failed(source_id, failed_hashes, "validation_failed")
  Updates status, normalized_by, processed_at on raw_ingestion_events rows

Return: count of articles written
```

---

## 8. AI Normalization System

### When AI is invoked

AI is a **fallback**, not the default. The deterministic normalizer runs first. AI is only called when:
1. Deterministic normalization produces an invalid article (bad title or URL), AND
2. An AI provider is configured (DB active config or ANTHROPIC_API_KEY env var)

This means: for well-structured RSS feeds, AI is never called. For messy REST APIs with non-standard field names, AI fills in the gaps.

### Provider Resolution

```
IngestionService._load_ai_provider()
    ↓
    ai_provider_repo.get_active()  ← Check DB first
    ↓ (if None or error)
    get_env_fallback_provider()    ← Check ANTHROPIC_API_KEY
    ↓ (if None)
    return None                    ← Deterministic only
```

### Adding a New Provider

1. Create `app/services/normalization/providers/your_prov.py`
2. Subclass `AIProvider` from `base.py`
3. Implement `model_id` property and `normalize()` method
4. Register in `provider_factory._build()` with a new `if provider == "yourprovider":` branch
5. Add the provider name to `SUPPORTED_PROVIDERS` in `app/models/ai_provider.py`
6. Add default model to `PROVIDER_DEFAULT_MODELS`
7. Add default base URL to `PROVIDER_BASE_URLS` (or `None` for SDK-default)

### The System Prompt

`NORMALIZATION_SYSTEM_PROMPT` in `providers/base.py` instructs the LLM to:
- Return **only** valid JSON (no prose, no markdown)
- Extract 6 specific fields: `title`, `description`, `url`, `published_at`, `image_url`, `author`
- Normalize `published_at` to ISO 8601 UTC
- Use `null` for missing optional fields

The same prompt is used for all providers — adding a new provider doesn't require writing a new prompt.

---

## 9. Scheduler

The APScheduler runs inside the FastAPI process (no separate worker process needed).

```
start_scheduler() called at app startup (lifespan)
    ↓
scheduler.add_job(
    run_ingestion_for_all_active_sources,
    trigger="interval",
    minutes=5,
    max_instances=1   ← prevents overlapping runs
)
```

**Each scheduled run:**
1. Opens one DB session to load active sources, then closes it
2. For each source, opens a **dedicated** DB session and ingests concurrently
3. `asyncio.gather(*tasks, return_exceptions=True)` — all sources run simultaneously; one failure doesn't stop others
4. Logs success/failure counts

**Limitation:** The scheduler does not pass `ai_provider_repo` to `IngestionService` — it only uses the env-var fallback, not the DB-configured provider. This is a known gap. To fix: pass `AIProviderRepository(db)` in `_ingest_one_source`.

---

## 10. Configuration & Environment

### Required environment variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | YES | PostgreSQL connection string with asyncpg driver |
| `ANTHROPIC_API_KEY` | NO | Enables Claude as env-var fallback normalizer |
| `DEBUG` | NO | `true`/`false` — enables SQL echo logging |

### `DATABASE_URL` format

```
postgresql+asyncpg://username:password@host:port/database_name
```

The `+asyncpg` is critical — it tells SQLAlchemy to use the asyncpg driver instead of psycopg2.

### Running the server

```bash
# Install dependencies
uv sync

# Run database migrations
uv run alembic upgrade head

# Start development server
uv run uvicorn app.main:app --reload --port 8000

# API docs available at:
# http://localhost:8000/docs    (Swagger UI)
# http://localhost:8000/redoc   (ReDoc)
```

### Running migrations

```bash
# Apply all pending migrations
uv run alembic upgrade head

# Create a new migration after changing a model
uv run alembic revision --autogenerate -m "describe_your_change"

# Downgrade one step
uv run alembic downgrade -1
```

---

## 11. How Data Flows (End-to-End Diagram)

```
                        ┌─────────────────────────────────────────┐
                        │           EXTERNAL WORLD                │
                        │  RSS Feeds  │  REST APIs  │  Frontend  │
                        └──────┬──────┴──────┬──────┴─────┬───────┘
                               │             │            │ HTTP
                        ┌──────▼─────────────▼────────────▼───────┐
                        │           FastAPI Application            │
                        │                                          │
                        │  /sources    /articles    /ingest        │
                        │  /ai-providers  /health                  │
                        │                                          │
                        │  ┌─────────┐  ┌──────────┐              │
                        │  │ Routes  │  │ Scheduler│              │
                        │  └────┬────┘  └────┬─────┘              │
                        │       │             │ every 5 min        │
                        │  ┌────▼─────────────▼─────┐             │
                        │  │     IngestionService    │             │
                        │  │  ┌──────────────────┐  │             │
                        │  │  │   RSSFetcher     │  │             │
                        │  │  │   RestFetcher    │  │             │
                        │  │  └────────┬─────────┘  │             │
                        │  │           │ raw items   │             │
                        │  │  ┌────────▼─────────┐  │             │
                        │  │  │ source_normalizer │  │             │
                        │  │  │ (deterministic)  │  │             │
                        │  │  └────────┬─────────┘  │             │
                        │  │           │ valid?      │             │
                        │  │        ┌──▼──┐          │             │
                        │  │        │ Yes │→ to DB   │             │
                        │  │        └──┬──┘          │             │
                        │  │           │ No          │             │
                        │  │  ┌────────▼─────────┐  │             │
                        │  │  │  AI Provider     │  │             │
                        │  │  │  (Anthropic/     │  │             │
                        │  │  │   OpenAI/Gemini) │  │             │
                        │  │  └────────┬─────────┘  │             │
                        │  └───────────┼─────────────┘             │
                        │             │                            │
                        │  ┌──────────▼──────────────────────┐    │
                        │  │       Repositories               │    │
                        │  │  SourceRepo  ArticleRepo         │    │
                        │  │  RawIngestionRepo  AIProviderRepo│    │
                        │  └──────────┬──────────────────────┘    │
                        └─────────────┼────────────────────────────┘
                                      │ async SQL (asyncpg)
                        ┌─────────────▼──────────────────────────┐
                        │              PostgreSQL                 │
                        │                                         │
                        │  sources  │  articles                   │
                        │  raw_ingestion_events                   │
                        │  ai_provider_configs                    │
                        └─────────────────────────────────────────┘
```

---

## 12. Line-by-Line Code Reference

### Quick lookup table: which file owns which behavior

| Behavior | File | Method/Function |
|---|---|---|
| App startup | `app/main.py` | `lifespan()` |
| Route registration | `app/main.py` | `app.include_router()` |
| Read env vars | `app/core/config.py` | `Settings` class |
| Create DB engine | `app/core/database.py` | `engine`, `AsyncSessionLocal` |
| Inject repos into routes | `app/core/deps.py` | `get_*_repo()`, `get_ingestion_service()` |
| `sources` table schema | `app/models/source.py` | `Source` class |
| `articles` table schema | `app/models/article.py` | `Article` class |
| `raw_ingestion_events` schema | `app/models/raw_event.py` | `RawIngestionEvent` class |
| `ai_provider_configs` schema | `app/models/ai_provider.py` | `AIProviderConfig` class |
| Create a source | `app/repositories/source_repo.py` | `SourceRepository.create()` |
| Batch upsert articles | `app/repositories/article_repo.py` | `ArticleRepository.upsert_batch()` |
| Store raw events | `app/repositories/raw_ingestion_repo.py` | `RawIngestionRepository.store_batch()` |
| Content dedup hash | `app/repositories/raw_ingestion_repo.py` | `compute_content_hash()` |
| Activate AI provider | `app/repositories/ai_provider_repo.py` | `AIProviderRepository.activate()` |
| Validate article shape | `app/schemas/source_schema.py` | `SourceCreate`, `SourceResponse` |
| Fetch RSS feed | `app/services/fetchers/rss_fetcher.py` | `RSSFetcher.fetch()` |
| Fetch REST API | `app/services/fetchers/rest_fetcher.py` | `RestFetcher.fetch()` |
| Map raw → canonical | `app/services/source_normalizer.py` | `normalize()` |
| Parse dates | `app/services/source_normalizer.py` | `parse_date()` |
| Convert feedparser → dict | `app/services/source_normalizer.py` | `to_plain_dict()` |
| Validate canonical article | `app/services/normalization/canonical_validator.py` | `validate()` |
| Full ingestion pipeline | `app/services/ingestion_service.py` | `IngestionService.ingest()` |
| Load AI provider | `app/services/ingestion_service.py` | `IngestionService._load_ai_provider()` |
| Env-var AI fallback | `app/services/normalization/ai_processor.py` | `get_env_fallback_provider()` |
| Instantiate/cache providers | `app/services/normalization/provider_factory.py` | `create_from_config()` |
| AI system prompt | `app/services/normalization/providers/base.py` | `NORMALIZATION_SYSTEM_PROMPT` |
| Parse LLM response | `app/services/normalization/providers/base.py` | `parse_llm_output()` |
| Claude normalization | `app/services/normalization/providers/anthropic_prov.py` | `AnthropicProvider.normalize()` |
| GPT/Gemini/custom norm. | `app/services/normalization/providers/openai_prov.py` | `OpenAICompatibleProvider.normalize()` |
| Background scheduler | `app/services/scheduler.py` | `run_ingestion_for_all_active_sources()` |
| POST /sources | `app/api/routes_sources.py` | `create_source()` |
| GET /articles (paginated) | `app/api/routes_articles.py` | `list_articles()` |
| POST /ingest | `app/api/routes_ingest.py` | `trigger_ingest()` |
| PATCH /ai-providers/{id}/activate | `app/api/routes_ai_providers.py` | `activate_ai_provider()` |
| DB migration baseline | `migrations/versions/29df1b34a087_initial_schema.py` | `upgrade()` |
| Add raw events table | `migrations/versions/c8f2a1e3b456_add_raw_ingestion_events.py` | `upgrade()` |
| Add AI configs table | `migrations/versions/d9e4f5a6b789_add_ai_provider_configs.py` | `upgrade()` |

---

*Generated 2026-02-20. Covers all files in the news_app_backend project.*
