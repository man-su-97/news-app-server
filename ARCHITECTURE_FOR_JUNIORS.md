# ARCHITECTURE FOR JUNIORS

> A plain-English guide to the News Aggregator Backend.
> Written for someone who knows basic Python but is new to FastAPI architecture.

---

## 1. Big Picture (Explain Like I'm New)

### What does this backend do?

Imagine you work at a newspaper office. Every few minutes, someone goes to 10 different websites, copies the headlines, runs them past an editor who knows crime law, and the editor decides: "Yes, that's a crime story — file it." Then it gets a short summary, a priority score, and a location tag, and goes into the archive for readers to search.

**This backend does exactly that — automatically, for crime news.**

- It periodically visits RSS feeds and REST APIs (news websites that publish machine-readable articles).
- It sends each article to an AI (Gemini or Claude) which reads it and answers: Is this a crime story? What kind? Where? How important?
- Non-crime articles are thrown away. Crime articles are saved in a PostgreSQL database with all the AI-generated tags.
- A frontend app can then call this API to get a sorted, filtered feed of crime news.

### What happens when the app runs?

1. The server starts (`uvicorn app.main:app`).
2. A **background scheduler** wakes up every 5 minutes.
3. It fetches every active news source from the database.
4. For each source, it downloads articles, sends them through the AI, and saves crime articles.
5. Meanwhile, the HTTP API is always live — a frontend or you can call `GET /articles/` at any time to read what was saved.

### Main moving parts

| Part | What it does |
|---|---|
| **Scheduler** | Wakes up every 5 min, triggers ingestion |
| **Fetchers** | Download raw articles from RSS feeds or REST APIs |
| **AI Providers** | Send articles to Gemini/Claude, get back structured data |
| **Repositories** | Save/read data from PostgreSQL |
| **Routers** | Expose HTTP endpoints (the API that the frontend calls) |
| **Schemas** | Define what JSON looks in and out of those endpoints |
| **Models** | Define the database table structure |

---

## 2. Project Folder Map (Simple Explanation)

```
news_app_backend/
├── app/
│   ├── main.py                  ← Server entry point
│   ├── api/                     ← HTTP route handlers
│   ├── core/                    ← Config, DB connection, dependency wiring
│   ├── models/                  ← Database table definitions
│   ├── schemas/                 ← JSON shape for API requests/responses
│   ├── repositories/            ← All database reads and writes
│   └── services/                ← Business logic (ingestion, scheduling, AI)
│       ├── fetchers/            ← RSS and REST downloaders
│       └── normalization/       ← AI provider code
│           └── providers/       ← Gemini, Anthropic, OpenAI implementations
├── migrations/                  ← Alembic DB migration scripts
├── .env                         ← Secret config (DATABASE_URL, API keys)
└── pyproject.toml               ← Project dependencies
```

---

### `app/api/` — HTTP Route Handlers

**What goes here:** Functions that handle HTTP requests (GET, POST, PATCH, DELETE).

**Why it exists:** This is where the "outside world" (a browser, mobile app, or curl command) talks to your server.

**What NOT to put here:** Database queries, business logic, AI calls. Routes should be thin — they receive a request, call a service or repo, and return a response.

**Files:**
- `routes_articles.py` — `GET /articles/`, `GET /articles/{id}` (read news cards)
- `routes_sources.py` — `POST /sources/`, `GET /sources/` (manage news feeds)
- `routes_ingest.py` — `POST /ingest/` (manually trigger a fetch run)
- `routes_ai_providers.py` — manage which AI model is active

**Example responsibility:** A user hits `GET /articles/?limit=10`. The route reads the `limit` query param, calls `repo.get_all(limit=10)`, and returns JSON. That's it.

---

### `app/core/` — Config, Database, and Dependency Wiring

**What goes here:** The infrastructure plumbing that every other part of the app uses.

**Why it exists:** One place for database connection settings, environment variable reading, and the glue code that connects routes to services.

**Files:**
- `config.py` — reads `.env` file, validates required settings like `DATABASE_URL`
- `database.py` — creates the PostgreSQL connection pool; defines `get_db()` (one session per request)
- `deps.py` — dependency factory functions that wire repos and services together

**What NOT to put here:** Business logic, SQL queries, API routes.

---

### `app/models/` — Database Table Definitions

**What goes here:** Python classes that mirror your database tables. One class = one table.

**Why it exists:** SQLAlchemy uses these classes to generate SQL for you. You write Python, it talks to the database.

**Files:**
- `base.py` — the parent class every model inherits from
- `article.py` → `articles` table (stores crime news)
- `source.py` → `sources` table (stores feed URLs)
- `raw_event.py` → `raw_ingestion_events` table (audit log of every raw payload received)
- `ai_provider.py` → `ai_provider_configs` table (stores AI credentials and which is active)

**What NOT to put here:** Business logic, HTTP code, validation rules. A model only describes columns and relationships.

---

### `app/schemas/` — JSON Request and Response Shapes

**What goes here:** Pydantic classes that define exactly what JSON comes IN to your API and what JSON goes OUT.

**Why it exists:** These are the "contract" between your API and its callers. They also do automatic input validation — if someone sends a string where you expect an integer, FastAPI rejects it immediately with a clear error.

**Key distinction:**
- `models/article.py` = describes the **database table** (SQLAlchemy)
- `schemas/article_schema.py` = describes the **API response** (Pydantic)

They can differ — for example, `ArticleResponse` never exposes `raw_payload` even though the database stores it.

**What NOT to put here:** Database queries, business logic, anything async.

---

### `app/repositories/` — Database Read/Write Operations

**What goes here:** All SQL queries, INSERTs, UPDATEs, and SELECTs. One class per table.

**Why it exists:** To keep all database code in one place. If you need to change a query, you change it here — not scattered across route handlers and services.

**Files:**
- `article_repo.py` — upsert articles, list by date, count total
- `source_repo.py` — create/list/get sources
- `raw_ingestion_repo.py` — store raw payloads, mark them normalized/failed
- `ai_provider_repo.py` — create/activate/delete AI provider configs

**What NOT to put here:** HTTP logic, business decisions, AI calls.

---

### `app/services/` — Business Logic

**What goes here:** The "brains" of the app. Code that orchestrates multiple operations to accomplish a goal.

**Why it exists:** Business logic that's too complex for a route handler (which should be thin) but doesn't belong in a repository (which only does DB operations).

**Files:**
- `ingestion_service.py` — the main pipeline: fetch → AI process → filter → save
- `scheduler.py` — runs `IngestionService` for every active source every 5 minutes
- `fetchers/rss_fetcher.py` — downloads and parses RSS XML feeds
- `fetchers/rest_fetcher.py` — downloads JSON from REST APIs
- `normalization/providers/` — Gemini, Anthropic, OpenAI implementations
- `normalization/provider_factory.py` — decides which AI provider to instantiate

**What NOT to put here:** Raw SQL (use repos), HTTP response logic (use routes).

---

### `migrations/` — Database Migration Scripts

**What goes here:** Alembic auto-generated scripts that describe how to change the database schema over time (add a column, change a type, etc.).

**Why it exists:** You cannot just change a model class and expect the real database to update itself. Migrations are the formal instructions.

**What NOT to put here:** Application logic. Migration files should only contain `op.add_column()`, `op.create_table()`, etc.

---

## 3. How a Request Actually Works (Step by Step)

### Example: `GET /articles/?limit=5`

```
Browser / Frontend
        │
        │  HTTP GET /articles/?limit=5
        ▼
┌─────────────────────────────┐
│   FastAPI (app/main.py)     │  ← Receives the request
│   Middleware: CORS check    │  ← Is this origin allowed?
└────────────┬────────────────┘
             │
             ▼
┌─────────────────────────────┐
│  routes_articles.py         │  ← Router matches /articles/
│  list_articles(limit=5)     │  ← FastAPI extracts ?limit=5
│  Depends(get_article_repo)  │  ← FastAPI calls get_article_repo()
└────────────┬────────────────┘
             │
             ▼
┌─────────────────────────────┐
│  core/deps.py               │  ← get_article_repo() runs
│  get_article_repo()         │  ← calls get_db() first
│      └─ get_db()            │  ← opens a DB session for this request
└────────────┬────────────────┘
             │
             ▼
┌─────────────────────────────┐
│  ArticleRepository          │  ← repo.get_all(limit=5, offset=0)
│  SELECT * FROM articles     │  ← async SQLAlchemy query to PostgreSQL
│  ORDER BY published_at DESC │
│  LIMIT 5                    │
└────────────┬────────────────┘
             │
             ▼
┌─────────────────────────────┐
│  PostgreSQL Database        │  ← returns 5 Article rows
└────────────┬────────────────┘
             │
             ▼
┌─────────────────────────────┐
│  ArticleListResponse schema │  ← Pydantic serializes ORM objects → JSON
│  { total, limit, items: [] }│
└────────────┬────────────────┘
             │
             ▼
        Browser / Frontend
   HTTP 200 { "total": 312, "limit": 5, "items": [...] }
```

**What runs first:** Middleware (CORS check), then the router matches the URL, then FastAPI runs dependency injection (opens a DB session), then the route handler runs, then the repository queries the DB.

**Where data changes shape:**
- `raw_payload` (from RSS/REST) → AI processes it → Python dict → `Article` ORM object (DB row) → `ArticleResponse` schema (JSON)

**Where validation happens:**
- **Input:** Pydantic validates query params (`limit` must be 1-100) and request bodies automatically. FastAPI returns HTTP 422 if validation fails.
- **Output:** Pydantic schemas control which fields appear in the JSON response and how they're formatted (e.g. `datetime` → ISO string).

---

## 4. RSS Feed Flow (Beginner Friendly)

Here is what happens when the scheduler triggers ingestion for a source like `https://timesofindia.indiatimes.com/rss.cms`:

```
Scheduler (every 5 min)
        │
        ▼
IngestionService.ingest(source)
        │
        ├─ Step 1: FETCH
        │   RSSFetcher calls feedparser.parse(url)
        │   feedparser downloads the XML and returns a list of article entries
        │   Each entry is a dict: {title, link, summary, published, media_thumbnail, ...}
        │
        ├─ Step 2: STORE RAW
        │   Every raw entry is saved to raw_ingestion_events table BEFORE processing
        │   A SHA-256 hash of (source_id + payload) is the dedup key
        │   If the same article shows up next time → hash matches → silently skipped
        │   Status = "pending"
        │
        ├─ Step 3: LOAD AI PROVIDER
        │   Check DB for an active AI config (POST /ai-providers + PATCH /activate)
        │   If none → check GEMINI_API_KEY env var
        │   If none → check ANTHROPIC_API_KEY env var
        │   If none → skip ingestion (no AI = no article classification)
        │
        ├─ Step 4: PROCESS (concurrent, up to 2 at a time)
        │   For each raw article:
        │     GeminiLangGraphProvider.process(raw, "rss"):
        │       Node 1: DuckDuckGo search for "{title} crime news" (context)
        │       Node 2: Send raw payload + search results to Gemini
        │       Gemini returns ONE JSON with ALL fields:
        │         title, url, description, image_url, published_at
        │         is_crime, category, sub_category, location, region
        │         summary, importance_score
        │
        ├─ Step 5: FILTER
        │   is_crime = false? → article dropped silently
        │   is_crime = true? → keep
        │
        ├─ Step 6: UPSERT
        │   All valid crime articles inserted in ONE database query
        │   Duplicate URL? → update existing row (publisher corrected the article)
        │
        └─ Step 7: AUDIT
            raw_ingestion_events rows updated:
              success → status="normalized", normalized_by="ai:gemini_langgraph:gemini-2.0-flash"
              failure → status="failed", error_message="..."
```

**How duplicates are avoided:**

Two layers of protection:

1. **Raw level:** `content_hash` (SHA-256 of source_id + payload). If you fetch the same article twice, the hash matches and `ON CONFLICT DO NOTHING` skips the insert. Status stays "pending" — it is not re-processed.

2. **Article level:** The `articles.url` column has a `UNIQUE` constraint. If the same article URL arrives from a different path, `ON CONFLICT DO UPDATE` overwrites the old row with fresh data instead of inserting a duplicate.

---

## 5. Important Files Explained (Junior Level)

### `app/main.py` — The Entry Point

**Why it exists:** This is the file `uvicorn` runs to start the server. It creates the FastAPI app object, configures CORS (cross-origin requests from the browser), registers all the routers, and starts/stops the background scheduler.

**When it runs:** Once, at server startup.

**What a junior should NEVER change without understanding:**
- The `lifespan` context manager (startup/shutdown hooks). Changing it incorrectly can leave background jobs running after the server stops.
- `include_router()` calls — if you remove one, that entire group of endpoints disappears.

---

### `app/core/database.py` — Database Connection Pool

**Why it exists:** Creates the SQLAlchemy async engine (the connection pool that actually talks to PostgreSQL) and defines `get_db()` which hands one DB session to each HTTP request.

**When it runs:** `engine` and `AsyncSessionLocal` are created once when Python imports this module. `get_db()` runs once per HTTP request.

**What a junior should NEVER change without understanding:**
- `pool_size` and `max_overflow` — these control how many PostgreSQL connections are open. Set too low → requests queue up. Set too high → PostgreSQL runs out of connections.
- `expire_on_commit=False` — without this, accessing `.id` on an ORM object after `commit()` would trigger an extra DB query. The ingestion pipeline depends on this behaviour.

---

### `app/core/deps.py` — Dependency Wiring

**Why it exists:** Defines the dependency functions (`get_article_repo`, `get_ingestion_service`, etc.) that FastAPI calls automatically when a route needs a repo or service. This is how the DB session gets shared across all repos in one request.

**When it runs:** Every time an HTTP request is made to a route that uses `Depends(...)`.

**What a junior should NEVER change without understanding:**
- `get_ingestion_service` passes the **same `db` session** to all four repositories. This means all DB writes in one ingest run are part of the same transaction. If you give each repo its own session, a crash halfway through will leave the DB in an inconsistent state (some rows written, some not).

---

### `app/models/` — Database Table Definitions

**Why they exist:** SQLAlchemy uses these Python classes to generate and run SQL. When you write `select(Article).where(Article.id == 5)`, SQLAlchemy translates that to `SELECT * FROM articles WHERE id = 5` — no raw SQL needed.

**When they run:** Models are loaded at startup. Every query that touches a table uses the corresponding model class.

**What a junior should NEVER change without understanding:**
- Adding or removing a column in a model does NOT automatically change the real database. You must also create and run an Alembic migration (`alembic revision --autogenerate` + `alembic upgrade head`). Skip this and your app will crash with a column mismatch error.
- `unique=True` on `articles.url` is the deduplication key for the entire pipeline. Removing it would allow duplicate articles to be saved.

---

### `app/schemas/` — API Request/Response Shapes

**Why they exist:** Pydantic schemas do two jobs: (1) validate incoming data so bad input is rejected before it reaches the database, and (2) control exactly what fields are serialized into JSON responses.

**When they run:** At request time. FastAPI calls Pydantic automatically.

**What a junior should NEVER change without understanding:**
- `model_config = {"from_attributes": True}` in response schemas. Without this line, FastAPI cannot convert a SQLAlchemy ORM object (like `Article`) into the Pydantic schema. It must be present on every response schema that reads from a model.
- Removing a field from a response schema removes it from the API response — even if the database still stores it. Adding a new field to the schema without adding it to the model/migration will cause a crash.

---

### `app/repositories/` — Database Operations

**Why they exist:** Every SQL query lives here. Routes and services never write raw SQL — they call methods on repository classes.

**When they run:** At request time (when a route or service calls a method like `repo.get_all()`).

**What a junior should NEVER change without understanding:**
- `upsert_batch()` in `article_repo.py` uses `ON CONFLICT DO UPDATE` on the `url` column. This is atomic — it handles the "already exists" case without a race condition. Replacing it with a "check then insert" pattern would introduce a race condition under concurrent writes.
- `store_batch()` in `raw_ingestion_repo.py` uses `ON CONFLICT DO NOTHING` on `content_hash`. This is what prevents duplicate processing. Removing it would reprocess the same articles every 5 minutes.

---

### `app/services/ingestion_service.py` — The Pipeline Orchestrator

**Why it exists:** This is the main "brain" that coordinates fetching, AI processing, filtering, and saving. It calls fetchers, repositories, and AI providers in the right order.

**When it runs:** Triggered by the scheduler every 5 minutes, OR manually via `POST /ingest/`.

**What a junior should NEVER change without understanding:**
- `asyncio.Semaphore(AI_CONCURRENCY_LIMIT)` — this limits how many simultaneous AI calls are made. The Gemini free tier allows ~5 requests per minute. Without the semaphore, 50 articles would fire 50 simultaneous API calls → rate limit errors → all articles dropped.
- `return_exceptions=True` in `asyncio.gather()` — this ensures one failing article does not cancel all other articles. Remove it and a single bad article crashes the entire batch.

---

## 6. Dependency Injection — Simple Explanation

### What is `get_db`?

`get_db()` is a function in `database.py` that opens a database session and "yields" it to whoever needs it. After the request finishes, the session is automatically closed — even if an error occurred.

```python
# database.py
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session   # ← give the session to the route
        # session closes automatically after the route returns
```

Think of it like a checkout counter at a library. You borrow the session for your request, use it, and return it when you're done. You don't have to remember to return it — FastAPI handles that.

### Why do we use `Depends()`?

`Depends()` tells FastAPI: "before you run my route function, first run this other function and pass me its result."

```python
# routes_articles.py
@router.get("/")
async def list_articles(
    repo: ArticleRepository = Depends(get_article_repo),
    #                         ↑ FastAPI calls get_article_repo()
    #                           and injects the result as `repo`
):
    return await repo.get_all()
```

Without `Depends()`, you would have to manually open a DB session inside every route function. With it, FastAPI handles the entire lifecycle automatically.

### What happens during a request lifecycle?

```
Request arrives
    │
    ├─ FastAPI sees: Depends(get_article_repo)
    ├─ get_article_repo() is called
    │     └─ which calls: Depends(get_db)
    │           └─ get_db() opens a DB session ← session is born here
    │
    ├─ ArticleRepository(db) is created ← repo gets the session
    │
    ├─ Route function runs:
    │     repo.get_all() → DB query → results
    │
    ├─ Response is serialized and sent to client
    │
    └─ Session is closed ← session dies here (after yield in get_db)
```

The session lives for exactly one request. This is correct — sessions should be short-lived.

### Multiple repos, same session

In `deps.py`, `get_ingestion_service` creates **four repositories** but passes the **same `db` session** to all of them:

```python
async def get_ingestion_service(db: AsyncSession = Depends(get_db)) -> IngestionService:
    return IngestionService(
        source_repo=SourceRepository(db),    # same db
        article_repo=ArticleRepository(db),  # same db
        raw_repo=RawIngestionRepository(db), # same db
        ai_provider_repo=AIProviderRepository(db),  # same db
    )
```

This means all writes in one ingest run happen in the same database transaction. If one fails, you can roll back cleanly. If each repo had its own session, a crash halfway through would leave inconsistent data.

---

## 7. How To Navigate This Codebase (Practical Guide)

### WHERE SHOULD I GO IF…

---

**I want to add a new API endpoint (e.g. `DELETE /articles/{id}`)**

1. Open `app/api/routes_articles.py`
2. Add a new `@router.delete("/{article_id}")` function
3. If it needs a new DB operation, add a method to `app/repositories/article_repo.py`
4. If the method needs a new dependency, add it to `app/core/deps.py`
5. You do NOT need to touch `main.py` — the router is already registered there

---

**I want to change what fields are returned in `GET /articles/`**

1. Open `app/schemas/article_schema.py`
2. Add or remove fields from `ArticleResponse`
3. If you're adding a field that comes from the database, make sure it exists in `app/models/article.py` too
4. If it's a new database column, you also need a migration (`alembic revision --autogenerate`)

---

**I want to change the database logic (e.g. sort articles differently)**

1. Open `app/repositories/article_repo.py`
2. Find the `get_all()` method
3. Change the `.order_by()` clause

Do NOT change sorting logic inside the route handler — keep it in the repository.

---

**I want to add a new news source**

You don't need to write code. Use the running API:

```bash
# Add the source via the API
POST /sources/
{
    "name": "My Crime Feed",
    "type": "rss",
    "url": "https://example.com/crime-feed.rss"
}

# Test it immediately
POST /ingest/
{"source_id": 5}
```

The scheduler will then fetch it automatically every 5 minutes.

---

**I want to switch to a different AI provider (e.g. from Gemini to Claude)**

1. `POST /ai-providers/` with your new provider credentials
2. `PATCH /ai-providers/{new_id}/activate`
3. `POST /ingest/` with any source to test it

No code changes needed. The provider is resolved at runtime from the database.

---

**I want to add a completely new AI provider (e.g. Mistral)**

1. Create `app/services/normalization/providers/mistral_prov.py`
2. Make it subclass `AIProvider` from `providers/base.py`
3. Implement the `model_id` property and `process()` method
4. Add `"mistral"` to `SUPPORTED_PROVIDERS` in `app/models/ai_provider.py`
5. Add an `elif provider == "mistral"` branch in `provider_factory.py`

That's it — no changes needed in `IngestionService`, routes, or repos.

---

**I want to change how often the scheduler runs (e.g. every 10 minutes)**

1. Open `app/services/scheduler.py`
2. In `start_scheduler()`, change `minutes=5` to `minutes=10`

---

**I want to debug why articles are not being saved**

Check in this order:

1. **Is there an active AI provider?**
   `GET /ai-providers/active` — if `null`, no AI = no processing
2. **Is the source active?**
   `GET /sources/` — `is_active` must be `true`
3. **Are raw events being stored?**
   Query: `SELECT status, error_message FROM raw_ingestion_events ORDER BY created_at DESC LIMIT 20`
4. **Are articles non-crime?** The AI might be classifying them as `is_crime=false`
   Check the logs for: `Dropping non-crime article`
5. **Are you hitting rate limits?**
   Look for log lines mentioning `429` or `rate limit`

---

**I want to understand why the scheduler isn't picking up my DB AI provider**

The fix was already applied — `_ingest_one_source()` in `scheduler.py` now passes `ai_provider_repo` to `IngestionService`. If the scheduler is ignoring your DB config, check that `PATCH /ai-providers/{id}/activate` returned a success response and that `GET /ai-providers/active` returns your config.

---

**I want to understand a DB error**

Enable SQL logging to see every query:

```env
# .env
DEBUG=true
```

This makes SQLAlchemy print every SQL statement to the console. Disable for production.

---

## 8. Common Beginner Mistakes In This Project

---

### Mistake 1: Putting database queries inside route handlers

```python
# BAD ❌ — DB logic inside the route
@router.get("/articles/")
async def list_articles(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Article))  # ← SQL in the route!
    return result.scalars().all()

# GOOD ✓ — DB logic in the repository, route just calls it
@router.get("/articles/")
async def list_articles(repo: ArticleRepository = Depends(get_article_repo)):
    return await repo.get_all()
```

**Why it's a problem:** When you later need to reuse that query (in a service, in tests, in another route), you have to copy-paste it. The repository pattern exists so queries live in one place and can be changed once.

---

### Mistake 2: Confusing models with schemas

A common junior mistake: someone adds a field to `ArticleResponse` (the schema) and wonders why it doesn't appear. They forgot that `ArticleResponse` only exposes fields that come from the database model `Article`. If `Article` doesn't have the column, the schema can't return it.

- **Model** (`app/models/article.py`) = database table definition
- **Schema** (`app/schemas/article_schema.py`) = JSON shape

They look similar (both are Python classes with typed fields) but they are completely different in purpose.

---

### Mistake 3: Changing a model column without creating a migration

```python
# You added this to Article:
tags: Mapped[list] = mapped_column(JSONB, nullable=True)

# But you did NOT run:
alembic revision --autogenerate -m "add tags column"
alembic upgrade head
```

The app will crash with `column articles.tags does not exist`. The model tells SQLAlchemy what the table *should* look like — Alembic migrations are what actually change the real database.

---

### Mistake 4: Opening a new DB session inside a service or repo

```python
# BAD ❌ — opens its own session, breaks transaction isolation
async def my_method(self):
    async with AsyncSessionLocal() as new_db:  # ← DON'T do this
        ...

# GOOD ✓ — use the session that was injected via Depends()
async def my_method(self):
    await self.db.execute(...)  # ← use self.db (the injected session)
```

**Why it's a problem:** If `IngestionService` saves articles in its session, and you open a separate session to do something else, those two sessions are independent transactions. If one fails and rolls back, the other does not. You get inconsistent data.

---

### Mistake 5: Using `asyncio.Semaphore` incorrectly

The semaphore in `ingestion_service.py` limits concurrent AI calls to avoid rate limit errors. A common mistake is to create the semaphore inside the loop (which means each iteration creates a new semaphore that allows unlimited concurrency):

```python
# BAD ❌ — new semaphore per article = no actual limit
for raw in items:
    semaphore = asyncio.Semaphore(2)  # ← this is useless
    async with semaphore:
        await process(raw)

# GOOD ✓ — one semaphore shared by all coroutines
semaphore = asyncio.Semaphore(2)  # ← created ONCE, before the loop
tasks = [process_with_semaphore(raw, semaphore) for raw in items]
await asyncio.gather(*tasks)
```

---

### Mistake 6: Raising exceptions inside `process()` in an AI provider

Every `AIProvider.process()` method has a contract: **it must never raise an exception**. It must catch all errors internally and return `None`.

```python
# BAD ❌ — raises, crashes the caller
async def process(self, raw, source_type):
    response = await self._llm.invoke(...)  # ← if this fails, exception propagates
    return parse_output(response)

# GOOD ✓ — catches all errors, returns None
async def process(self, raw, source_type):
    try:
        response = await self._llm.invoke(...)
        return parse_output(response)
    except Exception as exc:
        logger.warning("Process failed: %s", exc)
        return None  # ← caller drops this article, continues with others
```

**Why it's a problem:** `IngestionService` uses `asyncio.gather(return_exceptions=True)` which catches exceptions. But if `process()` raises, it means the article is counted as a hard failure rather than a soft "skip" — and depending on where the exception propagates, it can crash the entire batch.

---

### Mistake 7: Adding a route with the same URL pattern as an existing one

In `routes_ai_providers.py`, notice this comment:

```python
@router.get("/active", response_model=AIProviderResponse | None)
async def get_active_provider(...):
    # IMPORTANT: This endpoint MUST be declared BEFORE "/{provider_id}"
```

If `GET /ai-providers/{provider_id}` came first, FastAPI would try to parse `"active"` as an integer and return a 422 error when you call `GET /ai-providers/active`. Always put literal string routes (`/active`, `/me`, `/count`) before parameterised routes (`/{id}`) in the same file.

---

## 9. Mini Glossary (Very Important)

| Term | Plain English |
|---|---|
| **Router** | A group of related URL endpoints. Think of it as a mini-app for one feature area (articles, sources, etc.). In FastAPI, a `APIRouter`. |
| **Service** | Business logic that coordinates multiple operations. `IngestionService` fetches, processes, and saves articles. It knows the steps but delegates the details to repos and AI providers. |
| **Repository** | The only place that runs SQL. One class per database table. Routes and services call methods here instead of writing raw SQL themselves. |
| **Schema** | A Pydantic class that defines the shape of JSON going IN (request body) or OUT (response) of the API. Not the same as a database model. |
| **Model** | A SQLAlchemy class that maps one Python class to one database table. `class Article(Base)` → `articles` table. |
| **Dependency Injection (DI)** | FastAPI's system for automatically creating objects a route needs. `Depends(get_db)` tells FastAPI to call `get_db()` and pass the result into your function. You don't call it yourself — FastAPI does. |
| **Async Session** | A database connection that uses Python's `async/await` so other requests can keep running while you wait for the DB to respond. |
| **Lifespan** | A FastAPI context manager that runs setup code when the server starts and cleanup code when it stops. Used here to start/stop the scheduler. |
| **Upsert** | "Insert or update." PostgreSQL's `INSERT ... ON CONFLICT DO UPDATE` — if a row already exists (e.g. same URL), update it; if not, insert a new one. |
| **Content hash** | A SHA-256 fingerprint of a raw article payload. Used as a deduplication key — if the same article arrives twice, the hashes match and the second one is silently skipped. |
| **Migration** | A numbered script (managed by Alembic) that describes how to change the real database schema. Required whenever you add/remove/change a column in a model. |
| **Scheduler** | A background job runner (APScheduler) that triggers ingestion every 5 minutes without any human action. |
| **Semaphore** | An async lock that limits how many coroutines can run simultaneously. `asyncio.Semaphore(2)` means at most 2 AI API calls run at the same time. |
| **Provider** | An AI backend (Gemini, Claude, OpenAI, etc.) wrapped in a Python class that implements the `AIProvider` interface. |
| **LangGraph** | A library for building stateful AI pipelines as graphs. This project uses it for a two-node pipeline: search → process. |
| **Bozo flag** | Feedparser's way of saying "this RSS XML was malformed, but I tried to parse it anyway." Logged as a warning, not an error. |
| **JSONB** | PostgreSQL's binary JSON column type. Faster to query than plain JSON. Used for `raw_payload` and `config` columns. |
| **`expire_on_commit=False`** | A SQLAlchemy session setting that keeps ORM object data in memory after a `commit()`. Without it, accessing `.id` after saving would trigger a new DB query. |
